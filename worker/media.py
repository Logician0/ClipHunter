"""ClipHunter's local, one-hour media worker. All candidate times are chunk-relative."""
import collections
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def run(args, timeout=4200, **kw):
    result = subprocess.run(list(map(str, args)), capture_output=True, timeout=timeout, **kw)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1300:].strip() or "Media operation failed.")
    return result.stdout


def run_progress(args,path,duration,phase,timeout=900,base=0,span=1):
    """Record measured media progress and ETA without inventing a percentage."""
    path=Path(path)
    begun=time.monotonic();last=0;tail=collections.deque(maxlen=24)
    save(path,{'phase':phase,'fraction':base,'etaSeconds':None})
    with subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as proc:
        watchdog=threading.Timer(timeout,proc.kill)
        watchdog.start()
        try:
            for line in proc.stdout:
                tail.append(line)
                fraction=None
                percent=re.search(r'\[download\]\s+([0-9.]+)%',line)
                stamp=re.search(r'(?:time=|out_time=)(\d+):(\d+):(\d+(?:\.\d+)?)',line)
                if percent:fraction=min(.98,float(percent[1])/100)
                elif stamp and duration:
                    seconds=int(stamp[1])*3600+int(stamp[2])*60+float(stamp[3])
                    fraction=min(.98,seconds/duration)
                now=time.monotonic()
                if fraction is not None and now-last>.6:
                    eta=(now-begun)*(1-fraction)/fraction if fraction>.02 else None
                    save(path,{'phase':phase,'fraction':round(base+span*fraction,3),'etaSeconds':round(eta) if eta is not None else None})
                    last=now
                if now-begun>timeout:proc.kill();raise subprocess.TimeoutExpired(args,timeout)
            code=proc.wait(timeout=max(1,timeout-(time.monotonic()-begun)))
        except Exception:
            proc.kill();proc.wait();raise
        finally:
            watchdog.cancel()
    if time.monotonic()-begun>=timeout:
        raise subprocess.TimeoutExpired(args,timeout)
    if code:raise RuntimeError(''.join(tail)[-1300:].strip() or f'{phase} failed.')
    save(path,{'phase':phase,'fraction':round(base+span,3),'etaSeconds':0})


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf8")
    temp.replace(path)


def canonical(url):
    url=url.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{11}',url):
        return 'https://www.youtube.com/watch?v='+url
    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        raise ValueError("Use a public HTTPS stream link.")
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    if host in ("youtube.com", "youtu.be", "studio.youtube.com"):
        vid = (parse_qs(u.query).get("v", [""])[0] if u.path == "/watch" and host == "youtube.com"
               else u.path.strip("/") if host == "youtu.be" else u.path.removeprefix("/live/") if u.path.startswith("/live/") else
               u.path.split('/')[2] if host == 'studio.youtube.com' and re.fullmatch(r'/video/[A-Za-z0-9_-]{11}/(?:edit|analytics|comments)?/?',u.path) else "")
        if re.fullmatch(r"[a-zA-Z0-9_-]{11}", vid):
            return "https://www.youtube.com/watch?v=" + vid
    patterns = {"twitch.tv": r"/(?:videos/[0-9]+|[A-Za-z0-9_]+)/?", "kick.com": r"/(?:video/[a-fA-F0-9-]+|[A-Za-z0-9_-]+)/?"}
    if host in patterns and re.fullmatch(patterns[host], u.path):
        return "https://" + host + u.path.rstrip("/")
    raise ValueError("This link is not supported yet. Try a YouTube, Twitch or Kick stream link.")


def probe(path):
    return json.loads(run(["ffprobe","-v","error","-show_format","-show_streams","-of","json",path], timeout=30))


def ingest(url, hour, folder):
    from worker.youtube_auth import cookie_args
    if hour < 1:
        raise ValueError("Hour numbers start at one.")
    if shutil.disk_usage(folder).free < 10_000_000_000:
        raise RuntimeError("Not enough disk space. Free at least 10 GB.")
    ytdlp = [sys.executable, "-m", "yt_dlp", "--ignore-config","--js-runtimes","node",*cookie_args(url),"--no-playlist","--no-warnings","--socket-timeout","20","--retries","3","--concurrent-fragments","8"]
    choice = "bv*[height<=480]+ba/b[height<=480]/b"
    meta = json.loads(run(ytdlp + ["-J","-f",choice,"--",url], timeout=120))
    start = (hour-1)*3600
    duration = meta.get("duration") or 0
    live = meta.get("is_live",False)
    if meta.get("live_status") == "is_upcoming":
        raise ValueError("This stream has not started.")
    if not live and duration and (start>=duration or (hour>1 and duration-start<600)):
        raise ValueError("You have reached the end of the stream.")
    end = min(start+3600,duration) if duration else start+3600
    if duration and 0 < duration-end < 600:
        end = duration
    formats = meta.get('requested_formats') or [meta]
    bitrate = sum(float(fmt.get('tbr') or 0) for fmt in formats)
    if bitrate > 0:
        estimate_seconds = duration if duration and duration <= 7200 else end-start
        save(folder/'download-estimate.json',{'bytes':round(bitrate*1000/8*estimate_seconds),'approximate':True})
    if live:
        args = ["ffmpeg","-nostdin","-v","error","-y"]
        for fmt in formats:
            args += ["-i",fmt["url"]]
        args += ["-map","0:v:0","-map",("1:a:0?" if len(formats)>1 else "0:a:0?"),"-t","3600","-c","copy",folder/"capture.mp4"]
        run(args, timeout=3900)
    else:
        cached = False
        if duration and duration <= 7200:
            cache_name="cache-"+hashlib.sha256(url.encode()).hexdigest()[:16]
            cache=folder.parent/(cache_name+".mp4")
            if not cache.exists():
                native="bv[height<=480][ext=mp4][protocol=https]+ba[ext=m4a][protocol=https]"
                try:
                    run(ytdlp+["-f",native,"--merge-output-format","mp4","-o",
                               str(folder.parent/(cache_name+".%(ext)s")),"--",url])
                except (RuntimeError,subprocess.TimeoutExpired):
                    pass
            if cache.exists():
                run(["ffmpeg","-nostdin","-v","error","-y","-ss",str(start),"-i",cache,
                     "-t",str(end-start),"-c","copy","-avoid_negative_ts","make_zero",folder/"capture.mp4"],timeout=240)
                cached=True
        if not cached:
            run(ytdlp + ["--force-overwrites","-f",choice,"--download-sections",f"*{start}-{end}",
                         "--merge-output-format","mp4","--remux-video","mp4",
                         "-o",str(folder/"capture.%(ext)s"),"--",url])
    media = folder/"capture.mp4"
    if not media.is_file():
        raise RuntimeError("The download finished without a readable video.")
    info = probe(media)
    if not any(s["codec_type"]=="video" for s in info["streams"]):
        raise RuntimeError("The downloaded file has no video stream.")
    if not live and duration and not .95*(end-start)<=float(info["format"]["duration"])<=1.05*(end-start)+4:
        raise RuntimeError("The stream download ended early. Please retry the scan.")
    media.replace(folder/"source.mp4")
    save(folder/"source.json", {"title":meta.get("title"),"url":url,"hour":hour,"live":live,"duration":duration,"start":start,"end":end})


