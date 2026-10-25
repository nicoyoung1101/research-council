import copy
import json
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import execution_flow as flow
from bridge import CouncilError, prompt_for
import test_dynamic as fixtures
from test_dynamic import wait


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.task=dict(id='task',plan=dict(hash='hash',proposal=dict(acceptance=['File','Numbers'])),approval={})
        self.c=flow.control(self.task,'verification')
        self.receipt={k:self.c[k] for k in ('nonce','taskId','planHash')}
        self.receipt.update(state='done',checkpoint='Final check',summary='Inspected exact output',nextAction='',
                            checks=[dict(index=i,status='pass',evidence='file.csv, independently recomputed') for i in range(2)])
    def parse(self,changes=None,role=None):
        r=copy.deepcopy(self.receipt);r.update(changes or {})
        c=dict(self.c,**({'role':role} if role else {}))
        return flow.parse('Readable answer\n<council_execution>'+json.dumps(r)+'</council_execution>',c,self.task['plan'])
    def test_final_requires_every_criterion_once_with_evidence(self):
        text,r=self.parse();self.assertEqual(text,'Readable answer');self.assertEqual(r['state'],'done')
        for checks in ([],self.receipt['checks'][:1],[self.receipt['checks'][0]]*2,
                       [dict(index=0,status='pass',evidence=''),self.receipt['checks'][1]],
                       [dict(index=0,status='fail',evidence='Mismatch'),self.receipt['checks'][1]],
                       [dict(index=0,status='unverified',evidence='Pending'),self.receipt['checks'][1]],
                       [dict(index=True,status='pass',evidence='Invalid'),self.receipt['checks'][1]],
                       [dict(index=2,status='pass',evidence='Invalid')]):
            with self.subTest(checks=checks),self.assertRaises(ValueError):self.parse(dict(checks=checks))
    def test_wrong_identity_role_and_missing_handoff_are_rejected(self):
        for k in ('nonce','taskId','planHash'):
            with self.subTest(key=k),self.assertRaises(ValueError):self.parse({k:'another'})
        for state,role in [('continue','execution'),('review_required','verification'),('anything','verification')]:
            with self.subTest(state=state),self.assertRaises(ValueError):self.parse(dict(state=state),role)
        for text in ('Answer only','<council_execution>[]</council_execution>','<council_execution>{bad}</council_execution>'):
            with self.subTest(text=text),self.assertRaises(ValueError):flow.parse(text,self.c,self.task['plan'])
    def test_checkpoint_can_cover_subset_but_needs_named_next_step(self):
        _,r=self.parse(dict(state='continue',checks=[],nextAction='Run frozen evaluation'))
        self.assertEqual(r['state'],'continue')
        with self.assertRaises(ValueError):self.parse(dict(state='continue',checks=[],nextAction=''))
    def test_recovery_deduplicates_results_and_does_not_skip_blocked_role(self):
        for state in ('done','needs_user','continue'):
            task=copy.deepcopy(self.task);r=dict(self.receipt,state=state)
            job=dict(id='j',request=dict(executionControl=self.c),results=[dict(agentId='verifier',executionReceipt=r)])
            flow.record(task,job);flow.record(task,job)
            self.assertEqual(len(task['stages']),1)
            self.assertEqual(task['workflowNext'],'verification' if state=='needs_user' else 'execution')
        task=copy.deepcopy(self.task);job['results'][0]['executionReceipt']['planHash']='other'
        flow.record(task,job);self.assertFalse(task.get('stages'));self.assertIn('identity',task['handoffIssue'])
    def test_recovered_final_result_never_restarts_executor(self):
        task=copy.deepcopy(self.task);task['stages']=[dict(role='verification',state='done')]
        controller=SimpleNamespace(c=SimpleNamespace(jobs={}),invoke=lambda *args:self.fail('Extra model invocation'))
        flow.run(controller,{},task,{}, {})


