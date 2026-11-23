import tempfile
import unittest
from pathlib import Path

from worker.media import compose, probe, run, save


class AudioLayerTests(unittest.TestCase):
    def test_extra_audio_layer_renders_with_source_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=5:d=21',
                 '-f','lavfi','-i','sine=frequency=440:duration=21','-c:v','libx264','-c:a','aac',folder/'source.mp4'])
            run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=8',
                 '-c:a','libmp3lame','-f','mp3',folder/'music-1.bin'])
            save(folder/'signals.json',{'focus':[.5]*21})
            save(folder/'layout.json',{'mode':'full','width':320,'height':180,'facecamBox':None})
            save(folder/'edit-1.json',{'layoutMode':'full','captionMode':'off','sourceVolume':.7,
                                      'musicVolume':.5,'musicStart':2,'textOverlays':[]})
            compose(folder,0,20,folder/'preview-1.mp4')
            result=probe(folder/'preview-1.mp4')
            self.assertTrue(any(stream['codec_type']=='audio' for stream in result['streams']))
            self.assertAlmostEqual(float(result['format']['duration']),20,delta=.15)

    def test_extra_audio_layer_renders_when_source_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=5:d=21',
                 '-c:v','libx264',folder/'source.mp4'])
            run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=5',
                 '-c:a','libmp3lame','-f','mp3',folder/'music-1.bin'])
            save(folder/'signals.json',{'focus':[.5]*21})
            save(folder/'layout.json',{'mode':'full','width':320,'height':180,'facecamBox':None})
            save(folder/'edit-1.json',{'layoutMode':'full','captionMode':'off','musicStart':3,'textOverlays':[]})
            compose(folder,0,20,folder/'preview-1.mp4')
            result=probe(folder/'preview-1.mp4')
            self.assertTrue(any(stream['codec_type']=='audio' for stream in result['streams']))


if __name__=='__main__':unittest.main()
