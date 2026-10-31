import unittest

from unalix import clear_url


class YouTubeRules(unittest.TestCase):
    # Issue #12
    def test_is_param_removed_from_shorts(self):
        self.assertEqual(clear_url('https://youtube.com/shorts/abcDEF12345?is=XyZ123abc'),
                         'https://youtube.com/shorts/abcDEF12345')

    def test_is_param_removed_from_normal_videos(self):
        self.assertEqual(clear_url('https://www.youtube.com/watch?v=abcDEF12345&is=XyZ123abc'),
                         'https://www.youtube.com/watch?v=abcDEF12345')
        self.assertEqual(clear_url('https://youtu.be/abcDEF12345?is=XyZ123abc'),
                         'https://youtu.be/abcDEF12345')

    def test_si_param_still_removed(self):
        self.assertEqual(clear_url('https://youtu.be/abcDEF12345?si=XyZ123abc'),
                         'https://youtu.be/abcDEF12345')

    def test_functional_params_kept(self):
        url = 'https://www.youtube.com/watch?v=abcDEF12345&t=30s&list=PL123'
        self.assertEqual(clear_url(url + '&is=abc'), url)

    def test_params_that_merely_contain_is_are_kept(self):
        url = 'https://www.youtube.com/watch?v=abcDEF12345&this=1&exists=2'
        self.assertEqual(clear_url(url), url)


class TikTokRules(unittest.TestCase):
    # Issue #10 (desktop share links)
    def test_desktop_share_params_removed(self):
        url = 'https://www.tiktok.com/@jdhperc/video/7593109045465140511'
        dirty = url + '?_t=8abc&_r=1&is_from_webapp=1&is_copy_url=1&sender_device=pc&sender_web_id=123&web_id=456'
        self.assertEqual(clear_url(dirty), url)


if __name__ == '__main__':
    unittest.main()
