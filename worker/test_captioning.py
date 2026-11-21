import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.captioning import transcribe_clip
from worker.media import captions


class CaptioningTest(unittest.TestCase):
    def test_groups_recognized_words_and_reports_language(self):
        class Model:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, **kwargs):
                words = [
                    types.SimpleNamespace(start=.1, end=.5, word=' नमस्ते'),
                    types.SimpleNamespace(start=.6, end=1.1, word=' दोस्तों'),
                ]
                piece = types.SimpleNamespace(words=words, text='', start=0, end=1.1)
                return iter([piece]), types.SimpleNamespace(language='hi', language_probability=.98)

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'chunks' / '1' / 'source.mp4'
            source.parent.mkdir(parents=True)
            source.touch()
            with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}):
                with patch('worker.captioning.subprocess.run'):
                    result = transcribe_clip(source, 10, 15)
        self.assertEqual(result['language'], 'hi')
        self.assertEqual(result['segments'], [{'start': 10.1, 'end': 11.1, 'text': 'नमस्ते दोस्तों'}])

    def test_auto_retries_garbled_hindi_detection_as_english(self):
        class Model:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, language=None, **kwargs):
                if language == 'en':
                    words = [types.SimpleNamespace(start=.1, end=.9, word=' Welcome')]
                    piece = types.SimpleNamespace(words=words, text='Welcome', start=.1, end=.9, avg_logprob=-.3)
                    return iter([piece]), types.SimpleNamespace(language='en', language_probability=1)
                words = [types.SimpleNamespace(start=.1, end=.9, word=' ङङङ')]
                piece = types.SimpleNamespace(words=words, text='ङङङ', start=.1, end=.9, avg_logprob=-2)
                return iter([piece]), types.SimpleNamespace(language='hi', language_probability=.7)

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'chunks' / '1' / 'source.mp4'
            source.parent.mkdir(parents=True)
            source.touch()
            with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}):
                with patch('worker.captioning.subprocess.run'):
                    result = transcribe_clip(source, 10, 15)
        self.assertEqual(result['language'], 'en')
        self.assertIsNone(result['confidence'])
        self.assertEqual(result['segments'][0]['text'], 'Welcome')

    def test_custom_hindi_and_explicit_no_captions(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            self.assertIsNone(captions([], 0, 2, directory, 360, custom=[]))
            manifest = captions([], 0, 2, directory, 360, custom=[{'start': .1, 'end': 1.2, 'text': 'नमस्ते'}])
            self.assertTrue(manifest.exists())
            self.assertTrue((directory / 'text0.png').exists())


if __name__ == '__main__':
    unittest.main()
