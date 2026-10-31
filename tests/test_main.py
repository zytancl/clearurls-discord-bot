import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import discord

import main
from settings import GuildSettings

TRACKED = 'https://example.com/page?utm_source=twitter&id=7'
CLEAN = 'https://example.com/page?id=7'


def make_message(content, *, bot=False, attachments=(), stickers=(), reference=None):
    message = MagicMock()
    message.content = content
    message.id = 111
    message.guild.id = 42
    message.author.bot = bot
    message.author.mention = '<@5>'
    message.attachments = list(attachments)
    message.stickers = list(stickers)
    message.reference = reference
    message.edit = AsyncMock()
    message.delete = AsyncMock()
    message.reply = AsyncMock()
    message.channel.send = AsyncMock()
    message.channel.permissions_for.return_value = discord.Permissions(
        manage_messages=True, add_reactions=True, read_message_history=True)
    return message


class OnMessage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main.settings = GuildSettings(':memory:')

    def enable_delete(self):
        main.settings.set_delete_original(42, True)

    def set_permissions(self, message, **perms):
        message.channel.permissions_for.return_value = discord.Permissions(**perms)

    async def test_ignores_messages_without_tracking(self):
        message = make_message('hello https://example.com/page?id=7')
        await main.on_message(message)
        message.reply.assert_not_called()
        message.channel.send.assert_not_called()

    async def test_ignores_dms(self):
        message = make_message(TRACKED)
        message.guild = None
        await main.on_message(message)
        message.reply.assert_not_called()

    async def test_default_mode_replies_and_keeps_original(self):
        message = make_message(f'look {TRACKED}')
        await main.on_message(message)
        message.edit.assert_awaited_once_with(suppress=True)
        self.assertIn(CLEAN, message.reply.await_args.args[0])
        message.delete.assert_not_called()
        message.reply.return_value.add_reaction.assert_awaited_once_with('🗑')

    async def test_default_mode_without_manage_messages_suppresses_own_embeds(self):
        message = make_message(TRACKED)
        self.set_permissions(message, add_reactions=True, read_message_history=True)
        await main.on_message(message)
        message.edit.assert_not_called()
        message.reply.return_value.edit.assert_awaited_once_with(suppress=True)
        message.reply.return_value.add_reaction.assert_not_called()

    async def test_delete_mode_reposts_cleaned_message_then_deletes(self):
        self.enable_delete()
        message = make_message(f'check this out {TRACKED} and https://example.com/ok')
        order = MagicMock()
        order.attach_mock(message.channel.send, 'send')
        order.attach_mock(message.delete, 'delete')
        await main.on_message(message)

        self.assertEqual([c[0] for c in order.mock_calls], ['send', 'delete'])
        text = message.channel.send.await_args.args[0]
        self.assertIn('<@5> sent the following message, which has automatically been cleaned of tracking links', text)
        self.assertIn(f'#delete-original', text)
        self.assertIn(f'check this out {CLEAN} and https://example.com/ok', text)
        self.assertNotIn('utm_source', text)
        kwargs = message.channel.send.await_args.kwargs
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        self.assertTrue(kwargs['silent'])
        message.reply.assert_not_called()
        message.edit.assert_not_called()

    async def test_delete_mode_only_changes_the_dirty_links(self):
        self.enable_delete()
        # one URL being a prefix of another must not corrupt it
        message = make_message('https://example.com/a?utm_source=1 https://example.com/a?utm_source=12&x=1')
        await main.on_message(message)
        text = message.channel.send.await_args.args[0]
        self.assertTrue(text.endswith('>>> https://example.com/a https://example.com/a?x=1'), text)

    async def test_delete_mode_preserves_reply_context(self):
        self.enable_delete()
        ref = MagicMock(message_id=900, channel_id=800, guild_id=42)
        message = make_message(TRACKED, reference=ref)
        await main.on_message(message)
        sent_ref = message.channel.send.await_args.kwargs['reference']
        self.assertEqual((sent_ref.message_id, sent_ref.channel_id, sent_ref.fail_if_not_exists), (900, 800, False))

    async def test_delete_mode_off_by_default_per_guild(self):
        main.settings.set_delete_original(999, True)  # a different server
        message = make_message(TRACKED)
        await main.on_message(message)
        message.delete.assert_not_called()
        message.reply.assert_awaited_once()

    async def test_delete_mode_falls_back_without_manage_messages(self):
        self.enable_delete()
        message = make_message(TRACKED)
        self.set_permissions(message, add_reactions=True, read_message_history=True)
        await main.on_message(message)
        message.delete.assert_not_called()
        message.reply.assert_awaited_once()

    async def test_delete_mode_falls_back_for_attachments_stickers_and_bots(self):
        self.enable_delete()
        for kwargs in ({'attachments': [object()]}, {'stickers': [object()]}, {'bot': True}):
            message = make_message(TRACKED, **kwargs)
            await main.on_message(message)
            message.delete.assert_not_called()
            message.reply.assert_awaited_once()

    async def test_delete_mode_falls_back_when_too_long_to_repost(self):
        self.enable_delete()
        message = make_message('x' * 1900 + ' ' + TRACKED)
        await main.on_message(message)
        message.delete.assert_not_called()
        message.channel.send.assert_not_called()
        message.reply.assert_awaited_once()

    async def test_original_is_kept_if_repost_fails(self):
        self.enable_delete()
        message = make_message(TRACKED)
        message.channel.send.side_effect = discord.Forbidden(MagicMock(status=403), 'no')
        with self.assertRaises(discord.Forbidden):
            await main.on_message(message)
        message.delete.assert_not_called()

    async def test_already_deleted_original_is_tolerated(self):
        self.enable_delete()
        message = make_message(TRACKED)
        message.delete.side_effect = discord.NotFound(MagicMock(status=404), 'gone')
        await main.on_message(message)  # must not raise


