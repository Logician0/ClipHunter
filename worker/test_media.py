import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from types import SimpleNamespace

import numpy as np

from worker.media import canonical, captions, chat_reactions, chat_heatmap, select, robust, run, render, probe, save, plan_sparse_scan, prepare_clip, extend_clip, fetch_chat, audio_candidates


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

    def test_chat_velocity_finds_burst_without_emojis(self):
        seconds=600
        chat={str(t):[2,0,2] for t in range(seconds)}
        for t in range(200,212):chat[str(t)]=[18,0,15]
        clips=select({'chat':chat_reactions(chat,seconds)},[],seconds)
        self.assertTrue(any(clip['start']<=205<=clip['end'] for clip in clips))

    def test_chat_map_and_candidate_evidence(self):
        chat={str(t):[1,0,1] for t in range(600)}
        for t in range(220,238):chat[str(t)]=[16,6,12]
        map=chat_heatmap(chat,600)
        self.assertEqual(len(map['posts']),40)
        self.assertEqual(sum(map['posts']),600+18*15)
        self.assertGreater(map['posts'][15],map['posts'][0])
        clips=select({'chat':chat_reactions(chat,600)},[],600)
        self.assertTrue(any(c['start']<220<c['end'] and 'viewer posts' in c['reason'] for c in clips))
        self.assertTrue(all(35<=c['end']-c['start']<=65 for c in clips))

    def test_single_account_spam_is_not_a_highlight(self):
        chat={str(t):[1,0,1] for t in range(600)}
        for t in range(220,238):chat[str(t)]=[30,20,1]
        self.assertEqual(select({'chat':chat_reactions(chat,600)},[],600),[])

    def test_youtube_replay_actions_are_counted(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);replay=folder/'chat-replay.live_chat.json.part'
            with replay.open('w') as stream:
                for second in range(0,121):
                    for author in range(4):
                        action={'replayChatItemAction':{'videoOffsetTimeMsec':str(second*1000),
                                'actions':[{'addChatItemAction':{'item':{'liveChatTextMessageRenderer':{
                                'authorExternalChannelId':f'viewer-{author}',
                                'message':{'runs':[{'text':'What a moment'}]}}}}}]}}
                        stream.write(json.dumps(action)+'\n')
            counts=fetch_chat(folder,'https://www.youtube.com/watch?v=abcdefghijk',0,120,
                              {'subtitles':{'live_chat':[{'ext':'json'}]}})
            self.assertEqual(sum(v[0] for v in counts.values()),480)
            self.assertEqual(counts[42][2],4)
            self.assertEqual(json.loads((folder/'chat.json').read_text())['status'],'available')

    def test_audio_only_fallback_finds_speech_energy_rise(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            def fake_download(*_args,**_kwargs):
                samples=np.arange(600*4000)
                seconds=samples/4000
                amplitude=np.where((seconds>=200)&(seconds<214),.5,.008)
                signal=(np.sin(2*math.pi*400*seconds)*amplitude*32767).astype('<i2')
                with wave.open(str(folder/'audio-scan.wav'),'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(4000);out.writeframes(signal.tobytes())
            class FakeModel:
                def __init__(self,*_args,**_kwargs):pass
                def transcribe(self,*_args,**_kwargs):
                    return [SimpleNamespace(text='Wow what happened in that game',avg_logprob=-.2)],None
            with patch('worker.media.run_progress',side_effect=fake_download),patch('faster_whisper.WhisperModel',FakeModel):
                clips=audio_candidates(folder,'https://www.youtube.com/watch?v=abcdefghijk',0,600)
            self.assertTrue(any(clip['start']<=205<=clip['end'] for clip in clips))
            self.assertFalse(list(folder.glob('audio-scan.*')))

    def test_sparse_scan_indexes_chat_without_downloading_video(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            chat={str(t):[8,7,5] for t in range(120,130)}
            with patch('worker.media.run',return_value=json.dumps({'duration':3600,'is_live':False,'title':'Test'}).encode()),patch('worker.media.fetch_chat',return_value=chat):
                clips=plan_sparse_scan('https://www.youtube.com/watch?v=abcdefghijk',1,folder)
            self.assertTrue(clips)
            self.assertFalse((folder/'source.mp4').exists())
            self.assertTrue(json.loads((folder/'source.json').read_text())['sparse'])

    def test_prepared_clip_contains_edit_handles(self):
        with tempfile.TemporaryDirectory() as d:
            parent=Path(d)
            save(parent/'source.json',{'start':0,'end':600,'duration':600})
            clip=parent/'highlight-1'
            def fake_download(args,progress,duration,phase,timeout):
                run(['ffmpeg','-v','error','-f','lavfi','-i',f'testsrc2=size=128x72:rate=2:duration={duration}',
                     '-c:v','libx264',clip/'capture.mp4'])
            with patch('worker.media.run_progress',side_effect=fake_download):
                start,end=prepare_clip(clip,1,'https://www.youtube.com/watch?v=abcdefghijk',1,100,142)
            self.assertEqual((start,end),(45,87))
            self.assertTrue((clip/'source.mp4').exists())
            self.assertTrue((clip/'signals.json').exists())

    def test_extend_downloads_only_missing_source_range(self):
        with tempfile.TemporaryDirectory() as d:
            parent=Path(d);clip=parent/'highlight-1';clip.mkdir()
            save(parent/'source.json',{'start':0,'end':500})
            save(clip/'source.json',{'start':100,'end':125,'sparse':True,'url':'https://www.youtube.com/watch?v=abcdefghijk'})
            save(clip/'layout.json',{'mode':'full','width':128,'height':72,'facecamBox':None})
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=2:duration=25','-c:v','libx264',clip/'source.mp4'])
            requested=[]
            def fake_download(args,progress,duration,phase,timeout):
                requested.append((duration,phase))
                output=Path(str(args[args.index('-o')+1]).replace('%(ext)s','mp4'))
                run(['ffmpeg','-v','error','-f','lavfi','-i',f'testsrc2=size=128x72:rate=2:duration={duration}','-c:v','libx264',output])
            with patch('worker.media.run_progress',side_effect=fake_download):
                shift=extend_clip(clip,'before',seconds=30)
            self.assertAlmostEqual(shift,30,places=1)
            self.assertEqual(requested,[(30,'Downloading extra footage')])
            self.assertAlmostEqual(float(probe(clip/'source.mp4')['format']['duration']),55,places=1)
            self.assertEqual(json.loads((clip/'source.json').read_text())['start'],70)

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
            self.assertEqual((video["width"],video["height"]),(480,854))
            self.assertAlmostEqual(float(info["format"]["duration"]),20,places=1)

    def test_export_quality_720_vertical(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=2:duration=21','-c:v','libx264',folder/'source.mp4'])
            save(folder/'signals.json',{'focus':[.5]*21})
            save(folder/'layout.json',{'mode':'full','width':128,'height':72})
            save(folder/'export-55.json',{'width':720})
            target=folder/'clip-55.mp4'
            render(folder,0,20,target)
            video=next(s for s in probe(target)['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(720,1280))


if __name__=="__main__":
    unittest.main()
