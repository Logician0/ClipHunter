import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.captioning import transcribe_clip
from worker.media import captions


class CaptioningTest(unittest.TestCase):
    def test_large_v3_translates_selected_clip_to_english(self):
        observed=[]
        class Model:
            def __init__(self,name,*args,**kwargs):observed.append(name)
            def transcribe(self,*args,**kwargs):
                observed.append(kwargs['task'])
                piece=types.SimpleNamespace(words=[types.SimpleNamespace(start=.1,end=.7,word=' Hello')],text='Hello',start=.1,end=.7)
                return iter([piece]),types.SimpleNamespace(language='fr',language_probability=.9)
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'chunks'/'1'/'source.mp4';source.parent.mkdir(parents=True);source.touch()
            with patch.dict(sys.modules,{'faster_whisper':types.SimpleNamespace(WhisperModel=Model)}),patch('worker.captioning.subprocess.run'):
                result=transcribe_clip(source,10,15,output='en')
        self.assertEqual(observed,['large-v3','translate'])
        self.assertEqual(result['captionLanguage'],'en')
        self.assertEqual(result['language'],'fr')

    def test_selected_caption_language_keeps_word_timing(self):
        class Model:
            def __init__(self,*args,**kwargs):pass
            def transcribe(self,*args,**kwargs):
                self.task=kwargs['task']
                piece=types.SimpleNamespace(words=[types.SimpleNamespace(start=.1,end=.7,word=' Hello')],text='Hello',start=.1,end=.7)
                return iter([piece]),types.SimpleNamespace(language='en',language_probability=.99)
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'chunks'/'1'/'source.mp4';source.parent.mkdir(parents=True);source.touch()
            translated=[{'start':10.1,'end':10.7,'text':'Hola'}]
            with patch.dict(sys.modules,{'faster_whisper':types.SimpleNamespace(WhisperModel=Model)}),patch('worker.captioning.subprocess.run'),patch('worker.captioning.translate_captions',return_value=translated) as translate:
                result=transcribe_clip(source,10,15,output='es')
        translate.assert_called_once()
        self.assertEqual(result['captionLanguage'],'es')
        self.assertEqual(result['segments'],translated)

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

    def test_unicode_caption_frame(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            manifest=captions([],0,2,directory,360,custom=[{'start':.1,'end':1.2,'text':'こんにちは 世界'}])
            self.assertTrue(manifest.exists())
            self.assertTrue((directory/'text0.png').exists())


if __name__ == '__main__':
    unittest.main()
