import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from bridge import Council, CouncilError, atomic_json, prompt_for
from experiment_monitor import Monitor, parse, validate


class ManagedExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.calls=[];self.handler=None
        def runner(a,p,j):
            self.calls.append((a.copy(),p))
            return self.handler(a,p,j)
        self.c=Council(self.root/'data',runner=runner,auth=lambda p:dict(installed=True,loggedIn=True))
        self.c.wait_approval=lambda *args:dict(choice='accept')
        self.agent=dict(id='claude',name='Claude',provider='claude',enabled=True,role='debater',model='chosen-model',effort='high')
        self.job=dict(id='job',status='running',created=time.time(),events=[],results=[],cancel=threading.Event(),
            request=dict(kind='execution',profile='native',sessionId='s',runId='run',experimentId='experiment',
                         question='Run approved fixture',agents=[self.agent],approvedPlan=dict(hash='frozen-plan'),executionApproval=dict(kind='human_confirmed')))
        self.c.jobs['job']=self.job
    def tearDown(self):
        self.c.close();self.tmp.cleanup()
    def spec(self,code="import time;print('epoch=1',flush=True);time.sleep(.5);print('DONE',flush=True)",**extra):
        return dict(dict(action='start',key='fixture-step',command=[sys.executable,'-u','-c',code],cwd=str(self.root),
                         logPath=str(self.root/'train.log'),completionMarker='DONE',failurePatterns=['Traceback'],expectedSeconds=10),**extra)
    def block(self,spec):return dict(text='Handing long work to bridge.\n<council_monitor>'+json.dumps(spec)+'</council_monitor>')
    def test_healthy_long_process_calls_model_exactly_twice(self):
        spec=self.spec();self.handler=lambda a,p,j:self.block(spec) if len(self.calls)==1 else dict(text='Verified saved DONE output')
        result=self.c.answer(self.job,self.agent,'')
        self.assertEqual(result['text'],'Verified saved DONE output');self.assertEqual(len(self.calls),2)
        self.assertTrue(all(a['model']=='chosen-model' and a['effort']=='high' for a,p in self.calls))
        self.assertIn('"exitCode": 0',self.calls[-1][1]);self.assertIn('epoch=1',self.calls[-1][1])
        self.assertEqual(list(self.job['managedExperiments'].values())[0]['status'],'complete')
    def test_launch_needs_plan_and_exact_command_approval(self):
        touched=self.root/'should-not-exist';spec=self.spec(code='from pathlib import Path;Path('+repr(str(touched))+').touch()')
        self.job['request'].pop('executionApproval')
        with self.assertRaises(CouncilError):self.c.experiment_monitor.launch(spec,self.job,self.agent)
        self.job['request']['executionApproval']=dict(kind='human_confirmed')
        asked=[];self.c.wait_approval=lambda *args:(asked.append(args) or dict(choice='cancel'))
        with self.assertRaises(CouncilError):self.c.experiment_monitor.launch(spec,self.job,self.agent)
        self.assertFalse(touched.exists());self.assertEqual(asked[0][3]['command'],spec['command'])
    def test_expected_duration_wakes_once_and_does_not_kill(self):
        entry=self.c.experiment_monitor.launch(self.spec(expectedSeconds=.1),self.job,self.agent)
        first=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
        self.assertEqual(first['reason'],'expected_duration_exceeded');self.assertNotIn(first['status'],('failed','cancelled'))
        final=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
        self.assertEqual(final['reason'],'finished');self.assertEqual(final['exitCode'],0)
        self.assertEqual(entry['notified'].count('expected_duration_exceeded'),1)
    def test_errors_nonzero_exit_and_missing_marker_are_distinct(self):
        for index,(code,marker) in enumerate([("print('Traceback fixture');raise SystemExit(7)",'DONE'),("print('wrong marker')",'DONE')]):
            spec=self.spec(code=code,key='step'+str(index),completionMarker=marker)
            entry=self.c.experiment_monitor.launch(spec,self.job,self.agent)
            result=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
            if result['status']=='running':result=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['exitCode'],7 if index==0 else 0)
    def test_failure_marker_outside_log_tail_is_not_lost(self):
        entry=self.c.experiment_monitor.launch(self.spec(code="print('Traceback earlier');print('x\\n'*200);print('DONE')"),self.job,self.agent)
        result=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
        if result['status']=='running':result=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
        self.assertEqual(result['matchedErrors'],['Traceback']);self.assertLessEqual(len(result['lastLines']),30)
    def test_cancel_terminates_program_owned_process_and_saves_receipt(self):
        entry=self.c.experiment_monitor.launch(self.spec(code="import time;print('started',flush=True);time.sleep(30)"),self.job,self.agent)
        self.c.cancel('job')
        with self.assertRaises(CouncilError):self.c.experiment_monitor.wait(entry,self.job,self.agent)
        self.assertIn(self.c.experiment_monitor.summary(entry)['status'],('cancelled','interrupted'))
    def test_recover_manager_and_idempotent_launch_do_not_duplicate_command(self):
        spec=self.spec();entry=self.c.experiment_monitor.launch(spec,self.job,self.agent)
        other=Monitor(self.c,atomic_json,CouncilError)
        duplicate=other.launch(spec,self.job,self.agent)
        self.assertEqual(entry['id'],duplicate['id']);self.assertEqual(len(other.records),1)
        result=other.wait(duplicate,self.job,self.agent,interval=.02)
        self.assertEqual(result['exitCode'],0);self.assertEqual((self.root/'train.log').read_text().count('DONE'),1)
    def test_foreign_monitor_and_changed_step_key_are_rejected(self):
        entry=self.c.experiment_monitor.launch(self.spec(),self.job,self.agent)
        with self.assertRaises(CouncilError):self.c.experiment_monitor.launch(dict(action='wait',monitorId=entry['id']),self.job,dict(self.agent,id='other'))
        with self.assertRaises(CouncilError):self.c.experiment_monitor.launch(self.spec(code="print('different')"),self.job,self.agent)
    def test_nohup_and_invalid_specs_are_rejected(self):
        for change in [dict(command=['nohup','python3']),dict(command='python3 train.py'),dict(expectedSeconds=-1),dict(expectedSeconds=float('nan'))]:
            with self.assertRaises(ValueError):validate(self.spec(**change))
    def test_execution_prompt_uses_program_monitor_and_short_summary(self):
        prompt=prompt_for(self.agent,self.job['request'])
        self.assertIn('<council_monitor>',prompt);self.assertIn('Do not launch background processes yourself',prompt)
        self.assertNotIn('Prefer short polling waits',prompt)
    def test_pid_disappearance_does_not_report_success_or_kill_unrelated_pid(self):
        entry=self.c.experiment_monitor.launch(self.spec(),self.job,self.agent)
        with patch('experiment_monitor.identity',return_value='different process'),patch('experiment_monitor.os.killpg') as kill:
            self.assertEqual(self.c.experiment_monitor.summary(entry)['status'],'interrupted')
            self.c.experiment_monitor.stop(entry);kill.assert_not_called()

    def test_preexisting_log_marker_is_not_evidence_for_new_run(self):
        (self.root/'train.log').write_text('DONE\n')
        entry=self.c.experiment_monitor.launch(self.spec(code="print('new run no result')"),self.job,self.agent)
        view=self.c.experiment_monitor.wait(entry,self.job,self.agent,interval=.02)
        self.assertEqual(view['status'],'failed');self.assertFalse(view['completionMarkerFound'])

    def test_finished_receipt_cannot_trigger_unbounded_model_loop(self):
        def handle(a,p,j):
            if len(self.calls)==1:return self.block(self.spec())
            return self.block(dict(action='wait',monitorId=j['lastMonitorWake']['monitorId']))
        self.handler=handle
        with self.assertRaises(CouncilError) as caught:self.c.answer(self.job,self.agent,'')
        self.assertEqual(caught.exception.code,'invalid_monitor');self.assertEqual(len(self.calls),2)

    def test_controller_runs_independent_verifier_only_after_executor_finishes(self):
        reviewer=dict(self.agent,id='codex',provider='codex')
        def handle(a,p,j):
            q=j['request']
            if q['kind']=='debate':
                plan=q['control']['plan']
                control=dict(nonce=q['control']['nonce'],decision='ready',reviewedPlanHash=plan['hash'] if plan else 'proposed',
                    proposal=None if plan else dict(title='Fixture',body='Run fixture process',acceptance=['DONE exists']),blockers=[],nextAction='Execute')
                return dict(text='Review\n<council_control>'+json.dumps(control)+'</council_control>')
            if q['kind']=='execution':
                if not j.get('lastMonitorWake'):return self.block(self.spec())
                return dict(text='Executor checked DONE')
            if q['kind']=='verification':
                self.assertIn('DONE',(self.root/'train.log').read_text())
                return dict(text='Independent verifier checked DONE')
            return dict(text='Independent fixture answer')
        self.handler=handle
        rid=self.c.controller.create(dict(requestId='create',sessionId='pipeline',question='Fixture',roster=[self.agent,reviewer],profile='native',packet={}))['id']
        def action(body):
            self.c.controller.action(rid,body)
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                r=self.c.controller.public(self.c.controller.runs[rid])
                if r['status']!='running':return r
                time.sleep(.02)
            self.fail('Controller did not settle')
        r=action(dict(action='review'));self.assertEqual(r['status'],'ready')
        before=len(self.calls)
        r=action(dict(action='execute',planHash=r['plan']['hash'],followupReview=False))
        self.assertEqual(r['experiments'][0]['status'],'reviewed')
        self.assertEqual([a['id'] for a,p in self.calls[before:]],['claude','claude','codex'])

    def test_previous_worker_cleanup_cannot_disable_new_auto_dispatch(self):
        rid=self.c.controller.create(dict(requestId='generation',sessionId='generation',question='Fixture',roster=[self.agent,dict(self.agent,id='codex',provider='codex')],profile='native',packet={}))['id']
        r=self.c.controller.runs[rid];r['workerGeneration']=1
        def next_worker(*args,**kw):
            r.update(workerGeneration=2,auto=True,resumeAction='auto',_remainingSeconds=999)
        with patch.object(self.c.controller,'one',side_effect=next_worker):
            self.c.controller.work(r,'next',1)
        self.assertTrue(r['auto']);self.assertEqual(r['resumeAction'],'auto');self.assertEqual(r['_remainingSeconds'],999)
