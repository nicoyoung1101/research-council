import copy
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest

from bridge import Council, CouncilError, validate_request
from side_context import Reader, prepare, MAX_FULL


def agent(provider='codex'):
    return dict(id='side-a', name='Side', role='reviewer', provider=provider, model='default', effort='default', rules='', tools={'webSearch': True})


class SideSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.project=self.root/'project';self.project.mkdir()
        (self.project/'plan.md').write_text('Research plan\nThe teacher uses six sensors.\nNext: verify calibration.\n',encoding='utf-8')
        self.c=Council(self.root/'data',runner=lambda a,p,j:{'text':'A focused answer'},auth=lambda p:{'installed':True,'loggedIn':True})
        self.state=dict(sessions=[dict(id='main',question='Research topic',workspace=str(self.project),contextIds=['attached'],shownTurns=[
            dict(type='user',id='q1',text='OLDER_HOST_DETAIL'),
            dict(type='agent',id='claude',kind='debate',round=2,text='PEER_CALIBRATION_DETAIL\nThis is still a claim, not verified evidence.')],
            editedMarkdown='ACCEPTED_NOTES',live={},subChats=[dict(id='private-side',messages=[dict(text='OTHER_SIDE_SECRET')])])],
            library=[dict(id='attached',name='paper.md',text='ATTACHED_ORIGINAL'),dict(id='not-attached',name='other.md',text='UNRELATED_LIBRARY_SECRET')])
        self.c.save_state(dict(revision=0,state=self.state))
        self.body=dict(kind='sidechat',sessionId='side-test',question='Explain calibration',agents=[agent()],packet={},
                       sideContext=dict(discussionId='main',localFiles=True,fullDiscussion=False,roots=[]))

    def tearDown(self):
        self.c.close();self.tmp.cleanup()

    def done(self,body=None):
        j=self.c.start(body or self.body);deadline=time.time()+4
        while time.time()<deadline:
            result=self.c.public(self.c.jobs[j['id']])
            if result['status'] in ('complete','cancelled','failed'):
                return result
            time.sleep(.01)
        self.fail('Side job did not finish')

    def read_request(self,prompt,specs):
        nonce=re.search(r'<council_read nonce="([a-f0-9]+)">',prompt)[1]
        return {'text':'<council_read nonce="'+nonce+'">'+json.dumps(specs)+'</council_read>'}

    def reader(self):
        return Reader(prepare(self.c,self.body,CouncilError))

    def test_snapshot_includes_only_this_discussion_and_attached_sources(self):
        snapshot=prepare(self.c,self.body,CouncilError);joined=json.dumps(snapshot)
        for text in ['OLDER_HOST_DETAIL','PEER_CALIBRATION_DETAIL','ACCEPTED_NOTES','ATTACHED_ORIGINAL']:
            self.assertIn(text,joined)
        self.assertNotIn('OTHER_SIDE_SECRET',joined);self.assertNotIn('UNRELATED_LIBRARY_SECRET',joined)
        self.assertEqual(snapshot['roots'],[str(self.project)])

    def test_lazy_model_requests_reads_then_answers_with_actual_sources(self):
        prompts=[]
        def runner(a,p,j):
            prompts.append(p)
            if len(prompts)==1:
                return self.read_request(p,[dict(op='search_discussion',query='CALIBRATION'),dict(op='read_file',source='R1/plan.md',start=2,count=1)])
            self.assertIn('The teacher uses six sensors.',p)
            return {'text':'The plan uses six sensors [R1/plan.md L2–2].','usage':{'input_tokens':10,'output_tokens':4}}
        self.c.runner=runner;r=self.done()
        self.assertEqual(r['status'],'complete');answer=r['results'][0]
        self.assertEqual(answer['modelCalls'],2);self.assertEqual(len(answer['retrievalUsage']),2)
        read=next(x for x in answer['sourceReads'] if x['op']=='read_file')
        self.assertTrue(read['ok']);self.assertEqual(read['start'],2);self.assertEqual(read['end'],2)
        self.assertEqual(len(read['sha256']),64);self.assertIn('2: The teacher',read['text'])
        self.assertNotIn('sideSourceIndex',r)
        self.assertEqual((self.project/'plan.md').read_text(),'Research plan\nThe teacher uses six sensors.\nNext: verify calibration.\n')

    def test_same_source_access_protocol_works_for_every_provider(self):
        for provider in ('claude','codex','gemini'):
            calls=[]
            def runner(a,p,j):
                calls.append(p)
                return self.read_request(p,[dict(op='read_file',source='A0001')]) if len(calls)==1 else {'text':'Explained from attached original'}
            self.c.runner=runner;body=copy.deepcopy(self.body);body['agents']=[agent(provider)];body['sessionId']=provider
            r=self.done(body);self.assertEqual(r['status'],'complete');self.assertEqual(r['results'][0]['modelCalls'],2)
            self.assertIn('ATTACHED_ORIGINAL',calls[-1])

    def test_full_discussion_is_explicit_and_size_limited_before_calling(self):
        self.body['sideContext']['fullDiscussion']=True
        r=self.done();self.assertEqual(r['status'],'complete')
        full=next(x for x in r['sourceReads'] if x['op']=='full_discussion');self.assertIn('OLDER_HOST_DETAIL',full['text'])
        self.c.state['sessions'][0]['shownTurns'].append(dict(type='agent',id='x',text='x'*(MAX_FULL+1)))
        with self.assertRaises(CouncilError) as e:self.c.start(self.body|{'sessionId':'too-big'})
        self.assertEqual(e.exception.code,'context_too_large')
        self.body['sideContext']['fullDiscussion']=False
        self.assertTrue(prepare(self.c,self.body,CouncilError)['sources'])

    def test_scope_disabled_means_no_project_or_attached_sources(self):
        self.body['sideContext']['localFiles']=False;snapshot=prepare(self.c,self.body,CouncilError)
        self.assertEqual(snapshot['roots'],[]);self.assertNotIn('ATTACHED_ORIGINAL',json.dumps(snapshot))
        read=Reader(snapshot).call(dict(op='read_file',source='R1/plan.md'))
        self.assertFalse(read['ok'])

    def test_extra_directories_and_missing_source_discussion(self):
        extra=self.root/'extra';extra.mkdir();self.body['sideContext']['roots']=[str(extra)]
        self.assertEqual(prepare(self.c,self.body,CouncilError)['roots'],[str(self.project),str(extra)])
        self.body['sideContext']['discussionId']='other'
        with self.assertRaises(CouncilError):prepare(self.c,self.body,CouncilError)

    def test_path_traversal_absolute_hidden_and_secret_files_are_denied(self):
        reader=self.reader()
        for path in ['R1/../outside.md','/etc/passwd','R2/plan.md','R1/.env','R1/.git/config.json','R1/credentials.json','R1/key.pem','R1/plan.md/../plan.md']:
            with self.subTest(path=path):self.assertFalse(reader.call(dict(op='read_file',source=path))['ok'])
        self.assertTrue(reader.call(dict(op='read_file',source='R1/plan.md'))['ok'])

    def test_symlink_file_and_directory_escape_are_denied(self):
        outside=self.root/'outside';outside.mkdir();(outside/'private.md').write_text('OUTSIDE_SECRET')
        (self.project/'linked.md').symlink_to(outside/'private.md');(self.project/'linked').symlink_to(outside,target_is_directory=True)
        reader=self.reader()
        for path in ['R1/linked.md','R1/linked/private.md']:
            self.assertFalse(reader.call(dict(op='read_file',source=path))['ok'])
        search=reader.call(dict(op='search_files',query='OUTSIDE_SECRET'))
        self.assertEqual(search['matches'],[])

    def test_symlink_replacing_scope_root_is_denied(self):
        snapshot=prepare(self.c,self.body,CouncilError);self.project.rename(self.root/'old')
        self.project.symlink_to(self.root/'old',target_is_directory=True)
        self.assertFalse(Reader(snapshot).call(dict(op='read_file',source='R1/plan.md'))['ok'])
        self.assertFalse(Reader(snapshot).call(dict(op='search_files',query=''))['ok'])

    def test_search_snippets_and_line_read_are_labelled(self):
        reader=self.reader();result=reader.call(dict(op='search_discussion',query='CALIBRATION'))
        self.assertEqual(len(result['matches']),1);source=result['matches'][0]['source']
        r=reader.call(dict(op='read_discussion',source=source,start=2,count=1))
        self.assertEqual(r['start'],2);self.assertIn('still a claim',r['text'])
        self.assertTrue(reader.call(dict(op='search_files',query='teacher'))['matches'])
        self.assertFalse(reader.call(dict(op='read_discussion',source='A0001'))['ok'])

    def test_large_binary_and_non_regular_sources_are_not_read(self):
        (self.project/'binary.txt').write_bytes(b'\x00abc');(self.project/'huge.txt').write_bytes(b'a'*2000001)
        reader=self.reader()
        for path in ['R1/binary.txt','R1/huge.txt']:
            self.assertFalse(reader.call(dict(op='read_file',source=path))['ok'])
        import os
        os.mkfifo(self.project/'pipe.txt')
        self.assertFalse(reader.call(dict(op='read_file',source='R1/pipe.txt'))['ok'])

    def test_unknown_write_operation_cannot_modify_files(self):
        reader=self.reader();r=reader.call(dict(op='write_file',source='R1/plan.md',text='CHANGED'))
        self.assertFalse(r['ok']);self.assertNotIn('CHANGED',(self.project/'plan.md').read_text())

    def test_lookup_rounds_are_bounded_and_no_protocol_leaks_into_answer(self):
        self.c.runner=lambda a,p,j:self.read_request(p,[dict(op='search_discussion',query='calibration')])
        r=self.done();self.assertEqual(r['status'],'failed');self.assertEqual(r['error']['code'],'budget_reached')
        self.assertEqual(r['modelCalls'],5);self.assertEqual(r['results'],[])

    def test_cancel_during_lookup_does_not_start_another_model_call(self):
        entered=threading.Event();calls=[]
        def runner(a,p,j):
            calls.append(p);entered.set();j['cancel'].wait(2)
            return self.read_request(p,[dict(op='read_file',source='R1/plan.md')])
        self.c.runner=runner;j=self.c.start(self.body);self.assertTrue(entered.wait(2));self.c.cancel(j['id'])
        deadline=time.time()+2
        while self.c.jobs[j['id']]['status']=='running' and time.time()<deadline:time.sleep(.01)
        self.assertEqual(self.c.jobs[j['id']]['status'],'cancelled');self.assertEqual(len(calls),1)

    def test_validation_keeps_native_cli_disabled_and_scope_side_only(self):
        for changes in [dict(kind='question'),dict(profile='native'),dict(sideContext=dict(discussionId='main',fullDiscussion='yes')),dict(sideContext=dict(discussionId='main',roots=['relative']))]:
            with self.assertRaises(CouncilError):validate_request(self.body|changes)
        self.body['sideContext']['roots']=['/']
        with self.assertRaises(CouncilError):prepare(self.c,self.body,CouncilError)

    def test_canonical_main_answers_include_results_not_yet_saved_by_ui(self):
        self.c.runner=lambda a,p,j:{'text':'CANONICAL_UNSEEN_IN_SAVED_UI '+a['id']}
        roster=[dict(agent(),id=key,role='debater',enabled=True) for key in ('a','b')]
        run=self.c.controller.create(dict(requestId='main-run',sessionId='main',question='Canonical topic',roster=roster,profile='native',packet={},
                    initialInstructions=[dict(type='user',id='initial',text='INITIAL_MAIN_INSTRUCTION',to='all')]))
        self.c.state['sessions'][0]['live']={'councilId':run['id']}
        self.c.controller.action(run['id'],{'action':'round'})
        deadline=time.time()+2
        while self.c.controller.runs[run['id']]['status']=='running' and time.time()<deadline:time.sleep(.01)
        snapshot=prepare(self.c,self.body,CouncilError)
        self.assertIn('CANONICAL_UNSEEN_IN_SAVED_UI',json.dumps(snapshot))
        self.assertIn('INITIAL_MAIN_INSTRUCTION',json.dumps(snapshot))
        self.assertNotIn('OTHER_SIDE_SECRET',json.dumps(snapshot))

    def test_source_receipts_persist_across_service_restart(self):
        calls=[]
        def runner(a,p,j):
            calls.append(p)
            return self.read_request(p,[dict(op='read_file',source='R1/plan.md')]) if len(calls)==1 else {'text':'Checked','usage':{'input_tokens':20,'output_tokens':3}}
        self.c.runner=runner;r=self.done();self.assertEqual(r['status'],'complete')
        self.c.close();self.c=Council(self.root/'data',runner=runner,auth=lambda p:{'installed':True,'loggedIn':True})
        loaded=self.c.public(self.c.jobs[r['id']])
        self.assertEqual(loaded['results'][0]['sourceReads'],r['results'][0]['sourceReads'])
        self.assertNotIn('sideSourceIndex',loaded)

    def test_retrieval_calls_accumulate_usage_without_changing_latest_context(self):
        calls=[]
        def runner(a,p,j):
            calls.append(p)
            result=self.read_request(p,[dict(op='read_file',source='R1/plan.md')]) if len(calls)==1 else {'text':'Checked'}
            result.update(usage={'input_tokens':20,'output_tokens':3},context={'usedTokens':23})
            return result
        self.c.runner=runner;answer=self.done()['results'][0]
        self.assertEqual(answer['usage'],{'input_tokens':40,'output_tokens':6})
        self.assertEqual(answer['context'],{'usedTokens':23})

    def test_total_retrieval_time_budget_stops_further_calls(self):
        self.c.timeout=.03;calls=[]
        def runner(a,p,j):
            calls.append(p);time.sleep(.06)
            return self.read_request(p,[dict(op='read_file',source='R1/plan.md')])
        self.c.runner=runner;r=self.done()
        self.assertEqual(r['status'],'failed');self.assertEqual(r['error']['code'],'timeout')
        self.assertEqual(len(calls),1)

    def test_snapshot_does_not_follow_later_main_discussion_edits(self):
        snapshot=prepare(self.c,self.body,CouncilError)
        self.c.state['sessions'][0]['shownTurns'].append(dict(type='agent',text='LATER_MAIN_MESSAGE'))
        self.assertNotIn('LATER_MAIN_MESSAGE',json.dumps(snapshot))
        r=Reader(snapshot).call(dict(op='search_discussion',query='LATER_MAIN_MESSAGE'));self.assertEqual(r['matches'],[])


if __name__=='__main__':unittest.main()
