"""Local OAuth and resumable YouTube publishing. Secrets stay outside the release tree."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CONFIG = Path(os.environ.get('CLIPHUNTER_CONFIG_DIR', Path.home()/'.config'/'ClipHunter'))
CLIENT = CONFIG/'youtube-oauth-client.json'
TOKEN = CONFIG/'youtube-oauth-token.json'
PENDING = CONFIG/'youtube-oauth-pending.json'
UPLOADS = CONFIG/'youtube-uploads'
AUTH_URI = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
REDIRECT = f"http://127.0.0.1:{os.environ.get('CLIPHUNTER_API_PORT','3101')}/api/youtube/oauth/callback"
SCOPES = 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'


def private_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    temporary=path.with_suffix(path.suffix+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump(value,stream)
        os.replace(temporary,path)
        os.chmod(path,0o600)
    finally:
        if temporary.exists():temporary.unlink()


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


def save_client(value):
    if not isinstance(value,dict):raise ValueError('Choose the Google OAuth desktop client JSON file')
    client=value.get('installed')
    if not isinstance(client,dict):raise ValueError('Create a Desktop app OAuth client in Google Cloud and import its JSON')
    client_id,secret=client.get('client_id'),client.get('client_secret')
    if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.apps\.googleusercontent\.com',client_id):
        raise ValueError('Invalid Google OAuth client ID')
    if not isinstance(secret,str) or not 5<=len(secret)<=300:raise ValueError('Invalid Google OAuth client secret')
    if client.get('auth_uri') not in (None,AUTH_URI,'https://accounts.google.com/o/oauth2/auth') or client.get('token_uri') not in (None,TOKEN_URI):
        raise ValueError('OAuth endpoints must be Google endpoints')
    private_json(CLIENT,{'client_id':client_id,'client_secret':secret})
    TOKEN.unlink(missing_ok=True)
    return {'configured':True}


def configured():return CLIENT.exists()


def start_auth():
    client=read_json(CLIENT)
    if not client:raise ValueError('Import a Google OAuth desktop client JSON in Settings first')
    state=secrets.token_urlsafe(32)
    verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    private_json(PENDING,{'state':state,'verifier':verifier,'expires':time.time()+600})
    query=urlencode({'client_id':client['client_id'],'redirect_uri':REDIRECT,'response_type':'code',
                     'scope':SCOPES,'access_type':'offline','prompt':'consent','state':state,
                     'code_challenge':challenge,'code_challenge_method':'S256'})
    return AUTH_URI+'?'+query


def _post_form(url,fields):
    request=Request(url,data=urlencode(fields).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
    try:
        with urlopen(request,timeout=30) as response:return json.load(response)
    except HTTPError as exc:
        raise ValueError('Google authorization failed: '+exc.read(300).decode(errors='replace')) from None


def finish_auth(code,state):
    pending=read_json(PENDING)
    if not pending or time.time()>pending['expires'] or not secrets.compare_digest(str(state),pending['state']):
        raise ValueError('Google authorization expired or did not match this request')
    PENDING.unlink(missing_ok=True)
    if not code or len(code)>4096:raise ValueError('Google did not return an authorization code')
    client=read_json(CLIENT)
    token=_post_form(TOKEN_URI,{'code':code,'client_id':client['client_id'],'client_secret':client['client_secret'],
                                'redirect_uri':REDIRECT,'grant_type':'authorization_code','code_verifier':pending['verifier']})
    if not token.get('refresh_token') or not token.get('access_token'):
        raise ValueError('Google did not grant offline upload access; reconnect and grant access')
    token['expires_at']=time.time()+int(token.get('expires_in',3600))-60
    private_json(TOKEN,token)
    try:channel_info=channel()
    except Exception:
        TOKEN.unlink(missing_ok=True)
        raise
    return channel_info


def access_token():
    token=read_json(TOKEN)
    if not token or not token.get('refresh_token'):raise ValueError('Connect a YouTube channel in Settings')
    if token.get('access_token') and token.get('expires_at',0)>time.time():return token['access_token']
    client=read_json(CLIENT)
    if not client:raise ValueError('Google OAuth client configuration is missing')
    result=_post_form(TOKEN_URI,{'refresh_token':token['refresh_token'],'client_id':client['client_id'],
                                 'client_secret':client['client_secret'],'grant_type':'refresh_token'})
    token.update(result)
    token['expires_at']=time.time()+int(result.get('expires_in',3600))-60
    private_json(TOKEN,token)
    return token['access_token']


def _google_json(url):
    request=Request(url,headers={'Authorization':'Bearer '+access_token()})
    try:
        with urlopen(request,timeout=30) as response:return json.load(response)
    except HTTPError as exc:
        raise ValueError('YouTube channel lookup failed: '+exc.read(300).decode(errors='replace')) from None


def channel():
    data=_google_json('https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true')
    items=data.get('items') or []
    if not items:raise ValueError('The selected Google account has no accessible YouTube channel')
    item=items[0]
    details={'id':item['id'],'title':item.get('snippet',{}).get('title','YouTube channel')}
    private_json(CONFIG/'youtube-channel.json',details)
    return details


def status():
    details=read_json(CONFIG/'youtube-channel.json') if TOKEN.exists() else None
    return {'configured':configured(),'connected':bool(TOKEN.exists()),'channel':details}


def disconnect():
    token=read_json(TOKEN)
    if token:
        request=Request('https://oauth2.googleapis.com/revoke',
                        data=urlencode({'token':token.get('refresh_token','')}).encode(),method='POST',
                        headers={'Content-Type':'application/x-www-form-urlencoded'})
        try:
            with urlopen(request,timeout=15):pass
        except (HTTPError,URLError):pass
    TOKEN.unlink(missing_ok=True)
    (CONFIG/'youtube-channel.json').unlink(missing_ok=True)
    PENDING.unlink(missing_ok=True)


def validate_metadata(value):
    if not isinstance(value,dict):raise ValueError('Enter video details')
    title=str(value.get('title','')).strip();description=str(value.get('description','')).strip()
    tags=value.get('tags',[])
    if not title or len(title)>100:raise ValueError('Video title must be 1–100 characters')
    if len(description)>5000:raise ValueError('Description must be at most 5,000 characters')
    if not isinstance(tags,list) or len(tags)>30 or any(not isinstance(tag,str) or not tag.strip() or len(tag)>80 for tag in tags):
        raise ValueError('Use up to 30 short tags')
    privacy=value.get('privacy')
    if privacy not in ('public','unlisted','private','schedule'):raise ValueError('Choose a publishing option')
    publish_at=None
    if privacy=='schedule':
        try:parsed=datetime.fromisoformat(value['publishAt'].replace('Z','+00:00'))
        except (KeyError,ValueError,TypeError):raise ValueError('Choose a valid schedule date and time') from None
        if parsed.tzinfo is None or parsed.timestamp()<time.time()+60:raise ValueError('Schedule at least one minute in the future')
        publish_at=parsed.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    made_for_kids=value.get('madeForKids')
    if not isinstance(made_for_kids,bool):raise ValueError('Choose whether this video is made for kids')
    return {'title':title,'description':description,'tags':[tag.strip() for tag in tags],
            'privacy':privacy,'publishAt':publish_at,'madeForKids':made_for_kids}


def _response(request):
    try:return urlopen(request,timeout=90)
    except HTTPError as exc:return exc


def _validated_session(uri):
    parsed=urlsplit(uri)
    if parsed.scheme!='https' or parsed.hostname not in ('www.googleapis.com','upload.googleapis.com'):
        raise ValueError('Unexpected YouTube upload endpoint')
    return uri


def upload_video(job_id,file,metadata,progress):
    file=Path(file);size=file.stat().st_size;mtime=file.stat().st_mtime_ns
    if size<=0:raise ValueError('Rendered clip is empty')
    UPLOADS.mkdir(parents=True,exist_ok=True,mode=0o700)
    state_file=UPLOADS/f'{int(job_id)}.json'
    state=read_json(state_file) or {}
    if state.get('video_id'):return state['video_id']
    uri=state.get('session')
    if state and (state.get('size')!=size or state.get('mtime')!=mtime):
        raise ValueError('The rendered file changed after upload started; start a new upload')
    if not uri:
        status={'privacyStatus':'private' if metadata['privacy']=='schedule' else metadata['privacy'],
                'selfDeclaredMadeForKids':metadata['madeForKids']}
        if metadata['publishAt']:status['publishAt']=metadata['publishAt']
        body={'snippet':{'title':metadata['title'],'description':metadata['description'],
                         'tags':metadata['tags'],'categoryId':'20'},'status':status}
        request=Request('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
                        data=json.dumps(body).encode(),method='POST',headers={
                        'Authorization':'Bearer '+access_token(),'Content-Type':'application/json; charset=UTF-8',
                        'X-Upload-Content-Length':str(size),'X-Upload-Content-Type':'video/mp4'})
        response=_response(request)
        if response.status not in (200,201):raise ValueError('YouTube rejected the upload: '+response.read(400).decode(errors='replace'))
        uri=_validated_session(response.headers.get('Location',''))
        private_json(state_file,{'session':uri,'size':size,'mtime':mtime})
    else:uri=_validated_session(uri)
    # Ask YouTube for its acknowledged byte range, including after a process restart.
    probe=Request(uri,data=b'',method='PUT',headers={'Authorization':'Bearer '+access_token(),
                  'Content-Length':'0','Content-Range':f'bytes */{size}'})
    response=_response(probe)
    if response.status in (200,201):
        result=json.load(response);private_json(state_file,{**state,'video_id':result['id']});progress(1,size,size)
        return result['id']
    if response.status!=308:raise ValueError('Could not resume YouTube upload: '+response.read(350).decode(errors='replace'))
    match=re.search(r'bytes=0-(\d+)',response.headers.get('Range',''))
    offset=int(match[1])+1 if match else 0
    begun=time.monotonic();chunk_size=8*1024*1024
    with file.open('rb') as stream:
        stream.seek(offset)
        while offset<size:
            if file.stat().st_size!=size or file.stat().st_mtime_ns!=mtime:
                raise ValueError('Rendered clip changed during upload')
            payload=stream.read(min(chunk_size,size-offset))
            if not payload:raise ValueError('Rendered clip ended early')
            end=offset+len(payload)-1
            request=Request(uri,data=payload,method='PUT',headers={'Authorization':'Bearer '+access_token(),
                            'Content-Type':'video/mp4','Content-Length':str(len(payload)),
                            'Content-Range':f'bytes {offset}-{end}/{size}'})
            response=_response(request)
            if response.status in (200,201):
                result=json.load(response);private_json(state_file,{'session':uri,'size':size,'mtime':mtime,'video_id':result['id']});progress(1,size,size)
                return result['id']
            if response.status!=308:
                raise ValueError('YouTube upload failed: '+response.read(350).decode(errors='replace'))
            match=re.search(r'bytes=0-(\d+)',response.headers.get('Range',''))
            acknowledged=int(match[1])+1 if match else offset
            if acknowledged<=offset:raise ValueError('YouTube did not accept the uploaded chunk')
            offset=acknowledged;stream.seek(offset)
            elapsed=time.monotonic()-begun
            rate=offset/max(1,elapsed)
            progress(offset/size,offset,size,round((size-offset)/rate) if rate else None)
    raise ValueError('YouTube did not confirm the completed upload')


def finish_job(job_id):
    (UPLOADS/f'{int(job_id)}.json').unlink(missing_ok=True)
