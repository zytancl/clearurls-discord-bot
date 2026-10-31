import asyncio
import logging
import os
import re
import discord
from discord import app_commands
from dotenv import load_dotenv
from unalix import clear_url
from prometheus_client import start_http_server, Summary, Counter, Gauge

from settings import GuildSettings
from shortlinks import is_short_link_token, resolve_short_url

logger = logging.getLogger(__name__)

DOCS_URL = 'https://danielzting.github.io/clearurls-discord-bot/'
URL_PATTERN = re.compile(r'https?://[^\s]+')
MAX_MESSAGE_LENGTH = 2000
# Cap on short links followed per message, so one message can't trigger a flood of requests
MAX_SHORT_LINKS_PER_MESSAGE = 5


class ClearUrlsClient(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


intents = discord.Intents.default()
intents.message_content = True
client = ClearUrlsClient(intents=intents)

# Opened in __main__ once .env has been loaded
settings = None

process_message_time = Summary('process_message_time', 'Time spent processing message')
process_react_time = Summary('process_react_time', 'Time spent processing react')
messages = Counter('messages', 'Total number of messages processed')
cleaned_messages = Counter('cleaned_messages', 'Number of messages with tracking links cleaned')
deleted_messages = Counter('deleted_messages', 'Number of cleaned messages that were deleted with the trash react')
replaced_messages = Counter('replaced_messages', 'Number of original messages deleted and reposted by the delete-original setting')
servers = Gauge('servers', 'Number of servers the bot is in')
members = Gauge('members', 'Combined member count of all servers the bot is in')

async def count_servers_members():
    while True:
        servers.set(len(client.guilds))
        members.set(sum([guild.member_count for guild in client.guilds]))
        await asyncio.sleep(60)

@client.event
async def on_ready():
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name='for tracking links'))
    asyncio.create_task(count_servers_members())

@client.tree.command(name='delete-original', description='Delete messages that contain tracking links and repost them cleaned')
@app_commands.describe(enabled='True to delete and repost messages with tracking links, False to just reply to them')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def delete_original(interaction: discord.Interaction, enabled: bool):
    # default_permissions can be overridden in a server's integration settings, so check again here
    if not interaction.permissions.manage_guild:
        await interaction.response.send_message('You need the **Manage Server** permission to change this setting.', ephemeral=True)
        return

    settings.set_delete_original(interaction.guild_id, enabled)
    if enabled:
        text = ('Messages containing tracking links will now be deleted and reposted with the tracking removed. '
                f'[Details]({DOCS_URL}#delete-original)')
        if not interaction.app_permissions.manage_messages:
            text += '\n⚠️ I don\'t have the **Manage Messages** permission in this channel, so I can\'t delete messages here yet. Until I do, I\'ll reply as usual.'
    else:
        text = 'Messages containing tracking links will no longer be deleted. I\'ll reply with the cleaned links instead.'
    await interaction.response.send_message(text, ephemeral=True)

async def find_cleaned_urls(content):
    """Return {original url: cleaned url} for every URL in the content that changes when cleaned."""
    urls = list(dict.fromkeys(URL_PATTERN.findall(content)))

    # Resolve short links (e.g. vm.tiktok.com) concurrently, up to a per-message cap
    short_links_left = MAX_SHORT_LINKS_PER_MESSAGE
    tasks = []
    for url in urls:
        if is_short_link_token(url) and short_links_left > 0:
            short_links_left -= 1
            tasks.append(resolve_short_url(url))
        else:
            tasks.append(asyncio.sleep(0, result=url))
    resolved = await asyncio.gather(*tasks)

    cleaned = {}
    for url, resolved_url in zip(urls, resolved):
        result = clear_url(resolved_url)
        # Ignore trailing & in comparing, as these are not used for tracking
        # This is to fix a bug where right clicking on an image in the Discord *app* (not browser) > Copy Link on context menu would create a link ending in &
        # Pasting this link into Discord would then trigger the bot since the cleaned link removed the &, even though the image link didn't have tracking parameters
        if result.strip('&') != url.strip('&'):
            cleaned[url] = result
    return cleaned

def build_replacement_text(message, cleaned):
    """The text that replaces an original message when it is deleted, or None if it wouldn't fit in one message."""
    body = URL_PATTERN.sub(lambda match: cleaned.get(match.group(0), match.group(0)), message.content)
    text = (f'{message.author.mention} sent the following message, which has automatically been cleaned of tracking links '
            f'([what\'s this?](<{DOCS_URL}#delete-original>)):\n>>> {body}')
    return text if len(text) <= MAX_MESSAGE_LENGTH else None

async def replace_original(message, text):
    """Repost a cleaned copy of the message, then delete the original."""
    reference = None
    if message.reference is not None and message.reference.message_id is not None:
        # Keep the reply context if the original was a reply to something
        reference = discord.MessageReference(
            message_id=message.reference.message_id,
            channel_id=message.reference.channel_id,
            guild_id=message.reference.guild_id,
            fail_if_not_exists=False,
        )
    # Send before deleting so nothing is lost if sending fails. Mentions are shown but never
    # pinged, since anyone mentioned in the original was already notified when it was posted.
    await message.channel.send(text, reference=reference, allowed_mentions=discord.AllowedMentions.none(), silent=True)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.warning('Could not delete original message %s', message.id, exc_info=True)
    replaced_messages.inc()

@process_message_time.time()
@client.event
async def on_message(message):
    messages.inc()
    # Ignore DMs. Also ignore our own messages, which never contain tracking links
    # but would otherwise risk infinite recursion if that ever changed
    if message.guild is None or message.author == client.user:
        return

    cleaned = await find_cleaned_urls(message.content)
    if not cleaned:
        return

    permissions = message.channel.permissions_for(message.guild.me)

    # Delete-original mode: repost the message cleaned and delete the original. Only done for
    # humans (not bots or webhooks) and plain messages, so no attachments or stickers are lost.
    if (settings.get_delete_original(message.guild.id)
            and permissions.manage_messages
            and not message.author.bot
            and not message.attachments
            and not message.stickers):
        text = build_replacement_text(message, cleaned)
        if text is not None:
            await replace_original(message, text)
            cleaned_messages.inc()
            return

    # Suppress embeds for original message to avoid visual clutter
    if permissions.manage_messages:
        await message.edit(suppress=True)
    text = 'It appears that you have sent one or more links with tracking parameters. Below are the same links with those fields removed:\n' + '\n'.join(cleaned.values())
    reply = await message.reply(text, mention_author=False)
    cleaned_messages.inc()

    # Suppress embeds for bot messages if unable to suppress embeds for original message to avoid visual clutter
    if not permissions.manage_messages:
        await reply.edit(suppress=True)
    # Add :wastebasket: emoji for easy deletion if necessary
    if permissions.add_reactions and permissions.read_message_history and permissions.manage_messages:
        await reply.add_reaction('🗑')

@process_react_time.time()
@client.event
async def on_raw_reaction_add(payload):
    # Delete messages if the original sender clicks the trash can react
    if payload.emoji.name != '🗑':
        return

    channel = await client.fetch_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)

    if message.reference is None or message.author != client.user:
        return

    original_channel = await client.fetch_channel(message.reference.channel_id)
    original_message = await original_channel.fetch_message(message.reference.message_id)
    user = await client.fetch_user(payload.user_id)
    permissions = message.channel.permissions_for(message.guild.me)

    if permissions.manage_messages and original_message.author == user:
        await message.delete()
        deleted_messages.inc()
    
if __name__ == '__main__':
    load_dotenv()
    settings = GuildSettings()
    start_http_server(8000)
    client.run(os.environ['TOKEN'])