def plan_sparse_scan(url,hour,folder,metadata=None):
    """Read VOD chat before transferring any video bytes."""
    from worker.youtube_auth import cookie_args
    folder=Path(folder)
    save(folder/'scan-progress.json',{'phase':'Inspecting stream','fraction':.02,'etaSeconds':None})
    command=[sys.executable,"-m","yt_dlp","--ignore-config","--js-runtimes","node",*cookie_args(url),"--no-playlist","--no-warnings","--skip-download","-J","--",url]
    meta=metadata if metadata is not None else json.loads(run(command,timeout=120))
    if meta.get("is_live") or not meta.get("duration"):
        return None
    duration=float(meta['duration'])
    hour_start=(hour-1)*3600
    if hour_start>=duration:raise ValueError('You have reached the end of the stream.')
    hour_end=min(hour_start+3600,duration)
    chat=fetch_chat(folder,url,hour_start,hour_end-hour_start,meta)
    candidates=select({'chat':chat_reactions(chat,hour_end-hour_start)},[],hour_end-hour_start)
    if not candidates:
        candidates=audio_candidates(folder,url,hour_start,hour_end)
    chat_info=json.loads((folder/'chat.json').read_text()) if (folder/'chat.json').exists() else {}
    scan_info=json.loads((folder/'scan-progress.json').read_text()) if (folder/'scan-progress.json').exists() else {}
    method='chat' if candidates and candidates[0].get('source')!='audio' else 'audio' if candidates else 'none'
    warning=scan_info.get('warning') or chat_info.get('warning')
    save(folder/'source.json',{'title':meta.get('title'),'url':url,'hour':hour,'live':False,'sparse':True,
                               'duration':duration,'start':hour_start,'end':hour_end,'scanMethod':method,
                               'chatStatus':chat_info.get('status','unknown'),'scanWarning':warning})
    save(folder/'scan-progress.json',{'phase':'Scan complete','fraction':1,'etaSeconds':0,'message':f'{len(candidates)} suggested moments'})
    return candidates


def prepare_clip(folder,highlight,url,hour,start,end):
    """Download a small edit window around one chosen moment."""
    from worker.youtube_auth import cookie_args
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    if not shutil.disk_usage(folder).free>=2_000_000_000:raise RuntimeError('Free at least 2 GB before downloading a clip.')
    chunk_meta=json.loads((folder.parent/'source.json').read_text())
    hour_start=float(chunk_meta['start']);hour_end=float(chunk_meta['end'])
    absolute_start=hour_start+float(start);absolute_end=hour_start+float(end)
    window_start=max(hour_start,absolute_start-45)
    window_end=min(hour_end,absolute_end+45)
    if window_end-window_start<20:raise ValueError('Not enough stream footage for this clip.')
    command=[sys.executable,'-m','yt_dlp','--ignore-config','--js-runtimes','node',*cookie_args(url),'--no-playlist','--no-warnings','--socket-timeout','20','--retries','3','--concurrent-fragments','8',
             '-f','bv*[height<=480]+ba/b[height<=480]/b','--download-sections',f'*{window_start:.3f}-{window_end:.3f}',
             '--force-keyframes-at-cuts','--merge-output-format','mp4','--remux-video','mp4','-o',folder/'capture.%(ext)s','--',url]
    run_progress([*command[:3],'--newline',*command[3:]],folder/'job-progress.json',window_end-window_start,'Downloading clip window',timeout=900)
    source=folder/'capture.mp4'
    if not source.is_file():raise RuntimeError('The selected video range could not be downloaded.')
    actual=float(probe(source)['format']['duration'])
    if actual < absolute_end-window_start-1:raise RuntimeError('The selected video range ended early. Retry this clip.')
    source.replace(folder/'source.mp4')
    local_start=absolute_start-window_start;local_end=absolute_end-window_start
    save(folder/'source.json',{'url':url,'hour':hour,'live':False,'sparse':True,'start':window_start,'end':window_start+actual,'requestedEnd':window_end})
    layout=detect_layout(folder/'source.mp4')
    save(folder/'layout.json',layout)
    features=signals(folder/'source.mp4',actual,any(s['codec_type']=='audio' for s in probe(folder/'source.mp4')['streams']),layout,[],None)
    save(folder/'signals.json',features)
    return round(local_start,3),round(local_end,3)


