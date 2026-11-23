import unittest

from worker.caption_export import render_srt


class CaptionExportTests(unittest.TestCase):
    def test_rebases_and_clips_lines_to_exported_range(self):
        srt=render_srt([
            {'start':9.5,'end':11.25,'text':'Hello'},
            {'start':12,'end':15.5,'text':'नमस्ते'},
            {'start':20,'end':21,'text':'Outside'},
        ],10,15)
        self.assertIn('00:00:00,000 --> 00:00:01,250\nHello',srt)
        self.assertIn('00:00:02,000 --> 00:00:05,000\nनमस्ते',srt)
        self.assertNotIn('Outside',srt)


if __name__=='__main__':unittest.main()
