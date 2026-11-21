"""Optional owner-supplied YouTube session for local yt-dlp jobs."""
from pathlib import Path
import os

COOKIE_FILE = Path(os.environ.get('CLIPHUNTER_CONFIG_DIR', Path.home()/'.config'/'ClipHunter'))/'youtube-cookies.txt'

def cookie_args(url):
    if 'youtube.com/watch?' in url and COOKIE_FILE.is_file():
        return ['--cookies',str(COOKIE_FILE)]
    return []

def save_cookies(contents):
    if not isinstance(contents,str) or len(contents.encode('utf8'))>300_000:
        raise ValueError('Use a YouTube-only cookies.txt file under 300 KB.')
    lines=contents.splitlines()
    if not lines or lines[0] not in ('# Netscape HTTP Cookie File','# HTTP Cookie File'):
        raise ValueError('Select a Netscape-format cookies.txt file.')
    kept=[lines[0]]
    count=0
    for line in lines[1:]:
        if not line or line.startswith('#') and not line.startswith('#HttpOnly_'):
            continue
        fields=line.removeprefix('#HttpOnly_').split('\t')
        if len(fields)!=7:raise ValueError('Invalid cookies.txt row.')
        domain=fields[0].lstrip('.').lower()
        if domain not in ('youtube.com','google.com','googlevideo.com') and not domain.endswith(('.youtube.com','.google.com','.googlevideo.com')):
            raise ValueError('Export only YouTube-related cookies, not your full browser session.')
        kept.append(line)
        count+=1
    if not count:raise ValueError('No YouTube cookies found in this file.')
    COOKIE_FILE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(COOKIE_FILE.parent,0o700)
    temp=COOKIE_FILE.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as file:file.write('\n'.join(kept)+'\n')
    os.replace(temp,COOKIE_FILE)
    os.chmod(COOKIE_FILE,0o600)