def extend_clip(folder,side,seconds=60):
    """Fetch only the missing side of a sparse source, then join it locally."""
    from worker.youtube_auth import cookie_args
    folder=Path(folder)
    meta=json.loads((folder/'source.json').read_text())
    hour=json.loads((folder.parent/'source.json').read_text())
    if not meta.get('sparse') or side not in ('before','after'):raise ValueError('This source cannot be extended.')
    old_start=float(meta['start']);old_end=float(meta['end'])
    if side=='before':
        begin=max(float(hour['start']),old_start-seconds);finish=old_start
    else:
        begin=old_end;finish=min(float(hour['end']),old_end+seconds)
    if finish-begin<2:raise ValueError('No more stream footage is available on that side.')
    with tempfile.TemporaryDirectory(dir=folder,prefix='.extend-') as scratch:
        temp=Path(scratch)
        command=[sys.executable,'-m','yt_dlp','--newline','--ignore-config','--js-runtimes','node',*cookie_args(meta['url']),
                 '--no-playlist','--no-warnings','--socket-timeout','20','--retries','3','-f','bv*[height<=480]+ba/b[height<=480]/b',
                 '--download-sections',f'*{begin:.3f}-{finish:.3f}','--force-keyframes-at-cuts','--merge-output-format','mp4','--remux-video','mp4',
                 '-o',temp/'extra.%(ext)s','--',meta['url']]
        run_progress(command,folder/'job-progress.json',finish-begin,'Downloading extra footage',timeout=600)
        extra=temp/'extra.mp4'
        if not extra.exists():raise RuntimeError('The extra footage did not download.')
        extra_duration=float(probe(extra)['format']['duration'])
        if extra_duration<finish-begin-1:raise RuntimeError('The extra footage ended early.')
        save(folder/'job-progress.json',{'phase':'Joining source windows','fraction':None,'etaSeconds':None})
        parts=[extra,folder/'source.mp4'] if side=='before' else [folder/'source.mp4',extra]
        manifest=temp/'parts.ffconcat'
        manifest.write_text('ffconcat version 1.0\n'+''.join("file '"+str(path).replace("'","'\\''")+"'\n" for path in parts))
        joined=temp/'joined.mp4'
        run(['ffmpeg','-nostdin','-v','error','-y','-f','concat','-safe','0','-i',manifest,'-c','copy','-movflags','+faststart',joined],timeout=180)
        actual=float(probe(joined)['format']['duration'])
        if actual<old_end-old_start+extra_duration-1:raise RuntimeError('The joined source is incomplete.')
        joined.replace(folder/'source.mp4')
    shift=extra_duration if side=='before' else 0
    new_start=begin if side=='before' else old_start
    save(folder/'source.json',{**meta,'start':new_start,'end':new_start+actual})
    save(folder/'job-progress.json',{'phase':'Analyzing extended footage','fraction':None,'etaSeconds':None})
    layout=json.loads((folder/'layout.json').read_text())
    info=probe(folder/'source.mp4')
    features=signals(folder/'source.mp4',actual,any(s['codec_type']=='audio' for s in info['streams']),layout,[],None)
    save(folder/'signals.json',features)
    save(folder/'job-progress.json',{'phase':'Source ready','fraction':1,'etaSeconds':0})
    return shift


def transcribe(media,folder,has_audio,duration=None):
    path = folder/"transcript.json"
    if path.exists():
        return json.loads(path.read_text())["words"]
    words = []
    warning = None
    if has_audio and os.environ.get("CLIPHUNTER_TRANSCRIBE","1") != "0":
        try:
            from faster_whisper import WhisperModel
            model_name=os.environ.get("WHISPER_MODEL","small")
            try:
                model=WhisperModel(model_name,device="cpu",compute_type="int8",cpu_threads=4,local_files_only=True)
            except Exception:
                try:
                    model=WhisperModel("base",device="cpu",compute_type="int8",cpu_threads=4,local_files_only=True)
                except Exception:
                    model=WhisperModel(model_name,device="cpu",compute_type="int8",cpu_threads=4)
            segments, _ = model.transcribe(str(media),beam_size=1,vad_filter=True,word_timestamps=True)
            save(folder/'scan-progress.json',{'phase':'Transcribing','fraction':0})
            for seg in segments:
                words.extend({"w":w.word.strip(),"s":round(w.start,3),"e":round(w.end,3)} for w in seg.words or [] if w.word.strip())
                if duration:save(folder/'scan-progress.json',{'phase':'Transcribing','fraction':min(.99,seg.end/duration)})
        except Exception as e:
            warning = "Transcription unavailable: " + str(e)[:250]
    elif has_audio:
        warning = "Transcription disabled."
    save(path, {"words":words,"warning":warning})
    return words


def detect_layout(media):
    video = cv2.VideoCapture(str(media))
    detector = cv2.CascadeClassifier(cv2.data.haarcascades+"haarcascade_frontalface_default.xml")
    samples = []
    width, height, count = (video.get(key) for key in (cv2.CAP_PROP_FRAME_WIDTH,cv2.CAP_PROP_FRAME_HEIGHT,cv2.CAP_PROP_FRAME_COUNT))
    for i in range(12):
        video.set(cv2.CAP_PROP_POS_FRAMES,int((count-1)*(i+.5)/12))
        ok, frame = video.read()
        if not ok: continue
        scaled = cv2.resize(frame,(640,max(1,round(640*height/width))))
        h,w = scaled.shape[:2]
        faces = detector.detectMultiScale(cv2.cvtColor(scaled,cv2.COLOR_BGR2GRAY),1.12,5,minSize=(18,18))
        samples.append([(float((x+a/2)/w),float((y+b/2)/h),float(a/w),float(b/h)) for x,y,a,b in faces if a/w<.38])
    video.release()
    clusters = []
    for ref in (f for batch in samples for f in batch):
        group = []
        for batch in samples:
            near = [f for f in batch if math.hypot(f[0]-ref[0],f[1]-ref[1])<.07]
            if near: group.append(min(near,key=lambda f:math.hypot(f[0]-ref[0],f[1]-ref[1])))
        clusters.append(group)
    group = max(clusters,key=len,default=[])
    box = None
    face_center = None
    if len(group)>=7:
        x,y,a,b = np.median(group,axis=0)
        face_center = float(x)
        bw,bh = min(1,a*2.4),min(1,b*2.2)
        if not (.25<x<.75 and .2<y<.8 and (bh>.55 or bw>.42)):
            box = [float(np.clip(x-bw/2,0,1-bw)),float(np.clip(y-bh*.42,0,1-bh)),float(bw),float(bh)]
    return {"facecamBox":box,"fullFaceCenter":face_center if box is None else None,
            "width":int(width),"height":int(height),"mode":"split" if box else "full"}


def robust(values):
    values = np.asarray(values,dtype=float)
    med = np.median(values)
    scale = max(1e-6,1.4826*np.median(np.abs(values-med)),np.std(values)*.12)
    return np.clip((values-med)/scale,-2,8)


def _chat_action(action):
    replay=action.get('replayChatItemAction') or {}
    try:at=float(replay.get('videoOffsetTimeMsec',-1000))/1000
    except (ValueError,TypeError):return None
    for entry in replay.get('actions',[]):
        item=(entry.get('addChatItemAction') or {}).get('item') or {}
        renderer=next((v for k,v in item.items() if k.endswith('Renderer') and isinstance(v,dict)),None)
        if not renderer:continue
        message=renderer.get('message') or renderer.get('headerSubtext') or {}
        parts=[]
        for run in message.get('runs',[]):
            if run.get('text'):parts.append(run['text'])
            parts.extend((run.get('emoji') or {}).get('shortcuts') or [])
        body=' '.join(parts) or message.get('simpleText','')
        author=renderer.get('authorExternalChannelId') or (renderer.get('authorName') or {}).get('simpleText') or renderer.get('id')
        return at,body,author
    return None


def _chat_offset(path):
    try:
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-131072))
            lines=stream.read().splitlines()
        for line in reversed(lines):
            try:
                action=json.loads(line)
                replay=action.get('replayChatItemAction') or {}
                return float(replay['videoOffsetTimeMsec'])/1000
            except (ValueError,KeyError,TypeError):continue
    except OSError:pass
    return None