class TikTokShortLinks(unittest.IsolatedAsyncioTestCase):
    """Issue #10, end to end through on_message."""
    def setUp(self):
        main.settings = GuildSettings(':memory:')

    async def test_short_link_replaced_with_clean_desktop_link(self):
        full = 'https://www.tiktok.com/@jdhperc/video/7593109045465140511'
        resolver = AsyncMock(return_value=full + '?_r=1&_t=8abc&u_code=xyz')
        message = make_message('https://vm.tiktok.com/ZNRfD3vnG/')
        with mock.patch.object(main, 'resolve_short_url', resolver):
            await main.on_message(message)
        resolver.assert_awaited_once_with('https://vm.tiktok.com/ZNRfD3vnG/')
        self.assertTrue(message.reply.await_args.args[0].endswith('\n' + full))

    async def test_unresolvable_short_link_is_left_alone(self):
        message = make_message('https://vm.tiktok.com/ZNRfD3vnG/')
        with mock.patch.object(main, 'resolve_short_url', AsyncMock(side_effect=lambda url: url)):
            await main.on_message(message)
        message.reply.assert_not_called()

    async def test_short_link_resolution_is_capped_per_message(self):
        links = ' '.join(f'https://vm.tiktok.com/Z{i}/' for i in range(20))
        resolver = AsyncMock(side_effect=lambda url: url)
        with mock.patch.object(main, 'resolve_short_url', resolver):
            await main.find_cleaned_urls(links)
        self.assertEqual(resolver.await_count, main.MAX_SHORT_LINKS_PER_MESSAGE)

    async def test_regular_links_never_hit_the_resolver(self):
        resolver = AsyncMock()
        with mock.patch.object(main, 'resolve_short_url', resolver):
            await main.find_cleaned_urls(TRACKED)
        resolver.assert_not_called()


class DeleteOriginalCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main.settings = GuildSettings(':memory:')

    def interaction(self, *, manage_guild, bot_manage_messages=True):
        interaction = MagicMock()
        interaction.guild_id = 42
        interaction.permissions = discord.Permissions(manage_guild=manage_guild)
        interaction.app_permissions = discord.Permissions(manage_messages=bot_manage_messages)
        interaction.response.send_message = AsyncMock()
        return interaction

    async def test_manager_can_enable_and_disable(self):
        interaction = self.interaction(manage_guild=True)
        await main.delete_original.callback(interaction, True)
        self.assertTrue(main.settings.get_delete_original(42))
        self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])
        await main.delete_original.callback(interaction, False)
        self.assertFalse(main.settings.get_delete_original(42))

    async def test_non_manager_is_rejected(self):
        interaction = self.interaction(manage_guild=False)
        await main.delete_original.callback(interaction, True)
        self.assertFalse(main.settings.get_delete_original(42))
        self.assertIn('Manage Server', interaction.response.send_message.await_args.args[0])

    async def test_warns_when_bot_cannot_delete(self):
        interaction = self.interaction(manage_guild=True, bot_manage_messages=False)
        await main.delete_original.callback(interaction, True)
        self.assertIn('Manage Messages', interaction.response.send_message.await_args.args[0])

    def test_command_is_registered_guild_only_and_gated(self):
        command = main.client.tree.get_command('delete-original')
        self.assertIsNotNone(command)
        self.assertTrue(command.guild_only)
        self.assertTrue(command.default_permissions.manage_guild)


if __name__ == '__main__':
    unittest.main()