class StagedWorkflowTests(unittest.TestCase):
    setUp=fixtures.DynamicTests.setUp
    tearDown=fixtures.DynamicTests.tearDown
    output=fixtures.DynamicTests.output
    create=fixtures.DynamicTests.create
    action=fixtures.DynamicTests.action
    approval=fixtures.HumanExecutionTests.approval
    def ready(self):
        rid=self.create();r=self.action(rid,'review');return rid,r
    def answer(self,a,p,j,state=None):
        q=j['request']
        if not q.get('executionControl'):return self.output(a,p,j)
        c=q['executionControl'];n=len(c['previous']);role=c['role']
        state=state or (('review_required' if n==0 else 'done') if role=='execution' else ('continue' if n==1 else 'done'))
        receipt={k:c[k] for k in ('nonce','taskId','planHash')}
        receipt.update(state=state,checkpoint='Checkpoint '+str(n),summary='Actual checked fixture '+str(n),nextAction='Remaining frozen work',checks=[dict(index=i,status='pass',evidence='Independent fixture evidence') for i,_ in enumerate(q['approvedPlan']['proposal']['acceptance'])])
        if c.get('preflight'):
            receipt['state']='needs_user' if state=='needs_user' else 'continue'
            receipt['issueChecks']=[dict(key=i['key'],status='resolved',evidence='Independent preflight evidence') for i in c['preflightIssues']]
        return dict(text='Observed stage '+str(n)+'\n<council_execution>'+json.dumps(receipt)+'</council_execution>')
    def start(self,rid,r):
        return self.action(rid,'execute',executionFlow='staged',approval=self.approval(r),executorId='b',reviewerId='a')
    def test_gate_review_then_continuation_then_final_no_extra_discussion(self):
        rid,r=self.ready();before=len(self.seen);self.behavior=self.answer;r=self.start(rid,r)
        task=r['experiments'][-1];calls=self.seen[before:]
        self.assertEqual([x['kind'] for x in calls],['execution','verification','execution','verification'])
        self.assertEqual([x['agents'][0]['id'] for x in calls],['b','a','b','a'])
        self.assertEqual(task['status'],'completed');self.assertEqual(len(task['stages']),4)
        self.assertFalse(r.get('activeExperiment'));self.assertEqual(r['status'],'idle')
        for q in calls:
            self.assertEqual(q['approvedPlan'],task['plan'])
            self.assertEqual(q['agents'][0]['effort'],'default')
            self.assertIn('Do not use sleep, polling',prompt_for(q['agents'][0],q))
        self.assertEqual([x['state'] for x in task['stages']],['review_required','continue','done','done'])
        saved=json.loads((Path(self.tmp.name)/'discussions'/(rid+'.json')).read_text())
        self.assertEqual(saved['experiments'][-1]['stages'],task['stages'])
    def test_plain_answer_cannot_mark_experiment_complete_or_auto_retry(self):
        rid,r=self.ready();before=len(self.seen);r=self.start(rid,r);task=r['experiments'][-1]
        self.assertEqual(len(self.seen),before+1);self.assertEqual(task['status'],'needs_decision')
        self.assertEqual(task['error']['code'],'execution_handoff_invalid')
        self.assertIn('Missing execution',task['error']['detail'])
    def test_user_gate_requires_explicit_decision_and_resumes_same_role_plan(self):
        rid,r=self.ready();self.behavior=lambda a,p,j:self.answer(a,p,j,'needs_user');r=self.start(rid,r);task=r['experiments'][-1]
        self.assertEqual(task['workflowNext'],'execution');self.assertEqual(task['status'],'needs_decision')
        body=dict(action='resume_experiment',requestId='same-resume',taskId=task['id'],planHash=task['plan']['hash'],executionFlow='staged',text='continue')
        with self.assertRaises(CouncilError):self.c.controller.action(rid,body)
        self.behavior=self.answer;body['decision']='Keep frozen settings; use verified output and continue the remaining approved work.'
        self.c.controller.action(rid,body);r=wait(self.c,rid);new=r['experiments'][-1]
        self.assertEqual(new['status'],'completed');self.assertEqual(new['plan'],task['plan'])
        calls=[q for q in self.seen if q.get('experimentId')==new['id']]
        self.assertEqual(calls[0]['kind'],'execution');self.assertEqual(calls[0]['executionControl']['decision'],body['decision'])
        count=len(self.seen);self.c.controller.action(rid,body);self.assertEqual(len(self.seen),count)
    def test_verifier_failed_gate_returns_to_verifier_after_user_decision(self):
        rid,r=self.ready();self.behavior=lambda a,p,j:self.answer(a,p,j,'needs_user' if j['request']['kind']=='verification' else None)
        r=self.start(rid,r);task=r['experiments'][-1];self.assertEqual(task['workflowNext'],'verification')
        self.behavior=self.answer;before=len(self.seen)
        r=self.action(rid,'resume_experiment',requestId='verifier-resume',taskId=task['id'],planHash=task['plan']['hash'],executionFlow='staged',decision='Recheck the corrected approved fixture.',text='continue')
        self.assertEqual(self.seen[before]['kind'],'verification');self.assertEqual(r['experiments'][-1]['status'],'completed')
    def test_paused_committed_handoff_recovers_without_repeating_executor(self):
        rid,r=self.ready();original=self.c.controller.invoke
        def invoke(*args,**kw):
            result=original(*args,**kw)
            if args[1]=='execution':
                self.c.controller.runs[rid]['pauseRequested']=True
                raise CouncilError('paused','Pause after durable result')
            return result
        self.c.controller.invoke=invoke;self.behavior=self.answer;r=self.start(rid,r)
        task=r['experiments'][-1];self.assertEqual(task['status'],'interrupted');self.assertEqual(len(task['stages']),1)
        self.c.controller.invoke=original;before=len(self.seen)
        r=self.action(rid,'resume_experiment',requestId='pause-resume',taskId=task['id'],planHash=task['plan']['hash'],executionFlow='staged',text='continue')
        self.assertEqual(self.seen[before]['kind'],'verification');self.assertEqual(r['experiments'][-1]['status'],'completed')
        self.assertEqual(len(r['experiments'][-1]['stages']),4)
    def test_pause_after_blocked_receipt_still_requires_decision_on_resume(self):
        rid,r=self.ready();original=self.c.controller.invoke
        def invoke(*args,**kw):
            original(*args,**kw)
            self.c.controller.runs[rid]['pauseRequested']=True
            raise CouncilError('paused','Pause after blocked receipt')
        self.c.controller.invoke=invoke;self.behavior=lambda a,p,j:self.answer(a,p,j,'needs_user')
        r=self.start(rid,r);task=r['experiments'][-1]
        self.assertEqual(task['status'],'interrupted');self.assertTrue(r['resumableExperiment']['requiresDecision'])
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='resume_experiment',requestId='blocked-pause',taskId=task['id'],planHash=task['plan']['hash'],executionFlow='staged',text='continue'))
        self.c.controller.invoke=original

    def test_repeated_unchanged_handoffs_stop_without_endless_calls(self):
        rid,r=self.ready()
        def stalled(a,p,j):
            q=j['request'];c=q.get('executionControl')
            if not c:return self.output(a,p,j)
            receipt={k:c[k] for k in ('nonce','taskId','planHash')}
            receipt.update(state='review_required' if c['role']=='execution' else 'continue',checkpoint='Same',summary='Same',nextAction='Same',checks=[])
            return dict(text='<council_execution>'+json.dumps(receipt)+'</council_execution>')
        self.behavior=stalled;before=len(self.seen);r=self.start(rid,r)
        self.assertEqual(r['experiments'][-1]['status'],'needs_decision');self.assertEqual(r['reason'],'execution_stalled')
        self.assertEqual(len(self.seen)-before,5)
    def test_legacy_returned_task_can_be_checked_and_continued_without_new_plan(self):
        rid,r=self.ready();r=self.action(rid,'execute',approval=self.approval(r),followupReview=False)
        old=r['experiments'][-1];self.assertEqual(old['status'],'reviewed');self.assertEqual(r['resumableExperiment']['id'],old['id'])
        self.assertTrue(r['resumableExperiment']['requiresDecision'])
        with self.assertRaises(CouncilError):self.c.controller.action(rid,dict(action='resume_experiment',requestId='legacy',taskId=old['id'],planHash=old['plan']['hash'],executionFlow='staged',text='continue'))
        self.behavior=self.answer;before=len(self.seen)
        r=self.action(rid,'resume_experiment',requestId='legacy',taskId=old['id'],planHash=old['plan']['hash'],executionFlow='staged',text='continue',decision='Independently check existing outputs and continue only remaining approved work.')
        self.assertEqual(r['experiments'][-1]['plan'],old['plan']);self.assertEqual(r['experiments'][-1]['status'],'completed')
        self.assertEqual(self.seen[before]['kind'],'verification')
        self.assertEqual(len(self.seen)-before,1)  # No executor replay when the verifier can finish from existing evidence.

