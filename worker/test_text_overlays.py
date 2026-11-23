import tempfile
import unittest
from pathlib import Path

from PIL import Image

from worker.media import compose, run, save
from worker.text_overlays import validate_text_overlays


class TextOverlayTests(unittest.TestCase):
    def test_validation_rejects_invalid_timing_and_colors(self):
        valid={'id':'title1','text':'A big moment','start':1,'end':5,'x':.5,'y':.24,
               'size':64,'color':'#ffffff','background':'#000000'}
        self.assertEqual(validate_text_overlays([valid],20)[0]['text'],'A big moment')
        for change in ({'end':21},{'x':1.2},{'color':'red'},{'text':'bad\nline'}):
            with self.assertRaises(ValueError):
                validate_text_overlays([{**valid,**change}],20)

    def test_export_shows_text_only_inside_its_timed_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=5:d=22',
                 '-c:v','libx264',folder/'source.mp4'])
            save(folder/'signals.json',{'focus':[.5]*22})
            save(folder/'layout.json',{'mode':'full','width':320,'height':180,'facecamBox':None})
            save(folder/'edit-1.json',{'layoutMode':'full','captionMode':'off','textOverlays':[
                {'id':'title1','text':'GOAL [1]: wow','start':1,'end':5,'x':.5,'y':.24,
                 'size':64,'color':'#ffffff','background':'#000000'}]})
            compose(folder,0,20,folder/'preview-1.mp4')
            for second,name in ((2,'active'),(10,'inactive')):
                run(['ffmpeg','-v','error','-ss',str(second),'-i',folder/'preview-1.mp4',
                     '-frames:v','1',folder/f'{name}.png'])
            active=Image.open(folder/'active.png').convert('RGB')
            inactive=Image.open(folder/'inactive.png').convert('RGB')
            self.assertNotEqual(active.getpixel((240,205)),inactive.getpixel((240,205)))


if __name__=='__main__':unittest.main()
