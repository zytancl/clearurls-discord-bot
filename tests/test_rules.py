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



# Every parameter listed on https://www.untracklink.com/tracking-parameters, with
# the kinds of link it has to be stripped from.
G = 'https://example.com/page?id=7'
YT='https://www.youtube.com/watch?v=abcDEF12345'
SP='https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC'
RD='https://www.reddit.com/r/test/comments/abc123/title/'
X ='https://x.com/user/status/1234567890'
TW='https://twitter.com/user/status/1234567890'
PIN='https://www.pinterest.com/pin/1234567890/'
TH='https://www.threads.net/@user/post/Cabc123'
TH2='https://www.threads.com/@user/post/Cabc123'
LI='https://www.linkedin.com/posts/user_activity-123'
SC='https://www.snapchat.com/add/user'
SC2='https://www.snapchat.com/spotlight/abc'
FB='https://www.facebook.com/user/posts/123'
IG='https://www.instagram.com/p/Cabc123/'
TT='https://www.tiktok.com/@user/video/7593109045465140511'
MATRIX = {
 'context':[SP], 'dclid':[G], 'fbclid':[G], 'feature':[YT], 'gbraid':[G], 'gclid':[G],
 'igsh':[IG], 'igshid':[IG], 'invite_code':[PIN], 'is_from_webapp':[TT], 'li_fat_id':[G,LI],
 'locale':[SC], 'mc_cid':[G], 'mc_eid':[G], 'mibextid':[FB], 'msclkid':[G], 'nd':[SP], 'pp':[YT],
 'rcm':[LI], 'rdid':[FB], 'ref':[G,FB], 'ref_src':[X,TW], 's':[X,TW], 'sec_uid':[TT],
 'sender_device':[TT], 'sender_id':[PIN], 'sfnsn':[FB], 'share_app_id':[TT], 'share_id':[RD,SC,SC2],
 'share_link_id':[TT], 'si':[YT,SP], 'sid':[SC,SC2], 'slof':[TH,TH2], 'social_sharing':[TT],
 't':[X,TW], 'trackingId':[LI], 'trk':[LI], 'ttclid':[G], 'twclid':[G],
 'utm_campaign':[G], 'utm_content':[G], 'utm_id':[G], 'utm_medium':[G], 'utm_name':[RD],
 'utm_source':[G], 'utm_term':[G], 'u_code':[TT], 'wbraid':[G], 'xmt':[TH,TH2], 'yclid':[G],
 '_hsenc':[G], '_hsmi':[G], '_r':[TT], '_t':[TT], '__cft__[0]':[FB], '__tn__':[FB],
}
SAMPLE = 'AbC123xyZ'


class PlatformTrackingParameters(unittest.TestCase):
    def test_every_listed_parameter_is_stripped(self):
        for param, bases in MATRIX.items():
            for base in bases:
                with self.subTest(param=param, url=base):
                    url = base + ('&' if '?' in base else '?') + f'{param}={SAMPLE}'
                    cleaned = clear_url(url)
                    self.assertNotIn(SAMPLE, cleaned)
                    self.assertEqual(cleaned, base)

    def test_works_alongside_functional_params(self):
        url = 'https://www.threads.net/@user/post/Cabc123?foo=bar'
        self.assertEqual(clear_url(url + '&slof=1&xmt=abc'), url)
        url = 'https://www.pinterest.co.uk/pin/123/?x=1'
        self.assertEqual(clear_url(url + '&invite_code=abc&sender_id=9'), url)


class FunctionalParametersAreKept(unittest.TestCase):
    """Parameters whose names are only tracking on one platform must survive everywhere else."""

    def test_youtube_start_time_kept(self):
        # `t` is stripped on X/Twitter but is a start time on YouTube
        url = 'https://www.youtube.com/watch?v=abcDEF12345&t=90s'
        self.assertEqual(clear_url(url), url)
        self.assertEqual(clear_url('https://youtu.be/abcDEF12345?t=90&si=abc'), 'https://youtu.be/abcDEF12345?t=90')

    def test_reddit_comment_context_kept(self):
        url = 'https://www.reddit.com/r/test/comments/abc123/title/def456/?context=3'
        self.assertEqual(clear_url(url), url)

    def test_platform_scoped_names_untouched_on_other_sites(self):
        url = 'https://example.com/page?id=7&context=3&nd=1&sid=5&locale=en&slof=1&xmt=2&rcm=3&rdid=4&sender_id=6&invite_code=7&share_id=8'
        self.assertEqual(clear_url(url), url)

    def test_similarly_named_params_untouched(self):
        for url in ('https://www.snapchat.com/add/user?sidebar=1&locale_override=x',
                    'https://open.spotify.com/track/abc?ndx=1&context_menu=2',
                    'https://www.tiktok.com/@u/video/1?share_app_name_x=1'):
            with self.subTest(url=url):
                self.assertEqual(clear_url(url), url)

    def test_lookalike_domains_untouched(self):
        for url in ('https://notpinterest.com/pin/1?sender_id=5', 'https://notthreads.net/post/1?slof=1'):
            with self.subTest(url=url):
                self.assertEqual(clear_url(url), url)

    def test_pinterest_other_tlds_covered(self):
        self.assertEqual(clear_url('https://www.pinterest.fr/pin/1/?invite_code=x'), 'https://www.pinterest.fr/pin/1/')
        self.assertEqual(clear_url('https://br.pinterest.com/pin/1/?sender_id=x'), 'https://br.pinterest.com/pin/1/')


if __name__ == '__main__':
    unittest.main()