def _yt_chat_file(folder):
    files=[p for p in folder.glob('chat-replay.live_chat.json*') if p.name.endswith(('.json','.json.part'))]
    return max(files,key=lambda p:p.stat().st_size,default=None)


def fetch_chat(folder,url,start,duration,metadata=None):
    """Use yt-dlp's replay extractor and expose progress from chat timestamps."""
    folder=Path(folder);path=folder/'chat.json';progress=folder/'scan-progress.json'
    if path.is_file():
        cached=json.loads(path.read_text())
        if cached.get('version')==3:return cached.get('counts',{})
    counts=collections.defaultdict(lambda:[0,0,0]);authors=collections.defaultdict(set)
    available=bool((metadata or {}).get('subtitles',{}).get('live_chat'))
    status='unavailable';warning=None
    save(progress,{'phase':'Reading chat replay','fraction':.08,'etaSeconds':None})
    if 'youtube.com/' in url and available:
        from worker.youtube_auth import cookie_args
        command=[sys.executable,'-m','yt_dlp','--ignore-config','--js-runtimes','node',*cookie_args(url),
                 '--no-playlist','--no-warnings','--skip-download','--write-subs','--sub-langs','live_chat',
                 '--fragment-retries','3','-o',folder/'chat-replay.%(ext)s','--',url]
        existing=_yt_chat_file(folder)
        if not existing or (_chat_offset(existing) or 0)<start+duration:
            begun=time.monotonic();last=0
            with (folder/'chat-download.log').open('w') as log:
                proc=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while proc.poll() is None:
                        if time.monotonic()-begun>420:warning='Chat replay timed out';break
                        file=_yt_chat_file(folder)
                        offset=_chat_offset(file) if file else None
                        now=time.monotonic()
                        if offset is not None and now-last>1:
                            fraction=min(.68,.08+.60*min(1,offset/max(1,start+duration)))
                            elapsed=now-begun
                            eta=elapsed*(.68-fraction)/max(.01,fraction-.08) if fraction>.1 else None
                            save(progress,{'phase':'Reading chat replay','fraction':round(fraction,3),'etaSeconds':round(eta) if eta else None})
                            last=now
                        if offset is not None and offset>=start+duration:break
                        time.sleep(.5)
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid,signal.SIGTERM)
                        try:proc.wait(timeout=4)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        file=_yt_chat_file(folder)
        if file:
            last_offset=_chat_offset(file)
            with file.open(encoding='utf8',errors='replace') as stream:
                for line in stream:
                    try:parsed=_chat_action(json.loads(line))
                    except (ValueError,TypeError):continue
                    if not parsed:continue
                    absolute,body,author=parsed;at=int(absolute-start)
                    if 0<=at<duration:
                        counts[at][0]+=1
                        counts[at][1]+=bool(re.search(r'\b(w+|clip|pog(?:gers)?|kekw|lul|lmao|lol|rofl|holy|insane|fire|hype|omg|gg)\b|[😂🤣😆😹🔥💀🤯😱👏🙌]+|[!?]{2,}',body,re.I))
                        authors[at].add(author or f'anonymous-{at}-{counts[at][0]}')
            file.unlink(missing_ok=True)
            if last_offset is not None and last_offset<start+duration-10:
                warning=f'Chat replay ended early at {int(last_offset//60)}:{int(last_offset%60):02d}.'
        status=('partial' if warning and counts else 'available') if counts else 'empty'
        if not counts and not warning:warning='YouTube lists chat replay, but returned no messages for this hour.'
    elif 'youtube.com/' in url:
        warning='YouTube did not expose chat replay for this video.'
    else:
        warning='Chat replay could not be read from this source.'
    for at in counts:counts[at][2]=len(authors[at])
    save(path,{'version':3,'counts':counts,'available':bool(counts),'status':status,'warning':warning})
    save(progress,{'phase':'Scoring audience activity','fraction':.70,'etaSeconds':None,'warning':warning})
    return counts


