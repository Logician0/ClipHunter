"""Loopback API, durable single-worker queue and session-protected media."""
import contextlib
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile
import subprocess
import socketserver
import signal
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from worker import live

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('CLIPHUNTER_DATA_DIR', ROOT / 'data'))
DATA.mkdir(exist_ok=True)
os.environ.setdefault('XDG_CACHE_HOME',str(DATA/'models'/'cache'))
os.environ.setdefault('ARGOS_PACKAGES_DIR',str(DATA/'models'/'argos'))
os.environ.setdefault('ARGOS_CHUNK_TYPE','DEFAULT')
attempts = defaultdict(deque)
lock = threading.Lock()
caption_lock = threading.Lock()
caption_active = set()

def atomic_json(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False))
    temporary.replace(path)

def caption_task(highlight, chunk, start, end, language, output, model_name):
    child=folder(chunk)/f'highlight-{highlight}'
    directory=child if child.exists() else folder(chunk)
    status=directory/f'caption-job-{highlight}.json'
    began=time.monotonic()
    def progress(fraction,phase='Recognizing speech'):
        eta=(time.monotonic()-began)*(1-fraction)/fraction if fraction>.02 else None
        atomic_json(status,{'status':'processing','phase':phase,'fraction':round(fraction,3),'etaSeconds':round(eta) if eta is not None else None})
    try:
        from worker.captioning import transcribe_clip
        result=transcribe_clip(directory/'source.mp4',start,end,language,output=output,model_name=model_name,progress=progress)
        atomic_json(directory/f'captions-{highlight}.json',result)
        atomic_json(status,{'status':'ready'})
    except Exception as exc:
        atomic_json(status,{'status':'error','error':str(exc)[:500]})
    finally:
        with caption_lock:caption_active.discard(highlight)

@contextlib.contextmanager
def db():
    with contextlib.closing(sqlite3.connect(DATA/'library.sqlite', timeout=20)) as c:
        c.row_factory = sqlite3.Row
        with c:
            yield c

