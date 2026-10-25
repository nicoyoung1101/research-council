import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from bridge import Council,CouncilError
from image_store import ImageStore,request_refs,claude_content
from native_cli import claude,codex
import test_native

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN2kAAAAASUVORK5CYII=')

class ImageTests(unittest.TestCase):
    def test_store_deduplicates_and_never_uses_supplied_paths(self):
        with tempfile.TemporaryDirectory() as d:
            store=ImageStore(d);body={'name':'../../private','mime':'image/png','data':base64.b64encode(PNG).decode()}
            a=store.put(body);b=store.put(body);self.assertEqual(a['id'],b['id']);self.assertEqual(len(list(Path(d).iterdir())),1)
            self.assertEqual(base64.b64decode(store.get(a['id'])['data']),PNG)
            for ident in ('../../state.json','image.png','0'*64+'.svg'):
                with self.assertRaises(ValueError):store.get(ident)
    def test_invalid_and_mismatched_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store=ImageStore(d)
            for mime,data in [('image/png','@@'),('image/svg+xml',base64.b64encode(b'<svg/>').decode()),('image/jpeg',base64.b64encode(PNG).decode())]:
                with self.assertRaises(ValueError):store.put({'mime':mime,'data':data})
            with self.assertRaises(ValueError):store.put({'mime':'image/png','data':'A'*7000000})
    def refs(self,n):return [{'id':str(i)*64+'.png','mime':'image/png'} for i in range(1,n+1)]
    def test_targeted_images_are_not_leaked_and_independent_answers_stay_independent(self):
        a,b,c=self.refs(3);request={'kind':'debate','initialInstructions':[{'images':[a]}],
            'moderator':[{'to':'claude','images':[b]},{'to':'codex','images':[c]}]}
        self.assertEqual(request_refs(request,{'id':'claude'}),[a,b]);self.assertEqual(request_refs(request,{'id':'codex'}),[a,c])
        request['kind']='independent';self.assertEqual(request_refs(request,{'id':'claude'}),[a])
        request['kind']='scribe';self.assertEqual(request_refs(request,{'id':'claude'}),[])
    def test_last_four_visible_images_are_selected_without_text_or_private_peer_images(self):
        refs=self.refs(6);r=request_refs({'kind':'sidechat','transcript':[{'type':'user','images':refs[:3]}],'images':refs[3:]},{'id':'a'})
        # Current attachments must follow history, so they are the newest inputs.
        self.assertEqual(r,refs[2:])
        self.assertNotIn('data',r[0])
    def test_gemini_image_rejection_happens_without_starting_a_model(self):
        with tempfile.TemporaryDirectory() as d:
            c=Council(d,runner=lambda *a:self.fail('must not run a model'),usage_reader=lambda:[])
            try:
                im=c.images.put({'mime':'image/png','data':base64.b64encode(PNG).decode()})
                with self.assertRaises(CouncilError) as exc:c.image_inputs({'id':'a','provider':'gemini'},{'kind':'sidechat','images':[im]})
                self.assertEqual(exc.exception.code,'images_unsupported')
            finally:c.close()
    def test_native_vision_protocols_send_actual_images(self):
        factory=test_native.NativeProtocolTests();im={'mime':'image/png','data':base64.b64encode(PNG).decode(),'path':'/private/user-selected.png'}
        w=factory.claude_wire([]);claude(w,'P',{},lambda _:None,[im]);m=next(m for m in w.sent if m.get('type')=='user')
        self.assertEqual(m['message']['content'][1]['source']['data'],im['data'])
        w=factory.codex_wire([]);codex(w,'P',{},lambda _:None,{},'/tmp',[im]);m=next(m for m in w.sent if m.get('method')=='turn/start')
        self.assertEqual(m['params']['input'][1],{'type':'localImage','path':im['path']})
    def test_persistence_and_tampering_detection(self):
        with tempfile.TemporaryDirectory() as d:
            im=ImageStore(d).put({'mime':'image/png','data':base64.b64encode(PNG).decode()});store=ImageStore(d)
            Path(store.get(im['id'])['path']).write_bytes(PNG+b'changed')
            with self.assertRaises(ValueError):store.get(im['id'])
