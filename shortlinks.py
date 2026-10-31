"""Resolve TikTok short links to their full desktop URLs.

Links shared from the TikTok mobile app (e.g. https://vm.tiktok.com/ZNRfD3vnG/)
hide their tracking data inside the redirect rather than in query parameters, so
the regular ruleset can't clean them. Following the redirect gives us the full
https://www.tiktok.com/@user/video/<id> URL, which can then be cleaned normally.

Safety: this makes outbound requests on behalf of whatever a user typed into a
chat, so it is deliberately locked down. Only known TikTok short-link hosts are
ever requested, redirects are followed by hand so every hop can be checked
against TikTok's domain, and the hop count and timeout are small. If anything
looks wrong the original URL is returned unchanged.
"""

import asyncio
import logging
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SHORTLINK_HOSTS = {'vm.tiktok.com', 'vt.tiktok.com'}
TRUSTED_DOMAIN = 'tiktok.com'
MAX_HOPS = 5
TIMEOUT = aiohttp.ClientTimeout(total=5)
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
)
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# The bot extracts URLs with a loose regex, so Discord formatting such as
# <url>, (url), **url** or ||url|| can leave trailing punctuation attached.
_TRAILING = re.compile(r'^(?P<core>.*?)(?P<trailer>[>)\]},.!?"\'*_~|]*)$', re.DOTALL)


def _split_trailing(url):
    match = _TRAILING.match(url)
    return match.group('core'), match.group('trailer')


def _is_trusted_host(host):
    host = (host or '').lower()
    return host == TRUSTED_DOMAIN or host.endswith('.' + TRUSTED_DOMAIN)


def is_short_link(url):
    """True for TikTok short links: vm./vt.tiktok.com/<code> and tiktok.com/t/<code>."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    host = (parsed.hostname or '').lower()
    path = parsed.path
    if host in SHORTLINK_HOSTS:
        return bool(path.strip('/'))
    if host in (TRUSTED_DOMAIN, 'www.' + TRUSTED_DOMAIN):
        return path.startswith('/t/') and bool(path[3:].strip('/'))
    return False


def is_short_link_token(url):
    """Like is_short_link, but tolerates trailing punctuation from a loose URL regex match."""
    return is_short_link(_split_trailing(url)[0])


async def resolve_short_url(url):
    """Return the full URL behind a TikTok short link, or `url` if it isn't one
    or can't be resolved."""
    core, trailer = _split_trailing(url)
    if not is_short_link(core):
        return url

    current = core
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT, headers={'User-Agent': USER_AGENT}) as session:
            for _ in range(MAX_HOPS):
                if not is_short_link(current):
                    break
                # Redirects are followed manually so every hop can be validated.
                # The body is never read; we only need the Location header.
                async with session.get(current, allow_redirects=False) as response:
                    location = response.headers.get('Location')
                    if response.status not in REDIRECT_STATUSES or not location:
                        return url
                    current = urllib.parse.urljoin(current, location)
                    if not _is_trusted_host(urllib.parse.urlparse(current).hostname):
                        return url
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        logger.warning('Could not resolve short link %s: %s', core, error)
        return url

    if is_short_link(current):
        # Hit the hop limit without reaching a full URL.
        return url
    return current + trailer
