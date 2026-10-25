import io
import json
import queue
import tempfile
import unittest
from unittest.mock import patch
import bridge
import model_catalog as models
import test_native


class CapturedInput(io.StringIO):
    def close(self):
        self.saved = self.getvalue()
        super().close()


class Process:
    pid = 7890123
    def __init__(self, messages):
        self.stdin = CapturedInput()
        self.stdout = io.StringIO(''.join(json.dumps(m)+'\n' for m in messages))
    def wait(self, timeout=None): return 0
    def poll(self): return 0


class ModelCatalogTests(unittest.TestCase):
    def test_codex_metadata_preserves_ultra_and_model_specific_levels(self):
        data = models.normalize('codex', [
            {'model':'sol','displayName':'Sol','supportedReasoningEfforts':[{'reasoningEffort':e} for e in ['low','max','ultra']], 'defaultReasoningEffort':'low','isDefault':True},
            {'model':'luna','supportedReasoningEfforts':[{'reasoningEffort':'max'}]}])
        self.assertEqual(data[0]['efforts'], ['low','max','ultra'])
        self.assertEqual(data[0]['defaultEffort'], 'low')
        self.assertEqual(data[1]['efforts'], ['max'])
        with self.assertRaises(ValueError): models.validate(data,'luna','ultra')
        models.validate(data,'sol','ultra')
        models.validate(data,'sol','default')
        models.validate(data,'custom','xhigh')  # No guessed restrictions for unknown models.

    def test_claude_exact_ids_aliases_and_no_effort_models(self):
        data = models.normalize('claude',[
            {'value':'sonnet','resolvedModel':'claude-sonnet-5','supportsEffort':True,'supportedEffortLevels':['low','medium','high','xhigh','max']},
            {'value':'haiku','resolvedModel':'claude-haiku-4-5-20251001'}])
        models.validate(data,'sonnet','max')
        models.validate(data,'claude-sonnet-5','xhigh')
        with self.assertRaises(ValueError): models.validate(data,'haiku','high')
        self.assertEqual(data[1]['efforts'],[])

    def test_codex_probe_only_initializes_and_lists_paginated_models(self):
        proc = Process([{'id':1,'result':{}},{'id':2,'result':{'data':[{'model':'first'}],'nextCursor':'page2'}},
                        {'id':3,'result':{'data':[{'model':'second'}]}}])
        with patch('model_catalog.subprocess.Popen', return_value=proc) as launch, patch('model_catalog.os.killpg'):
            data = models._probe('codex','codex',{},2)
        requests = [json.loads(x) for x in proc.stdin.saved.splitlines()]
        self.assertEqual([x['method'] for x in requests],['initialize','initialized','model/list','model/list'])
        self.assertEqual(requests[-1]['params']['cursor'],'page2')
        self.assertEqual([m['id'] for m in data],['first','second'])
        self.assertEqual(launch.call_args.args[0],['codex','app-server','--listen','stdio://'])

    def test_claude_probe_discards_account_fields_and_never_sends_user_message(self):
        proc = Process([{'type':'control_response','response':{'request_id':'models','subtype':'success','response':{
            'account':{'secret':'do not expose'},'models':[{'value':'opus','name':'Opus','accessToken':'do not expose','supportsEffort':True,'supportedEffortLevels':['max']}]}}}])
        with patch('model_catalog.subprocess.Popen',return_value=proc), patch('model_catalog.os.killpg'):
            data = models._probe('claude','claude',{},2)
        self.assertNotIn('do not expose',json.dumps(data))
        self.assertEqual(json.loads(proc.stdin.saved),{'type':'control_request','request_id':'models','request':{'subtype':'initialize'}})

    def test_catalog_failure_is_explicit_and_cached_without_inventing_levels(self):
        with patch('model_catalog._probe',side_effect=TimeoutError), patch.dict(models._CACHE,{},clear=True):
            data = models.catalog('codex','/missing-cli',{})
            self.assertEqual(data['models'],[])
            self.assertEqual(data['modelCatalogSource'],'unavailable')
            self.assertEqual(data['modelCatalogError'],'TimeoutError')
            self.assertEqual(models.catalog('codex','/missing-cli',{}),data)

    def test_probe_timeout_cleans_up(self):
        proc=Process([])
        with patch('model_catalog.subprocess.Popen',return_value=proc), patch('model_catalog.os.killpg') as stop, patch('model_catalog.queue.Queue') as inbox:
            inbox.return_value.get.side_effect=queue.Empty
            with self.assertRaises(TimeoutError):models._probe('codex','codex',{},.01)
            stop.assert_called_once()

    def test_restricted_launch_rejects_unsupported_and_preserves_valid_effort(self):
        data={'models':[{'id':'sol','efforts':['ultra']},{'id':'luna','efforts':['max']}]}
        with patch('bridge.locate',return_value='codex'),patch('bridge.model_catalog.catalog',return_value=data):
            with self.assertRaises(bridge.CouncilError):bridge.command({'provider':'codex','model':'luna','effort':'ultra'},'/tmp')
            args=bridge.command({'provider':'codex','model':'sol','effort':'ultra'},'/tmp')
            self.assertIn('model_reasoning_effort="ultra"',args)
        with patch('bridge.locate',return_value='claude'),patch('bridge.model_catalog.catalog') as read:
            args=bridge.command({'provider':'claude','model':'default','effort':'default'},'/tmp')
            read.assert_not_called()
            self.assertNotIn('--effort',args)

    def test_native_codex_sends_exact_ultra_without_remapping(self):
        wire=test_native.NativeProtocolTests().codex_wire([])
        test_native.codex(wire,'Prompt',{},lambda _:None,{'model':'gpt-6.1-sol','effort':'ultra'},'/tmp')
        turn=next(m for m in wire.sent if m.get('method')=='turn/start')
        self.assertEqual(turn['params']['effort'],'ultra')

    def test_native_claude_passes_max_exactly_and_default_omits_flag(self):
        for effort in ('max','default'):
            with patch('native_cli.Wire') as wire,patch('native_cli.claude',return_value={}):
                test_native.run(None,{'provider':'claude','model':'sonnet','effort':effort},'P',{},'claude',{},'/tmp',{'id':'own'},lambda _:None)
                args=wire.call_args.args[3]
                if effort=='max':self.assertEqual(args[args.index('--effort')+1],'max')
                else:self.assertNotIn('--effort',args)

    def test_native_rejects_unsupported_before_launching_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            council=bridge.Council(directory)
            try:
                with patch('bridge.locate',return_value='codex'),patch('bridge.model_catalog.catalog',return_value={'models':[{'id':'luna','efforts':['max']}]}),patch('bridge.native_cli.run') as launch:
                    with self.assertRaises(bridge.CouncilError):
                        council.native({'id':'codex','provider':'codex','model':'luna','effort':'ultra'},'P',{'id':'own','request':{}})
                    launch.assert_not_called()
            finally:council.close()

    def test_auth_fixture_without_binary_never_probes_real_cli(self):
        with patch('bridge.model_catalog.catalog') as read:
            info=bridge.capability_models({'provider':'codex','installed':True,'loggedIn':True})
            read.assert_not_called()
            self.assertNotIn('models',info)

if __name__=='__main__':unittest.main()