def chat_reactions(chat,duration):
    """Score audience surges against the local chat baseline, including emoji-free bursts."""
    n=math.ceil(duration)
    activity=np.zeros(n);reactions=np.zeros(n);people=np.zeros(n)
    for at,entry in (chat or {}).items():
        t=int(at)
        if 0<=t<n and len(entry)>=2:
            activity[t],reactions[t]=entry[:2]
            people[t]=entry[2] if len(entry)>2 else min(entry[0],entry[1])
    empty={"score":[0.]*n,"reactions":reactions.tolist(),"activity":activity.tolist(),"people":people.tolist(),"threshold":float('inf')}
    if not np.any(activity):return empty
    # Fifteen-second windows catch fast chat; the wider baseline adapts to a busy stream.
    width=min(15,n)
    burst=np.convolve(activity,np.ones(width),"same")[:n]
    hype=np.convolve(reactions,np.ones(width),"same")[:n]
    crowd=np.convolve(people,np.ones(width),"same")[:n]
    baseline_width=min(180,n)
    local=np.convolve(np.pad(activity,(baseline_width//2,baseline_width//2),mode='edge'),
                      np.ones(baseline_width)/baseline_width,'valid')[:n]*width
    local_crowd=np.convolve(np.pad(people,(baseline_width//2,baseline_width//2),mode='edge'),
                            np.ones(baseline_width)/baseline_width,'valid')[:n]*width
    # A large number of posts from one account is weaker evidence than a crowd.
    velocity=np.maximum(0,burst/np.maximum(2,local)-1)
    participation=np.maximum(0,crowd/np.maximum(2,local_crowd)-1)
    reaction_share=hype/np.maximum(1,burst)
    score=(2.4*velocity+1.3*participation+1.5*reaction_share)*np.minimum(1,crowd/3)
    # A steady conversation or isolated reaction must not become a suggested clip.
    score[(burst<5)|(crowd<3)|(velocity<.65)|(crowd/np.maximum(1,burst)<.25)]=0
    positive=score[score>0]
    threshold=(min(float(score.max()),max(2.2,float(np.quantile(positive,.65))))
               if len(positive) and score.max()>=2.2 else float('inf'))
    threshold=round(threshold,3)
    return {"score":score.round(3).tolist(),"reactions":reactions.tolist(),"activity":activity.tolist(),
            "people":people.tolist(),"threshold":threshold}


def chat_heatmap(chat,duration,bin_seconds=15):
    """Small, privacy-preserving activity map for the project screen."""
    bins=math.ceil(duration/bin_seconds)
    posts=[0]*bins;reactions=[0]*bins;people=[0]*bins
    for at,entry in (chat or {}).items():
        index=int(at)//bin_seconds
        if 0<=index<bins and entry:
            posts[index]+=int(entry[0])
            reactions[index]+=int(entry[1]) if len(entry)>1 else 0
            people[index]+=int(entry[2]) if len(entry)>2 else 0
    return {'binSeconds':bin_seconds,'duration':duration,'posts':posts,'reactions':reactions,'viewerPosts':people}


def audio_candidates(folder,url,hour_start,hour_end):
    """Use an audio-only range for fallback discovery; never fetch the hour's video."""
    from worker.youtube_auth import cookie_args
    folder=Path(folder);progress=folder/'scan-progress.json';duration=hour_end-hour_start
    save(progress,{'phase':'Checking speech and audio','fraction':.72,'etaSeconds':None})
    command=[sys.executable,'-m','yt_dlp','--newline','--ignore-config','--js-runtimes','node',*cookie_args(url),
             '--no-playlist','--no-warnings','--socket-timeout','20','--retries','3','--concurrent-fragments','8',
             '-f','ba[ext=m4a]/ba/bestaudio','--download-sections',f'*{hour_start:.3f}-{hour_end:.3f}',
             '--force-keyframes-at-cuts','-o',folder/'audio-scan.%(ext)s','--',url]
    try:
        run_progress(command,progress,duration,'Downloading audio for highlight search',timeout=900,base=.72,span=.15)
        audio=max((p for p in folder.glob('audio-scan.*') if p.suffix not in ('.part','.json','.tmp')),key=lambda p:p.stat().st_size)
        save(progress,{'phase':'Finding strong speech and sound changes','fraction':.88,'etaSeconds':None})
        raw=run(['ffmpeg','-nostdin','-v','error','-i',audio,'-vn','-af','highpass=f=180,lowpass=f=3500',
                 '-ac','1','-ar','4000','-f','s16le','-'],timeout=240)
        samples=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768
        n=min(math.ceil(duration),len(samples)//4000)
        if n<35:return []
        one=samples[:n*4000].reshape(n,4000)
        rms=20*np.log10(np.sqrt(np.mean(one*one,axis=1))+1e-6)
        smooth=np.convolve(rms,np.ones(5)/5,'same')
        baseline=np.array([np.median(rms[max(0,t-45):min(n,t+46)]) for t in range(n)])
        rise=np.maximum(0,smooth-baseline)
        # A sudden sustained rise is more useful than a constant loud soundtrack.
        score=np.convolve(rise,np.ones(8)/8,'same')
        floor=max(2.5,float(np.quantile(score,.88))+1)
        peaks=np.where((score>=floor)&(score>=np.roll(score,1))&(score>=np.roll(score,-1)))[0]
        picked=[]
        for t in sorted(peaks,key=lambda i:-score[i]):
            if any(abs(t-prev)<120 for prev in picked):continue
            picked.append(int(t))
            if len(picked)>=6:break
        top_speech=set(picked[:3])
        picked.sort()
        if not picked:return []
        assessed=[]
        try:
            from faster_whisper import WhisperModel
            model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,
                               download_root=str(folder.parents[1]/'models'),local_files_only=True)
        except Exception:model=None
        begun=time.monotonic()
        for i,t in enumerate(picked):
            begin=max(0,min(duration-42,t-25));finish=begin+42
            text='';speech_score=0
            if model and t in top_speech:
                with tempfile.TemporaryDirectory(prefix='.speech-',dir=folder) as scratch:
                    wav=Path(scratch)/'sample.wav'
                    run(['ffmpeg','-nostdin','-v','error','-ss',str(begin),'-t','42','-i',audio,
                         '-vn','-ac','1','-ar','16000','-y',wav],timeout=70)
                    segments,_=model.transcribe(str(wav),beam_size=1,vad_filter=True,condition_on_previous_text=False)
                    spoken=list(segments)
                    text=' '.join(x.text for x in spoken).strip()
                    words=len(text.split())
                    confidence=np.mean([x.avg_logprob for x in spoken]) if spoken else -2
                    speech_score=(min(2,words/18) if confidence>-.95 else 0)
                    speech_score+=min(1.5,len(re.findall(r'\b(?:wow|clutch|insane|crazy|no way|oh my|what|why|how|bhai|arre|kya|nahi|sach|yaar)\b',text,re.I))*.4)
            energy=float(score[t]);strength=energy+speech_score*1.5
            if text and speech_score==0:strength*=.6
            assessed.append((strength,begin,finish,t,text))
            elapsed=time.monotonic()-begun;completed=i+1
            save(progress,{'phase':f'Checking speech {completed}/{len(picked)}','fraction':round(.89+.1*completed/len(picked),3),
                           'etaSeconds':round(elapsed*(len(picked)-completed)/completed)})
        chosen=[]
        for strength,begin,finish,t,text in sorted(assessed,reverse=True):
            if any(begin<item['end']+90 and finish>item['start']-90 for item in chosen):continue
            title=f'Audio reaction at {t//60}:{t%60:02d}'
            reason='Strong change in speech or audio activity; review the moment.'
            if text:reason=f'Audio rise with speech: {text[:95]}'
            chosen.append({'start':round(begin,3),'end':round(finish,3),'title':title,'score':min(95,round(strength*12)),
                           'reason':reason,'source':'audio'})
            if len(chosen)>=5:break
        return sorted(chosen,key=lambda x:x['start'])
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired,StopIteration) as exc:
        save(progress,{'phase':'Audio scan unavailable','fraction':.99,'etaSeconds':0,'warning':str(exc)[-260:]})
        return []
    finally:
        for item in folder.glob('audio-scan.*'):
            if item.is_file():item.unlink(missing_ok=True)


def signals(media,duration,has_audio,layout,words,chat=None):
    n = math.ceil(duration)
    energy, flux, centroid, motion, rate, keywords = np.zeros((6,n))
    focus = np.full(n,.5)
    if has_audio:
        raw = run(["ffmpeg","-v","error","-i",media,"-vn","-ac","1","-ar","4000","-f","s16le","-"])
        audio = np.frombuffer(raw,dtype="<i2")
        prev = None
        for t in range(min(n,len(audio)//4000)):
            sample = audio[t*4000:(t+1)*4000].astype(float)/32768
            energy[t] = 10*np.log10(np.mean(sample**2)+1e-9)
            spectrum = np.abs(np.fft.rfft(sample.reshape(8,500),axis=1)).mean(axis=0)
            centroid[t] = np.dot(spectrum,np.arange(len(spectrum)))/(spectrum.sum()+1e-9)
            if prev is not None: flux[t] = np.maximum(spectrum-prev,0).mean()
            prev = spectrum
    cmd = ["ffmpeg","-v","error","-i",str(media),"-an","-vf","fps=2,scale=128:72,format=gray","-f","rawvideo","-"]
    with subprocess.Popen(cmd,stdout=subprocess.PIPE) as proc:
        prev = None
        frame_id = 0
        while True:
            data = proc.stdout.read(128*72)
            if len(data)!=128*72: break
            frame = np.frombuffer(data,np.uint8).reshape(72,128).astype(np.int16)
            t = min(n-1,frame_id//2)
            if prev is not None:
                d = np.abs(frame-prev)
                box = layout["facecamBox"]
                if box:
                    x,y,w,h = box
                    d[int(y*72):math.ceil((y+h)*72),int(x*128):math.ceil((x+w)*128)] = 0
                d[:3]=0; d[-3:]=0; d[:,:5]=0; d[:,-5:]=0
                if d.mean()<55:
                    motion[t] += d.mean()*.5
                    weights = np.maximum(d-16,0).sum(axis=0)
                    if weights.sum()>0: focus[t]=float(np.dot(weights,np.linspace(0,1,128))/weights.sum())
            prev,frame_id = frame,frame_id+1
        if proc.wait(): raise RuntimeError("Unable to decode the stream for motion analysis.")
    hype = {"holy","clutch","insane","unbelievable","crazy","wow","wtf","haha","bhai","arre","ghazab","sheesh"}
    for word in words:
        t=min(n-1,max(0,int(word["s"])))
        rate[t]+=1
        keywords[t]+=3*(word["w"].strip(".,!?").lower() in hype)
    excitation = .30*robust(energy-np.array([np.median(energy[max(0,i-30):i+1]) for i in range(n)]))+.10*robust(flux)+.18*robust(motion)+.24*robust(keywords)+.12*robust(rate)+.06*robust(centroid)
    if chat:
        activity=np.zeros(n); hype=np.zeros(n)
        for at,counts in chat.items():
            t=int(at)
            if 0<=t<n: activity[t],hype[t]=counts
        kernel=np.ones(5)/5
        excitation=.8*excitation+.14*robust(np.convolve(activity,kernel,"same"))+.06*robust(np.convolve(hype,kernel,"same"))
    excitation -= ((motion<1)&(rate==0)&(energy < -45)).astype(float)
    kernel = np.exp(-.5*(np.arange(-12,13)/4)**2)
    smooth = np.convolve(np.pad(excitation,(12,12),mode="edge"),kernel/kernel.sum(),"valid")
    return {"score":smooth.round(4).tolist(),"focus":focus.round(3).tolist(),"motion":motion.round(2).tolist(),"energy":energy.round(2).tolist()}


def select(features,words,duration):
    if duration < 35: return []
    chat=features.get("chat") or {}
    curve=np.asarray(chat.get("score",[]),dtype=float)
    if len(curve)<math.ceil(duration):return []
    threshold=chat.get("threshold",float("inf"))
    peaks=np.where((curve>=threshold)&(curve>=np.roll(curve,1))&(curve>=np.roll(curve,-1)))[0]
    if not len(peaks):return []
    chosen = []
    limit = min(5,max(1,round(5*duration/3600)))
    activity=chat.get('activity',[])
    people=chat.get('people',[])
    for peak in sorted(peaks,key=lambda t:-curve[t]):
        # Chat often reacts after the visual event. Follow the surge's shape for the tail.
        left=peak
        while left>0 and curve[left-1]>max(.4,threshold*.35) and peak-left<20:left-=1
        right=peak
        while right+1<len(curve) and curve[right+1]>max(.4,threshold*.35) and right-peak<30:right+=1
        start=max(0,float(left)-20)
        end=min(duration,max(start+35.,float(right)+9))
        if end-start>65:end=start+65
        if end-start<35:start=max(0,end-35)
        if any(start < c["end"]+120 and end > c["start"]-120 for c in chosen): continue
        window=chat["reactions"][max(0,left):min(len(curve),right+1)]
        count=round(sum(window))
        messages=round(sum(activity[max(0,left):min(len(curve),right+1)]))
        viewers=round(sum(people[max(0,left):min(len(curve),right+1)]))
        title="Audience surge at "+f"{peak//60}:{peak%60:02d}"
        evidence=f"{messages} chat messages and {viewers} viewer posts during the surge"
        if count:evidence+=f", with {count} strong reactions"
        chosen.append({"start":round(start,3),"end":round(end,3),"title":title,
                       "score":round(100*float(np.mean(curve<=curve[peak]))),
                       "reason":evidence+"."})
        if len(chosen)==limit: break
    return sorted(chosen,key=lambda c:c["start"])


def scan(url,hour,folder,metadata=None):
    url = canonical(url)
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    source=folder/"source.mp4"
    if source.exists() and not any(s.get('codec_type')=='video' for s in probe(source)['streams']):
        source.unlink()
        for name in ('transcript.json','layout.json','layout.jpg','signals.json','chat.json','source.json'):
            (folder/name).unlink(missing_ok=True)
    if not source.exists() and url:
        planned=plan_sparse_scan(url,hour,folder,metadata)
        if planned is not None:return planned
    if not source.exists(): ingest(url,hour,folder)
    return analyze(folder,url=url,hour=hour)


def analyze(folder,url=None,hour=1):
    folder=Path(folder); source=folder/"source.mp4"
    meta=probe(source)
    duration=float(meta["format"]["duration"])
    if duration < 35: raise ValueError("The available footage is shorter than 35 seconds.")
    has_audio=any(s["codec_type"]=="audio" for s in meta["streams"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        chat_job=pool.submit(fetch_chat,folder,url,(hour-1)*3600,duration) if url else None
        words=[]
        save(folder/'scan-progress.json',{'phase':'Analyzing','fraction':0})
        layout=detect_layout(source)
        save(folder/'scan-progress.json',{'phase':'Analyzing','fraction':.35})
        chat=chat_job.result() if chat_job else None
    save(folder/"layout.json",layout)
    save(folder/'scan-progress.json',{'phase':'Analyzing','fraction':.5})
    features=signals(source,duration,has_audio,layout,words,chat)
    features["chat"]=chat_reactions(chat,duration)
    save(folder/"signals.json",features)
    save(folder/'scan-progress.json',{'phase':'Analyzing','fraction':1})
    return select(features,words,duration)


def captions(words,start,end,directory,width,style=None,custom=None):
    selected=[w for w in words if start<=w["s"]<end and w["e"]>start]
    custom=[line for line in custom or [] if line['end']>start and line['start']<end and line['text'].strip()] if custom is not None else None
    if (custom is not None and not custom) or (custom is None and not selected): return None
    style=style or {}
    height=round(width*.18)
    def write_frame(name,text):
        image=Image.new("RGBA",(width,height))
        if text:
            draw=ImageDraw.Draw(image)
            devanagari=bool(re.search('[\u0900-\u097f]',text))
            multilingual=any(ord(character)>127 for character in text)
            font_name='Devanagari Sangam MN.ttc' if devanagari else style.get('font','Arial Bold.ttf')
            candidates=[]
            if devanagari:candidates += [Path('/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc'),Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf')]
            elif multilingual:candidates += [Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),Path('/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf')]
            candidates += [Path('/System/Library/Fonts/Supplemental')/font_name,Path('/usr/share/fonts/truetype/msttcorefonts')/font_name,Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
            font_path=next((candidate for candidate in candidates if candidate.exists()),None)
            if font_path is None:raise RuntimeError('A Unicode caption font is missing. Install Noto Sans fonts.')
            font=ImageFont.truetype(str(font_path),max(10,round(style.get('fontSize',43)*width/1080)))
            active=font
            while draw.textlength(text,font=active)>width*.90 and active.size>10:
                active=active.font_variant(size=active.size-2)
            box=draw.textbbox((width/2,height/2),text,font=active,anchor="mm")
            template=style.get('captionTemplate','solid')
            if template!='minimal':
                color=style.get('boxColor','#000000')
                draw.rounded_rectangle((box[0]-12,box[1]-9,box[2]+12,box[3]+9),radius=round(active.size*.20),fill=color)
                if template=='accent':draw.rectangle((box[0]-12,box[3]+5,box[2]+12,box[3]+9),fill=style.get('textColor','#ffffff'))
            draw.text((width/2,height/2),text,font=active,fill=style.get('textColor','#ffffff'),anchor="mm",stroke_width=2 if template=='minimal' else 0,stroke_fill='#000000')
        image.save(directory/name)
    write_frame("blank.png","")
    lines=["ffconcat version 1.0"]
    def segment(name,length):
        if length>0: lines.extend([f"file '{name}'",f"duration {length:.6f}"])
    cursor=start
    intervals=[]
    if custom is not None:
        intervals=[(line['start'],line['end'],line['text']) for line in custom]
    else:
        groups=[]
        for word in selected:
            if not groups or len(groups[-1])>=4 or word["s"]-groups[-1][-1]["e"]>1:groups.append([])
            groups[-1].append(word)
        intervals=[(group[0]['s'],min(end,group[-1]['e']+.12,groups[i+1][0]['s'] if i+1<len(groups) else end),' '.join(w['w'] for w in group)) for i,group in enumerate(groups)]
    for i,(begin,finish,content) in enumerate(intervals):
        begin=max(cursor,start,begin)
        finish=min(end,finish)
        if finish<=begin: continue
        segment("blank.png",begin-cursor)
        name=f"text{i}.png"
        write_frame(name,content)
        segment(name,finish-begin)
        cursor=finish
    segment("blank.png",end-cursor)
    lines.append("file 'blank.png'")
    manifest=directory/"captions.ffconcat"
    manifest.write_text("\n".join(lines)+"\n")
    return manifest


def render(folder,start,end,out):
    folder,out=Path(folder),Path(out)
    descriptor=folder/"source.json"
    metadata=json.loads(descriptor.read_text()) if descriptor.is_file() else {}
    if out.name.startswith("preview-") or not metadata.get("url") or metadata.get("live"):
        return compose(folder,start,end,out)
    match=re.fullmatch(r'clip-(\d+)\.mp4',out.name)
    export=json.loads((folder/f'export-{match[1]}.json').read_text()) if match and (folder/f'export-{match[1]}.json').exists() else {}
    export_width=export.get('width',1080)
    with tempfile.TemporaryDirectory(dir=folder,prefix=".highquality-") as scratch:
        temp=Path(scratch)
        chunk_start=metadata.get("start",0)
        absolute_start=chunk_start+start
        cut=max(0,absolute_start-3)
        try:
            from worker.youtube_auth import cookie_args
            run_progress([sys.executable,"-m","yt_dlp","--newline","--ignore-config","--js-runtimes","node",*cookie_args(metadata['url']),"--no-warnings","--no-playlist","--socket-timeout","15",
                 "--retries","2","-f",f"bv*[height<={export_width}]+ba/b[height<={export_width}]/b","--download-sections",
                 f"*{cut:.3f}-{chunk_start+end+3:.3f}","--force-keyframes-at-cuts","--merge-output-format","mp4","--remux-video","mp4",
                 "-o",temp/"best.%(ext)s","--",canonical(metadata["url"])],folder/'job-progress.json',end-start+6,'Downloading export quality',timeout=360)
            return compose(folder,start,end,out,temp/"best.mp4",absolute_start-cut)
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            save(out.with_suffix(".quality.json"),{"source":"analysis","warning":str(exc)[-350:]})
            raise RuntimeError('High-quality footage could not be downloaded: '+str(exc)[-350:])


def compose(folder,start,end,out,best_source=None,best_offset=None):
    folder,out=Path(folder),Path(out)
    source=best_source or folder/"source.mp4"
    info=probe(source)
    duration=float(info["format"]["duration"])
    offset=start if best_offset is None else best_offset
    if not (0<=offset and end>start and offset+end-start<=duration+.05 and 19.999<=end-start<=180.001):
        raise ValueError("Choose a 20 to 180 second interval inside the available footage.")
    layout=json.loads((folder/"layout.json").read_text())
    match=re.fullmatch(r'(?:preview|clip)-(\d+)\.mp4',out.name)
    edit_file=folder/f'edit-{match[1]}.json' if match else None
    edit=json.loads(edit_file.read_text()) if edit_file and edit_file.exists() else {}
    transcript=folder/"transcript.json"
    words=json.loads(transcript.read_text())["words"] if transcript.exists() else []
    focus=json.loads((folder/"signals.json").read_text())["focus"]
    export=json.loads((folder/f'export-{match[1]}.json').read_text()) if match and out.name.startswith('clip-') and (folder/f'export-{match[1]}.json').exists() else {}
    width=480 if out.name.startswith("preview-") else export.get('width',1080)
    height=round(width*16/9/2)*2
    box=(edit.get('facecamBox') if edit.get('layoutMode')=='split' else None) if edit else (layout.get("facecamBox") if layout.get("mode")!="full" else None)
    stream=next(s for s in info["streams"] if s["codec_type"]=="video")
    sw,sh=stream["width"],stream["height"]
    gh=round(height*(1-edit.get('facecamFraction',.5)))//2*2 if box else height
    faceh=height-gh
    cw=max(2,int(min(sw,sh*width/gh))//2*2)
    ch=max(2,int(min(sh,sw*gh/width))//2*2)
    xs=[]
    center=float(np.median(focus[int(start):int(min(end,start+4))]))
    for sample_offset in range(0,math.ceil(end-start)+3,3):
        t=min(len(focus)-1,int(start+sample_offset))
        target=float(np.median(focus[t:t+3]))
        if not edit and layout.get("fullFaceCenter") is not None:
            center=target=layout["fullFaceCenter"]
        center=.70*center+.30*target
        xpos=np.clip(center*sw-cw/2,0,sw-cw)
        if box:
            bx,_,bw,_=box
            if bx+bw<=.48 and (1-bx-bw)*sw>=cw:
                xpos=max(xpos,(bx+bw)*sw)
            elif bx>=.52 and bx*sw>=cw:
                xpos=min(xpos,bx*sw-cw)
        xs.append(round(xpos,2))
    # Piecewise-linear motion follows the action centroid without cuts between keyframes.
    position=str(xs[-1])
    for i in reversed(range(len(xs)-1)):
        position=f"if(lt(t,{(i+1)*3}),{xs[i]}+({xs[i+1]-xs[i]:.3f})*(t-{i*3})/3,{position})"
    game=f"crop={cw}:{ch}:'{position}':(ih-oh)/2,scale={width}:{gh},setsar=1"
    if edit.get('gameBox') and edit['gameBox'] != [0,0,1,1]:
        gx,gy,gw,gh_box=edit['gameBox']
        region_w,region_h=gw*sw,gh_box*sh
        crop_w=max(2,int(min(region_w,region_h*width/gh))//2*2)
        crop_h=max(2,int(min(region_h,region_w*gh/width))//2*2)
        crop_x=max(0,min(sw-crop_w,int((gx+gw/2)*sw-crop_w/2)))
        crop_y=max(0,min(sh-crop_h,int((gy+gh_box/2)*sh-crop_h/2)))
        game=f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={width}:{gh},setsar=1"
    if box:
        x,y,w,h=box
        fw=max(2,int(min(w*sw,h*sh*width/faceh))//2*2)
        fh=max(2,int(min(h*sh,w*sw*faceh/width))//2*2)
        fx=max(0,min(sw-fw,int((x+w/2)*sw-fw/2)))
        fy=max(0,min(sh-fh,int((y+h/2)*sh-fh/2)))
        order='[bottom][top]' if edit.get('facePosition')=='top' else '[top][bottom]'
        graph=f"[0:v]split[g][f];[g]{game}[top];[f]crop={fw}:{fh}:{fx}:{fy},scale={width}:{faceh},setsar=1[bottom];{order}vstack[composite]"
    else:
        graph=f"[0:v]{game}[composite]"
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent,prefix=".render-") as scratch:
        scratch=Path(scratch)
        args=["ffmpeg","-nostdin","-v","error","-y","-ss",str(offset),"-t",str(end-start),"-i",source]
        caption_file=folder/f'captions-{match[1]}.json' if match else None
        custom=json.loads(caption_file.read_text())['segments'] if caption_file and caption_file.exists() else []
        subtitles=captions(words,start,end,scratch,width,edit,custom) if edit.get('captionMode')=='auto' and custom else None
        input_index=1
        video_label='composite'
        audio_input="0:a:0"
        if subtitles:
            args+=["-f","concat","-safe","1","-i",subtitles]
            graph+=f";[{video_label}][{input_index}:v]overlay=x=0:y=(main_h-overlay_h)/2:eof_action=pass[captioned]"
            video_label='captioned'
            input_index+=1
        from worker.text_overlays import draw_text_overlay, validate_text_overlays
        overlays=validate_text_overlays(edit.get('textOverlays',[]),duration)
        for i,item in enumerate(overlays):
            if item['end']<=start or item['start']>=end:continue
            picture=scratch/f'overlay-{i}.png'
            draw_text_overlay(item,width,height,picture)
            args += ['-loop','1','-i',picture]
            begin=max(0,item['start']-start)
            finish=min(end-start,item['end']-start)
            next_label=f'text{i}'
            graph+=f";[{video_label}][{input_index}:v]overlay=x=0:y=0:enable='between(t,{begin:.3f},{finish:.3f})':shortest=1[{next_label}]"
            video_label=next_label
            input_index+=1
        graph+=f';[{video_label}]fps=30,format=yuv420p[out]'
        norm="loudnorm=I=-14:TP=-1.5:LRA=11"
        if not any(s["codec_type"]=="audio" for s in info["streams"]):
            audio_input=f'{input_index}:a'
            args+=["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
        else:
            # Measure the same stereo program that will be encoded. A mono source
            # downmixed after normalization otherwise changes integrated loudness.
            measure=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-nostats","-ss",str(offset),"-t",str(end-start),
                                    "-i",str(source),"-vn","-af","aformat=channel_layouts=stereo,"+norm+":print_format=json",
                                    "-f","null","-"],capture_output=True,timeout=100)
            match=re.search(rb'\{\s*"input_i".*?\}',measure.stderr,re.S)
            if match:
                stats=json.loads(match.group())
                fields={"measured_I":"input_i","measured_TP":"input_tp","measured_LRA":"input_lra","measured_thresh":"input_thresh","offset":"target_offset"}
                if all(math.isfinite(float(stats[k])) for k in fields.values()):
                    norm+=":"+":".join(k+"="+stats[v] for k,v in fields.items())+":linear=true"
            norm="aformat=channel_layouts=stereo,"+norm
        args+=["-filter_complex",graph,"-map","[out]","-map",audio_input,"-t",str(end-start),"-c:v","libx264",
               "-preset","veryfast","-crf","25" if width==480 else "19","-threads","4","-c:a","aac","-ar","48000",
               "-af",norm,"-ac","2","-b:a","192k","-movflags","+faststart",scratch/"output.mp4"]
        run_progress([*args[:-1],'-progress','pipe:1','-nostats',args[-1]],folder/'job-progress.json',end-start,'Rendering 480p preview' if width==480 else f'Rendering {width}×{height} export',timeout=1200)
        encoded=probe(scratch/"output.mp4")
        if abs(float(encoded["format"]["duration"])-(end-start))>.15:
            raise RuntimeError("The encoded clip duration differs from the selected interval.")
        (scratch/"output.mp4").replace(out)
    return str(out)
