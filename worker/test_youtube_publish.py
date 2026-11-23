import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from datetime import datetime,timedelta,timezone

from worker import youtube_publish as pub


class FakeResponse(io.BytesIO):
    def __init__(self,status,body=b'',headers=None):
        super().__init__(body);self.status=status;self.headers=headers or {}


class YoutubePublishTests(unittest.TestCase):
    def test_metadata_requires_explicit_audience_and_future_schedule(self):
        base={'title':'Clip title','description':'About the clip','tags':['gaming'],'privacy':'schedule'}
        with self.assertRaises(ValueError):pub.validate_metadata(base)
        future=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        clean=pub.validate_metadata({**base,'madeForKids':False,'publishAt':future})
        self.assertEqual(clean['privacy'],'schedule')
        self.assertTrue(clean['publishAt'].endswith('Z'))
        with self.assertRaises(ValueError):pub.validate_metadata({**base,'madeForKids':False,'publishAt':'2020-01-01T00:00:00Z'})

    def test_private_oauth_state_and_pkce(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(pub,'CONFIG',root),patch.object(pub,'CLIENT',root/'client.json'),patch.object(pub,'PENDING',root/'pending.json'),patch.object(pub,'TOKEN',root/'token.json'):
                pub.save_client({'installed':{'client_id':'123-abc.apps.googleusercontent.com','client_secret':'a-secret-value',
                                             'auth_uri':pub.AUTH_URI,'token_uri':pub.TOKEN_URI}})
                url=pub.start_auth();query=parse_qs(urlsplit(url).query)
                self.assertEqual(query['access_type'],['offline'])
                self.assertIn('youtube.upload',query['scope'][0])
                self.assertEqual(query['code_challenge_method'],['S256'])
                self.assertEqual((root/'client.json').stat().st_mode & 0o777,0o600)
                pending=pub.read_json(root/'pending.json')
                self.assertEqual(query['state'][0],pending['state'])
                self.assertNotIn(pending['verifier'],url)

    def test_resumable_upload_sends_ranges_and_reports_completion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/'clip.mp4';file.write_bytes(b'v'*(9*1024*1024))
            requests=[]
            def fake_response(request):
                requests.append(request)
                if request.get_method()=='POST':return FakeResponse(200,headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test'})
                if request.headers.get('Content-range','').startswith('bytes */'):return FakeResponse(308)
                if request.headers.get('Content-range','').startswith('bytes 0-'):return FakeResponse(308,headers={'Range':f'bytes=0-{8*1024*1024-1}'})
                return FakeResponse(201,json.dumps({'id':'abcdefghijk'}).encode())
            progress=[]
            metadata=pub.validate_metadata({'title':'Clip','description':'','tags':[],'privacy':'private','madeForKids':False})
            with patch.object(pub,'UPLOADS',root/'jobs'),patch.object(pub,'access_token',return_value='fake-token'),patch.object(pub,'_response',side_effect=fake_response):
                video_id=pub.upload_video(1,file,metadata,lambda *args:progress.append(args))
                self.assertEqual(video_id,'abcdefghijk')
                self.assertEqual(len(requests),4)
                self.assertEqual(requests[-1].headers['Content-range'],f'bytes {8*1024*1024}-{9*1024*1024-1}/{9*1024*1024}')
                self.assertEqual(progress[-1][0],1)
                self.assertEqual(pub.read_json(root/'jobs'/'1.json')['video_id'],video_id)
                pub.finish_job(1)
                self.assertFalse((root/'jobs'/'1.json').exists())
