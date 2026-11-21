import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from worker.media import canonical, captions, chat_reactions, select, robust, run, render, probe, save


class WorkerTests(unittest.TestCase):
    def test_platform_urls(self):
        expected="https://www.youtube.com/watch?v=abcdefghijk"
        for url in ("https://youtu.be/abcdefghijk?t=5","https://youtube.com/live/abcdefghijk",expected,
                    "abcdefghijk","https://studio.youtube.com/video/abcdefghijk/edit"):
            self.assertEqual(canonical(url),expected)
        for url in ("https://twitch.tv/videos/123","https://kick.com/test","https://kick.com/video/ab-cd"):
            self.assertEqual(canonical(url),url)
        for url in ("https://evil.example/", "https://youtube.com.evil.test/watch?v=abcdefghijk","file:///tmp/a","https://twitch.tv:1234/videos/5"):
            with self.assertRaises(ValueError): canonical(url)

    def test_selection(self):
        for seconds in (34,35,40,42,360,3600,4199):
            chat={str(t):[8,7,5] for center in range(60,seconds,180) for t in range(center,min(seconds,center+8))}
            features={"chat":chat_reactions(chat,seconds)}
            result=select(features,[],seconds)
            if seconds<=42:
                self.assertFalse(result)
                continue
            self.assertGreater(len(result),0)
            self.assertLessEqual(len(result),5)
            for item in result:
                self.assertGreaterEqual(item["start"],0)
                self.assertLessEqual(item["end"],seconds)
                self.assertTrue(35<=item["end"]-item["start"]<=50)
            for first,second in zip(result,result[1:]):
                self.assertGreaterEqual(second["start"]-first["end"],120)

    def test_speech_or_steady_chat_does_not_create_highlights(self):
        seconds=600
        speech=[{"s":t,"e":t+.4,"w":"wow"} for t in range(seconds)]
        steady={str(t):[1,0,1] for t in range(seconds)}
        self.assertEqual(select({"score":[100.]*seconds,"chat":chat_reactions(steady,seconds)},speech,seconds),[])
        self.assertEqual(select({"score":[100.]*seconds},speech,seconds),[])

    def test_caption_timeline(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            words=[{"s":1+i*.4,"e":1.35+i*.4,"w":"clip"} for i in range(9)]
            timeline=captions(words,0,8,folder,360)
            self.assertEqual(len(list(folder.glob("text*.png"))),3)
            durations=[float(line.split()[1]) for line in timeline.read_text().splitlines() if line.startswith("duration ")]
            self.assertAlmostEqual(sum(durations),8)
            self.assertTrue(all(d>0 for d in durations))

    def test_constant_signal(self):
        self.assertTrue(np.all(robust(np.full(15,17))==0))

    def test_trimmed_render_duration(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            run(["ffmpeg","-v","error","-f","lavfi","-i","color=black:size=128x72:rate=2:duration=25",
                 "-c:v","libx264",folder/"source.mp4"])
            save(folder/"signals.json",{"focus":[.5]*25})
            save(folder/"layout.json",{"mode":"full","width":128,"height":72})
            save(folder/"transcript.json",{"words":[]})
            target=folder/"preview-test.mp4"
            render(folder,2,22,target)
            self.assertAlmostEqual(float(probe(target)["format"]["duration"]),20,places=1)

    def test_clip_edit_changes_preview_layout(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=size=128x72:rate=30:duration=22",
                 "-f","lavfi","-i","sine=frequency=440:duration=22","-c:v","libx264","-c:a","aac",folder/"source.mp4"])
            save(folder/"signals.json",{"focus":[.5]*22})
            save(folder/"layout.json",{"mode":"full","width":128,"height":72})
            save(folder/"transcript.json",{"words":[{"w":"Edited","s":3,"e":4}]})
            save(folder/"edit-99.json",{"layoutMode":"split","gameBox":[0,0,.5,1],"facecamBox":[.5,0,.5,1],
                 "facecamFraction":.35,"captionTemplate":"accent","font":"Impact.ttf","fontSize":40,
                 "textColor":"#00ff00","boxColor":"#111111"})
            target=folder/"preview-99.mp4"
            render(folder,1,21,target)
            info=probe(target)
            video=next(s for s in info["streams"] if s["codec_type"]=="video")
            self.assertEqual((video["width"],video["height"]),(360,640))
            self.assertAlmostEqual(float(info["format"]["duration"]),20,places=1)


if __name__=="__main__":
    unittest.main()
