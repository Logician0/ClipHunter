import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from worker import youtube_auth

class CookieTests(unittest.TestCase):
    def test_import_only_youtube_cookies(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'private'/'youtube-cookies.txt'
            with patch.object(youtube_auth,'COOKIE_FILE',target):
                source='# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tvalue\n'
                youtube_auth.save_cookies(source)
                self.assertEqual(youtube_auth.cookie_args('https://www.youtube.com/watch?v=abcdefghijk'),['--cookies',str(target)])
                self.assertEqual(youtube_auth.cookie_args('https://twitch.tv/example'),[])
                self.assertEqual(target.stat().st_mode & 0o777,0o600)
                with self.assertRaises(ValueError):
                    youtube_auth.save_cookies(source+'.evil.example\tTRUE\t/\tTRUE\t0\tBAD\tvalue\n')
                self.assertEqual(target.read_text(),source)
