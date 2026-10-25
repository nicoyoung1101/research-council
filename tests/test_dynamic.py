import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from bridge import Council, CouncilError, effective_rules, prompt_for
from orchestration import parse_receipt


def agent(aid, provider='codex'):
    return dict(id=aid, provider=provider, enabled=True, name=aid, model='default', effort='default', role='debater', rules='', tools={})


def wait(c, rid):
    deadline=time.time()+8
    while time.time()<deadline:
        r=c.controller.public(c.controller.runs[rid])
        if r['status']!='running': return r
        time.sleep(.02)
    raise AssertionError('Controller did not settle')


class DynamicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.seen=[]
        self.behavior=None
        def runner(a,p,j):
            self.seen.append(copy.deepcopy(j['request']))
            if self.behavior: return self.behavior(a,p,j)
            return self.output(a,p,j)
        self.c=Council(self.tmp.name, runner=runner, auth=lambda p:{'installed':True,'loggedIn':True})
        self.body=dict(requestId='create',sessionId='s',question='Q',roster=[agent('a'),agent('b','claude')],profile='native',packet={})
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def output(self,a,p,j,**changes):
        q=j['request']
        if q['kind']!='debate': return {'text':a['id']+' independent answer'}
        control=q['control'];plan=control['plan']
        receipt=dict(nonce=control['nonce'],decision='ready',reviewedPlanHash=plan['hash'] if plan else 'proposed',proposal=None if plan else dict(title='Plan',body='Write a test file',acceptance=['File reads OK']),blockers=[],nextAction='Execute approved plan',researchStage='confirmation')
        receipt.update(changes)
        return {'text':a['id']+' published answer\n<council_control>'+json.dumps(receipt)+'</council_control>'}
    def create(self): return self.c.controller.create(self.body)['id']
    def action(self,rid,action,**extra):
        self.c.controller.action(rid,dict(action=action,**extra));return wait(self.c,rid)
    def settle_questions(self, rid):
        deadline = time.time()+4
        while time.time()<deadline:
            r = self.c.controller.public(self.c.controller.runs[rid])
            if not any(q['status']=='running' for q in r.get('questions', [])):
                return r
            time.sleep(.02)
        self.fail('Questions did not stop')

    def test_codex_access_updates_next_native_call_without_resetting_discussion(self):
        rid=self.create();self.action(rid,'round',codexPermissionMode='full')
        self.assertEqual(self.seen[-1]['codexPermissionMode'],'full')
        published=self.c.controller.runs[rid]['independent'].copy()
        self.action(rid,'next',codexPermissionMode='read-only')
        self.assertEqual(self.seen[-1]['codexPermissionMode'],'read-only')
        self.assertEqual(self.c.controller.runs[rid]['independent'],published)
        self.assertEqual(self.c.controller.runs[rid]['request']['codexPermissionMode'],'read-only')
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='next',codexPermissionMode='unknown'))

    def test_targeted_review_is_public_native_single_call_then_next_peer(self):
        rid=self.create();self.action(rid,'round');calls=len(self.seen)
        message=dict(id='review-q',text='Do you agree with the peer? Confirm the next step.',to='all',
                     quotes=[dict(source='a',text='Original exact claim')])
        r=self.action(rid,'review_one',reviewerId='b',message=message)
        self.assertEqual(len(self.seen),calls+1)
        request=self.seen[-1]
        self.assertEqual(request['kind'],'debate');self.assertEqual(request['profile'],'native')
        self.assertEqual([a['id'] for a in request['agents']],['b'])
        self.assertEqual(request['question'],message['text']);self.assertEqual(request['quotedReferences'],message['quotes'])
        self.assertEqual(r['activeQuestion']['to'],'all');self.assertEqual(r['activeQuestion']['reviewerId'],'b')
        self.assertNotEqual(r['status'],'ready');self.assertEqual(r['nextSpeaker']['id'],'a')
        r=self.action(rid,'next')
        self.assertEqual([a['id'] for a in self.seen[-1]['agents']],['a'])
        self.assertEqual(self.seen[-1]['kind'],'debate')
        prompt=prompt_for(self.seen[-1]['agents'][0],self.seen[-1])
        self.assertIn(message['text'],prompt);self.assertIn('b published answer',prompt)
        self.assertTrue(all(t.get('replyTo')=='review-q' for t in r['turns'] if t['type']=='agent'))

    def test_targeted_review_can_start_before_independent_answers(self):
        rid=self.create();r=self.action(rid,'review_one',reviewerId='b')
        self.assertEqual(r['calls'],1);self.assertEqual(self.seen[-1]['kind'],'debate')
        self.assertEqual(r['nextSpeaker']['id'],'a');r=self.action(rid,'next')
        self.assertEqual(r['calls'],2);self.assertEqual(self.seen[-1]['kind'],'debate')
        self.assertEqual([a['id'] for a in self.seen[-1]['agents']],['a'])

    def test_repeated_targeted_review_keeps_selected_member_then_alternates(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence',blockers=[])
        rid=self.create();self.action(rid,'round')
        r=self.action(rid,'review_one',reviewerId='b');first_round=r['round']
        r=self.action(rid,'review_one',reviewerId='b')
        self.assertEqual(r['round'],first_round+1);self.assertEqual(r['turns'][-1]['id'],'b')
        self.assertEqual(r['nextSpeaker']['id'],'a')
        r=self.action(rid,'next');self.assertEqual(r['turns'][-1]['id'],'a')
        r=self.action(rid,'review_one',reviewerId='a',message=dict(id='new-q',text='A new follow-up',to='all'))
        self.assertEqual(r['turns'][-1]['id'],'a');self.assertEqual(r['nextSpeaker']['id'],'b')

    def test_targeted_review_recipient_is_validated_before_mutation(self):
        rid=self.create()
        for target,to in [('missing','all'),('context','all'),('b','b')]:
            before=copy.deepcopy(self.c.controller.runs[rid])
            with self.assertRaises(CouncilError):
                self.c.controller.action(rid,dict(action='review_one',reviewerId=target,
                    message=dict(id='invalid',text='Question',to=to)))
            self.assertEqual(self.c.controller.runs[rid],before)
        self.assertEqual(len(self.seen),0)

    def test_targeted_review_retry_does_not_call_member_twice(self):
        rid=self.create();message=dict(id='once',text='Please review this claim',to='all')
        r=self.action(rid,'review_one',reviewerId='b',message=message);calls=r['calls']
        r=self.action(rid,'review_one',reviewerId='b',message=message)
        self.assertEqual(r['calls'],calls)
        self.assertEqual(len([t for t in r['turns'] if t['type']=='user']),1)

    def test_paused_targeted_review_resumes_same_member_then_next_peer(self):
        rid=self.create();self.action(rid,'round');self.action(rid,'next')
        entered=threading.Event()
        def runner(a,p,j):
            entered.set()
            if j['cancel'].wait(3):raise CouncilError('cancelled')
            return self.output(a,p,j)
        self.behavior=runner
        self.c.controller.action(rid,dict(action='review_one',reviewerId='a'))
        self.assertTrue(entered.wait(2));self.c.controller.action(rid,dict(action='pause'));r=wait(self.c,rid)
        self.assertEqual(r['nextSpeaker']['id'],'a');calls=r['calls']
        self.behavior=None;r=self.action(rid,'resume');self.assertEqual(r['calls'],calls)
        r=self.action(rid,'next');self.assertEqual(r['turns'][-1]['id'],'a')
        self.assertEqual(r['nextSpeaker']['id'],'b')

    def test_pause_stops_active_independent_and_resumes_only_missing_member(self):
        entered = threading.Event()
        def runner(a, p, j):
            if a['id']=='b':
                entered.set()
                if j['cancel'].wait(3): raise CouncilError('cancelled')
            return self.output(a,p,j)
        self.behavior=runner; rid=self.create()
        self.c.controller.action(rid, {'action':'round'})
        self.assertTrue(entered.wait(2))
        deadline=time.time()+2
        while not self.c.controller.runs[rid]['independent'] and time.time()<deadline:time.sleep(.02)
        self.c.controller.action(rid, {'action':'pause'}); r=wait(self.c,rid)
        self.assertEqual(r['reason'],'user'); self.assertIsNone(r['error'])
        self.assertEqual(set(r['independent']),{'a'})
        self.assertEqual(self.c.jobs[r['jobs'][-1]]['status'],'cancelled')
        self.behavior=None
        calls=r['calls'];r=self.action(rid,'resume');self.assertEqual(r['calls'],calls)
        r=self.action(rid,'next')
        self.assertEqual(set(r['independent']),{'a','b'})
        self.assertEqual([a['id'] for a in self.seen[-1]['agents']],['b'])
        self.assertEqual(r['calls'],3)
        self.assertFalse(r['thinkingPaused'])

    def test_resume_only_unlocks_automatic_review_until_next_is_clicked(self):
        entered=threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='debate':
                entered.set()
                if j['cancel'].wait(3):raise CouncilError('cancelled')
            return self.output(a,p,j)
        rid=self.create();self.action(rid,'round');self.behavior=runner
        self.c.controller.action(rid,{'action':'review_auto'});self.assertTrue(entered.wait(2))
        self.c.controller.action(rid,{'action':'pause'});r=wait(self.c,rid);calls=r['calls']
        r=self.action(rid,'resume')
        self.assertEqual(r['calls'],calls);self.assertFalse(r['thinkingPaused']);self.assertTrue(r['dispatchHeld'])
        self.assertEqual(r['reason'],'awaiting_dispatch');self.assertEqual(r['nextSpeaker']['id'],'a')
        self.behavior=None;r=self.action(rid,'next')
        self.assertEqual(r['calls'],calls+1);self.assertEqual(r['turns'][-1]['id'],'a')
        self.assertEqual(r['status'],'idle')

    def test_next_resumes_paused_question_one_original_member_at_a_time(self):
        entered=threading.Event()
        def runner(a,p,j):
            entered.set()
            if j['cancel'].wait(3):raise CouncilError('cancelled')
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create()
        self.c.controller.action(rid,dict(action='question',message=dict(id='q',text='Original question',to='all')))
        self.assertTrue(entered.wait(2));self.c.controller.action(rid,dict(action='pause'));r=self.settle_questions(rid)
        calls=r['calls'];r=self.action(rid,'resume');self.assertEqual(r['calls'],calls)
        self.behavior=None
        self.c.controller.action(rid,dict(action='next'));r=self.settle_questions(rid)
        self.assertEqual(r['calls'],calls+1);self.assertEqual(r['questions'][0]['status'],'paused')
        self.assertEqual(r['questions'][0]['completedAgents'],['a']);self.assertEqual(r['nextSpeaker']['id'],'b')
        self.c.controller.action(rid,dict(action='next'));r=self.settle_questions(rid)
        self.assertEqual(r['calls'],calls+2);self.assertEqual(r['questions'][0]['status'],'complete')
        self.assertEqual(r['questions'][0]['completedAgents'],['a','b'])
        self.assertTrue(all(q['question']=='Original question' for q in self.seen))

    def test_paused_question_survives_reload_and_continues_only_missing_answer(self):
        entered=threading.Event()
        def runner(a,p,j):
            if a['id']=='b':
                entered.set()
                if j['cancel'].wait(3):raise CouncilError('cancelled')
            return {'text':'Answer '+a['id']}
        self.behavior=runner;rid=self.create()
        self.c.controller.action(rid, {'action':'question','message':{'id':'q','text':'Why?','to':'all'}})
        self.assertTrue(entered.wait(2))
        deadline=time.time()+2
        while not self.c.jobs[self.c.controller.runs[rid]['questions'][0]['jobId']]['results'] and time.time()<deadline:time.sleep(.02)
        self.c.controller.action(rid, {'action':'pause'});r=self.settle_questions(rid)
        self.assertEqual(r['questions'][0]['status'],'paused')
        self.assertEqual(r['questions'][0]['completedAgents'],['a'])
        self.assertTrue(r['thinkingPaused'])
        self.c.close()
        self.c=Council(self.tmp.name,runner=lambda a,p,j:{'text':'Resumed '+a['id']},auth=lambda p:{'installed':True,'loggedIn':True})
        calls=self.c.controller.runs[rid]['calls']
        self.c.controller.action(rid, {'action':'resume'});r=self.settle_questions(rid)
        self.assertEqual(r['calls'],calls);self.assertEqual(r['questions'][0]['status'],'paused')
        self.c.controller.action(rid, {'action':'next'});r=self.settle_questions(rid)
        self.assertEqual(r['questions'][0]['status'],'complete')
        self.assertEqual(r['calls'],3)
        answers=[t for t in r['turns'] if t['type']=='agent']
        self.assertEqual([t['id'] for t in answers],['a','b'])
        self.assertEqual(answers[0]['text'],'Answer a')
        self.assertEqual(len([t for t in r['turns'] if t['type']=='user']),1)
        self.c.controller.action(rid, {'action':'resume'})
        self.assertEqual(self.c.controller.runs[rid]['calls'],3)

    def test_pause_experiment_preserves_artifact_and_continue_does_not_replay(self):
        entered=threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='execution':
                Path(j['request']['workspace'],'already-written.txt').write_text('partial experiment')
                entered.set()
                if j['cancel'].wait(4):raise CouncilError('cancelled')
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto')
        self.c.controller.action(rid, {'action':'execute','planHash':r['plan']['hash']})
        self.assertTrue(entered.wait(2))
        self.c.controller.action(rid, {'action':'pause'});r=wait(self.c,rid)
        calls=r['calls'];self.assertEqual(r['experiments'][0]['status'],'interrupted')
        self.assertEqual(Path(r['workspace'],'already-written.txt').read_text(),'partial experiment')
        r=self.action(rid,'resume');self.assertEqual(r['calls'],calls)
        self.assertFalse(r['reviews']);self.assertNotIn('activeExperiment',r)
        self.assertFalse(any(q['kind']=='verification' for q in self.seen))

    def test_shared_question_stops_old_review_and_late_receipt_cannot_approve_new_focus(self):
        entered=threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='debate' and j['request']['question']=='Q':
                entered.set();j['cancel'].wait(4)
            return self.output(a,p,j)
        rid=self.create();self.action(rid,'round');self.behavior=runner
        self.c.controller.action(rid,{'action':'review_auto'});self.assertTrue(entered.wait(2))
        old_job=self.c.controller.runs[rid]['pendingJob']
        message={'id':'new-task','text':'Focus on a quick AutoDL experiment, not slides','to':'all','quotes':[{'text':'six to three sensors','source':'Codex'}]}
        self.c.controller.action(rid,{'action':'question','message':message})
        r=wait(self.c,rid);r=self.settle_questions(rid)
        self.assertEqual(self.c.jobs[old_job]['status'],'cancelled')
        self.assertEqual(r['reason'],'new_question');self.assertEqual(r['activeQuestion'],message)
        self.assertIsNone(r['plan']);self.assertFalse(r['reviews']);self.assertFalse(r['blockers'])
        late=next(t for t in r['turns'] if t.get('jobId')==old_job)
        self.assertTrue(late['superseded'])
        self.assertLess(r['turns'].index(late),next(i for i,t in enumerate(r['turns']) if t.get('id')=='new-task'))
        for t in r['turns']:
            if t.get('kind')=='question':self.assertEqual(t['replyTo'],'new-task')
        calls=r['calls'];r=self.action(rid,'resume');self.assertEqual(r['calls'],calls)
        r=self.action(rid,'review_auto');self.assertEqual(r['status'],'ready')
        current=[q for q in self.seen if q['kind']=='debate' and q.get('focusMessageId')=='new-task']
        self.assertEqual(len(current),2)
        self.assertTrue(all(q['question']==message['text'] and q['researchQuestion']=='Q' and q['quotedReferences']==message['quotes'] for q in current))

    def test_review_message_becomes_current_question_and_invalidates_previous_approval(self):
        rid=self.create();r=self.action(rid,'auto');old_plan=r['plan']['hash']
        message={'id':'review-task','text':'Evaluate only a one-day pilot','to':'all','action':'review'}
        r=self.action(rid,'review',message=message)
        last=[q for q in self.seen if q['kind']=='debate'][-2:]
        self.assertTrue(all(q['question']==message['text'] and q['focusMessageId']==message['id'] for q in last))
        self.assertNotEqual(r['plan']['hash'],old_plan)
        self.assertTrue(any(p['hash']==old_plan for p in r['plans']))
        self.assertEqual(len([t for t in r['turns'] if t.get('id')=='review-task' and t['type']=='user']),1)

    def test_shared_question_during_experiment_defers_focus_until_frozen_verification(self):
        entered,release=threading.Event(),threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='execution':entered.set();release.wait(3)
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto');plan=copy.deepcopy(r['plan'])
        self.c.controller.action(rid,{'action':'execute','planHash':plan['hash']});self.assertTrue(entered.wait(2))
        message={'id':'after-experiment','text':'Interpret this result and pick the next small step','to':'all'}
        r=self.c.controller.action(rid,{'action':'question','message':message})
        self.assertEqual(r['plan'],plan);self.assertEqual(r['deferredFocus'],message)
        self.assertFalse(self.c.jobs[r['pendingJob']]['cancel'].is_set())
        release.set();r=wait(self.c,rid);r=self.settle_questions(rid)
        verification=next(q for q in self.seen if q['kind']=='verification')
        self.assertEqual(verification['approvedPlan'],plan)
        self.assertEqual(r['experiments'][0]['plan'],plan)
        self.assertEqual(r['activeQuestion'],message)
        self.assertTrue(all(q['question']==message['text'] for q in self.seen if q['kind']=='debate' and q.get('focusMessageId')=='after-experiment'))

    def test_failed_experiment_keeps_new_question_as_the_next_focus(self):
        entered,release=threading.Event(),threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='execution':
                entered.set();release.wait(3);raise CouncilError('cli_failed','Experiment interrupted')
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto');plan=copy.deepcopy(r['plan'])
        self.c.controller.action(rid,{'action':'execute','planHash':plan['hash']});self.assertTrue(entered.wait(2))
        message={'id':'inspect-failure','text':'Inspect the logs and explain the failure','to':'all'}
        self.c.controller.action(rid,{'action':'question','message':message});self.settle_questions(rid)
        release.set();r=wait(self.c,rid)
        self.assertEqual(r['activeQuestion'],message);self.assertNotIn('deferredFocus',r)
        self.assertEqual(r['experiments'][0]['plan'],plan);self.assertEqual(r['experiments'][0]['status'],'failed')
        self.assertIsNone(r['plan'])
        self.action(rid,'review')
        self.assertTrue(all(q['question']==message['text'] for q in self.seen if q['kind']=='debate' and q.get('focusMessageId')==message['id']))

    def test_legacy_question_focus_migrates_without_rerunning_or_losing_answers(self):
        rid=self.create();self.action(rid,'round');self.action(rid,'next')
        for i in range(2):
            self.c.controller.action(rid,{'action':'question','message':{'id':'q'+str(i),'text':'Question '+str(i),'to':'all'}})
            self.settle_questions(rid)
        r=self.c.controller.runs[rid];r.pop('focusRevision',None);r.pop('activeQuestion',None)
        for t in r['turns']:t.pop('replyTo',None)
        self.c.controller.persist(r);before=[t['text'] for t in r['turns']];calls=r['calls']
        self.c.close();self.c=Council(self.tmp.name,runner=lambda *x:self.fail('Migration must not invoke a model'),auth=lambda p:{'installed':True,'loggedIn':True})
        r=self.c.controller.public(self.c.controller.runs[rid])
        self.assertEqual(r['activeQuestion']['id'],'q1');self.assertEqual(r['calls'],calls)
        self.assertTrue(all(t['superseded'] for t in r['turns'] if t.get('kind')=='debate'))
        self.assertEqual([t['text'] for t in r['turns']],before)
        self.assertEqual([t['replyTo'] for t in r['turns'] if t.get('kind')=='question'],['q0','q0','q1','q1'])

    def test_dynamic_stops_on_same_version_and_peer_gets_latest(self):
        rid=self.create();r=self.action(rid,'auto')
        self.assertEqual(r['status'],'ready');self.assertEqual(r['calls'],4)
        calls=[x for x in self.seen if x['kind']=='debate']
        self.assertEqual(len(calls),2)
        self.assertTrue(any(t['text']=='a published answer' for t in calls[1]['transcript']))
        self.assertNotIn('council_control',r['turns'][0]['text'])
        self.assertEqual(len(set(v['planHash'] for v in r['reviews'].values())),1)
        self.assertTrue(Path(r['workspace']).is_dir())
    def test_original_sources_reach_both_without_context_or_peer_leakage(self):
        self.body['roster'].append(dict(agent('optional'),role='context',enabled=False))
        self.body['packet']={'documents':[{'name':'raw.md','text':'ORIGINAL_SOURCE_789'}]}
        self.body['initialInstructions']=[{'text':'Find local /tmp/raw.md and search the web','to':'all'}]
        rid=self.create();r=self.action(rid,'round')
        self.assertEqual(r['calls'],2)
        self.assertFalse(r.get('context'))
        self.assertEqual(len(r['independent']),2)
        for q in self.seen:
            self.assertFalse(q.get('contextAgent'))
            for a in q['agents']:
                p=prompt_for(a,q)
                self.assertIn('ORIGINAL_SOURCE_789',p)
                self.assertIn('/tmp/raw.md',p)
                self.assertNotIn('a independent answer',p)
                self.assertNotIn('b independent answer',p)
                self.assertIn('"transcript": []',p)
    def test_source_verification_rules_apply_only_to_native_debaters(self):
        q=dict(kind='debate',profile='native')
        for provider in ('claude','codex'):
            p=effective_rules(agent('a',provider),q)
            self.assertIn('Independently inspect user-specified local documents',p)
            self.assertIn('state access failures',p)
            self.assertNotIn('Independently inspect user-specified local documents',effective_rules(agent('a',provider),dict(q,profile='restricted')))
        self.assertNotIn('Independently inspect user-specified local documents',effective_rules(agent('g','gemini'),q))

    def test_next_is_exactly_one_and_alternates_across_rounds(self):
        rid=self.create();r=self.action(rid,'next');self.assertEqual(len(r['independent']),1)
        r=self.action(rid,'next');self.assertEqual(len(r['independent']),2)
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence',blockers=[dict(id='evidence',text='Need source')])
        self.action(rid,'round');self.action(rid,'next')
        calls=[x['agents'][0]['id'] for x in self.seen if x['kind']=='debate']
        self.assertEqual(calls,['a','b','a'])

    def test_speaker_rotation_covers_every_member_before_repeating(self):
        self.body['roster'].append(agent('c'))
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence')
        rid=self.create();self.action(rid,'round')
        for _ in range(3):self.action(rid,'round')
        self.assertEqual([q['agents'][0]['id'] for q in self.seen if q['kind']=='debate'],['a','b','c']*3)
        self.assertEqual(self.c.controller.public(self.c.controller.runs[rid])['nextSpeaker']['id'],'a')

    def test_cancelled_boundary_call_does_not_skip_next_speaker_after_reload(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence')
        rid=self.create();self.action(rid,'round');r=self.action(rid,'round')
        self.assertEqual(r['nextSpeaker']['id'],'a')
        entered=threading.Event()
        def runner(a,p,j):
            self.assertEqual(a['id'],'a');entered.set()
            if j['cancel'].wait(3):raise CouncilError('cancelled')
            return self.output(a,p,j,decision='need_evidence')
        self.behavior=runner
        self.c.controller.action(rid,{'action':'next'});self.assertTrue(entered.wait(2))
        self.c.controller.action(rid,{'action':'pause'});r=wait(self.c,rid)
        self.assertEqual(r['round'],2);self.assertEqual(r['nextSpeaker']['id'],'a')
        self.c.close();called=[]
        def resumed(a,p,j):
            called.append(a['id']);return self.output(a,p,j,decision='need_evidence')
        self.c=Council(self.tmp.name,runner=resumed,auth=lambda p:{'installed':True,'loggedIn':True})
        r=self.action(rid,'resume');self.assertFalse(called)
        r=self.action(rid,'next')
        self.assertEqual(called,['a']);self.assertEqual(r['nextSpeaker']['id'],'b')

    def test_new_focus_starts_a_new_speaker_sequence(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence')
        rid=self.create();self.action(rid,'round');self.action(rid,'next')
        r=self.action(rid,'review',message=dict(id='new-focus',text='Different question',to='all'))
        current=[q for q in self.seen if q.get('focusMessageId')=='new-focus']
        self.assertEqual([q['agents'][0]['id'] for q in current],['a','b'])

    def test_next_message_reaches_scheduled_peer_and_preserves_single_call(self):
        rid=self.create();self.action(rid,'round');self.action(rid,'next')
        message=dict(id='ask-peer',text='Do you agree with the last answer?',to='all',
                     quotes=[dict(id='quote',source='a',text='Original evidence')])
        before=self.c.controller.runs[rid]['calls']
        r=self.action(rid,'next',message=message)
        request=self.seen[-1]
        self.assertEqual([a['id'] for a in request['agents']],['b'])
        self.assertEqual(request['question'],message['text'])
        self.assertEqual(request['quotedReferences'],message['quotes'])
        self.assertEqual(r['calls'],before+1)
        self.assertEqual(r['turns'][-1]['replyTo'],'ask-peer')
        self.assertEqual(r['nextSpeaker']['id'],'a')
        self.assertFalse(r['experiments'])

    def test_next_message_can_explicitly_start_while_paused(self):
        rid=self.create();self.action(rid,'round');self.action(rid,'next');self.action(rid,'pause')
        r=self.action(rid,'next',message=dict(id='paused-followup',text='Please check this claim',to='all'))
        self.assertEqual(self.seen[-1]['agents'][0]['id'],'b')
        self.assertFalse(r['thinkingPaused']);self.assertFalse(r['pauseRequested'])

    def test_retrying_accepted_next_message_does_not_repeat_the_call(self):
        rid=self.create();self.action(rid,'round')
        message=dict(id='retry-next',text='Review the previous answer',to='all')
        r=self.action(rid,'next',message=message);calls=r['calls']
        r=self.action(rid,'next',message=message)
        self.assertEqual(r['calls'],calls)
        self.assertEqual(len([t for t in r['turns'] if t.get('id')=='retry-next']),1)

    def test_next_message_rejects_invalid_recipient_without_changing_focus(self):
        rid=self.create();self.action(rid,'round');before=copy.deepcopy(self.c.controller.runs[rid])
        with self.assertRaises(CouncilError):
            self.c.controller.action(rid,dict(action='next',message=dict(id='wrong',text='Claim',to='a')))
        for key in ('activeQuestion','focusRevision','turns','calls','speakerStart','generation'):
            self.assertEqual(self.c.controller.runs[rid].get(key),before.get(key),key)
    def test_new_plan_invalidates_old_ready(self):
        rid=self.create();self.action(rid,'round');self.action(rid,'next')
        self.behavior=lambda a,p,j:self.output(a,p,j,proposal=dict(title='Changed',body='Different plan',acceptance=['Different check']),reviewedPlanHash='proposed')
        r=self.action(rid,'next');self.assertEqual(r['status'],'idle');self.assertEqual(list(r['reviews']),['b']);self.assertEqual(r['plan']['version'],2)

    def test_need_user_finishes_both_peer_reviews_before_pausing(self):
        for action in ('review', 'review_auto', 'round', 'auto'):
            with self.subTest(action=action):
                self.body['requestId']='need-user-'+action
                rid=self.create();self.action(rid,'round')
                self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_user' if a['id']=='a' else 'revise',
                    blockers=[dict(id='gpu',text='Confirm GPU before execution')])
                start=len(self.seen)
                r=self.action(rid,action)
                reviews=[q for q in self.seen[start:] if q['kind']=='debate']
                self.assertEqual([q['agents'][0]['id'] for q in reviews],['a','b'])
                self.assertIn('a published answer',json.dumps(reviews[1]['transcript']))
                self.assertEqual((r['status'],r['reason']),('paused','need_user'))
                self.assertFalse(self.c.controller.ready(r))
                self.assertFalse(any(q['kind']=='execution' for q in self.seen[start:]))
                self.behavior=None

    def test_legacy_partial_need_user_round_finishes_missing_peer(self):
        rid=self.create();self.action(rid,'round')
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_user' if a['id']=='a' else 'revise')
        # Simulate a persisted partial round from the previous app version.
        raw=self.c.controller.runs[rid]
        self.c.controller.one(raw)
        raw.update(status='paused',reason='need_user');raw.pop('needUser',None)
        self.assertEqual(len([q for q in self.seen if q['kind']=='debate']),1)
        r=self.action(rid,'review')
        self.assertEqual([q['agents'][0]['id'] for q in self.seen if q['kind']=='debate'],['a','b'])
        self.assertEqual((r['status'],r['reason']),('paused','need_user'))

    def test_explicit_next_can_still_stop_after_one_need_user_answer(self):
        rid=self.create();self.action(rid,'round')
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_user')
        r=self.action(rid,'next')
        self.assertEqual((r['status'],r['reason']),('paused','need_user'))
        self.assertEqual([q['agents'][0]['id'] for q in self.seen if q['kind']=='debate'],['a'])

    def test_inherited_agreement_does_not_skip_remaining_speaker(self):
        rid=self.create();r=self.action(rid,'auto')
        raw=self.c.controller.runs[rid]
        raw.update(status='idle',round=raw['round']+1)
        start=len(self.seen)
        r=self.action(rid,'round')
        self.assertEqual(len([q for q in self.seen[start:] if q['kind']=='debate']),2)
        self.assertEqual((r['status'],r['reason']),('ready','unanimous'))

    def test_user_can_pause_while_second_member_reviews_need_user(self):
        entered=threading.Event()
        def runner(a,p,j):
            if a['id']=='b':
                entered.set()
                if j['cancel'].wait(3):raise CouncilError('cancelled')
            return self.output(a,p,j,decision='need_user')
        rid=self.create();self.behavior=runner
        self.c.controller.action(rid,{'action':'review_auto'})
        self.assertTrue(entered.wait(2))
        self.c.controller.action(rid,{'action':'pause'});r=wait(self.c,rid)
        self.assertEqual((r['status'],r['reason']),('paused','user'))
        self.assertEqual(len([t for t in r['turns'] if t.get('kind')=='debate']),1)
        self.assertEqual(self.c.jobs[r['jobs'][-1]]['status'],'cancelled')
    def test_stale_ready_and_malformed_receipts_never_converge(self):
        rid=self.create();self.action(rid,'round')
        self.behavior=lambda a,p,j:self.output(a,p,j,reviewedPlanHash='wrong')
        r=self.action(rid,'next');self.assertEqual(r['reason'],'invalid_receipt');self.assertFalse(self.c.controller.ready(r))
        self.behavior=lambda a,p,j:{'text':'I completely agree; execute now'}
        r=self.action(rid,'next');self.assertEqual(r['reason'],'invalid_receipt');self.assertEqual(r['turns'][-1]['text'],'I completely agree; execute now')
    def test_discussion_ignores_local_call_and_time_budgets(self):
        self.body['budgets']={'calls':2,'seconds':30}
        rid=self.create()
        run=self.c.controller.runs[rid]
        run['calls']=501;run['elapsed']=90000
        r=self.action(rid,'auto')
        self.assertEqual(r['status'],'ready')
        self.assertGreater(r['calls'],501)
        self.assertTrue(r['budgets']['unlimited'])

    def test_old_budget_pause_is_cleared_on_reload(self):
        rid=self.create();run=self.c.controller.runs[rid]
        run.update(status='paused',reason='budget_reached',error={'code':'budget_reached'})
        run['budgets']={'calls':2,'seconds':30};run['calls']=501;run['elapsed']=90000
        self.c.controller.persist(run);self.c.close()
        self.c=Council(self.tmp.name,runner=lambda a,p,j:self.output(a,p,j),auth=lambda p:{'installed':True,'loggedIn':True})
        r=self.c.controller.public(self.c.controller.runs[rid])
        self.assertIsNone(r['reason']);self.assertIsNone(r['error'])
        self.assertTrue(r['budgets']['unlimited'])
        self.assertEqual(self.action(rid,'auto')['status'],'ready')
    def test_stagnation_is_pause_not_agreement(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence',blockers=[dict(id='source',text='Missing evidence')])
        rid=self.create();r=self.action(rid,'auto');self.assertEqual(r['reason'],'stalled');self.assertEqual(r['round'],3);self.assertFalse(self.c.controller.ready(r))
    def test_moderator_change_invalidates_exact_plan_approval(self):
        rid=self.create();r=self.action(rid,'auto');old=r['plan']['hash']
        r=self.action(rid,'moderator',moderator=[dict(text='Changed condition',to='all')]);self.assertEqual(r['reviews'],{});self.assertNotEqual(old,r['plan']['hash'])
        with self.assertRaises(CouncilError):self.action(rid,'execute',planHash=old)
    def test_experiments_ignore_exhausted_discussion_seconds_without_consuming_them(self):
        rid=self.create();r=self.action(rid,'auto')
        for thread in self.c.controller.threads:thread.join(2)
        run=self.c.controller.runs[rid]
        run['elapsed']=31;run['budgets']['seconds']=30
        def runner(a,p,j):
            if j['request']['kind'] in ('execution','verification'):
                time.sleep(.18)
                self.c.event(j,dict(agentId=a['id'],type='assistant',tool=dict(type='tool_use',id='t',name='Bash',input=dict(command='train'))))
                self.c.event(j,dict(agentId=a['id'],type='user',tool=dict(type='tool_result',tool_use_id='t',content='checkpoint saved')))
            return self.output(a,p,j)
        self.behavior=runner
        r=self.action(rid,'execute',planHash=r['plan']['hash'],followupReview=False)
        self.assertEqual(r['experiments'][0]['status'],'reviewed');self.assertEqual(r['reason'],'execution_finished')
        self.assertGreaterEqual(r['experimentElapsed'],.36);self.assertLess(r['elapsed']-31,.1)
        self.assertEqual(len(r['experiments'][0]['activities']),2)
        for activity in r['experiments'][0]['activities']:
            self.assertTrue(activity['unlimitedDuration'])
            self.assertIn('checkpoint saved',str(activity['executionProgress']))

    def test_pause_cancels_unlimited_experiment_and_preserves_progress(self):
        rid=self.create();r=self.action(rid,'auto');entered=threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='execution':
                self.c.event(j,dict(agentId=a['id'],type='command_output',toolId='t',output='epoch=2 checkpoint saved'))
                entered.set();j['cancel'].wait(4);raise CouncilError('cancelled')
            return self.output(a,p,j)
        self.behavior=runner
        self.c.controller.action(rid,dict(action='execute',planHash=r['plan']['hash'],followupReview=False));self.assertTrue(entered.wait(2))
        self.c.controller.action(rid,dict(action='pause'));r=wait(self.c,rid)
        self.assertEqual(r['experiments'][0]['status'],'interrupted')
        self.assertIn('epoch=2',str(r['experiments'][0]['activities']))
        calls=r['calls'];self.action(rid,'resume');self.assertEqual(self.c.controller.runs[rid]['calls'],calls)

    def interrupted_experiment(self):
        rid=self.create();r=self.action(rid,'auto')
        self.behavior=lambda a,p,j: (_ for _ in ()).throw(CouncilError('timeout')) if j['request']['kind']=='execution' else self.output(a,p,j)
        r=self.action(rid,'execute',planHash=r['plan']['hash'],executorId='b',reviewerId='a',followupReview=False)
        self.behavior=None
        for thread in self.c.controller.threads:thread.join(2)
        return rid,self.c.controller.public(self.c.controller.runs[rid])

    def test_explicit_experiment_resume_preserves_plan_members_and_does_not_prepare(self):
        rid,r=self.interrupted_experiment();source=copy.deepcopy(r['experiments'][-1]);calls=r['calls']
        request=dict(requestId='resume-once',taskId=source['id'],planHash=source['plan']['hash'],text='继续执行')
        r=self.action(rid,'resume_experiment',**request)
        self.assertEqual(r['calls'],calls+2);task=r['experiments'][-1]
        self.assertEqual(task['status'],'reviewed');self.assertEqual(task['resumedFrom'],source['id'])
        self.assertEqual(task['plan'],source['plan']);self.assertEqual((task['executor'],task['reviewer']),('b','a'))
        self.assertEqual(r['experiments'][0],source)
        calls=self.seen[-2:];self.assertEqual([q['kind'] for q in calls],['execution','verification'])
        for q in calls:
            self.assertEqual(q['resumeExperiment']['sourceTaskId'],source['id'])
            self.assertEqual(q['approvedPlan'],source['plan'])
            self.assertIn('CONTINUE EXECUTION',prompt_for(q['agents'][0],q))
        repeated=self.c.controller.action(rid,dict(action='resume_experiment',**request))
        self.assertEqual(repeated['calls'],r['calls']);self.assertEqual(len(repeated['experiments']),2)
        self.assertEqual(repeated['resumableExperiment']['status'],'reviewed')  # Legacy pair-returned is not whole-plan completion.

    def test_resume_rejects_changed_scope_stale_plan_and_missing_explicit_request(self):
        rid,r=self.interrupted_experiment();source=r['experiments'][-1]
        base=dict(action='resume_experiment',requestId='resume',taskId=source['id'],planHash=source['plan']['hash'])
        for changes in [dict(requestId=None),dict(taskId='other'),dict(planHash='wrong'),dict(text='Change to 1000 epochs on paid cloud')]:
            with self.assertRaises(CouncilError):self.c.controller.action(rid,{**base,**changes})
        self.assertEqual(len(self.c.controller.runs[rid]['experiments']),1)

    def test_resume_does_not_depend_on_unrelated_malformed_review_receipt(self):
        rid,r=self.interrupted_experiment();source=r['experiments'][-1];run=self.c.controller.runs[rid]
        run['reviewError']='Malformed later review';run['error']=dict(code='invalid_receipt')
        r=self.action(rid,'resume_experiment',requestId='after-bad-review',taskId=source['id'],planHash=source['plan']['hash'])
        self.assertEqual(r['experiments'][-1]['status'],'reviewed');self.assertIsNone(r['error'])
        self.assertNotIn('reviewError',r)

    def test_execution_runs_one_executor_then_independent_verifier(self):
        rid=self.create();r=self.action(rid,'auto')
        r=self.action(rid,'execute',planHash=r['plan']['hash']);self.assertEqual(r['status'],'ready')
        self.assertEqual([x['kind'] for x in self.seen[4:]],['execution','verification','debate','debate'])
        self.assertNotEqual(self.seen[4]['agents'][0]['id'],self.seen[5]['agents'][0]['id'])
        self.assertEqual(r['experiments'][0]['status'],'reviewed')
        for q in self.seen[6:]:
            self.assertEqual([x['kind'] for x in q['transcript'] if x.get('kind') in ('execution','verification')],['execution','verification'])
    def test_multiple_experiments_keep_frozen_plans_and_results(self):
        rid=self.create();r=self.action(rid,'auto');first_plan=copy.deepcopy(r['plan'])
        r=self.action(rid,'execute',planHash=first_plan['hash']);first=copy.deepcopy(r['experiments'][0])
        self.assertEqual(first['plan'],first_plan)
        self.assertNotEqual(r['plan']['hash'],first_plan['hash'])
        r=self.action(rid,'execute',planHash=r['plan']['hash'])
        self.assertEqual(len(r['experiments']),2);self.assertEqual(r['experiments'][0],first)
        self.assertEqual(len([t for t in r['turns'] if t['type']=='experiment']),2)
        self.assertEqual(len([q for q in self.seen if q['kind']=='execution']),2)
        self.assertEqual(r['status'],'ready')

    def test_ready_is_reviewable_again_without_starting_an_experiment(self):
        rid=self.create();r=self.action(rid,'auto');r=self.action(rid,'next')
        self.assertEqual(r['status'],'idle');self.assertEqual(r['calls'],5)
        self.assertFalse(r['experiments']);self.assertEqual(list(r['reviews']),['a'])

    def test_questions_during_execution_do_not_rewrite_frozen_task(self):
        entered,release=threading.Event(),threading.Event()
        def runner(a,p,j):
            if j['request']['kind']=='execution':entered.set();release.wait(4)
            if j['request']['kind']=='question':return {'text':'Explanation from '+a['id']}
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto');approved=copy.deepcopy(r['plan'])
        self.c.controller.action(rid,dict(action='execute',planHash=approved['hash']));self.assertTrue(entered.wait(3))
        message=dict(id='q1',type='user',text='Why this experiment?',to='b')
        r=self.c.controller.action(rid,dict(action='question',message=message))
        self.assertEqual(r['status'],'running');self.assertEqual(r['experiments'][0]['plan'],approved)
        deadline=time.time()+3
        while time.time()<deadline and self.c.controller.runs[rid]['questions'][0]['status']=='running':time.sleep(.02)
        r=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(r['questions'][0]['status'],'complete')
        q=next(x for x in self.seen if x['kind']=='question');self.assertEqual(q['profile'],'restricted');self.assertEqual([a['id'] for a in q['agents']],['b'])
        self.assertIn('Do not execute, edit files',prompt_for(q['agents'][0],q))
        self.c.controller.action(rid,dict(action='moderator',moderator=[dict(text='New future constraint',to='all')]))
        release.set();r=wait(self.c,rid)
        verification=next(x for x in self.seen if x['kind']=='verification');self.assertEqual(verification['approvedPlan'],approved)
        self.assertEqual(r['experiments'][0]['plan'],approved);self.assertEqual(r['moderator'][0]['text'],'New future constraint')
        self.assertTrue(any(t.get('kind')=='question' for t in r['turns']))

    def test_question_idempotency_target_privacy_and_resume_context(self):
        self.behavior=lambda a,p,j: {'text':'PRIVATE_EXPLANATION'} if j['request']['kind']=='question' else self.output(a,p,j)
        rid=self.create();r=self.action(rid,'auto');msg=dict(id='q',text='PRIVATE_QUESTION',to='a')
        self.c.controller.action(rid,dict(action='question',message=msg))
        deadline=time.time()+3
        while time.time()<deadline and self.c.controller.runs[rid]['questions'][0]['status']=='running':time.sleep(.02)
        r=self.c.controller.action(rid,dict(action='question',message=msg));self.assertEqual(len(r['questions']),1)
        self.assertEqual(len([q for q in self.seen if q['kind']=='question']),1);self.assertFalse(r['reviews'])
        r=self.action(rid,'round');requests=[q for q in self.seen if q['kind']=='debate'][-2:]
        for q in requests:
            prompt=prompt_for(q['agents'][0],q)
            self.assertEqual('PRIVATE_QUESTION' in prompt,q['agents'][0]['id']=='a')
            self.assertEqual('PRIVATE_EXPLANATION' in prompt,q['agents'][0]['id']=='a')

    def test_failed_verification_keeps_actual_partial_result_for_next_review(self):
        def runner(a,p,j):
            if j['request']['kind']=='verification':raise CouncilError('cli_failed','Verification failed')
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto');r=self.action(rid,'execute',planHash=r['plan']['hash'])
        self.assertEqual(r['status'],'paused');self.assertEqual(r['experiments'][0]['status'],'failed')
        self.assertIn('execution',r['experiments'][0]);self.assertNotIn('verification',r['experiments'][0])
        r=self.action(rid,'next');last=self.seen[-1]
        self.assertTrue(any(t.get('kind')=='execution' for t in last['transcript']))

    def test_legacy_history_is_reference_data_without_execution_approval(self):
        self.body['history']={'independent':{'a':{'text':'OLD_A'},'b':{'text':'OLD_B'}},'turns':[dict(type='agent',id='a',text='OLD_TURN',round=3)]}
        rid=self.create();r=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(r['phase'],'debate');self.assertEqual(r['round'],4)
        with self.assertRaises(CouncilError):self.action(rid,'execute',planHash='forged')
        r=self.action(rid,'next');self.assertEqual(r['calls'],1)
        self.assertTrue(any(t['text']=='OLD_TURN' for t in self.seen[-1]['transcript']))

    def test_adaptive_focus_can_combine_approaches_without_a_forced_plan(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_evidence',proposal=None,focus=['exploration','evidence'],focusReason='Comparing ideas and available evidence')
        rid=self.create();self.action(rid,'round');r=self.action(rid,'next')
        self.assertIsNone(r['plan']);self.assertEqual(r['reviews']['a']['focus'],['exploration','evidence'])
        self.assertIn('not mutually exclusive stages',prompt_for(self.seen[-1]['agents'][0],self.seen[-1]))

    def test_explicit_independent_uses_fresh_lane_without_peer_context(self):
        rid=self.create();initial=self.action(rid,'round')['independent'].copy()
        self.action(rid,'round')
        message=dict(id='fresh-analysis',text='Reconsider the raw evidence',to='all',action='independent')
        self.c.controller.action(rid,dict(action='independent',message=message))
        deadline=time.time()+5
        while time.time()<deadline:
            r=self.c.controller.public(self.c.controller.runs[rid])
            if r['questions'][0]['status']=='complete':break
            time.sleep(.02)
        q=self.seen[-1]
        self.assertEqual(q['kind'],'independent');self.assertEqual(q['profile'],'native')
        self.assertEqual(q['transcript'],[]);self.assertEqual(q['moderator'],[])
        self.assertNotEqual(q['runId'],rid);self.assertEqual(r['independent'],initial)
        for a in q['agents']:
            self.assertNotIn('a published answer',prompt_for(a,q))
        self.assertEqual(r['turns'][-1]['action'],'independent')

    def test_explicit_review_does_not_force_independent_answers(self):
        rid=self.create();r=self.action(rid,'review')
        self.assertEqual([q['kind'] for q in self.seen],['debate','debate'])
        self.assertEqual(r['independent'],{});self.assertEqual(r['status'],'ready')
        self.assertTrue(any(t.get('id')=='a' for t in self.seen[1]['transcript']))

    def test_composer_execution_uses_selected_pair_and_stops_after_verification(self):
        rid=self.create();r=self.action(rid,'review')
        r=self.action(rid,'execute',planHash=r['plan']['hash'],executorId='b',reviewerId='a',followupReview=False)
        self.assertEqual([q['kind'] for q in self.seen[-2:]],['execution','verification'])
        self.assertEqual([q['agents'][0]['id'] for q in self.seen[-2:]],['b','a'])
        self.assertEqual(r['status'],'idle');self.assertEqual(r['experiments'][0]['status'],'reviewed')
        self.assertEqual(r['experiments'][0]['executor'],'b')

    def test_execution_rejects_invalid_or_identical_selected_members(self):
        rid=self.create();r=self.action(rid,'review')
        for executor,reviewer in [('a','a'),('missing','b'),('a','missing')]:
            with self.assertRaises(CouncilError):
                self.c.controller.action(rid,dict(action='execute',planHash=r['plan']['hash'],executorId=executor,reviewerId=reviewer))
        self.assertEqual(len(self.seen),2)

    def test_approval_mode_updates_future_calls_without_resetting_answers(self):
        rid=self.c.controller.create(self.body)['id']
        self.c.controller.action(rid,{'action':'round','claudePermissionMode':'manual'});r=wait(self.c,rid)
        self.assertEqual(len(r['independent']),2);self.assertEqual(self.seen[-1]['claudePermissionMode'],'manual')
        self.c.controller.action(rid,{'action':'next','claudePermissionMode':'auto'});r=wait(self.c,rid)
        self.assertEqual(len(r['independent']),2);self.assertEqual(self.seen[-1]['claudePermissionMode'],'auto')
        with self.assertRaises(CouncilError):self.c.controller.action(rid,{'action':'next','claudePermissionMode':'bypassPermissions'})

    def test_question_receives_separate_quoted_references(self):
        r=self.c.controller.create(self.body);rid=r['id']
        quotes=[dict(id='quote',source='Peer · previous answer',text='Reference evidence excerpt')]
        r=self.c.controller.action(rid,dict(action='question',message=dict(id='quoted-q',text='Explain this',to='a',quotes=quotes)))
        deadline=time.time()+5
        while time.time()<deadline and self.c.controller.runs[rid]['questions'][0]['status']=='running':time.sleep(.02)
        request=next(x for x in self.seen if x['kind']=='question')
        self.assertEqual(request['question'],'Explain this');self.assertEqual(request['quotedReferences'],quotes)
        self.assertIn('Reference evidence excerpt',prompt_for(request['agents'][0],request))
        self.assertEqual(self.c.controller.runs[rid]['turns'][0]['quotes'],quotes)

    def test_restart_preserves_experiments_questions_and_does_not_restart_tasks(self):
        self.behavior=lambda a,p,j:{'text':'Explanation'} if j['request']['kind']=='question' else self.output(a,p,j)
        rid=self.create();r=self.action(rid,'auto');r=self.action(rid,'execute',planHash=r['plan']['hash'])
        self.c.controller.action(rid,dict(action='question',message=dict(id='restart-q',text='Explain result',to='all')))
        deadline=time.time()+3
        while time.time()<deadline and self.c.controller.runs[rid]['questions'][0]['status']=='running':time.sleep(.02)
        before=self.c.controller.public(self.c.controller.runs[rid]);self.c.close()
        self.c=Council(self.tmp.name,runner=lambda *x:{'text':'MUST NOT RUN'},auth=lambda p:{'installed':True,'loggedIn':True})
        after=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(before['experiments'],after['experiments']);self.assertEqual(before['questions'],after['questions']);self.assertEqual(before['turns'],after['turns'])

    def test_legacy_execution_upgrade_retains_result_and_can_continue(self):
        rid=self.create();r=self.action(rid,'auto');r=self.action(rid,'execute',planHash=r['plan']['hash'])
        raw=self.c.controller.runs[rid];task=copy.deepcopy(raw['experiments'][0]);raw.pop('experiments');raw['turns']=[t for t in raw['turns'] if t['type']!='experiment'];raw['status']='executed';self.c.controller.persist(raw);self.c.close()
        self.c=Council(self.tmp.name,runner=lambda a,p,j:self.output(a,p,j),auth=lambda p:{'installed':True,'loggedIn':True})
        record=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(record['experiments'][0]['execution'],task['execution']);self.assertEqual(record['experiments'][0]['verification'],task['verification'])
        r=self.action(rid,'next');self.assertEqual(r['status'],'idle');self.assertEqual(len(r['experiments']),1)

    def test_restart_during_experiment_returns_to_review_without_reexecution(self):
        rid=self.create();r=self.action(rid,'auto');r=self.action(rid,'execute',planHash=r['plan']['hash'])
        raw=self.c.controller.runs[rid];raw['status']='running';raw['activeExperiment']=raw['experiments'][0]['id'];raw['experiments'][0]['status']='running';self.c.controller.persist(raw);self.c.close()
        called=[]
        def runner(a,p,j):called.append(j['request']['kind']);return self.output(a,p,j)
        self.c=Council(self.tmp.name,runner=runner,auth=lambda p:{'installed':True,'loggedIn':True})
        r=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(r['status'],'paused');self.assertNotIn('activeExperiment',r);self.assertFalse(r['reviews']);self.assertEqual(r['experiments'][0]['status'],'interrupted')
        self.action(rid,'next');self.assertEqual(called,['debate'])

    def test_receipts_reject_fake_nonce_and_ready_with_blockers(self):
        control={'nonce':'host'}
        for receipt in [dict(nonce='peer',decision='ready'),dict(nonce='host',decision='ready',researchStage='confirmation',nextAction='x',reviewedPlanHash='x',blockers=[dict(id='b',text='unresolved')])]:
            with self.assertRaises(ValueError):parse_receipt('<council_control>'+json.dumps(receipt)+'</council_control>',control)
    def test_persistent_controller_does_not_auto_resume_after_restart(self):
        rid=self.create();r=self.action(rid,'auto');self.c.controller.runs[rid]['status']='running';self.c.controller.persist(self.c.controller.runs[rid]);self.c.close()
        self.c=Council(self.tmp.name,runner=lambda *x:{'text':'unused'},auth=lambda p:{'installed':True,'loggedIn':True})
        r=self.c.controller.public(self.c.controller.runs[rid]);self.assertEqual(r['reason'],'interrupted');self.assertEqual(r['plan']['hash'],r['plans'][-1]['hash']);self.assertEqual(r['calls'],4)
    def test_queued_moderator_invalidates_inflight_approval_before_next_speaker(self):
        entered, release = threading.Event(), threading.Event()
        first = [True]
        def runner(a,p,j):
            if j['request']['kind']=='debate' and first[0]:
                first[0]=False;entered.set();release.wait(3)
            return self.output(a,p,j)
        self.behavior=runner
        rid=self.create();self.c.controller.action(rid,{'action':'auto'})
        self.assertTrue(entered.wait(3))
        self.c.controller.action(rid,{'action':'moderator','moderator':[dict(text='New constraint',to='all')]})
        release.set();r=wait(self.c,rid)
        self.assertEqual(r['status'],'ready');self.assertEqual(r['generation'],1)
        self.assertGreaterEqual(r['calls'],5)
        self.assertEqual([x for x in self.seen if x['kind']=='debate'][1]['moderator'][0]['text'],'New constraint')
    def test_fresh_tool_evidence_can_continue_past_previous_call_budget(self):
        self.body['budgets']={'calls':12,'seconds':60}
        counter=[0]
        def runner(a,p,j):
            if j['request']['kind']=='debate':
                counter[0]+=1
                if counter[0]>=14:return self.output(a,p,j)
                self.c.event(j,{'agentId':a['id'],'tool':{'type':'tool_result','content':'New source '+str(counter[0])}})
                return self.output(a,p,j,decision='need_evidence',blockers=[dict(id='source',text='Still investigating')])
            return self.output(a,p,j)
        self.behavior=runner;rid=self.create();r=self.action(rid,'auto')
        self.assertEqual(r['status'],'ready');self.assertGreater(r['calls'],12);self.assertGreater(r['round'],3)

    def test_permissions_are_job_bound_one_use_and_cancel_expires(self):
        j={'id':'j','request':{'kind':'independent','agents':[agent('a')]},'status':'running','events':[],'cancel':threading.Event()};self.c.jobs['j']=j
        result=[]
        t=threading.Thread(target=lambda:result.append(self.c.wait_approval(j,agent('a'),'test',{'command':'pwd'},['accept','decline'])));t.start()
        while not j.get('approvals'):time.sleep(.01)
        aid=j['approvals'][0]['id']
        with self.assertRaises(CouncilError):self.c.decide('j',aid,{'choice':'bypass'})
        self.c.decide('j',aid,{'choice':'decline'});t.join(2);self.assertEqual(result,[{'choice':'decline'}])
        with self.assertRaises(CouncilError):self.c.decide('j',aid,{'choice':'accept'})
        j['status']='complete'
    def test_legacy_prompt_stays_restricted_native_prompt_keeps_tools(self):
        request=dict(kind='independent',question='Q',agents=[agent('a')])
        self.assertIn('Research only:',prompt_for(agent('a'),request))
        self.assertNotIn('Research only:',prompt_for(agent('a'),dict(request,profile='native')))

class HumanExecutionTests(unittest.TestCase):
    setUp = DynamicTests.setUp
    tearDown = DynamicTests.tearDown
    output = DynamicTests.output
    create = DynamicTests.create
    action = DynamicTests.action
    settle_questions = DynamicTests.settle_questions
    def approval(self, r, **changes):
        view=r['executionReview']
        result=dict(token=view['token'],proposal=copy.deepcopy(view['candidate']['proposal']),
                    decisions={i['key']:'Defer upload; run locally with validated inputs only.' for i in view['issues']})
        result.update(changes)
        return result

    def blocked_plan(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_user',
            blockers=[dict(id='upload',text='Confirm permission before upload')])
        rid=self.create();r=self.action(rid,'review')
        self.behavior=None
        return rid,r

    def test_focus_keeps_candidate_and_author_objections_but_invalidates_reviews(self):
        rid,r=self.blocked_plan();old=copy.deepcopy(r['plan'])
        self.c.controller.action(rid,dict(action='question',message=dict(id='follow',text='Summarize the differences',to='all')))
        r=self.settle_questions(rid)
        self.assertEqual(r['plan']['proposal'],old['proposal']);self.assertNotEqual(r['plan']['hash'],old['hash'])
        self.assertFalse(r['reviews']);self.assertFalse(self.c.controller.ready(self.c.controller.runs[rid]))
        self.assertEqual(len(r['executionReview']['issues']),2)
        self.assertTrue(all(i['text']=='Confirm permission before upload' for i in r['executionReview']['issues']))

    def test_explicit_human_decisions_freeze_plan_and_reach_both_roles_without_fake_consensus(self):
        rid,r=self.blocked_plan();reviews=copy.deepcopy(r['reviews']);blockers=copy.deepcopy(r['blockers'])
        approval=self.approval(r);approval['proposal']['body']+='\nOnly a local smoke test; no upload.'
        r=self.action(rid,'execute',approval=approval,executorId='b',reviewerId='a',followupReview=False)
        task=r['experiments'][0];record=task['approval']
        self.assertEqual(task['status'],'reviewed');self.assertEqual(record['kind'],'human_confirmed')
        self.assertFalse(record['peerUnanimous']);self.assertTrue(record['edited'])
        self.assertEqual(record['peerReviews'],reviews);self.assertEqual(record['peerBlockers'],blockers)
        calls=[q for q in self.seen if q['kind'] in ('execution','verification')]
        self.assertEqual([q['agents'][0]['id'] for q in calls],['b','a'])
        for q in calls:
            self.assertEqual(q['approvedPlan'],task['plan']);self.assertEqual(q['executionApproval'],record)
            self.assertIn('explicit human resolutions',prompt_for(q['agents'][0],q))
        saved=json.loads((Path(self.tmp.name)/'discussions'/(rid+'.json')).read_text())
        self.assertEqual(saved['experiments'][0]['approval'],record)
        self.assertIsNone(r['executionReview']['candidate'])

    def test_every_open_issue_needs_explicit_nonempty_resolution(self):
        rid,r=self.blocked_plan();calls=r['calls']
        for decisions in [{},{r['executionReview']['issues'][0]['key']:'Local only'},
                          {i['key']:' ' for i in r['executionReview']['issues']}]:
            with self.assertRaises(CouncilError):
                self.c.controller.action(rid,dict(action='execute',approval=self.approval(r,decisions=decisions)))
        self.assertEqual(self.c.controller.runs[rid]['calls'],calls)
        self.assertFalse(self.c.controller.runs[rid].get('experiments'))

    def test_stale_confirmation_fails_after_any_new_question(self):
        rid,r=self.blocked_plan();approval=self.approval(r)
        self.c.controller.action(rid,dict(action='question',message=dict(id='changed',text='Different experiment scope',to='all')))
        self.settle_questions(rid)
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='execute',approval=approval))
        self.assertFalse(self.c.controller.runs[rid].get('experiments'))

    def test_old_focus_deleted_candidate_is_recovered_without_calls_or_consensus(self):
        rid,r=self.blocked_plan();run=self.c.controller.runs[rid];candidate=copy.deepcopy(run['plan']);run['plan']=None
        calls=run['calls'];public=self.c.controller.public(run)
        self.assertTrue(public['executionReview']['recovered']);self.assertEqual(public['executionReview']['candidate'],candidate)
        self.assertIsNone(run['plan']);self.assertEqual(run['calls'],calls);self.assertFalse(public['executionReview']['unanimous'])
        r=self.action(rid,'execute',approval=self.approval(public),followupReview=False)
        self.assertEqual(r['experiments'][0]['status'],'reviewed')

    def test_recovery_does_not_replay_an_attempted_experiment(self):
        rid,r=self.blocked_plan();run=self.c.controller.runs[rid]
        run['experiments']=[dict(id='interrupted',plan=copy.deepcopy(run['plan']),created=time.time(),status='interrupted')]
        self.assertIsNone(self.c.controller.public(run)['executionReview']['candidate'])
        run['plan']=None
        self.assertIsNone(self.c.controller.public(run)['executionReview']['candidate'])

    def test_incomplete_or_oversize_manual_plan_cannot_execute(self):
        rid,r=self.blocked_plan()
        for proposal in [{},dict(title='X',body='',acceptance=['OK']),dict(title='X',body='Scope',acceptance=[]),
                         dict(title='X',body='Scope',acceptance=['x'*4001])]:
            with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='execute',approval=self.approval(r,proposal=proposal)))
        self.assertFalse(self.c.controller.runs[rid].get('experiments'))

    def test_pending_committed_review_is_merged_before_confirmation_validation(self):
        rid,r=self.blocked_plan();run=self.c.controller.runs[rid];approval=self.approval(r)
        jid=run['jobs'][-1];job=self.c.jobs[jid]
        # Simulate a crash after job commit but before the controller merged it.
        run['turns']=[t for t in run['turns'] if t.get('jobId')!=jid]
        run['reviews'].pop('b',None);run['blockers'].pop('b',None);run['pendingJob']=jid
        approval=self.approval(self.c.controller.public(run))
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='execute',approval=approval))
        self.assertIn('b',run['reviews']);self.assertIsNone(run['pendingJob'])
        self.assertFalse(run.get('experiments'))

    def test_manual_confirmation_is_still_blocked_by_running_question(self):
        rid,r=self.blocked_plan();run=self.c.controller.runs[rid]
        run['questions']=[dict(id='q',jobId='pending',status='running')]
        public=self.c.controller.public(run)
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='execute',approval=self.approval(public)))
        self.assertFalse(run.get('experiments'))

if __name__=='__main__':unittest.main()