class AutomaticRecoveryTests(unittest.TestCase):
    setUp=fixtures.DynamicTests.setUp
    tearDown=fixtures.DynamicTests.tearDown
    output=fixtures.DynamicTests.output
    create=fixtures.DynamicTests.create
    action=fixtures.DynamicTests.action
    approval=fixtures.HumanExecutionTests.approval
    ready=StagedWorkflowTests.ready
    answer=StagedWorkflowTests.answer
    start=StagedWorkflowTests.start

    def test_unreviewed_plan_needs_no_extra_instructions_and_verifies_first(self):
        rid,r=self.ready();live=self.c.controller.runs[rid];live['reviews']={};r=self.c.controller.public(live)
        self.assertTrue(r['executionReview']['issues']);self.behavior=self.answer;before=len(self.seen)
        r=self.action(rid,'execute',executionFlow='staged',allowHelperRepair=True,approval=self.approval(r,decisions={},issuePolicy='review_first'))
        task=r['experiments'][-1];calls=self.seen[before:]
        self.assertEqual([q['kind'] for q in calls],['verification','execution','verification'])
        self.assertTrue(calls[0]['executionControl']['preflight']);self.assertFalse(task['preflightPending'])
        self.assertEqual(task['status'],'completed');self.assertFalse(task['approval']['peerUnanimous'])
        self.assertTrue(all(i['deferredToVerifier'] for i in task['approval']['issues']))
        self.assertEqual([q['agents'][0]['effort'] for q in calls],['default']*3)

    def test_missing_issue_evidence_cannot_start_executor(self):
        rid,r=self.ready();self.c.controller.runs[rid]['reviews']={};r=self.c.controller.public(self.c.controller.runs[rid])
        def missing(a,p,j):
            out=self.answer(a,p,j);return dict(text=out['text'].replace('"resolved"','"needs_user"'))
        self.behavior=missing;before=len(self.seen)
        r=self.action(rid,'execute',executionFlow='staged',approval=self.approval(r,decisions={},issuePolicy='review_first'))
        self.assertEqual(r['experiments'][-1]['status'],'needs_decision');self.assertEqual(len(self.seen)-before,1)
        self.assertEqual(self.seen[-1]['kind'],'verification')

    def test_scientific_issue_still_blocks_after_automatic_preflight(self):
        self.behavior=lambda a,p,j:self.output(a,p,j,decision='need_user',blockers=[dict(id='permission',text='External upload permission missing')])
        rid=self.create();r=self.action(rid,'review');self.behavior=lambda a,p,j:self.answer(a,p,j,'needs_user')
        before=len(self.seen);r=self.action(rid,'execute',executionFlow='staged',allowHelperRepair=True,approval=self.approval(r,decisions={},issuePolicy='review_first'))
        self.assertEqual(len(self.seen)-before,1);self.assertEqual(r['reason'],'execution_needs_decision')
        self.assertTrue(r['experiments'][-1]['preflightPending'])

    def test_legacy_resume_can_verify_without_repeated_human_directive(self):
        rid,r=self.ready();r=self.action(rid,'execute',approval=self.approval(r),followupReview=False);old=r['experiments'][-1]
        self.behavior=self.answer;before=len(self.seen)
        body=dict(requestId='verify-existing',taskId=old['id'],planHash=old['plan']['hash'],executionFlow='staged',continuationMode='verify_existing',allowHelperRepair=True,decision='',text='continue')
        r=self.action(rid,'resume_experiment',**body);task=r['experiments'][-1]
        self.assertEqual(task['plan'],old['plan']);self.assertEqual(task['executor'],old['executor']);self.assertEqual(task['reviewer'],old['reviewer'])
        self.assertEqual(len(self.seen)-before,1);self.assertEqual(self.seen[-1]['kind'],'verification')
        self.assertEqual(task['status'],'completed');self.assertEqual(task['approval']['helperRecovery']['maxAttempts'],2)
        count=len(self.seen);self.c.controller.action(rid,dict(action='resume_experiment',**body));self.assertEqual(len(self.seen),count)

    def test_auxiliary_repair_is_bounded_and_returns_only_to_original_verifier(self):
        rid,r=self.ready();helper=Path(self.c.controller.runs[rid]['workspace'])/'audit.py';helper.write_text('original = True')
        original=helper.read_bytes();before=len(self.seen)
        def response(a,p,j):
            c=j['request'].get('executionControl')
            if c and c['role']=='verification':
                receipt={k:c[k] for k in ('nonce','taskId','planHash')}
                receipt.update(state='repair',checkpoint='Path parsing',summary='Annotation captured in filename',nextAction='Fix helper only',checks=[],repair=dict(target=str(helper),problem='Incorrect filename parsing',change='Resolve structured paths without annotation',UNTRUSTED='drop'))
                return dict(text='<council_execution>'+json.dumps(receipt)+'</council_execution>')
            return self.answer(a,p,j)
        self.behavior=response;r=self.action(rid,'execute',executionFlow='staged',allowHelperRepair=True,approval=self.approval(r))
        task=r['experiments'][-1];calls=self.seen[before:]
        self.assertEqual([q['kind'] for q in calls],['execution','verification','verification','verification'])
        self.assertEqual(task['repairAttempts'],2);self.assertEqual(task['status'],'needs_decision')
        self.assertNotIn('UNTRUSTED',calls[-1]['executionControl']['repairAuthorization'])
        self.assertEqual(calls[-1]['executionControl']['repairAuthorization']['attempt'],2);self.assertEqual(helper.read_bytes(),original)
        count=len(task['stages']);flow.recover(task,self.c.jobs);self.assertEqual(len(task['stages']),count)
        r=self.action(rid,'resume_experiment',requestId='repair-resume',taskId=task['id'],planHash=task['plan']['hash'],executionFlow='staged',continuationMode='verify_existing',allowHelperRepair=True,text='continue')
        self.assertEqual(r['experiments'][-1]['repairAttempts'],2);self.assertEqual(r['experiments'][-1]['status'],'needs_decision')

    def test_terminal_persistence_freezes_time_across_later_saves(self):
        from unittest.mock import patch
        job=dict(id='clock-fixture',status='failed',created=100)
        with patch('bridge.time.time',return_value=700):self.c.persist(job)
        with patch('bridge.time.time',return_value=900):self.c.persist(job)
        self.assertEqual(job['finishedAt'],700);self.assertEqual(job['updated'],900)

    def test_repair_decline_does_not_retry(self):
        rid,r=self.ready();self.behavior=lambda a,p,j:self.answer(a,p,j,'repair' if j['request']['kind']=='verification' else None)
        before=len(self.seen);r=self.action(rid,'execute',executionFlow='staged',allowHelperRepair=False,approval=self.approval(r))
        self.assertEqual(len(self.seen)-before,2);self.assertEqual(r['experiments'][-1]['status'],'needs_decision')

