import copy
import io
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from bridge import Council
from usage_status import codex_windows,claude_windows,gemini_windows,context_sample,read_codex,read_claude,read_gemini,read_all,snapshot
import test_native
from native_cli import claude,codex

class UsageTests(unittest.TestCase):
    def test_claude_windows_preserve_shared_and_model_scope_and_unknown(self):
        r=claude_windows({'rate_limits_available':True,'rate_limits':{
            'five_hour':{'utilization':0,'resets_at':None},'seven_day':{'utilization':8,'resets_at':'2026-10-22T00:00:00Z'},
            'seven_day_opus':None,'seven_day_sonnet':{'utilization':None},
            'model_scoped':[{'display_name':'Model bucket','utilization':100}],
            'extra_usage':{'utilization':42,'identity':'PRIVATE'}}})
        self.assertEqual([w['remainingPercent'] for w in r],[100,92,None,0])
        self.assertEqual([w['bucket'] for w in r],['Claude','Claude','Sonnet','Model bucket'])
        self.assertEqual(r[0]['durationMinutes'],300);self.assertIsNone(r[0]['resetsAt'])
        self.assertIsInstance(r[1]['resetsAt'],float);self.assertNotIn('PRIVATE',json.dumps(r))
        self.assertEqual(claude_windows({'rate_limits_available':False,'rate_limits':{'five_hour':{'utilization':0}}}),[])
    def gemini_response(self):
        return {'status':'SUCCESS','num_turns':0,'email':'PRIVATE','command':{'name':'usage','data':{'groups':[
            {'name':'Gemini Models','buckets':[{'id':'gemini-weekly','window':'weekly','remaining_fraction':.25,'reset_time':'2026-10-26T00:00:00Z'}]},
            {'name':'Claude and GPT models','buckets':[{'id':'3p-5h','window':'5h','remaining_fraction':0,'reset_time':'bad'},
                                                      {'id':'unknown','remaining_fraction':None},{'id':'invalid','remaining_fraction':2}]}]}}}
    def test_gemini_windows_require_command_reply_and_keep_buckets_distinct(self):
        u=self.gemini_response();r=gemini_windows(u)
        self.assertEqual([w['remainingPercent'] for w in r],[25,0,None,None])
        self.assertEqual(r[0]['durationMinutes'],10080);self.assertEqual(r[1]['durationMinutes'],300)
        self.assertIsNone(r[1]['resetsAt']);self.assertNotIn('PRIVATE',json.dumps(r))
        u['num_turns']=1;self.assertEqual(gemini_windows(u),[])
        self.assertEqual(gemini_windows({'status':'SUCCESS','response':'You have 100% left'}),[])
    def test_claude_reader_sends_only_metadata_and_skips_transcript_scan(self):
        sent=[]
        class Input:
            def write(self,s):sent.append(json.loads(s))
            def flush(self):pass
            def close(self):pass
        class Proc:
            stdin=Input();stdout=io.StringIO('\n'.join(json.dumps(m) for m in [
                {'type':'control_response','response':{'subtype':'success','request_id':'init','response':{'identity':'PRIVATE'}}},
                {'type':'control_response','response':{'subtype':'success','request_id':'quota','response':{
                    'session':{'secret':'PRIVATE'},'rate_limits_available':True,'rate_limits':{'seven_day':{'utilization':8}}}}}])+'\n')
            def poll(self):return 0
        with patch('usage_status.subprocess.Popen',return_value=Proc()) as spawn:r=read_claude('claude',{})
        self.assertEqual([m['request'] for m in sent],[{'subtype':'initialize'},{'subtype':'get_usage','skip_behaviors':True}])
        self.assertTrue(all(m['type']=='control_request' for m in sent));self.assertNotIn('PRIVATE',json.dumps(r))
        self.assertTrue(r['available']);self.assertIn('--no-session-persistence',spawn.call_args.args[0]);self.assertIn('--safe-mode',spawn.call_args.args[0])
    def test_gemini_reader_only_uses_supported_builtin_command(self):
        raw=self.gemini_response()
        class Proc:
            stdin=None;stdout=io.StringIO();returncode=0
            def communicate(self,timeout):return json.dumps(raw),None
            def poll(self):return 0
        with patch('usage_status.subprocess.run',return_value=subprocess.CompletedProcess([],0,'1.4.3\n')),patch('usage_status.subprocess.Popen',return_value=Proc()) as spawn:
            r=read_gemini('agy',{})
        self.assertEqual(spawn.call_args.args[0],['agy','-p','/usage','--output-format','json'])
        self.assertTrue(r['available']);self.assertNotIn('PRIVATE',json.dumps(r))
    def test_old_gemini_cli_is_never_sent_a_slash_prompt(self):
        for version in ('1.1.10\n','unknown'):
            with patch('usage_status.subprocess.run',return_value=subprocess.CompletedProcess([],0,version)),patch('usage_status.subprocess.Popen') as spawn:
                self.assertEqual(read_gemini('agy',{})['reason'],'unsupported_version');spawn.assert_not_called()
    def test_reader_errors_are_isolated_without_fabricated_percentages(self):
        with patch('usage_status.read_claude',side_effect=ValueError()),patch('usage_status.read_codex',return_value={'provider':'codex','available':True}),patch('usage_status.read_gemini',return_value={'provider':'gemini','available':True}):
            r=read_all(lambda p:p,lambda p:{})
        self.assertEqual([p['available'] for p in r],[False,True,True]);self.assertEqual(r[0]['windows'],[])
    def test_zero_unknown_and_multi_bucket_are_distinct(self):
        rows=codex_windows({'rateLimitsByLimitId':{'a':{'primary':{'usedPercent':0}},'b':{'primary':{'usedPercent':100},'secondary':{}}}})
        self.assertEqual([r['remainingPercent'] for r in rows],[100,0,None])
        self.assertIsNone(rows[0]['durationMinutes'])
        self.assertEqual(codex_windows({'rateLimits':None}),[])
    def test_context_uses_last_snapshot_not_total(self):
        c=context_sample('codex',{'last':{'totalTokens':1000},'total':{'totalTokens':99999},'modelContextWindow':10000})
        self.assertEqual(c['usedPercent'],10)
        self.assertIsNone(context_sample('codex',{'input_tokens':123})['usedTokens'])
    def test_claude_context_includes_cache_and_excludes_aggregate(self):
        c=context_sample('claude',{'input_tokens':999999},{'input_tokens':100,'cache_creation_input_tokens':200,'cache_read_input_tokens':700,'output_tokens':1000},{'m':{'contextWindow':10000}},'m')
        self.assertEqual(c['usedTokens'],1000);self.assertEqual(c['usedPercent'],10)
        self.assertIsNone(context_sample('claude',{'input_tokens':999999})['usedTokens'])
        self.assertIsNone(context_sample('gemini',{'total_tokens':999})['usedPercent'])
    def test_metadata_reader_never_starts_inference_or_returns_identity(self):
        sent=[]
        class Input:
            def write(self,s):sent.append(json.loads(s))
            def flush(self):pass
            def close(self):pass
        class Proc:
            stdin=Input();stdout=io.StringIO(json.dumps({'id':1,'result':{}})+'\n'+json.dumps({'id':2,'result':{'accountId':'PRIVATE','rateLimits':{'primary':{'usedPercent':21}}}})+'\n')
            def poll(self):return 0
        with patch('usage_status.subprocess.Popen',return_value=Proc()):r=read_codex('codex',{})
        self.assertEqual([m['method'] for m in sent],['initialize','initialized','account/rateLimits/read'])
        self.assertNotIn('PRIVATE',json.dumps(r));self.assertEqual(r['windows'][0]['remainingPercent'],79)
    def test_snapshot_is_run_scoped_and_caches_only_account_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            reads=[]
            c=Council(directory,runner=lambda *a:None,usage_reader=lambda:reads.append(1) or [])
            try:
                a={'id':'a','provider':'codex','name':'A','role':'debater','model':'m'}
                for rid in ('old','current'):
                    c.jobs[rid]=dict(id=rid,request=dict(sessionId='s',runId=rid,agents=[a]),created=1,updated=2,status='complete',results=[dict(agentId='a',usage={'last':{'totalTokens':100},'modelContextWindow':1000})],events=[])
                r=snapshot(c,'s','current');self.assertEqual(r['agents'][0]['jobId'],'current')
                self.assertEqual(r['agents'][0]['context']['usedPercent'],10)
                self.assertEqual(snapshot(c,'different')['agents'],[]);self.assertEqual(len(reads),1)
            finally:c.close()
    def test_native_protocols_preserve_context_metadata(self):
        factory=test_native.NativeProtocolTests();u={'last':{'totalTokens':42},'modelContextWindow':100}
        w=factory.codex_wire([{'method':'thread/tokenUsage/updated','params':{'tokenUsage':u}}]);r=codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertEqual(r['context']['usedPercent'],42);self.assertTrue(any(e.get('type')=='context_usage' for e in w.record))
        w=factory.claude_wire([{'type':'assistant','message':{'content':[],'usage':{'input_tokens':50}}}])
        events=list(w.events);events[-1]['usage']={'input_tokens':100000};events[-1]['modelUsage']={'claude-model':{'contextWindow':1000}};w.events=iter(events)
        self.assertEqual(claude(w,'P',{},lambda x:None)['context']['usedPercent'],5)