def initialize():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,url TEXT,title TEXT);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,project INTEGER,hour INTEGER,status TEXT,error TEXT,UNIQUE(project,hour));
        CREATE TABLE IF NOT EXISTS highlights(id INTEGER PRIMARY KEY,chunk INTEGER,start REAL,end REAL,title TEXT,status TEXT,error TEXT,clip TEXT,preview TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,expires INTEGER);
        CREATE TABLE IF NOT EXISTS streams(project INTEGER PRIMARY KEY,is_live INTEGER,stopped INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS offsets(chunk INTEGER PRIMARY KEY,ending INTEGER);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,model TEXT,gb INTEGER);
        CREATE TABLE IF NOT EXISTS youtube_uploads(id INTEGER PRIMARY KEY,highlight INTEGER,status TEXT,
          metadata TEXT,progress REAL,bytes_sent INTEGER,total_bytes INTEGER,eta_seconds INTEGER,
          video_id TEXT,error TEXT,created_at INTEGER);
        INSERT OR IGNORE INTO settings VALUES(1,'base',12);
        UPDATE chunks SET status='queued' WHERE status='scanning';
        UPDATE highlights SET status='queued' WHERE status='rendering';
        UPDATE youtube_uploads SET status='queued' WHERE status='uploading';
        """)
        columns={row['name'] for row in c.execute('PRAGMA table_info(highlights)')}
        if 'score' not in columns:c.execute('ALTER TABLE highlights ADD COLUMN score INTEGER')
        if 'reason' not in columns:c.execute('ALTER TABLE highlights ADD COLUMN reason TEXT')
        c.execute("UPDATE highlights SET reason='High combined motion, audio or speech activity.' WHERE reason IS NULL")

def check_url(url):
    from worker.media import canonical
    return canonical(url)

def folder(chunk):
    p=DATA/'chunks'/str(chunk)
    p.mkdir(exist_ok=True,parents=True)
    return p

def highlight_folder(highlight):
    """New VOD clips have isolated media; existing hour downloads still work."""
    parent=folder(highlight['chunk'])
    child=parent/f"highlight-{highlight['id']}"
    return child if child.exists() else parent

def worker():
    from worker.media import scan, render, prepare_clip, extend_clip
    while True:
        with db() as c:
            h=c.execute("SELECT * FROM highlights WHERE status IN ('queued','previewing','preparing','expanding') ORDER BY CASE status WHEN 'previewing' THEN 0 WHEN 'expanding' THEN 1 WHEN 'preparing' THEN 2 ELSE 3 END,id LIMIT 1").fetchone()
            k=None if h else c.execute("SELECT c.*,p.url FROM chunks c JOIN projects p ON p.id=c.project WHERE c.status='queued' ORDER BY c.id LIMIT 1").fetchone()
            if h and h['status']=='queued': c.execute("UPDATE highlights SET status='rendering' WHERE id=?",(h['id'],))
            if k: c.execute("UPDATE chunks SET status='scanning' WHERE id=?",(k['id'],))
        if not h and not k:
            time.sleep(.5)
            continue
        try:
            if shutil.disk_usage(DATA).free < 2*1024**3: raise ValueError('Free at least 2 GB of disk space and retry.')
            if h:
                if h['status']=='expanding':
                    d=highlight_folder(h)
                    plan=json.loads((d/'expand-plan.json').read_text())
                    shift=extend_clip(d,plan['side'])
                    if shift:
                        captions_file=d/f'captions-{h["id"]}.json'
                        if captions_file.exists():
                            lines=json.loads(captions_file.read_text())
                            for line in lines.get('segments',[]):line['start']=round(line['start']+shift,3);line['end']=round(line['end']+shift,3)
                            atomic_json(captions_file,lines)
                    (d/f'frame-{h["id"]}.jpg').unlink(missing_ok=True)
                    with db() as c:c.execute("UPDATE highlights SET start=start+?,end=end+?,status='ready',error=NULL WHERE id=?",(shift,shift,h['id']))
                    (d/'expand-plan.json').unlink(missing_ok=True)
                    continue
                if h['status']=='preparing':
                    d=highlight_folder(h)
                    plan=json.loads((d/'plan.json').read_text())
                    a,b=prepare_clip(d,h['id'],plan['url'],plan['hour'],plan['start'],plan['end'])
                    with db() as c:c.execute("UPDATE highlights SET start=?,end=?,status='previewing',error=NULL WHERE id=?",(a,b,h['id']))
                    continue
                if h['status']=='previewing':
                    build_previews(render,h['chunk'])
                    continue
                dest=highlight_folder(h)/f"clip-{h['id']}.mp4"
                render(dest.parent,h['start'],h['end'],dest)
                with db() as c: c.execute("UPDATE highlights SET status='ready',clip=?,error=NULL WHERE id=?",(f"/api/media/{h['id']}/clip",h['id']))
            else:
                atomic_json(folder(k['id'])/'scan-progress.json',{'phase':'Inspecting stream','fraction':.02,'etaSeconds':None})
                with db() as c: prefs=c.execute('SELECT * FROM settings').fetchone()
                os.environ['WHISPER_MODEL']=prefs['model']
                if sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file()) > prefs['gb']*1024**3:raise ValueError('Workspace storage limit reached. Increase it in Settings.')
                with db() as c: stream=c.execute('SELECT * FROM streams WHERE project=?',(k['project'],)).fetchone()
                stream_meta=None
                if not stream or k['hour']==1:
                    meta=live.describe(k['url'])
                    stream_meta=meta
                    with db() as c:
                        c.execute('INSERT INTO streams(project,is_live) VALUES(?,?) ON CONFLICT(project) DO UPDATE SET is_live=excluded.is_live',(k['project'],bool(meta.get('is_live'))))
                        if meta.get('title'):c.execute('UPDATE projects SET title=? WHERE id=?',(meta['title'],k['project']))
                        stream=c.execute('SELECT * FROM streams WHERE project=?',(k['project'],)).fetchone()
                    if not stream['is_live']:live.stop(DATA/'live'/str(k['project']))
                if stream['is_live']:
                    path=DATA/'live'/str(k['project'])
                    if not stream['stopped']:live.start(k['url'],path)
                    if not (folder(k['id'])/'source.mp4').exists():
                        for _ in range(12):
                            if len(list(path.glob('[0-9]*.ts'))) >= 3 or not live.recording(path):break
                            time.sleep(5)
                        with db() as c:
                            pos=c.execute('SELECT COALESCE(MAX(ending),0) FROM offsets JOIN chunks ON offsets.chunk=chunks.id WHERE chunks.project=?',(k['project'],)).fetchone()[0]
                        ending=live.snapshot(path,folder(k['id']),pos)
                        with db() as c:c.execute('INSERT OR REPLACE INTO offsets VALUES(?,?)',(k['id'],ending))
                items=scan(k['url'],k['hour'],folder(k['id']),stream_meta)
                with db() as c:
                    sparse=json.loads((folder(k['id'])/'source.json').read_text()).get('sparse',False)
                    occupied=[]
                    for previous in c.execute('SELECT * FROM highlights WHERE chunk=?',(k['id'],)).fetchall():
                        plan=highlight_folder(previous)/'plan.json'
                        times=json.loads(plan.read_text()) if plan.exists() else previous
                        occupied.append((float(times['start']),float(times['end'])))
                    for item in items:
                        if any(item['start']<end+35 and item['end']>start-35 for start,end in occupied):continue
                        hid=c.execute("INSERT INTO highlights(chunk,start,end,title,status,score,reason) VALUES(?,?,?,?,?,?,?)",
                                  (k['id'],item['start'],item['end'],item['title'],'preparing' if sparse else 'previewing',item.get('score'),item.get('reason'))).lastrowid
                        occupied.append((item['start'],item['end']))
                        if sparse:
                            d=folder(k['id'])/f'highlight-{hid}';d.mkdir(exist_ok=True)
                            atomic_json(d/'plan.json',{'url':k['url'],'hour':k['hour'],'start':item['start'],'end':item['end']})
                    c.execute("UPDATE chunks SET status='ready',error=NULL WHERE id=?",(k['id'],))
        except Exception as exc:
            with db() as c:
                table='highlights' if h else 'chunks'
                c.execute(f"UPDATE {table} SET status='error',error=? WHERE id=?",(str(exc)[-900:],(h or k)['id']))
        if k:
            build_previews(render,k['id'])

def upload_worker():
    from worker import youtube_publish
    while True:
        with db() as c:
            job=c.execute("SELECT * FROM youtube_uploads WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if job:c.execute("UPDATE youtube_uploads SET status='uploading',error=NULL WHERE id=?",(job['id'],))
        if not job:
            time.sleep(1)
            continue
        try:
            with db() as c:h=c.execute('SELECT * FROM highlights WHERE id=?',(job['highlight'],)).fetchone()
            if not h or not h['clip']:raise ValueError('Render the clip again before uploading')
            media=highlight_folder(h)/f"clip-{h['id']}.mp4"
            if not media.exists():raise ValueError('The rendered MP4 is missing')
            def progress(fraction,sent,total,eta=None):
                with db() as c:c.execute('UPDATE youtube_uploads SET progress=?,bytes_sent=?,total_bytes=?,eta_seconds=? WHERE id=?',
                                      (round(fraction,3),sent,total,eta,job['id']))
            video_id=youtube_publish.upload_video(job['id'],media,json.loads(job['metadata']),progress)
            with db() as c:c.execute("UPDATE youtube_uploads SET status='complete',progress=1,video_id=?,eta_seconds=0 WHERE id=?",(video_id,job['id']))
            youtube_publish.finish_job(job['id'])
        except Exception as exc:
            with db() as c:c.execute("UPDATE youtube_uploads SET status='error',error=? WHERE id=?",(str(exc)[-700:],job['id']))

def build_previews(render,chunk):
    with db() as c: items=c.execute("SELECT * FROM highlights WHERE chunk=? AND status='previewing'",(chunk,)).fetchall()
    for item in items:
        try:
            dest=highlight_folder(item)/f"preview-{item['id']}.mp4"
            render(dest.parent,item['start'],item['end'],dest)
            with db() as c: c.execute("UPDATE highlights SET preview=?,status='ready' WHERE id=? AND status='previewing'",(f"/api/media/{item['id']}/preview",item['id']))
        except Exception as exc:
            with db() as c: c.execute("UPDATE highlights SET status='error',error=? WHERE id=? AND status='previewing'",(str(exc)[-900:],item['id']))

def state(c):
    projects=[]
    for p in c.execute("SELECT * FROM projects ORDER BY id DESC"):
        chunks=[]
        for k in c.execute("SELECT * FROM chunks WHERE project=? ORDER BY hour",(p['id'],)):
            hs=c.execute("SELECT * FROM highlights WHERE chunk=? ORDER BY id",(k['id'],)).fetchall()
            stage=None
            duration=None
            chunk_folder=DATA/'chunks'/str(k['id'])
            metadata=chunk_folder/'source.json'
            if metadata.exists():
                source_info=json.loads(metadata.read_text())
                duration=source_info['end']-source_info['start']
            elif (chunk_folder/'signals.json').exists():
                duration=len(json.loads((chunk_folder/'signals.json').read_text())['score'])
            if k['status']=='scanning':
                if (chunk_folder/'signals.json').exists():stage='Preparing previews'
                elif (chunk_folder/'source.mp4').exists():stage='Finding chat moments'
                else:stage='Checking chat'
            source=chunk_folder/'source.mp4'
            progress=None;eta=None
            progress_file=chunk_folder/'scan-progress.json'
            if k['status']=='scanning' and progress_file.exists():
                try:
                    saved=json.loads(progress_file.read_text())
                    stage=saved.get('phase',stage)
                    if saved.get('fraction') is not None:progress=max(0,min(1,float(saved['fraction'])))
                    eta=saved.get('etaSeconds')
                except (ValueError,TypeError,KeyError):pass
            clip_sources=[highlight_folder(h)/'source.mp4' for h in hs]
            sources=[path for path in [source,*clip_sources] if path.exists()]
            highlights=[]
            for h in hs:
                d=highlight_folder(h)
                job=d/'job-progress.json';job_state={}
                if job.exists():
                    try:job_state=json.loads(job.read_text())
                    except (ValueError,OSError):pass
                plan=d/'plan.json';original={}
                if plan.exists():
                    try:original=json.loads(plan.read_text())
                    except (ValueError,OSError):pass
                preview_file=d/f'preview-{h["id"]}.mp4'
                source_file=d/'source.mp4'
                highlights.append(dict(h,sourceAvailable=source_file.exists(),sourceBytes=source_file.stat().st_size if source_file.exists() else 0,sourceVersion=source_file.stat().st_mtime_ns if source_file.exists() else None,previewVersion=preview_file.stat().st_mtime_ns if preview_file.exists() else None,job=job_state,originalStart=original.get('start'),originalEnd=original.get('end')))
            chunks.append(dict(k,stage=stage,progress=progress,etaSeconds=eta,duration=duration,
                               sparse=bool(metadata.exists() and source_info.get('sparse')),
                               scanMethod=source_info.get('scanMethod') if metadata.exists() else None,
                               chatStatus=source_info.get('chatStatus') if metadata.exists() else None,
                               scanWarning=source_info.get('scanWarning') if metadata.exists() else None,
                               sourceAvailable=bool(sources),sourceBytes=sum(path.stat().st_size for path in set(sources)),highlights=highlights))
        stream=c.execute('SELECT * FROM streams WHERE project=?',(p['id'],)).fetchone()
        projects.append(dict(p,chunks=chunks,isLive=bool(stream and stream['is_live']),recording=live.recording(DATA/'live'/str(p['id']))))
    return dict(projects=projects)

class API(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if self.path.startswith('/api/youtube/oauth/callback'):
            return super().log_message('Google OAuth callback handled')
        return super().log_message(format,*args)

    def json(self,status,obj,cookie=None):
        b=json.dumps(obj).encode()
        self.send_response(status)
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def file(self,path,mime):
        size=path.stat().st_size
        start,end=0,size-1
        header=self.headers.get('Range')
        if header:
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
            if not m:return self.json(416,{'error':'Invalid range'})
            start=int(m[1])
            end=min(end,int(m[2])) if m[2] else end
            if start>end:return self.json(416,{'error':'Invalid range'})
        self.send_response(206 if header else 200)
        self.send_header('Content-Type',mime)
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','private, no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if mime=='application/zip':self.send_header('Content-Disposition','attachment; filename="ClipHunter.zip"')
        if header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length',str(end-start+1))
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start)
            remaining=end-start+1
            while remaining:
                b=f.read(min(remaining,262144))
                if not b:break
                self.wfile.write(b)
                remaining-=len(b)

    def handle_api(self):
        try:
            with db() as c:self.route(c)
        except (BrokenPipeError, ConnectionResetError):pass
        except (ValueError,TypeError,KeyError) as exc:self.json(400,{'error':str(exc)})
        except FileNotFoundError:self.json(404,{'error':'File unavailable'})
        except Exception:
            import traceback
            traceback.print_exc()
            self.json(500,{'error':'Request failed. See the local service log.'})

    do_GET=do_POST=do_PATCH=do_PUT=do_DELETE=handle_api
    def route(self,c):
        from worker import auth
        path=urlsplit(self.path).path
        method=self.command
        if path=='/api/health':return self.json(200,dict(ok=True,worker=runner.is_alive(),version='0.1'))
        if path=='/api/auth/status' and method=='GET':
            return self.json(200,{'setupRequired':not auth.configured(ROOT)})
        if path=='/api/youtube/oauth/callback' and method=='GET':
            from worker import youtube_publish
            query=parse_qs(urlsplit(self.path).query)
            try:
                if query.get('error'):raise ValueError('Google authorization was declined')
                youtube_publish.finish_auth((query.get('code') or [''])[0],(query.get('state') or [''])[0])
                result='connected'
            except (ValueError,KeyError) as exc:
                print('YouTube connection:',str(exc)[:200])
                result='failed'
            self.send_response(303)
            self.send_header('Location',f'http://127.0.0.1:3000/settings?youtube={result}')
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers()
            return
        body={}
        raw_audio=re.fullmatch(r'/api/highlights/\d+/audio',path) and method=='POST'
        if method!='GET':
            origin=self.headers.get('Origin')
            if origin and urlsplit(origin).hostname not in ('localhost','127.0.0.1'):return self.json(403,{'error':'Invalid origin'})
            n=int(self.headers.get('Content-Length',0))
            limit=50_000_000 if raw_audio else 400_000 if path=='/api/youtube-cookies' else 200_000 if re.fullmatch(r'/api/highlights/\d+/captions',path) else 8192
            if not 0<=n<=limit:raise ValueError('Request too large')
            if not raw_audio:body=json.loads(self.rfile.read(n) or '{}')
        if path in ('/api/login','/api/setup') and method=='POST':
            now=time.time()
            with lock:
                q=attempts[self.client_address[0]]
                while q and q[0]<now-60:q.popleft()
                if len(q)>=8:return self.json(429,{'error':'Try again in one minute'})
                if path=='/api/setup':
                    if auth.configured(ROOT):return self.json(409,{'error':'This studio already has a password'})
                    auth.set_password(body.get('password'))
                elif not auth.verify(body.get('password'),ROOT):
                    q.append(now)
                    return self.json(401,{'error':'Incorrect password'})
            token=secrets.token_urlsafe(32)
            c.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),int(now)+604800))
            return self.json(200,{'ok':True},f'ch_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800')
        cookies=SimpleCookie(self.headers.get('Cookie',''))
        token=cookies.get('ch_session')
        if not token or not c.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.value.encode()).hexdigest(),time.time())).fetchone():return self.json(401,{'error':'Sign in'})
        m=re.fullmatch(r'/api/highlights/(\d+)/audio',path)
        if m:
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            d=highlight_folder(h)
            music=d/f'music-{h["id"]}.bin'
            if method=='GET':return self.json(200,{'present':music.exists(),'bytes':music.stat().st_size if music.exists() else 0})
            if c.execute("SELECT 1 FROM youtube_uploads WHERE highlight=? AND status IN ('queued','uploading')",(m[1],)).fetchone():raise ValueError('Wait for this clip to finish uploading before changing audio')
            if h['status'] in ('queued','rendering','previewing','preparing','expanding'):raise ValueError('Wait for the current clip job to finish')
            if method=='DELETE':
                music.unlink(missing_ok=True)
                return self.json(200,{'present':False})
            if method=='POST':
                if n<100 or self.headers.get('Content-Type','').split(';')[0] not in ('audio/mpeg','audio/mp4','audio/x-m4a','audio/wav','audio/x-wav','audio/aac','application/octet-stream'):raise ValueError('Choose an MP3, M4A, WAV or AAC file under 50 MB')
                partial=music.with_suffix('.upload')
                try:
                    with partial.open('wb') as output:
                        remaining=n
                        while remaining:
                            block=self.rfile.read(min(1024*1024,remaining))
                            if not block:raise ValueError('Audio upload was interrupted')
                            output.write(block);remaining-=len(block)
                    signature=partial.open('rb').read(16)
                    if not (signature.startswith((b'ID3',b'RIFF')) or signature[4:8]==b'ftyp' or len(signature)>1 and signature[0]==0xff and signature[1]&0xf0==0xf0):raise ValueError('Choose a valid MP3, M4A, WAV or AAC file')
                    probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type:format=format_name','-of','json',str(partial)],capture_output=True,timeout=20,check=True)
                    media=json.loads(probe.stdout)
                    if media.get('format',{}).get('format_name') not in ('mp3','wav','aac','mov,mp4,m4a,3gp,3g2,mj2') or not any(stream.get('codec_type')=='audio' for stream in media.get('streams',[])):raise ValueError('Choose a valid audio file')
                    partial.replace(music)
                finally:partial.unlink(missing_ok=True)
                return self.json(200,{'present':True,'bytes':music.stat().st_size})
        if path=='/api/password' and method=='PUT':
            if not auth.verify(body.get('currentPassword'),ROOT):raise ValueError('Current password is incorrect')
            auth.set_password(body.get('newPassword'))
            c.execute('DELETE FROM sessions WHERE token<>?',(hashlib.sha256(token.value.encode()).hexdigest(),))
            return self.json(200,{'ok':True})
        if path=='/api/state' and method=='GET':return self.json(200,state(c))
        m=re.fullmatch(r'/api/chunks/(\d+)/chat-heatmap',path)
        if m and method=='GET':
            chunk=c.execute('SELECT id FROM chunks WHERE id=?',(m[1],)).fetchone()
            if not chunk:raise ValueError('Unknown stream hour')
            from worker.media import chat_heatmap
            chunk_folder=folder(chunk['id'])
            chat_file=chunk_folder/'chat.json'
            source_file=chunk_folder/'source.json'
            source=json.loads(source_file.read_text()) if source_file.exists() else {}
            duration=max(0,float(source.get('end',0))-float(source.get('start',0)))
            if chat_file.exists():
                replay=json.loads(chat_file.read_text())
                if not duration:duration=max((int(t) for t in replay.get('counts',{})),default=0)+1
                return self.json(200,dict(chat_heatmap(replay.get('counts',{}),duration),status=replay.get('status','unknown')))
            return self.json(200,dict(chat_heatmap({},duration),status='pending' if not source else source.get('chatStatus','unavailable')))
        if path=='/api/youtube/channel':
            from worker import youtube_publish
            if method=='GET':return self.json(200,youtube_publish.status())
            if method=='DELETE':
                if c.execute("SELECT 1 FROM youtube_uploads WHERE status IN ('queued','uploading')").fetchone():
                    raise ValueError('Wait for active uploads before disconnecting')
                youtube_publish.disconnect()
                return self.json(200,{'ok':True})
        if path=='/api/youtube/client' and method=='POST':
            from worker import youtube_publish
            return self.json(200,youtube_publish.save_client(body))
        if path=='/api/youtube/oauth/start' and method=='POST':
            from worker import youtube_publish
            return self.json(200,{'url':youtube_publish.start_auth()})
        m=re.fullmatch(r'/api/youtube/highlights/(\d+)/defaults',path)
        if m and method=='GET':
            h=c.execute('SELECT h.*,p.title project_title,p.url project_url,k.hour FROM highlights h JOIN chunks k ON k.id=h.chunk JOIN projects p ON p.id=k.project WHERE h.id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            moment=float(h['start'])+(h['hour']-1)*3600
            title=(h['project_title'].split('|')[0].strip() or h['title'])[:65]
            title=f'{title} · highlight at {int(moment)//60}:{int(moment)%60:02d}'[:100]
            description=f'Highlight from {h["project_title"]}.\nOriginal stream: {h["project_url"]}\n\n#Shorts #Gaming'
            return self.json(200,{'title':title,'description':description,'tags':['Shorts','gaming','stream highlights'],
                                  'privacy':'private','madeForKids':False})
        m=re.fullmatch(r'/api/youtube/highlights/(\d+)/upload',path)
        if m:
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            if method=='GET':
                job=c.execute('SELECT id,status,progress,bytes_sent,total_bytes,eta_seconds,video_id,error,metadata FROM youtube_uploads WHERE highlight=? ORDER BY id DESC LIMIT 1',(m[1],)).fetchone()
                return self.json(200,dict(job) if job else {'status':'idle'})
            if method=='POST':
                from worker import youtube_publish
                if not youtube_publish.status()['connected']:raise ValueError('Connect a YouTube channel in Settings')
                if h['status']!='ready' or not h['clip'] or not (highlight_folder(h)/f"clip-{h['id']}.mp4").exists():
                    raise ValueError('Export a finished MP4 before uploading')
                if c.execute("SELECT 1 FROM youtube_uploads WHERE highlight=? AND status IN ('queued','uploading')",(m[1],)).fetchone():
                    raise ValueError('This clip is already uploading')
                details=youtube_publish.validate_metadata(body)
                job_id=c.execute("INSERT INTO youtube_uploads(highlight,status,metadata,progress,bytes_sent,total_bytes,created_at) VALUES(?,'queued',?,0,0,?,?)",
                                 (m[1],json.dumps(details), (highlight_folder(h)/f"clip-{h['id']}.mp4").stat().st_size,int(time.time()))).lastrowid
                return self.json(202,{'id':job_id,'status':'queued'})
        m=re.fullmatch(r'/api/youtube/uploads/(\d+)/retry',path)
        if m and method=='POST':
            job=c.execute('SELECT * FROM youtube_uploads WHERE id=?',(m[1],)).fetchone()
            if not job or job['status']!='error':raise ValueError('Only failed uploads can be retried')
            c.execute("UPDATE youtube_uploads SET status='queued',error=NULL WHERE id=?",(m[1],))
            return self.json(202,{'ok':True})
        if path=='/api/youtube-cookies' and method=='POST':
            from worker.youtube_auth import save_cookies
            save_cookies(body.get('cookies'))
            return self.json(200,{'ok':True})
        if path=='/api/logout' and method=='POST':
            c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.value.encode()).hexdigest(),))
            return self.json(200,{'ok':True},'ch_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
        if path=='/api/settings' and method in ('GET','PUT'):
            if method=='PUT':
                model,gb=body.get('model'),int(body.get('maxDataGB',0))
                if model not in ('tiny','base','small') or not 2<=gb<=100:raise ValueError('Choose a supported model and a storage limit of 2–100 GB')
                c.execute('UPDATE settings SET model=?,gb=?',(model,gb))
            s=c.execute('SELECT * FROM settings').fetchone()
            return self.json(200,{'model':s['model'],'maxDataGB':s['gb']})
        m=re.fullmatch(r'/api/chunks/(\d+)/rescan',path)
        if m and method=='POST':
            chunk=c.execute('SELECT * FROM chunks WHERE id=?',(m[1],)).fetchone()
            if not chunk:raise ValueError('Unknown stream hour')
            if chunk['status'] not in ('ready','error'):raise ValueError('Wait for the current scan')
            c.execute("UPDATE chunks SET status='queued',error=NULL WHERE id=?",(m[1],))
            return self.json(202,{'ok':True})
        m=re.fullmatch(r'/api/chunks/(\d+)/manual-clip',path)
        if m and method=='POST':
            chunk=c.execute('SELECT status FROM chunks WHERE id=?',(m[1],)).fetchone()
            if not chunk:raise ValueError('Unknown stream hour')
            if chunk['status']!='ready':raise ValueError('Wait for this hour to finish scanning')
            d=folder(m[1])
            metadata=d/'source.json'
            sparse=metadata.exists() and json.loads(metadata.read_text()).get('sparse',False)
            if not sparse and not (d/'source.mp4').exists():raise ValueError('The downloaded hour video is required to make a clip')
            signals=d/'signals.json'
            if not sparse and not signals.exists():raise ValueError('Analyze the hour before creating a clip')
            duration=(json.loads(metadata.read_text())['end']-json.loads(metadata.read_text())['start']) if sparse else len(json.loads(signals.read_text())['score'])
            if duration<20:raise ValueError('This hour is too short for a clip')
            if 'start' not in body:raise ValueError('Enter the exact stream time for a manual clip')
            start=float(body['start'])
            end=min(duration,start+42)
            if not (math.isfinite(start) and 0<=start<duration and end-start>=20):raise ValueError('Choose a start time with at least 20 seconds remaining')
            hid=c.execute("INSERT INTO highlights(chunk,start,end,title,status,score,reason) VALUES(?,?,?,?,?,NULL,?)",(m[1],start,end,f'Manual clip at {int(start)//60}:{int(start)%60:02d}','preparing' if sparse else 'previewing','Created manually; adjust the timing in the editor.')).lastrowid
            if sparse:
                project=c.execute('SELECT p.url,k.hour FROM chunks k JOIN projects p ON p.id=k.project WHERE k.id=?',(m[1],)).fetchone()
                child=d/f'highlight-{hid}';child.mkdir(exist_ok=True)
                atomic_json(child/'plan.json',{'url':project['url'],'hour':project['hour'],'start':start,'end':end})
            return self.json(201,{'id':hid})
        m=re.fullmatch(r'/api/chunks/(\d+)/(layout|frame|source)',path)
        if m and c.execute('SELECT 1 FROM chunks WHERE id=?',(m[1],)).fetchone():
            d=folder(m[1])
            if m[2]=='source' and method=='GET':return self.file(d/'source.mp4','video/mp4')
            if m[2]=='source' and method=='DELETE':
                k=c.execute('SELECT k.status,k.project,p.url FROM chunks k JOIN projects p ON p.id=k.project WHERE k.id=?',(m[1],)).fetchone()
                if k['status'] in ('queued','scanning') or c.execute("SELECT 1 FROM chunks WHERE project=? AND status IN ('queued','scanning')",(k['project'],)).fetchone() or c.execute("SELECT 1 FROM highlights WHERE chunk=? AND status IN ('queued','rendering','previewing','preparing','expanding')",(m[1],)).fetchone():
                    raise ValueError('Wait for scanning, previews and renders to finish before deleting this source')
                removed=0
                cache=d.parent/('cache-'+hashlib.sha256(k['url'].encode()).hexdigest()[:16]+'.mp4')
                for path in (d/'source.mp4',d/'capture.mp4',cache):
                    if path.exists():removed+=path.stat().st_size;path.unlink()
                for path in d.glob('highlight-*/source.mp4'):
                    removed+=path.stat().st_size;path.unlink()
                return self.json(200,{'ok':True,'removedBytes':removed})
            if m[2]=='frame' and method=='GET':
                frame=d/'layout.jpg'
                if not frame.exists():subprocess.run(['ffmpeg','-v','error','-y','-ss','5','-i',str(d/'source.mp4'),'-frames:v','1','-vf','scale=720:-2',str(frame)],check=True,timeout=30)
                return self.file(frame,'image/jpeg')
            if m[2]=='layout':
                layout=d/'layout.json'
                x=json.loads(layout.read_text())
                initial=d/'auto-layout.json'
                if method=='PATCH':
                    if c.execute("SELECT 1 FROM highlights WHERE chunk=? AND status IN ('queued','rendering','previewing')",(m[1],)).fetchone():raise ValueError('Wait for pending jobs before adjusting the layout')
                    mode=body.get('mode')
                    if mode not in ('auto','split','full'):raise ValueError('Invalid layout')
                    if not initial.exists():initial.write_text(json.dumps(x))
                    if mode=='auto':x=json.loads(initial.read_text())
                    else:
                        box=body.get('box')
                        if mode=='split' and not (isinstance(box,list) and len(box)==4 and all(isinstance(v,(float,int)) and 0<=v<=1 for v in box) and box[2]>.01 and box[3]>.01 and box[0]+box[2]<=1.000001 and box[1]+box[3]<=1.000001):raise ValueError('Draw a box inside the frame')
                        x.update(mode=mode,facecamBox=box if mode=='split' else None)
                    x['selection']=mode
                    layout.write_text(json.dumps(x))
                    c.execute("UPDATE highlights SET status='previewing',preview=NULL,clip=NULL WHERE chunk=?",(m[1],))
                return self.json(200,{'mode':x.get('selection','auto'),'box':x.get('facecamBox')})
        if path=='/api/projects' and method=='POST':
            url=check_url(body['url'])
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT id FROM projects WHERE url=?',(url,)).fetchone()
            if existing:return self.json(200,{'id':existing['id'],'existing':True})
            pid=c.execute('INSERT INTO projects(url,title) VALUES(?,?)',(url,urlsplit(url).path.strip('/')[:80])).lastrowid
            c.execute("INSERT INTO chunks(project,hour,status) VALUES(?,1,'queued')",(pid,))
            return self.json(201,{'id':pid})
        m=re.fullmatch(r'/api/projects/(\d+)/(scan|zip|stop)',path)
        if m and c.execute('SELECT 1 FROM projects WHERE id=?',(m[1],)).fetchone():
            if m[2]=='stop' and method=='POST':
                live.stop(DATA/'live'/m[1])
                c.execute('UPDATE streams SET stopped=1 WHERE project=?',(m[1],))
                return self.json(200,{'ok':True})
            if m[2]=='scan' and method=='POST':
                c.execute('BEGIN IMMEDIATE')
                k=c.execute('SELECT * FROM chunks WHERE project=? ORDER BY hour DESC LIMIT 1',(m[1],)).fetchone()
                if k['status']=='error':c.execute("UPDATE chunks SET status='queued',error=NULL WHERE id=?",(k['id'],))
                elif k['status']=='ready':c.execute("INSERT INTO chunks(project,hour,status) VALUES(?,?,'queued')",(m[1],k['hour']+1))
                return self.json(202,{'ok':True})
            if m[2]=='zip' and method=='GET':
                import tempfile
                with tempfile.NamedTemporaryFile(dir=DATA,suffix='.zip') as f:
                    with zipfile.ZipFile(f.name,'w') as z:
                        for h in c.execute("SELECT h.* FROM highlights h JOIN chunks k ON k.id=h.chunk WHERE k.project=? AND h.clip IS NOT NULL",(m[1],)):
                            name=f"clip-{h['id']}.mp4"
                            z.write(highlight_folder(h)/name,name)
                    return self.file(Path(f.name),'application/zip')
        m=re.fullmatch(r'/api/highlights/(\d+)/captions\.srt',path)
        if m and method=='GET':
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            captions_file=highlight_folder(h)/f'captions-{h["id"]}.json'
            if not captions_file.exists():return self.json(404,{'error':'Generate or add captions first'})
            from worker.caption_export import render_srt
            saved=json.loads(captions_file.read_text())
            payload=render_srt(saved.get('segments',[]),h['start'],h['end']).encode('utf-8-sig')
            self.send_response(200)
            self.send_header('Content-Type','application/x-subrip; charset=utf-8')
            self.send_header('Content-Disposition',f'attachment; filename="clip-{h["id"]}.srt"')
            self.send_header('Cache-Control','private, no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        m=re.fullmatch(r'/api/highlights/(\d+)/captions',path)
        if m:
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            d=highlight_folder(h)
            captions_file=d/f'captions-{h["id"]}.json'
            job_file=d/f'caption-job-{h["id"]}.json'
            if method=='GET':
                saved=json.loads(captions_file.read_text()) if captions_file.exists() else {'language':None,'confidence':None,'segments':[]}
                job=json.loads(job_file.read_text()) if job_file.exists() else {'status':'idle'}
                if job['status']=='processing':
                    with caption_lock:active=h['id'] in caption_active
                    if not active:job={'status':'error','error':'Caption generation was interrupted. Try again.'}
                return self.json(200,{**saved,'job':job})
            if method=='POST':
                language=body.get('language','auto')
                output=body.get('output','original')
                model_name=body.get('model','large-v3')
                if language!='auto' and (not isinstance(language,str) or not re.fullmatch(r'[a-z]{2,3}',language)):
                    raise ValueError('Choose a supported spoken language')
                from worker.captioning import TARGET_LANGUAGES
                if output not in ('original','en') and output not in TARGET_LANGUAGES:raise ValueError('Choose a supported caption language')
                if model_name not in ('large-v3','small'):raise ValueError('Choose a supported speech model')
                if not (d/'source.mp4').exists():raise ValueError('This hour source was deleted')
                with caption_lock:
                    if caption_active:return self.json(409,{'error':'Another caption job is running. Try again when it finishes.'})
                    caption_active.add(h['id'])
                atomic_json(job_file,{'status':'processing','phase':'Preparing speech model','fraction':0,'etaSeconds':None})
                threading.Thread(target=caption_task,args=(h['id'],h['chunk'],h['start'],h['end'],language,output,model_name),daemon=True).start()
                return self.json(202,{'status':'processing'})
            if method=='PUT':
                with caption_lock:
                    if h['id'] in caption_active:raise ValueError('Wait for caption recognition to finish')
                segments=body.get('segments')
                if not isinstance(segments,list) or len(segments)>200:raise ValueError('Provide up to 200 caption lines')
                duration=len(json.loads((d/'signals.json').read_text())['score'])
                clean=[]
                for item in segments:
                    if not isinstance(item,dict) or not isinstance(item.get('text'),str) or not 0<len(item['text'].strip())<=200:raise ValueError('Each caption needs 1–200 characters')
                    a,b=float(item.get('start')),float(item.get('end'))
                    if not (math.isfinite(a) and math.isfinite(b) and 0<=a<b<=duration):raise ValueError('Keep caption times within this hour')
                    clean.append({'start':round(a,3),'end':round(b,3),'text':item['text'].strip()})
                clean.sort(key=lambda item:item['start'])
                if any(clean[i]['end']>clean[i+1]['start']+.01 for i in range(len(clean)-1)):raise ValueError('Caption lines cannot overlap')
                current=json.loads(captions_file.read_text()) if captions_file.exists() else {}
                atomic_json(captions_file,{'language':current.get('language'),'confidence':current.get('confidence'),'segments':clean})
                return self.json(200,{'ok':True})
        m=re.fullmatch(r'/api/highlights/(\d+)/(source|layout|waveform)',path)
        if m and method=='GET':
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            d=highlight_folder(h)
            if m[2]=='source':return self.file(d/'source.mp4','video/mp4')
            if m[2]=='waveform':
                energy=json.loads((d/'signals.json').read_text()).get('energy',[])
                return self.json(200,{'samples':[round(max(0,min(1,(float(value)+60)/45)),3) for value in energy]})
            layout=json.loads((d/'layout.json').read_text())
            return self.json(200,{'mode':layout.get('mode','full'),'box':layout.get('facecamBox')})
        m=re.fullmatch(r'/api/highlights/(\d+)/extend',path)
        if m and method=='POST':
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            if h['status'] not in ('ready','error'):raise ValueError('Wait for the current clip job to finish')
            d=highlight_folder(h)
            if d==folder(h['chunk']):raise ValueError('This hour source is already downloaded.')
            side=body.get('side')
            if side not in ('before','after'):raise ValueError('Choose earlier or later footage')
            meta=json.loads((d/'source.json').read_text())
            hour=json.loads((d.parent/'source.json').read_text())
            available=(float(meta['start'])-float(hour['start'])) if side=='before' else (float(hour['end'])-float(meta['end']))
            if available<2:raise ValueError('No more footage is available on that side')
            atomic_json(d/'expand-plan.json',{'side':side})
            c.execute("UPDATE highlights SET status='expanding',error=NULL WHERE id=?",(h['id'],))
            return self.json(202,{'status':'expanding','seconds':min(60,available)})
        m=re.fullmatch(r'/api/highlights/(\d+)/(edit|frame)',path)
        if m:
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            d=highlight_folder(h)
            if m[2]=='frame' and method=='GET':
                frame=d/f'frame-{h["id"]}.jpg'
                if not frame.exists():
                    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(min(h['start']+5,h['end']-1)),'-i',str(d/'source.mp4'),'-frames:v','1','-vf','scale=960:-2',str(frame)],check=True,timeout=45)
                return self.file(frame,'image/jpeg')
            if m[2]=='edit':
                settings=d/f'edit-{h["id"]}.json'
                if method=='GET':
                    words=json.loads((d/'transcript.json').read_text()).get('words',[]) if (d/'transcript.json').exists() else []
                    example=' '.join(w['w'] for w in words if h['start']<=w['s']<h['end'])[:4]
                    source_duration=float(json.loads((d/'source.json').read_text()).get('end',0))-float(json.loads((d/'source.json').read_text()).get('start',0)) if (d/'source.json').exists() else len(json.loads((d/'signals.json').read_text())['score'])
                    sparse=d!=folder(h['chunk'])
                    meta=json.loads((d/'source.json').read_text()) if sparse else {}
                    hour=json.loads((d.parent/'source.json').read_text()) if sparse else {}
                    plan=json.loads((d/'plan.json').read_text()) if sparse and (d/'plan.json').exists() else {}
                    reaction_at=(float(hour['start'])+(float(plan['start'])+float(plan['end']))/2-float(meta['start'])) if plan else None
                    return self.json(200,{'edit':json.loads(settings.read_text()) if settings.exists() else {},'start':h['start'],'end':h['end'],'chunk':h['chunk'],'sourceDuration':source_duration,'reactionAt':reaction_at,'sparse':sparse,'canExtendBefore':sparse and float(meta['start'])-float(hour['start'])>=2,'canExtendAfter':sparse and float(hour['end'])-float(meta['end'])>=2,'captionExample':example})
                if method=='PATCH':
                    if c.execute("SELECT 1 FROM youtube_uploads WHERE highlight=? AND status IN ('queued','uploading')",(m[1],)).fetchone():
                        raise ValueError('Wait for this clip to finish uploading before editing')
                    if h['status'] in ('queued','rendering','previewing','preparing','expanding'):raise ValueError('Wait for the current clip job to finish')
                    if not (d/'source.mp4').exists():raise ValueError('This hour source was deleted. Existing clips remain available.')
                    a,b=float(body.get('start')),float(body.get('end'))
                    duration=len(json.loads((d/'signals.json').read_text())['score'])
                    if not (0<=a<b<=duration and 20<=b-a<=180):raise ValueError('Choose a 20–180 second range within the footage')
                    edit=body.get('edit')
                    if not isinstance(edit,dict):raise ValueError('Invalid edit')
                    if edit.get('layoutMode') not in ('full','split') or edit.get('facePosition') not in ('top','bottom') or edit.get('captionTemplate') not in ('solid','minimal','accent') or edit.get('font') not in ('Arial Bold.ttf','Impact.ttf','Georgia Bold.ttf','Verdana Bold.ttf'):
                        raise ValueError('Choose a supported layout, caption template and font')
                    if not isinstance(edit.get('fontSize'),int) or not 28<=edit['fontSize']<=72:raise ValueError('Caption size must be 28–72')
                    if not isinstance(edit.get('facecamFraction'),(float,int)) or not .25<=edit['facecamFraction']<=.65:raise ValueError('Facecam height must be 25–65%')
                    for color in ('textColor','boxColor'):
                        if not isinstance(edit.get(color),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',edit[color]):raise ValueError('Use a six-digit caption color')
                    for key in ('gameBox','facecamBox'):
                        box=edit.get(key)
                        if not (isinstance(box,list) and len(box)==4 and all(isinstance(v,(float,int)) and 0<=v<=1 for v in box) and box[2]>=.05 and box[3]>=.05 and box[0]+box[2]<=1.000001 and box[1]+box[3]<=1.000001):
                            raise ValueError('Keep both crop boxes inside the source frame')
                    if edit.get('captionMode','auto') not in ('auto','off'):raise ValueError('Choose captions on or off')
                    caption_language=edit.get('captionLanguage','auto')
                    if caption_language!='auto' and (not isinstance(caption_language,str) or not re.fullmatch(r'[a-z]{2,3}',caption_language)):
                        raise ValueError('Choose a supported spoken language')
                    from worker.captioning import TARGET_LANGUAGES
                    if edit.get('captionOutput','original') not in ('original','en') and edit.get('captionOutput') not in TARGET_LANGUAGES:raise ValueError('Choose a supported caption language')
                    from worker.text_overlays import validate_text_overlays
                    text_overlays=validate_text_overlays(edit.get('textOverlays',[]),duration)
                    saved={key:edit[key] for key in ('layoutMode','facePosition','captionTemplate','font','fontSize','facecamFraction','textColor','boxColor','gameBox','facecamBox')}
                    saved.update(captionMode=edit.get('captionMode','off'),captionLanguage=caption_language,captionOutput=edit.get('captionOutput','original'))
                    saved['textOverlays']=text_overlays
                    for key in ('sourceVolume','musicVolume'):
                        value=edit.get(key,1 if key=='sourceVolume' else .5)
                        if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=2:raise ValueError('Audio volume must be 0–200%')
                        saved[key]=round(value,3)
                    music_start=edit.get('musicStart',0)
                    if not isinstance(music_start,(int,float)) or not math.isfinite(music_start) or not 0<=music_start<=180:raise ValueError('Audio layer start must be within the clip')
                    saved['musicStart']=round(music_start,3)
                    temporary=settings.with_suffix('.tmp')
                    temporary.write_text(json.dumps(saved))
                    temporary.replace(settings)
                    (d/f'frame-{h["id"]}.jpg').unlink(missing_ok=True)
                    c.execute("UPDATE highlights SET start=?,end=?,clip=NULL,preview=NULL,status='previewing',error=NULL WHERE id=?",(a,b,h['id']))
                    return self.json(200,{'ok':True})
        m=re.fullmatch(r'/api/highlights/(\d+)(/render)?',path)
        if m:
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if not h:return self.json(404,{'error':'Unknown highlight'})
            if m[2] and method=='POST':
                if c.execute("SELECT 1 FROM youtube_uploads WHERE highlight=? AND status IN ('queued','uploading')",(m[1],)).fetchone():
                    raise ValueError('Wait for this clip to finish uploading before rendering again')
                if not (highlight_folder(h)/'source.mp4').exists():raise ValueError('The source clip was deleted. Existing renders remain available.')
                if h['status'] in ('previewing','preparing','expanding','rendering','queued'):raise ValueError('Wait for the current clip job to finish')
                width=body.get('width',1080)
                if width not in (720,1080):raise ValueError('Choose 720×1280 or 1080×1920 export')
                atomic_json(highlight_folder(h)/f'export-{h["id"]}.json',{'width':width})
                c.execute("UPDATE highlights SET status='queued',error=NULL WHERE id=? AND status NOT IN ('queued','rendering')",(m[1],))
                return self.json(202,{'ok':True})
            if not m[2] and method=='PATCH':
                a,b=float(body['start']),float(body['end'])
                duration=len(json.loads((highlight_folder(h)/'signals.json').read_text())['score'])
                if not (0<=a<b<=duration and 20<=b-a<=180):raise ValueError('Choose a 20–180 second range within the available footage')
                if h['status'] in ('queued','rendering','previewing','preparing','expanding'):raise ValueError('Wait for this job to finish')
                c.execute("UPDATE highlights SET start=?,end=?,clip=NULL,preview=NULL,status='previewing' WHERE id=?",(a,b,m[1]))
                return self.json(200,{'ok':True})
        m=re.fullmatch(r'/api/media/(\d+)/(preview|clip)',path)
        if m and method=='GET':
            h=c.execute('SELECT * FROM highlights WHERE id=?',(m[1],)).fetchone()
            if h and h[m[2]]:return self.file(highlight_folder(h)/f'{m[2]}-{m[1]}.mp4','video/mp4')
        self.json(404,{'error':'Unknown route'})

if __name__=='__main__':
    initialize()
    runner=threading.Thread(target=worker,daemon=True)
    runner.start()
    publisher=threading.Thread(target=upload_worker,daemon=True)
    publisher.start()
    class LocalServer(ThreadingHTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name,self.server_port=self.server_address
    def shutdown(*_):
        for path in list(live.recorders):live.stop(path)
        raise SystemExit
    signal.signal(signal.SIGTERM,shutdown)
    LocalServer((os.environ.get('CLIPHUNTER_API_BIND','127.0.0.1'),int(os.environ.get('CLIPHUNTER_API_PORT','3101'))),API).serve_forever()
