"""Record independent live segments so the user can scan completed footage."""
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from worker.youtube_auth import cookie_args

recorders={}
guard=threading.Lock()

def describe(url):
    command=[sys.executable,'-m','yt_dlp','--js-runtimes','node',*cookie_args(url),'--no-playlist','--socket-timeout','10','--no-warnings','--skip-download','-J',url]
    proc=subprocess.run(command,capture_output=True,timeout=90)
    if proc.returncode:
        formats=subprocess.run([sys.executable,'-m','yt_dlp','--js-runtimes','node',*cookie_args(url),'--no-playlist','-F',url],capture_output=True,timeout=90)
        if formats.returncode==0 and b'm3u8' in formats.stdout and b'audio only' in formats.stdout:
            return {'is_live':True,'title':url}
        raise ValueError('Could not inspect this stream. YouTube may require sign-in; try again later or use a publicly playable link.')
    return json.loads(proc.stdout)

def recording(path):
    path=Path(path).resolve()
    with guard:
        p=recorders.get(path)
        return bool(p and p.poll() is None)

def start(url,path):
    path=Path(path).resolve()
    path.mkdir(parents=True,exist_ok=True)
    with guard:
        if path in recorders and recorders[path].poll() is None:return
        result=subprocess.run([sys.executable,'-m','yt_dlp','--js-runtimes','node',*cookie_args(url),'--no-playlist','-f','bv[vcodec^=avc1][height<=720]+ba/bv*[height<=720]+ba/b[height<=720]/best','-g',url],capture_output=True,timeout=90,text=True)
        if result.returncode:
            if 'Sign in to confirm' in result.stderr or 'not a bot' in result.stderr:
                raise ValueError('YouTube blocked automated access with a sign-in/bot check. The video may play in your browser but cannot be recorded by this app right now.')
            raise ValueError('The live source could not be opened. Check that the stream is public and retry.')
        sources=result.stdout.splitlines()
        if not sources:raise ValueError('The live source returned no playable streams.')
        nums=[int(p.stem) for p in path.glob('[0-9]*.ts') if p.stem.isdigit()]
        with (path/'record.log').open('ab') as log:
            inputs=sum((['-i',src] for src in sources[:2]),[])
            audio=['-map','1:a:0'] if len(sources)>1 else ['-map','0:a:0?']
            recorders[path]=subprocess.Popen(['ffmpeg','-nostdin','-loglevel','error',*inputs,'-map','0:v:0',*audio,'-c','copy','-f','segment','-segment_time','30','-segment_start_number',str(max(nums,default=-1)+1),'-reset_timestamps','1',str(path/'%08d.ts')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log)

def stop(path):
    path=Path(path).resolve()
    with guard:
        proc=recorders.get(path)
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:proc.kill()

def snapshot(path,dest,offset):
    path=Path(path).resolve()
    dest=Path(dest).resolve()
    files=sorted(path.glob('[0-9]*.ts'))
    if recording(path):files=files[:-1]
    selected=[]
    elapsed=0
    for f in files[offset:]:
        d=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(f)],text=True,timeout=10))
        selected.append(f)
        elapsed+=d
        if elapsed>=3600:break
    if elapsed<35:raise ValueError('Recording live. Wait for at least 60 seconds of footage, then retry the scan.')
    manifest=dest/'segments.txt'
    manifest.write_text(''.join("file '"+str(f)+"'\n" for f in selected))
    tmp=dest/'capture.tmp.mp4'
    subprocess.run(['ffmpeg','-nostdin','-y','-loglevel','error','-f','concat','-safe','0','-i',str(manifest),'-c','copy',str(tmp)],check=True)
    streams=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_type','-of','csv=p=0',str(tmp)],text=True,timeout=20)
    if 'video' not in streams:
        tmp.unlink(missing_ok=True)
        raise ValueError('The live recorder captured audio without video. Retry the scan; ClipHunter will select an H.264 video stream.')
    os.replace(tmp,dest/'source.mp4')
    return offset+len(selected)
