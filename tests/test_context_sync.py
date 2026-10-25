import base64
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import context_sync as sync
from bridge import Council, CouncilError, prompt_for
from native_cli import NativeError


def agent(ident='claude', provider='claude'):
    return dict(id=ident, provider=provider, role='debater', model='default', effort='default')


def request(**extra):
    return dict(dict(runId='run', sessionId='s', kind='question', profile='native',
                     question='Current question', packet={}, transcript=[], moderator=[]), **extra)


def rendered(payload):
    return 'Current task rules'+sync.MARKER+json.dumps(payload, ensure_ascii=False)+'\nCONTROL_SCHEMA_NONCE_123'


class ContextDeliveryTests(unittest.TestCase):
    def test_bootstrap_excerpts_keep_complete_retrievable_record_without_nested_results(self):
        text='SOURCE_START '+('evidence '*15000)+' SOURCE_END'
        payload=dict(question='NEW', transcript=[dict(type='agent',id='codex',text=text,
            result=dict(text=text, nativeSessionId='PRIVATE_SESSION', usage=dict(output_tokens=99)))])
        prompt,state,record=sync.prepare(rendered(payload),{},agent(),'/filtered/record.json')
        self.assertLess(len(prompt),26000)
        self.assertEqual(record['transcript'][0]['text'],text)
        self.assertNotIn('PRIVATE_SESSION', json.dumps(record))
        self.assertNotIn('result',record['transcript'][0])
        self.assertIn('Excerpt',prompt)
        self.assertTrue(prompt.endswith('CONTROL_SCHEMA_NONCE_123'))
        self.assertIn('/filtered/record.json',prompt)

    def test_resume_sends_new_peer_and_user_but_never_repeats_own_published_reply(self):
        a=agent();first=dict(question='Q1',transcript=[dict(id='codex',type='agent',text='OLD_PEER')])
        _,state,_=sync.prepare(rendered(first),{},a,'/record')
        state=sync.completed(state,dict(text='MY_REPLY\n<council_control>{}</council_control>'))
        second=copy.deepcopy(first);second['question']='Q2'
        second['transcript'] += [dict(id='claude',type='agent',text='MY_REPLY'),
            dict(id='codex',type='agent',text='NEW_PEER'),dict(id='user-2',type='user',text='NEW_QUESTION')]
        prompt,state2,_=sync.prepare(rendered(second),dict(contextSync=state),a,'/record')
        self.assertNotIn('OLD_PEER',prompt);self.assertNotIn('MY_REPLY',prompt)
        self.assertIn('NEW_PEER',prompt);self.assertIn('NEW_QUESTION',prompt)
        self.assertEqual(sync.decode(prompt)[1]['contextDelivery']['mode'],'delta')
        again,_,_=sync.prepare(rendered(second),dict(contextSync=state2),a,'/record')
        self.assertNotIn('NEW_PEER',again)

    def test_exact_authority_and_current_quotes_survive_large_context(self):
        plan=dict(hash='HASH',body='AUTHORITATIVE_PLAN '*5000)
        approval=dict(instruction='HUMAN_RESOLUTION '*3000,peerUnanimous=False)
        p=dict(question='CURRENT',approvedPlan=plan,executionApproval=approval,
               quotedReferences=[dict(text='EXACT_QUOTE')],transcript=[])
        prompt,state,_=sync.prepare(rendered(p),{},agent(),'/record')
        again,_,_=sync.prepare(rendered(p),dict(contextSync=state),agent(),'/record')
        data=sync.decode(again)[1]
        self.assertEqual(data['approvedPlan'],plan);self.assertEqual(data['executionApproval'],approval)
        self.assertIn('EXACT_QUOTE',prompt)

    def test_edits_and_removed_fields_are_delivered_without_resending_unchanged_evidence(self):
        p=dict(question='Q',evidence=dict(text='SAME_SOURCE'),currentPlan='P',transcript=[dict(id='m',text='BEFORE')])
        _,state,_=sync.prepare(rendered(p),{},agent(),'/record')
        p.pop('currentPlan');p['transcript'][0]['text']='AFTER'
        prompt,_,_=sync.prepare(rendered(p),dict(contextSync=state),agent(),'/record')
        data=sync.decode(prompt)[1]
        self.assertEqual(data['currentPlan'],None);self.assertNotIn('SAME_SOURCE',prompt)
        self.assertIn('AFTER',prompt);self.assertIn('revisedOrRemovedRecords',prompt)

    def test_previous_logs_are_retrievable_not_duplicated_into_recovery_prompt(self):
        p=dict(question='Continue',resumeExperiment=dict(sourceTaskId='old',previousActivity=[
            dict(id='job',status='failed',executionProgress={'claude':{'output':'HUGE_LOG '*4000}})]))
        prompt,_,record=sync.prepare(rendered(p),{},agent(),'/record')
        self.assertNotIn('HUGE_LOG',prompt)
        self.assertIn('HUGE_LOG',json.dumps(record))
        self.assertIn('sourceTaskId',prompt)

    def test_directed_sources_never_enter_another_members_prompt_or_archive(self):
        q=request(transcript=[dict(type='user',to='codex',text='CODEX_ONLY'),
                              dict(type='user',to='all',text='PUBLIC')])
        prompt,_,record=sync.prepare(prompt_for(agent(),q),{},agent(),'/record')
        self.assertNotIn('CODEX_ONLY',prompt);self.assertNotIn('CODEX_ONLY',json.dumps(record))
        q['kind']='independent'
        prompt,_,record=sync.prepare(prompt_for(agent(),q),{},agent(),'/record')
        self.assertFalse(record['transcript']);self.assertNotIn('PUBLIC',prompt)


class PersistentDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Council(self.tmp.name,runner=lambda *a:{})
        self.seen=[];self.a=agent()
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def job(self,q):
        return dict(id='job'+str(time.time_ns()),request=q,status='running',created=time.time(),
                    events=[],results=[],cancel=threading.Event())
    def fake(self,*args,**kw):
        captured=list(args);captured[7]=copy.deepcopy(args[7]);self.seen.append((captured,kw))
        sid=args[7].get('id') or 'fresh-session'
        args[8](sid)
        return dict(text='NATIVE_REPLY',nativeSessionId=sid,context=dict(usedTokens=5000,windowTokens=200000))
    def native(self,q,runner=None):
        with patch('bridge.locate',return_value='cli'),patch('bridge.validate_effort'),patch('native_cli.run',side_effect=runner or self.fake):
            return self.c.native(self.a,prompt_for(self.a,q),self.job(q))
    def test_cursor_and_reply_survive_service_reload_and_followup_is_small(self):
        history=[dict(type='agent',id='codex',text='OLD_'+str(i)+'x'*3000) for i in range(35)]
        q=request(transcript=history);first=self.native(q)
        self.c.close();self.c=Council(self.tmp.name,runner=lambda *a:{})
        q['transcript'] += [dict(type='agent',id='claude',text='NATIVE_REPLY'),dict(type='agent',id='codex',text='NEW_PEER')]
        q['question']='FOLLOW_UP';r=self.native(q)
        prompt=self.seen[-1][0][2]
        self.assertIn('NEW_PEER',prompt);self.assertNotIn('OLD_',prompt);self.assertNotIn('NATIVE_REPLY',prompt)
        self.assertEqual(self.seen[-1][0][7]['id'],'fresh-session')
        self.assertLess(r['contextDelivery']['inputCharacters'],r['contextDelivery']['fullPromptCharacters']*.15)
        self.assertEqual(r['contextDelivery']['mode'],'delta')

    def test_unconfirmed_cancel_rotates_session_instead_of_repeating_bootstrap(self):
        q=request(transcript=[dict(type='agent',id='codex',text='MUST_DELIVER')])
        def fail(*args,**kw):
            args[8]('interrupted-session');raise NativeError('cancelled')
        with self.assertRaises(CouncilError):self.native(q,fail)
        self.assertNotIn('contextSync',next(iter(self.c.native_sessions.values())))
        self.native(q)
        self.assertNotIn('id',self.seen[-1][0][7])
        self.assertEqual(next(iter(self.c.native_sessions.values()))['previousSessions'][-1]['reason'],'unconfirmed_delivery')
        self.assertIn('MUST_DELIVER',self.seen[-1][0][2])

    def test_confirmed_cancel_reuses_session_and_sends_only_delta_across_reload(self):
        q=request(transcript=[dict(type='agent',id='codex',text='DELIVERED_ONCE')])
        def fail(*args,**kw):
            args[8]('confirmed-session');kw['delivery_callback']('sent_unconfirmed');kw['delivery_callback']('confirmed')
            raise NativeError('cancelled')
        with self.assertRaises(CouncilError):self.native(q,fail)
        session=next(iter(self.c.native_sessions.values()))
        self.assertEqual(session['delivery']['status'],'confirmed')
        self.c.close();self.c=Council(self.tmp.name,runner=lambda *a:{})
        q['transcript'].append(dict(type='agent',id='codex',text='ONLY_NEW_PART'))
        self.native(q)
        self.assertEqual(self.seen[-1][0][7]['id'],'confirmed-session')
        prompt=self.seen[-1][0][2]
        self.assertNotIn('DELIVERED_ONCE',prompt);self.assertIn('ONLY_NEW_PART',prompt)
        self.assertEqual(sync.decode(prompt)[1]['contextDelivery']['mode'],'delta')

    def test_unconfirmed_handoff_preparation_is_cached_but_never_resent_to_same_session(self):
        q=request(transcript=[dict(type='agent',id='codex',text='plan.md has a pending issue')])
        def fail(*args,**kw):
            args[8]('unknown-session');kw['delivery_callback']('sent_unconfirmed');raise NativeError('timeout')
        with self.assertRaises(CouncilError):self.native(q,fail)
        original=copy.deepcopy(next(iter(self.c.native_sessions.values()))['handoffCache'])
        with patch('handoff.build',side_effect=AssertionError('Must reuse prepared summary')):
            self.native(q)
        self.assertNotIn('id',self.seen[-1][0][7])
        self.assertEqual(next(iter(self.c.native_sessions.values()))['handoffCache'],original)

    def test_legacy_and_large_sessions_are_preserved_and_rebased_without_a_compaction_call(self):
        key=json.dumps(['run','claude','debater','claude'])
        self.c.native_sessions[key]=dict(id='old-bloated',permissions=[dict(toolName='Read',ruleContent='/research/**')])
        q=request();self.native(q)
        s=next(iter(self.c.native_sessions.values()))
        self.assertEqual(s['previousSessions'][0]['id'],'old-bloated')
        self.assertEqual(self.seen[-1][0][7]['permissions'][0]['ruleContent'],'/research/**')
        s['lastContext']=dict(usedTokens=150000,windowTokens=200000)
        self.native(q)
        self.assertEqual(len(self.seen),2)
        self.assertNotIn('id',self.seen[-1][0][7])
        self.assertEqual(next(iter(self.c.native_sessions.values()))['previousSessions'][-1]['reason'],'large_context_checkpoint')

    def test_independent_question_starts_fresh_without_prior_peer_memory(self):
        self.native(request(transcript=[dict(type='agent',id='codex',text='OLD_PEER')]))
        self.native(request(kind='independent',question='New independent question'))
        self.assertNotIn('OLD_PEER',self.seen[-1][0][2])
        self.assertEqual(next(iter(self.c.native_sessions.values()))['previousSessions'][-1]['reason'],'new_independent_question')
        self.native(request(transcript=[dict(type='agent',id='codex',text='LATER_PEER')]))
        self.native(request(kind='independent',question='New independent question'))
        self.assertEqual(next(iter(self.c.native_sessions.values()))['previousSessions'][-1]['reason'],'new_independent_question')

    def test_historical_images_are_not_reattached_but_explicit_images_are(self):
        im=self.c.images.put(dict(mime='image/png',data=base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode()))
        q=request(transcript=[dict(type='user',id='u',images=[im],text='IMAGE_QUESTION')])
        self.native(q);self.assertEqual(len(self.seen[-1][1]['images']),1)
        self.native(q);self.assertFalse(self.seen[-1][1]['images'])
        q['images']=[im];self.native(q);self.assertEqual(len(self.seen[-1][1]['images']),1)

    def test_same_member_calls_are_serialized_and_cannot_overwrite_the_cursor(self):
        entered=threading.Event();release=threading.Event();errors=[];count=[]
        def runner(*args,**kw):
            count.append(1)
            if len(count)==1:entered.set();release.wait(2)
            return self.fake(*args,**kw)
        def start(q):
            try:self.c.native(self.a,prompt_for(self.a,q),self.job(q))
            except Exception as e:errors.append(e)
        with patch('bridge.locate',return_value='cli'),patch('bridge.validate_effort'),patch('native_cli.run',side_effect=runner):
            t1=threading.Thread(target=start,args=(request(),));t1.start();self.assertTrue(entered.wait(2))
            t2=threading.Thread(target=start,args=(request(question='NEXT'),));t2.start()
            self.assertEqual(len(count),1);release.set();t1.join(3);t2.join(3)
        self.assertFalse(errors);self.assertEqual(len(count),2)
        self.assertEqual(self.seen[-1][0][7]['contextSync']['version'],sync.VERSION)


