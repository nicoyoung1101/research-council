import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from bridge import Council, CouncilError, capability, cli_env, command
from gemini_adapter import model_list, parse, prepare, check_settings, verify_guard, cached_output, without_tool_metadata
from gemini_guard import handle, decide, PROOF_FILE, public_url
from tests.test_bridge import agent, request, signed_in, wait


class GeminiAdapterTests(unittest.TestCase):
    def test_command_pins_available_gemini_and_has_no_coding_tools(self):
        with tempfile.TemporaryDirectory() as folder, patch('pathlib.Path.home',return_value=Path(folder)), patch('bridge.locate',return_value='/bin/agy'),patch('bridge.capability',return_value={'models':[{'id':'gemini-fixture-medium'}]}):
            a=agent(provider='gemini');args=command(a,folder)
            config=(Path(folder)/'.gemini/config/agents/research-council-text-v1/agent.md').read_text()
            self.assertIn('stream-json',args)
            self.assertIn('--input-format',args)
            self.assertIn('gemini-fixture-medium',args)
            self.assertIn('--disable-slash-commands',args)
            self.assertNotIn('--dangerously-skip-permissions',args)
            self.assertIn('tools: ["finish"]',config)
            self.assertIn('subagent: false',config)
            self.assertIn('mcpServers: []',config)

    def test_web_allowlist_has_only_search_and_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            text=prepare(folder,True,home=folder).read_text()
            self.assertIn('tools: ["search_web", "read_url_content", "view_file", "finish"]',text)
            self.assertNotIn('run_command,',text)

    def test_no_api_key_or_gateway_fallback(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':'secret','GOOGLE_API_KEY':'secret','GOOGLE_GENAI_USE_VERTEXAI':'true','AGY_LLM_GATEWAY_URL':'https://elsewhere','AGY_ACCOUNT':'other'}):
            env=cli_env('gemini','/tmp/isolated')
            for key in ('GEMINI_API_KEY','GOOGLE_API_KEY','GOOGLE_GENAI_USE_VERTEXAI','AGY_LLM_GATEWAY_URL','AGY_ACCOUNT'):
                self.assertNotIn(key,env)
            self.assertEqual(env['AGY_CLI_DISABLE_AUTO_UPDATE'],'true')

    def test_status_uses_official_metadata_not_credentials_or_paid_probe(self):
        with patch('bridge.locate',return_value='/bin/agy'),patch('bridge.subprocess.run') as run:
            from subprocess import CompletedProcess
            run.side_effect=[CompletedProcess([],0,'1.4.2',''),CompletedProcess([],0,'gemini-fixture-medium\tGemini Test\nclaude-other\tOther\n','')]
            info=capability('gemini')
            self.assertTrue(info['loggedIn'])
            self.assertTrue(info['authVerified'])
            self.assertEqual(info['models'],[{'id':'gemini-fixture-medium','name':'Gemini Test'}])
            self.assertEqual(run.call_args.args[0],['/bin/agy','models'])
        self.assertEqual(model_list('diagnostic\n'),[])

    def test_credit_overage_and_api_provider_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'.gemini/antigravity-cli';p.mkdir(parents=True)
            for settings in ({'useG1Credits':True},{'modelProvider':'gemini'}):
                (p/'settings.json').write_text(json.dumps(settings))
                with self.assertRaises(ValueError):check_settings(folder)

    def test_unsupported_effort_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as folder,patch('bridge.locate',return_value='/bin/agy'):
            a=agent(provider='gemini');a['effort']='high'
            with self.assertRaises(CouncilError):command(a,folder)

    def test_gemini_provider_does_not_route_custom_ids_to_other_models(self):
        with tempfile.TemporaryDirectory() as folder, patch('pathlib.Path.home',return_value=Path(folder)), patch('bridge.locate',return_value='/bin/agy'):
            a=agent(provider='gemini');a['model']='claude-other'
            with self.assertRaises(CouncilError):command(a,folder)

    def test_tool_events_keep_outcomes_without_echoing_user_or_thoughts(self):
        self.assertEqual(parse({'event':'step_update','step_update':{'step_type':'user_input','text_delta':'PRIVATE'}}),{})
        self.assertEqual(parse({'event':'step_update','step_update':{'step_type':'thought','text_delta':'PRIVATE'}}),{})
        tool=parse({'event':'step_update','step_update':{'step_type':'tool','step_index':3,'state':'ACTIVE','tool_name':'search_web','tool_info':{'parameters':{'query':'test'}}}})['tool']
        self.assertEqual(tool['name'],'search_web')
        done=parse({'event':'step_update','step_update':{'step_type':'tool','step_index':3,'state':'DONE','tool_info':{'error':{'message':'403'}}}})['tool']
        self.assertEqual(done['tool_use_id'],'3')
        self.assertEqual(done['error']['message'],'403')

    def run_stream(self,events,stderr='',proof=True):
        with tempfile.TemporaryDirectory() as folder:
            c=Council(folder,auth=signed_in)
            try:
                for event in events:
                    event.setdefault('conversation_id','fixture-conversation')
                script='import sys,json;raw=json.loads(sys.stdin.read());assert raw["event"]=="user";events='+repr(events)+';[print(json.dumps(e)) for e in events];sys.stderr.write('+repr(stderr)+')'
                # Use the real hook implementation in the fake child process.
                def fake_command(a,workspace):
                    prepare(workspace, home=folder)
                    start="import sys;sys.path.insert(0,"+repr(str(Path(__file__).resolve().parents[1]))+");from gemini_guard import handle;handle('start',{'workspacePaths':["+repr(workspace)+"],'conversationId':'fixture-conversation'},"+repr(workspace)+");"
                    code=start+script if proof else script
                    if stderr:code+=';sys.exit(1)'
                    return [sys.executable,'-c',code]
                body=request();body['agents']=[agent(provider='gemini')]
                with patch('bridge.command',side_effect=fake_command):
                    return wait(c,c.start(body))
            finally:c.close()

    def test_real_runner_uses_final_response_without_duplicate_chunks(self):
        done=self.run_stream([{'event':'init','init':{'model':'gemini-fixture','tools':[]}},
          {'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'中文'}},
          {'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'回答'}},
          {'event':'result','result':{'status':'SUCCESS','response':'中文回答','usage':{'output_tokens':4}}}])
        r=done['results'][0]
        self.assertEqual(done['status'],'complete')
        self.assertEqual(r['text'],'中文回答')
        self.assertEqual(r['effectiveModel'],'gemini-fixture')
        self.assertEqual(r['usage']['output_tokens'],4)

    def test_partial_or_nonterminal_output_is_not_success(self):
        done=self.run_stream([{'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'Partial'}},
           {'event':'result','result':{'status':'WAITING','response':'Partial'}}])
        self.assertEqual(done['status'],'failed')
        self.assertEqual(done['results'],[])

    def test_missing_terminal_result_cannot_publish_partial_answer(self):
        done=self.run_stream([{'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'Partial'}}])
        self.assertEqual(done['status'],'failed')

    def test_broad_catalog_without_guard_proof_stops_the_call(self):
        done=self.run_stream([{'event':'init','init':{'tools':['run_command']}},
          {'event':'result','result':{'status':'SUCCESS','response':'Not accepted'}}],proof=False)
        self.assertEqual(done['status'],'failed')
        self.assertEqual(done['error']['code'],'unsafe_cli_config',done.get('error'))

    def test_verification_failure_is_actionable_without_saving_auth_url(self):
        done=self.run_stream([], 'Eligibility check failed: Verify your account https://accounts.google.com/sensitive-flow')
        self.assertEqual(done['error']['code'],'account_verification_required')
        self.assertNotIn('sensitive-flow',json.dumps(done))


    def test_catalog_is_not_the_effective_model_tool_set(self):
        done=self.run_stream([{'event':'init','init':{'tools':['run_command','view_file','finish']}},
          {'event':'result','result':{'status':'SUCCESS','response':'Accepted only with a verified execution hook'}}])
        self.assertEqual(done['status'],'complete')

    def test_missing_init_cannot_bypass_guard(self):
        done=self.run_stream([{'event':'result','result':{'status':'SUCCESS','response':'No init'}}])
        self.assertEqual(done['error']['code'],'unsafe_cli_config',done.get('error'))

    def test_policy_denies_all_unlisted_tools_and_never_autoapproves_coding(self):
        for name in ('view_file','run_command','write_to_file','invoke_subagent','ask_permission','call_mcp_tool','schedule','unknown_future_tool'):
            self.assertEqual(decide({'name':name},['finish'])['decision'],'deny')
        self.assertEqual(decide({'name':'finish'},['finish'])['decision'],'allow')
        self.assertEqual(decide({'name':'search_web'},['finish'])['decision'],'deny')
        self.assertEqual(decide({'name':'search_web'},['search_web','finish'])['decision'],'auto_approve')

    def test_proof_is_bound_to_workspace_nonce_conversation_and_web_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            prepare(folder, home=folder)
            handle('start',{'workspacePaths':[folder],'conversationId':'one'},folder)
            verify_guard(folder,'one',timeout=0)
            for conversation,web in [('two',False),('one',True)]:
                with self.assertRaises(ValueError):verify_guard(folder,conversation,web,timeout=0)
            data=json.loads((Path(folder)/PROOF_FILE).read_text());data['nonce']='stale'
            (Path(folder)/PROOF_FILE).write_text(json.dumps(data))
            with self.assertRaises(ValueError):verify_guard(folder,'one',timeout=0)
            denied=handle('tool',{'workspacePaths':['/different'],'toolCall':{'name':'finish'}},folder)
            self.assertEqual(denied['decision'],'deny')

    def test_registration_preserves_other_hooks_and_noops_outside_app(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'.gemini/config';config.mkdir(parents=True)
            hooks=config/'hooks.json';hooks.write_text(json.dumps({'existing':{'enabled':False}}))
            prepare(folder, home=folder)
            data=json.loads(hooks.read_text());self.assertEqual(data['existing'],{'enabled':False})
            entry=next(v for k,v in data.items() if k.startswith('research-council-'))
            env=os.environ.copy();env.pop('RC_GEMINI_GUARD_ROOT',None)
            run=subprocess.run(entry['SessionStart'][0]['command'],shell=True,input='{}',text=True,capture_output=True,env=env)
            self.assertEqual(run.returncode,0);self.assertEqual(json.loads(run.stdout),{})

    def test_parallel_first_use_is_atomic_and_edited_agents_are_not_overwritten(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as folder:
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths=list(pool.map(lambda _:prepare(folder,home=folder),range(8)))
            self.assertEqual(len(set(paths)),1)
            paths[0].write_text('user changes')
            with self.assertRaises(ValueError):prepare(folder,home=folder)
            self.assertEqual(paths[0].read_text(),'user changes')


    def test_web_cache_access_is_bound_to_this_completed_tool_and_conversation(self):
        from gemini_guard import cache_file
        conversation='11111111-1111-1111-1111-111111111111'
        other='22222222-2222-2222-2222-222222222222'
        with tempfile.TemporaryDirectory() as folder, patch('pathlib.Path.home',return_value=Path(folder)):
            prepare(folder,True,home=folder)
            payload={'workspacePaths':[folder],'conversationId':conversation,'stepIdx':2,'toolCall':{'name':'read_url_content'}}
            cache=cache_file(conversation,2);cache.parent.mkdir(parents=True);cache.write_text('Public web content')
            view={**payload,'toolCall':{'name':'view_file','args':{'AbsolutePath':str(cache)}}}
            self.assertEqual(handle('tool',view,folder)['decision'],'deny')
            handle('post',{**payload,'error':'network failed'},folder)
            self.assertEqual(handle('tool',view,folder)['decision'],'deny')
            handle('post',payload,folder)
            self.assertEqual(cached_output(folder,{'conversation_id':conversation,'step_update':{'step_index':2,'state':'DONE','tool_name':'read_url_content'}}),'Public web content')
            self.assertIsNone(cached_output(folder,{'conversation_id':other,'step_update':{'step_index':2,'state':'DONE','tool_name':'read_url_content'}}))
            self.assertEqual(handle('tool',view,folder)['decision'],'auto_approve')
            self.assertEqual(handle('tool',{**view,'conversationId':other},folder)['decision'],'deny')
            outside=Path(folder)/'private.txt';outside.write_text('Not authorized')
            cache.unlink();cache.symlink_to(outside)
            self.assertEqual(handle('tool',view,folder)['decision'],'deny')
            for path in (outside,cache.parent/'transcript.jsonl'):
                view['toolCall']['args']['AbsolutePath']=str(path)
                self.assertEqual(handle('tool',view,folder)['decision'],'deny')


    def test_web_fetch_cannot_request_local_files_or_private_hosts(self):
        for url in ('file:///etc/passwd','http://localhost/test','http://127.0.0.1/','http://169.254.169.254/','http://10.0.0.1/','https://user:pass@example.com/','http://private.local/'):
            self.assertFalse(public_url(url),url)
        self.assertTrue(public_url('https://spec.commonmark.org/'))
        self.assertTrue(public_url('https://example.com/'))


    def test_finish_metadata_is_removed_without_changing_research_json(self):
        metadata='{"toolAction":"Completing","toolSummary":"Complete"}\n'
        text=metadata+'The source title is Example Domain.\n'
        self.assertEqual(without_tool_metadata(text),'The source title is Example Domain.\n')
        legitimate='{"newClaims":[],"snapshots":[]}\n'
        self.assertEqual(without_tool_metadata(legitimate),legitimate)
