import copy
import unittest
from execution_progress import unlimited, update, activity, OUTPUT_LIMIT


class ExecutionProgressTests(unittest.TestCase):
    def job(self, kind='execution', profile='native'):
        return dict(id='j',created=1,status='running',request=dict(kind=kind,profile=profile,agents=[dict(id='a',name='Claude')]),events=[],results=[])

    def event(self, job, **event):
        entry=dict(agentId='a',at=2,**event)
        update(job,entry)
        job['events'].append(entry)

    def test_unlimited_applies_only_to_native_execution_and_verification(self):
        for kind in ('execution','verification'):
            self.assertTrue(unlimited(dict(kind=kind,profile='native')))
            self.assertFalse(unlimited(dict(kind=kind,profile='restricted')))
        for kind in ('debate','question','independent','sidechat','tracking'):
            self.assertFalse(unlimited(dict(kind=kind,profile='native')))

    def test_streamed_command_output_is_visible_before_completion_and_not_duplicated(self):
        j=self.job()
        self.event(j,type='item/started',tool=dict(type='commandExecution',id='cmd',command='python -u train.py'))
        self.event(j,type='command_output',toolId='cmd',output='epoch=1 loss=0.5\n')
        state=j['executionProgress']['a']
        self.assertEqual(state['active']['cmd']['status'],'running');self.assertIn('epoch=1',state['output'])
        self.event(j,type='item/completed',tool=dict(type='commandExecution',id='cmd',aggregatedOutput='epoch=1 loss=0.5\n',exitCode=0))
        self.assertFalse(state['active']);self.assertEqual(state['output'].count('epoch=1'),1)
        self.assertEqual(state['recent'][-1]['status'],'complete')

    def test_claude_results_keep_tool_identity_failure_and_public_update(self):
        j=self.job('verification')
        self.event(j,type='assistant',tool=dict(type='tool_use',id='test',name='Bash',input=dict(command='pytest')))
        self.event(j,type='public_message',text='Checking saved checkpoints')
        self.event(j,type='user',tool=dict(type='tool_result',tool_use_id='test',content=[dict(type='text',text='1 FAILED')],is_error=True))
        state=j['executionProgress']['a']
        self.assertEqual(state['recent'][-1]['name'],'Bash');self.assertEqual(state['recent'][-1]['detail'],'pytest')
        self.assertEqual(state['recent'][-1]['status'],'failed');self.assertIn('1 FAILED',state['output'])
        self.assertEqual(state['message'],'Checking saved checkpoints')

    def test_activity_buffers_stay_bounded_and_ignore_reasoning(self):
        j=self.job()
        self.event(j,type='assistant',tool=dict(type='thinking',thinking='SECRET_REASONING'))
        self.assertNotIn('executionProgress',j)
        for n in range(80):
            self.event(j,type='assistant',tool=dict(type='tool_use',id=str(n),name='Bash',input=dict(command='long command')))
            self.event(j,type='command_output',toolId=str(n),output=str(n)+'x'*2000)
        state=j['executionProgress']['a']
        self.assertEqual(len(state['output']),OUTPUT_LIMIT);self.assertTrue(state['outputTruncated'])
        self.assertLessEqual(len(state['active']),16);self.assertLessEqual(len(state['recent']),16)
        self.assertLessEqual(len(state['streamedTools']),32)
        self.assertNotIn('SECRET_REASONING',str(state))

    def test_old_failed_job_activity_is_recovered_without_mutating_history(self):
        j=self.job();j['status']='failed'
        j['events']=[dict(agentId='a',at=1,type='assistant',tool=dict(type='tool_use',id='c',name='Bash',input=dict(command='train'))),dict(agentId='a',at=2,type='user',tool=dict(type='tool_result',tool_use_id='c',content='saved checkpoint'))]
        before=copy.deepcopy(j);view=activity(j)
        self.assertIn('saved checkpoint',view['executionProgress']['a']['output']);self.assertFalse(view['unlimitedDuration'])
        self.assertEqual(j,before)

    def test_terminal_call_does_not_claim_an_unfinished_tool_completed(self):
        j=self.job()
        self.event(j,type='assistant',tool=dict(type='tool_use',id='still-running',name='Bash',input=dict(command='long training')))
        j['status']='failed';view=activity(j)
        self.assertFalse(view['executionProgress']['a']['active'])
        self.assertEqual(view['executionProgress']['a']['recent'][-1]['status'],'unfinished')
        self.assertEqual(j['executionProgress']['a']['recent'][-1]['status'],'running')

    def test_terminal_activity_keeps_end_times_and_agent_failures(self):
        j=self.job();j.update(status='failed',updated=900,finishedAt=700,failures=[dict(agentId='a',at=690,code='timeout')],results=[dict(agentId='b',completedAt=680)])
        view=activity(j)
        self.assertEqual(view['finishedAt'],700);self.assertEqual(view['updated'],900)
        self.assertEqual(view['failures'][0]['at'],690);self.assertEqual(view['results'][0]['completedAt'],680)

    def test_native_policy_survives_event_truncation_and_remains_minimal(self):
        import json
        import tempfile
        from pathlib import Path
        from bridge import Council
        with tempfile.TemporaryDirectory() as root:
            c=Council(root,runner=lambda *a:{'text':'unused'},auth=lambda p:{'installed':True,'loggedIn':True})
            try:
                j=self.job('verification');j['request']['codexPermissionMode']='full'
                c.event(j,dict(type='native_session',agentId='a',policy=dict(approvalPolicy='never',sandbox=dict(type='dangerFullAccess'),cwd='PRIVATE_DIRECTORY',instructionSources=['PRIVATE_SOURCE'])))
                for n in range(260):c.event(j,dict(type='fixture_activity',agentId='a'))
                self.assertFalse(any(e['type']=='native_session' for e in j['events']))
                saved=json.loads((Path(root)/'jobs/j.json').read_text());view=activity(saved)
                self.assertEqual(view['nativePolicies']['a']['approvalPolicy'],'never')
                self.assertEqual(view['nativePolicies']['a']['sandboxType'],'dangerFullAccess')
                self.assertNotIn('PRIVATE_',str(view['nativePolicies']))
                self.assertEqual(c.public(j)['codexPermissionMode'],'full')
                self.assertEqual(view['codexPermissionMode'],'full')
            finally:c.close()

    def test_historical_native_policy_is_recovered_without_rewriting_job(self):
        j=self.job('verification');j['events']=[dict(type='native_session',agentId='a',at=2,policy=dict(approvalPolicy='on-request',sandbox=dict(type='readOnly')))]
        before=copy.deepcopy(j);view=activity(j)
        self.assertEqual(view['nativePolicies']['a']['sandboxType'],'readOnly');self.assertEqual(j,before)
        self.assertEqual(activity(self.job())['nativePolicies'],{})

    def test_question_activity_does_not_cache_tool_output(self):
        j=self.job('question');self.event(j,type='user',tool=dict(type='tool_result',tool_use_id='read',content='private document'))
        self.assertNotIn('executionProgress',j)
