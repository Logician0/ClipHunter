"""ClipHunter's local, one-hour media worker. All candidate times are chunk-relative."""
import collections
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
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


def fetch_chat(folder,url,start,duration):
    path=folder/"chat.json"
    if path.is_file():
        cached=json.loads(path.read_text())
        if cached.get("version")==2:return cached.get("counts",{})
    counts=collections.defaultdict(lambda:[0,0,0])
    authors=collections.defaultdict(set)
    if "kick.com/" not in url:
        with tempfile.TemporaryDirectory(dir=folder,prefix=".chat-") as scratch:
            raw=Path(scratch)/"messages.json"
            try:
                tool=Path(sys.executable).with_name("chat_downloader")
                run([tool,url,"--start_time",str(start),"--end_time",str(start+int(duration)),
                     "--max_messages","100000","--output",raw,"--quiet"],timeout=165)
                for message in json.loads(raw.read_text()):
                    at=int(message.get("time_in_seconds",-1)-start)
                    if 0<=at<duration:
                        body=message.get("message","") or ""
                        author=message.get("author",{})
                        identity=(author.get("id") or author.get("name") or str(len(authors[at]))) if isinstance(author,dict) else str(author)
                        counts[at][0]+=1
                        counts[at][1]+=bool(re.search(r"\b(w+|ww+|clip|pog(?:gers)?|kekw|lul|lmao|lol|rofl|holy|insane|fire|hype|omg|gg)\b|[😂🤣😆😹🔥💀🤯😱👏🙌]+",body,re.I) or re.search(r"([wW])\1{2,}",body))
                        authors[at].add(identity)
            except (OSError,RuntimeError,subprocess.TimeoutExpired,ValueError,TypeError):
                pass
    for at in counts:counts[at][2]=len(authors[at])
    save(path,{"version":2,"counts":counts,"available":bool(counts)})
    return counts


def chat_reactions(chat,duration):
    """Find unusually strong audience reactions, independent of spoken words."""
    n=math.ceil(duration)
    activity=np.zeros(n);reactions=np.zeros(n);people=np.zeros(n)
    for at,entry in (chat or {}).items():
        t=int(at)
        if 0<=t<n and len(entry)>=2:
            activity[t],reactions[t]=entry[:2]
            people[t]=entry[2] if len(entry)>2 else min(entry[0],entry[1])
    if not np.any(activity):return {"score":[0.]*n,"reactions":reactions.tolist(),"activity":activity.tolist(),"threshold":1e12}
    burst=np.convolve(activity,np.ones(12),"same")
    hype=np.convolve(reactions,np.ones(12),"same")
    crowd=np.convolve(people,np.ones(12),"same")
    baseline=float(np.median(np.convolve(activity,np.ones(60),"same")))
    score=(hype+0.12*burst)*np.minimum(1.0,crowd/2.0)
    threshold=max(3.0,baseline*0.9+2.0,float(np.quantile(score,.85))*1.5)
    return {"score":score.round(3).tolist(),"reactions":reactions.tolist(),"activity":activity.tolist(),"threshold":threshold}


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
    length = min(42.,duration)
    for peak in sorted(peaks,key=lambda t:-curve[t]):
        start = max(0,min(duration-length,float(peak)-.6*length))
        end = start+length
        if any(start < c["end"]+120 and end > c["start"]-120 for c in chosen): continue
        window=chat["reactions"][max(0,peak-6):min(len(curve),peak+7)]
        count=round(sum(window))
        title="Chat reaction at "+f"{peak//60}:{peak%60:02d}"
        chosen.append({"start":round(start,3),"end":round(end,3),"title":title,
                       "score":round(100*float(np.mean(curve<=curve[peak]))),
                       "reason":f"{count} excited chat reactions near {peak//60}:{peak%60:02d}."})
        if len(chosen)==limit: break
    return sorted(chosen,key=lambda c:c["start"])