if __name__=='__main__':unittest.main()


class HandoffTests(unittest.TestCase):
    def test_handoff_has_attribution_file_notes_open_issues_and_live_process(self):
        q=request(kind='debate',control=dict(blockers={'claude':[dict(text='Need calibration')]}))
        payload=dict(question='Next',transcript=[dict(type='agent',id='claude',jobId='source',text='Checked src/train.py:12: batch size is 8. Evidence is provisional.')],
                     managedExperiment=dict(pid=42,logPath='/tmp/train.log',status='running'))
        prompt,_,_=sync.prepare(rendered(payload),{},agent(),'/record',q)
        h=sync.decode(prompt)[1]['handoff']
        self.assertEqual(h['reportedFindings'][0]['author'],'claude')
        self.assertEqual(h['fileNotes'][0]['path'],'src/train.py')
        self.assertEqual(h['unresolved'],q['control']['blockers'])
        self.assertEqual(h['experimentState']['managedExperiment']['pid'],42)
        independent=sync.decode(sync.prepare(rendered(dict(payload,transcript=[])),{},agent(),'/record',request(kind='independent'))[0])[1]['handoff']
        self.assertEqual(independent['reportedFindings'],[]);self.assertEqual(independent['fileNotes'],[])

    def test_reset_reason_branches(self):
        current=dict(id='s',workspace='/w',contextProtocol=sync.VERSION,lastKind='independent',independentScope=sync.independent_scope(request(kind='independent')))
        cases=[({},request(),'/w',None), (dict(current,workspace='/old'),request(),'/w','workspace_changed'),
               (dict(current,contextProtocol=0),request(),'/w','legacy_repeated_history'),
               (dict(current,delivery=dict(status='sent_unconfirmed')),request(),'/w','unconfirmed_delivery'),
               (dict(current,lastContext=dict(usedTokens=120000)),request(),'/w','large_context_checkpoint'),
               (dict(current,lastContext=dict(usedTokens=70000,windowTokens=100000)),request(),'/w','large_context_checkpoint'),
               (current,request(kind='independent',question='New'),'/w','new_independent_question'),
               (current,request(kind='independent'),'/w',None), (current,request(),'/w',None)]
        for session,q,workspace,reason in cases:
            with self.subTest(reason=reason):self.assertEqual(sync.reset_reason(session,q,workspace),reason)

    def test_resume_handoff_preserves_process_locations_without_raw_logs(self):
        import handoff
        record=dict(resumeExperiment=dict(sourceTaskId='old',previousActivity=[dict(managedExperiments={'m':dict(monitorId='m',pid=42,status='running',logPath='/tmp/train.log',lastLines=['DO_NOT_REPLAY'])})]))
        state=handoff.experiment_state(record)
        self.assertEqual(state['publishedProcesses'][0]['pid'],42)
        self.assertEqual(state['publishedProcesses'][0]['logPath'],'/tmp/train.log')
        self.assertNotIn('DO_NOT_REPLAY',json.dumps(state))
