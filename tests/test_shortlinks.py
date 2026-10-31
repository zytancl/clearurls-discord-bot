import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

import shortlinks


class IsShortLink(unittest.TestCase):
    def test_tiktok_short_links(self):
        for url in ('https://vm.tiktok.com/ZNRfD3vnG/', 'https://vt.tiktok.com/ZSabc123/',
                    'http://vm.tiktok.com/ZNRfD3vnG', 'https://www.tiktok.com/t/ZTabc123/',
                    'https://tiktok.com/t/ZTabc123'):
            self.assertTrue(shortlinks.is_short_link(url), url)

    def test_not_short_links(self):
        for url in ('https://www.tiktok.com/@jdhperc/video/7593109045465140511',
                    'https://vm.tiktok.com/', 'https://www.tiktok.com/t/',
                    'https://vm.tiktok.com.evil.example/abc', 'https://evil.example/vm.tiktok.com/abc',
                    'https://example.com/t/abc', 'ftp://vm.tiktok.com/abc', 'not a url'):
            self.assertFalse(shortlinks.is_short_link(url), url)

    def test_trailing_punctuation_tolerated(self):
        for url in ('https://vm.tiktok.com/ZNRfD3vnG/>', 'https://vm.tiktok.com/ZNRfD3vnG).', 'https://vm.tiktok.com/ZNRfD3vnG||'):
            self.assertTrue(shortlinks.is_short_link_token(url), url)

    def test_trusted_hosts(self):
        self.assertTrue(shortlinks._is_trusted_host('www.tiktok.com'))
        self.assertTrue(shortlinks._is_trusted_host('tiktok.com'))
        self.assertFalse(shortlinks._is_trusted_host('nottiktok.com'))
        self.assertFalse(shortlinks._is_trusted_host('tiktok.com.evil.example'))
        self.assertFalse(shortlinks._is_trusted_host(None))


class ResolveShortUrl(unittest.IsolatedAsyncioTestCase):
    """Runs the real resolver against a local fake 'TikTok' server."""

    async def asyncSetUp(self):
        self.hits = []

        def redirect(location, status=301):
            async def handler(request):
                self.hits.append(request.path)
                raise web.HTTPMovedPermanently(location) if status == 301 else web.HTTPFound(location)
            return handler

        app = web.Application()
        app.router.add_get('/s/one', redirect('/full/video?_r=1&_t=abc'))
        app.router.add_get('/s/chain', redirect('/s/one', 302))
        app.router.add_get('/s/loop', redirect('/s/loop'))
        app.router.add_get('/s/evil', redirect('http://evil.example/steal'))
        async def dead(request):
            return web.Response(status=404)

        async def video(request):
            return web.Response(text='video page')

        app.router.add_get('/s/dead', dead)
        app.router.add_get('/full/video', video)
        self.server = TestServer(app)
        await self.server.start_server()
        self.base = f'http://127.0.0.1:{self.server.port}'

        # Point the resolver's allowlist at the fake server
        for patcher in (
            mock.patch.object(shortlinks, 'is_short_link', lambda url: '/s/' in url),
            mock.patch.object(shortlinks, '_is_trusted_host', lambda host: host == '127.0.0.1'),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await self.server.close()

    async def test_follows_redirect_to_full_url(self):
        self.assertEqual(await shortlinks.resolve_short_url(f'{self.base}/s/one'), f'{self.base}/full/video?_r=1&_t=abc')

    async def test_does_not_fetch_the_final_page(self):
        await shortlinks.resolve_short_url(f'{self.base}/s/one')
        self.assertEqual(self.hits, ['/s/one'])

    async def test_follows_chains(self):
        self.assertEqual(await shortlinks.resolve_short_url(f'{self.base}/s/chain'), f'{self.base}/full/video?_r=1&_t=abc')

    async def test_preserves_trailing_punctuation(self):
        self.assertEqual(await shortlinks.resolve_short_url(f'{self.base}/s/one>'), f'{self.base}/full/video?_r=1&_t=abc>')

    async def test_refuses_redirect_to_untrusted_host(self):
        url = f'{self.base}/s/evil'
        self.assertEqual(await shortlinks.resolve_short_url(url), url)

    async def test_gives_up_on_loops_after_max_hops(self):
        url = f'{self.base}/s/loop'
        self.assertEqual(await shortlinks.resolve_short_url(url), url)
        self.assertLessEqual(len(self.hits), shortlinks.MAX_HOPS)

    async def test_returns_original_on_non_redirect(self):
        url = f'{self.base}/s/dead'
        self.assertEqual(await shortlinks.resolve_short_url(url), url)

    async def test_returns_original_when_unreachable(self):
        url = 'http://127.0.0.1:1/s/x'
        self.assertEqual(await shortlinks.resolve_short_url(url), url)


class NonShortLinksAreNeverRequested(unittest.IsolatedAsyncioTestCase):
    async def test_regular_urls_untouched(self):
        with mock.patch('aiohttp.ClientSession') as session:
            for url in ('https://example.com/a?b=c', 'https://www.tiktok.com/@u/video/1', 'https://evil.example/vm.tiktok.com/x'):
                self.assertEqual(await shortlinks.resolve_short_url(url), url)
            session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