class RepairPathTests(unittest.TestCase):
    def test_repair_requires_existing_workspace_file_and_exact_role(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            helper=Path(root)/'audit.py';helper.touch();external=Path(outside)/'audit.py';external.touch();(Path(root)/'escape.py').symlink_to(external)
            task=dict(id='t',plan=dict(hash='h',proposal=dict(acceptance=['one'])),workspace=root,approval=dict(helperRecovery=flow.recovery_policy(True)))
            c=flow.control(task,'verification')
            r={k:c[k] for k in ('nonce','taskId','planHash')};r.update(state='repair',checkpoint='Parser',summary='Bad filename',nextAction='Correct parser',checks=[],repair=dict(target=str(helper),problem='Annotation',change='Parse safely'))
            def parse(value,receipt):return flow.parse('<council_execution>'+json.dumps(receipt)+'</council_execution>',value,task['plan'])
            self.assertIn('originalSha256',parse(c,r)[1]['repair'])
            for path in [external,Path(root)/'escape.py',Path(root)/'missing.py',Path(root)/'folder']:
                bad=copy.deepcopy(r);bad['repair']['target']=str(path)
                with self.subTest(path=path),self.assertRaises(ValueError):parse(c,bad)
            for override in [dict(role='execution'),dict(helperRecovery=None),dict(repairAttempts=2)]:
                with self.subTest(override=override),self.assertRaises(ValueError):parse(dict(c,**override),r)


class StagedMonitorTests(unittest.TestCase):
    import test_experiment_monitor as monitor_fixtures
    setUp=monitor_fixtures.ManagedExperimentTests.setUp
    tearDown=monitor_fixtures.ManagedExperimentTests.tearDown
    spec=monitor_fixtures.ManagedExperimentTests.spec
    block=monitor_fixtures.ManagedExperimentTests.block
    def run_monitored_stage(self,code=None):
        self.job['request']['approvedPlan']['proposal']=dict(acceptance=['Saved DONE output'])
        self.job['request']['executionControl']=c=flow.control(dict(id='experiment',plan=self.job['request']['approvedPlan']), 'execution')
        receipt={k:c[k] for k in ('nonce','taskId','planHash')}
        receipt.update(state='done',checkpoint='Program output',summary='Checked saved output',nextAction='',checks=[])
        self.handler=lambda a,p,j:self.block(self.spec(**({'code':code} if code else {}))) if len(self.calls)==1 else dict(text='Observed output\n<council_execution>'+json.dumps(receipt)+'</council_execution>')
        return self.c.answer(self.job,self.agent,'')
    def test_staged_monitor_waits_in_program_then_accepts_bound_receipt(self):
        result=self.run_monitored_stage()
        self.assertEqual(len(self.calls),2);self.assertEqual(result['executionReceipt']['state'],'done')
        self.assertTrue(all(a['model']=='chosen-model' and a['effort']=='high' for a,p in self.calls))
        self.assertIn('"exitCode": 0',self.calls[-1][1])
    def test_known_process_failure_cannot_be_overridden_by_success_receipt(self):
        result=self.run_monitored_stage("print('Traceback fixture');raise SystemExit(7)")
        self.assertNotIn('executionReceipt',result);self.assertIn('did not succeed',result['executionReceiptError'])
        self.assertEqual(len(self.calls),2)

if __name__=='__main__':unittest.main()
