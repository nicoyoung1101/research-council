import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import patch
from feedback import FeedbackStore, validate_config, deliver
from bridge import make_server
from test_images import PNG


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=self.root/'bundle.json';self.config.write_text('{}')
        self.calls=[]
        self.store=FeedbackStore(self.root/'data',sender=lambda endpoint,body:self.calls.append((endpoint,body)),bundled_config=self.config)
    def tearDown(self):self.tmp.cleanup()
    def body(self,**changes):return dict(id=str(uuid.uuid4()),message='反馈中的原始内容',category='idea',contact='',language='zh',images=[],**changes)
    def endpoint(self):self.config.write_text(json.dumps({'endpoint':'https://feedback.example/submit','email':'feedback@example.org'}))
    def test_local_save_is_honestly_unsent_and_survives_restart(self):
        result=self.store.submit(self.body());self.assertEqual(result['status'],'saved');self.assertEqual(self.calls,[])
        restored=FeedbackStore(self.store.data_dir,bundled_config=self.config)
        self.assertEqual(restored.list()[0]['message'],'反馈中的原始内容');self.assertEqual(restored.public_config()['method'],'local')
    def test_direct_delivery_is_explicit_and_idempotent(self):
        self.endpoint();body=self.body();result=self.store.submit(body)
        self.assertEqual(result['status'],'submitted');self.assertEqual(len(self.calls),1)
        self.assertEqual(self.store.submit(body)['status'],'submitted');self.store.send(body['id']);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0],'https://feedback.example/submit')
    def test_failure_retains_report_for_an_explicit_retry(self):
        self.endpoint()
        def broken(*args):raise TimeoutError('SECRET upstream detail')
        self.store.sender=broken;result=self.store.submit(self.body())
        self.assertEqual(result['status'],'saved');self.assertEqual(result['deliveryError'],'delivery_unconfirmed');self.assertNotIn('SECRET',json.dumps(result))
        self.store.sender=lambda *args:self.calls.append(args)
        self.assertEqual(self.store.send(result['id'])['status'],'submitted');self.assertEqual(len(self.calls),1)
    def test_local_report_can_be_delivered_after_release_configuration(self):
        result=self.store.submit(self.body());self.endpoint();self.assertEqual(self.store.send(result['id'])['status'],'submitted')
    def test_email_does_not_claim_to_have_sent(self):
        self.config.write_text(json.dumps({'email':'feedback@example.org'}))
        self.assertEqual(self.store.public_config()['method'],'email');self.assertEqual(self.store.submit(self.body())['status'],'saved');self.assertEqual(self.calls,[])
    def test_only_explicit_feedback_and_minimal_app_metadata_leave(self):
        self.endpoint();body=self.body();body.update(transcript='PRIVATE RESEARCH',token='PRIVATE TOKEN',workspace='/private/path',endpoint='https://attacker.example')
        self.store.submit(body);sent=self.calls[0][1];encoded=json.dumps(sent)
        self.assertNotIn('PRIVATE',encoded);self.assertNotIn('/private',encoded);self.assertNotIn('attacker',encoded)
        self.assertEqual(set(sent['environment']),{'appVersion','build','platform'})
    def test_export_contains_only_feedback_and_chosen_images(self):
        body=self.body();body['images']=[{'name':'/private/secret-name.png','mime':'image/png','data':base64.b64encode(PNG).decode()}]
        result=self.store.submit(body)
        with zipfile.ZipFile(io.BytesIO(self.store.export(result['id']))) as archive:
            self.assertEqual(set(archive.namelist()),{'feedback.json','feedback.txt','screenshot-1.png'})
            self.assertEqual(archive.read('screenshot-1.png'),PNG)
            self.assertNotIn('/private',archive.read('feedback.json').decode())
        self.assertNotIn('images',result);self.assertEqual(result['imageCount'],1)
    def test_invalid_input_cannot_read_paths_or_override_destination(self):
        for change in [{'id':'../state'},{'message':''},{'message':'x'*5001},{'contact':'bad\r\nBcc:other@example.org'},{'category':'untrusted'},{'language':'invalid'},{'images':[{'mime':'image/svg+xml','data':base64.b64encode(b'<svg/>').decode()}]}]:
            body=self.body();body.update(change)
            with self.assertRaises(ValueError):self.store.submit(body)
        self.assertEqual(self.calls,[])
    def test_request_id_cannot_be_reused_for_different_content(self):
        body=self.body();self.store.submit(body)
        with self.assertRaises(ValueError):self.store.submit({**body,'message':'different content'})
    def test_release_configuration_is_validated_and_not_publicly_exposed(self):
        for invalid in [{'email':'one@example.org,two@example.org'},{'endpoint':'http://localhost:1234/private'},{'endpoint':'https://user:secret@example.org'},{'endpoint':'https://example.org/#fragment'}]:
            with self.assertRaises(ValueError):validate_config(invalid)
        self.endpoint();public=self.store.public_config();self.assertEqual(public['destination'],'feedback.example');self.assertNotIn('endpoint',public)
    def test_invalid_config_does_not_lose_the_report(self):
        self.config.write_text('not JSON');result=self.store.submit(self.body());self.assertEqual(result['status'],'saved');self.assertEqual(result['deliveryError'],'configuration_error')
    def test_http_delivery_rejects_explicit_failure_ack(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"success": false}'
        with patch('feedback.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=Response()
            with self.assertRaises(ValueError):deliver('https://feedback.example',{'id':'request'})
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Idempotency-key'),'request')


class FeedbackHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.server=make_server(0,self.tmp.name)
        config=Path(self.tmp.name)/'feedback-test-bundle.json';config.write_text('{}')
        self.server.council.feedback.bundled_config=config
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.council.close();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def fetch(self,path,body=None,auth=True,**headers):
        if auth:headers['X-Council-Token']=self.server.council.token
        if body is not None:headers['Content-Type']='application/json'
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    def test_feedback_endpoints_require_same_origin_and_token(self):
        body=dict(id=str(uuid.uuid4()),message='A useful suggestion')
        self.assertEqual(self.fetch('/api/feedback',body,auth=False)[0],403)
        self.assertEqual(self.fetch('/api/feedback/config',auth=False)[0],403)
        self.assertEqual(self.fetch('/api/feedback',body,Origin='https://attacker.example')[0],403)
        code,raw=self.fetch('/api/feedback',body);self.assertEqual(code,201);report=json.loads(raw)
        self.assertEqual(report['status'],'saved')
        self.assertEqual(self.fetch('/api/feedback/'+report['id']+'/export',auth=False)[0],403)
        code,raw=self.fetch('/api/feedback/'+report['id']+'/export');self.assertEqual(code,200);self.assertTrue(zipfile.is_zipfile(io.BytesIO(raw)))
        self.assertEqual(self.fetch('/feedback-config.json')[0],404)
        self.assertEqual(self.fetch('/feedback/'+report['id']+'.json')[0],404)
        self.assertEqual(self.fetch('/api/feedback',{'id':'../state','message':'unsafe'})[0],400)
        self.assertEqual(len(json.loads(self.fetch('/api/feedback')[1])['reports']),1)
    def test_feedback_ui_is_bundled_without_external_scripts(self):
        _,raw=self.fetch('/index.html');self.assertIn(b'<script data-source="feedback-client.js">',raw);self.assertNotIn(b'<script src=',raw)
