import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from bridge import Council
from native_cli import Wire, NativeError, run
from usage_accounting import Meter, audit, quota_changes


def claude_event(mid='m', output=8):
    return dict(type='assistant', message=dict(id=mid, usage=dict(input_tokens=10,
        cache_creation_input_tokens=20, cache_read_input_tokens=30, output_tokens=output,
        output_tokens_details=dict(thinking_tokens=3)), content=[dict(type='tool_use',id='tool',name='Bash')]))


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Council(self.tmp.name,runner=lambda *a:{})
        self.job=dict(id='job',status='running',request=dict(kind='debate',runId='run',question='Q'),created=time.time(),events=[],results=[],cancel=threading.Event())
        self.agent=dict(id='a',provider='claude',model='chosen',effort='high')
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def meter(self, provider='claude', session=None):
        return Meter(self.c,dict(self.agent,provider=provider),self.job,session)
    def test_claude_duplicate_partial_and_final_usage_not_added_twice(self):
        m=self.meter();m.observe(claude_event());m.observe(claude_event());m.observe(claude_event(output=11));m.observe(claude_event('m2',5))
        self.assertEqual(m.data['tokens']['outputTokens'],16);self.assertEqual(m.data['toolCalls'],1)
        self.assertEqual(m.data['tokens']['inputTokens'],120)
        m.observe(dict(type='result',usage=dict(input_tokens=20,cache_creation_input_tokens=40,cache_read_input_tokens=60,output_tokens=16)))
        self.assertEqual(m.finish('complete')['tokens']['outputTokens'],16)
        self.assertEqual(m.data['tokens']['reasoningOutputTokens'],6)
        self.assertFalse(m.data['partial']);self.assertEqual(m.data['purpose'],'review')
    def test_stream_usage_and_tools_merge_by_message_and_tool_ids(self):
        m=self.meter();m.observe(dict(type='stream_event',event=dict(type='message_start',message=claude_event()['message'])))
        m.observe(dict(type='stream_event',event=dict(type='message_delta',usage=dict(output_tokens=11))))
        m.observe(claude_event(output=11));self.assertEqual(m.data['tokens']['outputTokens'],11)
        self.assertEqual(m.data['toolCalls'],1)
    def test_codex_uses_invocation_delta_of_cumulative_totals(self):
        m=self.meter('codex',dict(id='thread',usageTotal=dict(inputTokens=100,cachedInputTokens=80,outputTokens=10)))
        event=dict(method='thread/tokenUsage/updated',params=dict(tokenUsage=dict(total=dict(inputTokens=150,cachedInputTokens=110,outputTokens=16,reasoningOutputTokens=2),last=dict(totalTokens=99))))
        m.observe(event);m.observe(event)
        self.assertEqual(m.data['tokens']['inputTokens'],50);self.assertEqual(m.data['tokens']['cachedInputTokens'],30)
        self.assertEqual(m.data['tokens']['outputTokens'],6);self.assertEqual(m.data['contextEndTokens'],99)
    def test_quota_samples_missing_reset_and_shared_account_are_not_guessed(self):
        m=self.meter();self.assertIsNone(quota_changes(m.data)[0]['utilizationChange'])
        for value in (.91,.94):m.observe(dict(type='rate_limit_event',rate_limit_info=dict(rateLimitType='five_hour',utilization=value,resetsAt=100)))
        self.assertAlmostEqual(quota_changes(m.data)[0]['utilizationChange'],.03)
        m.observe(dict(type='rate_limit_event',rate_limit_info=dict(rateLimitType='five_hour',utilization=.01,resetsAt=200)))
        self.assertIsNone(quota_changes(m.data)[0]['utilizationChange'])
    def test_usage_persists_beyond_event_ring_and_service_restart(self):
        self.c.jobs['job']=self.job;m=self.meter();m.observe(claude_event())
        self.job['events']=[dict(type='other')]*250;self.c.persist(self.job)
        self.c.close();self.c=Council(self.tmp.name,runner=lambda *a:{})
        call=self.c.jobs['job']['usageCalls'][0]
        self.assertEqual(call['tokens']['outputTokens'],8);self.assertEqual(call['status'],'interrupted');self.assertTrue(call['partial'])
    def test_real_reader_saves_queued_usage_on_cancel_timeout_and_closed_stream(self):
        for provider in ('claude','codex'):
            for reason in ('cancelled','timeout','cli_failed'):
                with self.subTest(provider=provider,reason=reason):
                    job=copy.copy(self.job);job.update(id=provider+reason,events=[],usageCalls=[],cancel=threading.Event())
                    event=claude_event() if provider=='claude' else dict(method='thread/tokenUsage/updated',params=dict(tokenUsage=dict(total=dict(inputTokens=10,cachedInputTokens=3,outputTokens=5),last=dict(totalTokens=15))))
                    script='import time;print('+repr(json.dumps(event))+',flush=True);'+('time.sleep(10)' if reason!='cli_failed' else '')
                    w=Wire(self.c,dict(self.agent,provider=provider),job,[sys.executable,'-u','-c',script],self.tmp.name,os.environ.copy())
                    try:
                        deadline=time.monotonic()+3
                        while w.meter.data['tokens']['outputTokens'] is None and time.monotonic()<deadline:time.sleep(.005)
                        self.assertIsNotNone(w.meter.data['tokens']['outputTokens'])
                        if reason=='cancelled':job['cancel'].set()
                        if reason=='timeout':w.deadline=0
                        with self.assertRaises(NativeError) as caught:
                            while True:w.receive()
                        self.assertEqual(caught.exception.code,reason)
                    finally:w.close();w.meter.finish(reason)
                    saved=json.loads((Path(self.tmp.name)/'jobs'/f"{job['id']}.json").read_text())['usageCalls'][0]
                    self.assertTrue(saved['partial']);self.assertGreater(saved['tokens']['outputTokens'],0);self.assertIsNotNone(saved['endedAt'])
    def test_run_finally_records_transport_error(self):
        original=Wire
        def wire(*args,**kw):
            args=list(args);args[3]=[sys.executable,'-u','-c','import time;print('+repr(json.dumps(claude_event()))+',flush=True);time.sleep(10)']
            return original(*args,**kw)
        def protocol(w,*args):
            w.receive();raise NativeError('timeout')
        with patch('native_cli.Wire',side_effect=wire),patch('native_cli.claude',side_effect=protocol):
            with self.assertRaises(NativeError):run(self.c,self.agent,'P',self.job,'ignored',os.environ.copy(),self.tmp.name,{},lambda sid:None)
        self.assertEqual(self.job['usageCalls'][0]['status'],'timeout');self.assertTrue(self.job['usageCalls'][0]['partial'])
    def test_audit_includes_failed_usage_and_preserves_unknown(self):
        m=self.meter();m.observe(claude_event());m.finish('cancelled')
        report=audit([self.job,dict(id='old',status='failed',results=[])])
        self.assertEqual(report['cancelledOrFailed']['tokens']['outputTokens']['reported'],8)
        self.assertEqual(report['legacyUnknown'][0]['jobId'],'old')
        self.assertIsNone(report['calls'][0]['quotaChanges'][0]['utilizationChange'])
    def test_retry_metadata_does_not_change_request_idempotency(self):
        self.c.jobs['old']=dict(id='old',status='cancelled',request=self.job['request'],created=1)
        m=self.meter();self.assertEqual(m.data['purpose'],'retry');self.assertEqual(m.data['originalPurpose'],'debate')
        self.assertNotIn('retryOf',self.job['request'])

    def test_unknown_resumed_baseline_never_charges_prior_thread_usage_to_current_call(self):
        m=self.meter('codex',dict(id='old-thread'))
        m.observe(dict(method='thread/tokenUsage/updated',params=dict(tokenUsage=dict(total=dict(inputTokens=9000,outputTokens=1000),last=dict(inputTokens=800,outputTokens=80)))))
        self.assertIsNone(m.data['tokens']['inputTokens'])
        self.assertEqual(m.data['threadTotal']['inputTokens'],9000)
        self.assertEqual(m.data['baselineSource'],'unknown')
    def test_existing_saved_result_supplies_legacy_thread_baseline(self):
        self.c.jobs['prior']=dict(id='prior',status='complete',created=1,results=[dict(nativeSessionId='old-thread',usage=dict(total=dict(inputTokens=900,outputTokens=100)))])
        m=self.meter('codex',dict(id='old-thread'))
        m.observe(dict(method='thread/tokenUsage/updated',params=dict(tokenUsage=dict(total=dict(inputTokens=1000,outputTokens=120)))))
        self.assertEqual(m.data['tokens']['inputTokens'],100);self.assertEqual(m.data['tokens']['outputTokens'],20)
    def test_all_error_codes_are_in_failed_subtotal_and_context_start_is_refined(self):
        m=self.meter();m.observe(dict(type='assistant',message=dict(id='m',usage=dict(input_tokens=0,cache_creation_input_tokens=0,cache_read_input_tokens=0))))
        m.observe(claude_event());m.finish('empty_output')
        self.assertEqual(m.data['contextStartTokens'],60)
        self.assertEqual(audit([self.job])['cancelledOrFailed']['tokens']['outputTokens']['reported'],8)