def scan(url,hour,folder):
    url = canonical(url)
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    source=folder/"source.mp4"
    if source.exists() and not any(s.get('codec_type')=='video' for s in probe(source)['streams']):
        source.unlink()
        for name in ('transcript.json','layout.json','layout.jpg','signals.json','chat.json','source.json'):
            (folder/name).unlink(missing_ok=True)
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
            hindi=bool(re.search('[\u0900-\u097f]',text))
            font_name='Devanagari Sangam MN.ttc' if hindi else style.get('font','Arial Bold.ttf')
            candidates=[Path('/System/Library/Fonts/Supplemental')/font_name]
            if hindi:candidates += [Path('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf')]
            else:candidates += [Path('/usr/share/fonts/truetype/msttcorefonts')/font_name,Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
            font_path=next((candidate for candidate in candidates if candidate.exists()),None)
            if font_path is None:raise RuntimeError('A Hindi/English caption font is missing. Install Noto Sans Devanagari and DejaVu Sans.')
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
    with tempfile.TemporaryDirectory(dir=folder,prefix=".highquality-") as scratch:
        temp=Path(scratch)
        chunk_start=metadata.get("start",0)
        absolute_start=chunk_start+start
        cut=max(0,absolute_start-3)
        try:
            from worker.youtube_auth import cookie_args
            run([sys.executable,"-m","yt_dlp","--ignore-config","--js-runtimes","node",*cookie_args(metadata['url']),"--no-warnings","--no-playlist","--socket-timeout","15",
                 "--retries","1","-f","bv*[height<=1080]+ba/b[height<=1080]/b","--download-sections",
                 f"*{cut:.3f}-{chunk_start+end+3:.3f}","--force-keyframes-at-cuts","--merge-output-format","mp4","--remux-video","mp4",
                 "-o",temp/"best.%(ext)s","--",canonical(metadata["url"])],timeout=240)
            return compose(folder,start,end,out,temp/"best.mp4",absolute_start-cut)
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            save(out.with_suffix(".quality.json"),{"source":"analysis","warning":str(exc)[-350:]})
    return compose(folder,start,end,out)


def compose(folder,start,end,out,best_source=None,best_offset=None):
    folder,out=Path(folder),Path(out)
    source=best_source or folder/"source.mp4"
    info=probe(source)
    duration=float(info["format"]["duration"])
    offset=start if best_offset is None else best_offset
    if not (0<=offset and end>start and offset+end-start<=duration+.05 and 19.999<=end-start<=60.001):
        raise ValueError("Choose a 20 to 60 second interval inside this chunk.")
    layout=json.loads((folder/"layout.json").read_text())
    match=re.fullmatch(r'(?:preview|clip)-(\d+)\.mp4',out.name)
    edit_file=folder/f'edit-{match[1]}.json' if match else None
    edit=json.loads(edit_file.read_text()) if edit_file and edit_file.exists() else {}
    transcript=folder/"transcript.json"
    words=json.loads(transcript.read_text())["words"] if transcript.exists() else []
    focus=json.loads((folder/"signals.json").read_text())["focus"]
    width=360 if out.name.startswith("preview-") else 1080
    height=width*16//9
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
        custom=json.loads(caption_file.read_text())['segments'] if caption_file and caption_file.exists() else None
        subtitles=None if edit.get('captionMode')=='off' else captions(words,start,end,scratch,width,edit,custom)
        audio_input="0:a:0"
        if subtitles:
            args+=["-f","concat","-safe","1","-i",subtitles]
            graph+=";[composite][1:v]overlay=x=0:y=(main_h-overlay_h)/2:eof_action=pass,fps=30,format=yuv420p[out]"
        else: graph+=";[composite]fps=30,format=yuv420p[out]"
        norm="loudnorm=I=-14:TP=-1.5:LRA=11"
        if not any(s["codec_type"]=="audio" for s in info["streams"]):
            audio_input=("2" if subtitles else "1")+":a"
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
               "-preset","veryfast","-crf","25" if width==360 else "19","-threads","4","-c:a","aac","-ar","48000",
               "-af",norm,"-ac","2","-b:a","192k","-movflags","+faststart",scratch/"output.mp4"]
        run(args,timeout=600)
        encoded=probe(scratch/"output.mp4")
        if abs(float(encoded["format"]["duration"])-(end-start))>.15:
            raise RuntimeError("The encoded clip duration differs from the selected interval.")
        (scratch/"output.mp4").replace(out)
    return str(out)
