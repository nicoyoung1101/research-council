import unittest
from unittest.mock import patch
from native_cli import codex, claude, NativeError, run, permission_options


class FakeWire:
    def __init__(self, events, choices=None):
        self.events=iter(events);self.sent=[];self.record=[];self.choices=choices or [];self.asked=[]
    def send(self,x):self.sent.append(x)
    def receive(self):return next(self.events)
    def event(self,**x):self.record.append(x)
    def approval(self,m,p,c):
        self.asked.append((m,p,c));return self.choices.pop(0)


class NativeProtocolTests(unittest.TestCase):
    def test_cancellation_closes_real_native_process(self):
        import os, sys, tempfile, threading, time
        from types import SimpleNamespace
        from native_cli import Wire
        council=SimpleNamespace(timeout=10,lock=threading.RLock(),active={})
        job={'id':'cancel-test','cancel':threading.Event()}
        with tempfile.TemporaryDirectory() as directory:
            wire=Wire(council,{'id':'a'},job,[sys.executable,'-u','-c',"import time; print('{}',flush=True); time.sleep(20)"],directory,os.environ.copy())
            try:
                self.assertEqual(wire.receive(),{})
                self.assertIsNone(wire.proc.poll())
                job['cancel'].set()
                with self.assertRaises(NativeError) as caught:wire.receive()
                self.assertEqual(caught.exception.code,'cancelled')
            finally:
                wire.close()
            self.assertIsNotNone(wire.proc.poll())
            self.assertFalse(council.active)

    def test_native_experiment_wire_has_no_deadline_but_remains_cancellable(self):
        import os,sys,tempfile,threading,time
        from types import SimpleNamespace
        from native_cli import Wire
        council=SimpleNamespace(timeout=.01,lock=threading.RLock(),active={})
        for kind in ('execution','verification'):
            job=dict(id=kind,cancel=threading.Event(),request=dict(kind=kind,profile='native'))
            with tempfile.TemporaryDirectory() as directory:
                wire=Wire(council,dict(id='a'),job,[sys.executable,'-u','-c',"import time; time.sleep(.1); print('{}',flush=True); time.sleep(10)"],directory,os.environ.copy())
                try:
                    self.assertIsNone(wire.deadline);self.assertEqual(wire.receive(),{})
                    job['cancel'].set()
                    with self.assertRaises(NativeError) as caught:wire.receive()
                    self.assertEqual(caught.exception.code,'cancelled')
                finally:wire.close()
                self.assertIsNotNone(wire.proc.poll())

    def test_native_question_still_enforces_its_generation_deadline(self):
        import os,sys,tempfile,threading
        from types import SimpleNamespace
        from native_cli import Wire
        council=SimpleNamespace(timeout=.01,lock=threading.RLock(),active={})
        job=dict(id='q',cancel=threading.Event(),request=dict(kind='question',profile='native'))
        with tempfile.TemporaryDirectory() as directory:
            wire=Wire(council,dict(id='a'),job,[sys.executable,'-c','import time; time.sleep(10)'],directory,os.environ.copy())
            try:
                with self.assertRaises(NativeError) as caught:wire.receive()
                self.assertEqual(caught.exception.code,'timeout')
            finally:wire.close()

    def test_codex_command_delta_is_forwarded_without_reasoning_events(self):
        w=self.codex_wire([dict(method='item/commandExecution/outputDelta',params=dict(itemId='cmd',delta='epoch=3 loss=.2')),dict(method='item/reasoning/textDelta',params=dict(delta='HIDDEN'))])
        codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertTrue(any(x.get('type')=='command_output' and x.get('output')=='epoch=3 loss=.2' for x in w.record))
        self.assertNotIn('HIDDEN',str(w.record))

    def codex_wire(self, middle, choices=None, status='completed'):
        return FakeWire([{'id':1,'result':{}},{'id':2,'result':{'thread':{'id':'own-thread'},'model':'native-model','approvalPolicy':'on-request'}},{'id':3,'result':{'turn':{'id':'turn'}}},*middle,{'method':'item/completed','params':{'item':{'id':'message','type':'agentMessage','text':'Verified result'}}},{'method':'turn/completed','params':{'turn':{'id':'turn','status':status}}}],choices)
    def test_codex_exact_resume_and_command_permission(self):
        w=self.codex_wire([{'id':99,'method':'item/commandExecution/requestApproval','params':{'command':'pwd','availableDecisions':['accept','decline']}}],[{'choice':'decline'}]);saved=[]
        r=codex(w,'Prompt',{'id':'own-thread'},saved.append,{},'/tmp')
        self.assertTrue(w.sent[2]['params']['excludeTurns'])
        self.assertEqual(r['text'],'Verified result');self.assertEqual(w.sent[2]['method'],'thread/resume');self.assertEqual(w.sent[2]['params']['threadId'],'own-thread');self.assertEqual(w.sent[-1],{'id':99,'result':{'decision':'decline'}});self.assertEqual(saved,['own-thread'])
    def test_codex_selected_access_applies_to_fresh_and_resumed_threads_and_turn(self):
        for mode,policy,sandbox,thread in [('full','never','dangerFullAccess',{}),('full','never','dangerFullAccess',{'id':'same'}),('read-only','on-request','readOnly',{'id':'same'})]:
            with self.subTest(mode=mode,thread=thread):
                events=[{'id':1,'result':{}},{'id':2,'result':{'thread':{'id':'same'},'model':'selected-model','approvalPolicy':policy,'sandbox':{'type':sandbox}}},{'id':3,'result':{'turn':{'id':'turn'}}},{'method':'item/completed','params':{'item':{'id':'m','type':'agentMessage','text':'Answer'}}},{'method':'turn/completed','params':{'turn':{'id':'turn','status':'completed'}}}]
                w=FakeWire(events);codex(w,'P',thread,lambda x:None,{'model':'selected-model','effort':'high'},'/tmp',access=mode)
                setup=w.sent[2]['params'];turn=w.sent[3]['params']
                self.assertEqual(setup['sandbox'],'danger-full-access' if mode=='full' else 'read-only')
                self.assertEqual(setup['approvalPolicy'],policy)
                self.assertEqual(turn['sandboxPolicy'],{'type':sandbox});self.assertEqual(turn['approvalPolicy'],policy)
                self.assertEqual(setup['model'],'selected-model');self.assertEqual(turn['effort'],'high')

    def test_codex_rejected_permission_mode_stops_before_sending_prompt(self):
        w=self.codex_wire([])
        with self.assertRaises(NativeError) as caught:codex(w,'PRIVATE PROMPT',{},lambda x:None,{},'/tmp',access='full')
        self.assertEqual(caught.exception.code,'codex_permission_unavailable')
        self.assertFalse(any(m.get('method')=='turn/start' for m in w.sent))

    def test_codex_unspecified_access_preserves_local_configuration(self):
        w=self.codex_wire([]);codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertNotIn('sandbox',w.sent[2]['params']);self.assertNotIn('approvalPolicy',w.sent[2]['params'])
        self.assertNotIn('sandboxPolicy',w.sent[3]['params'])

    def test_codex_permissions_grants_only_requested_scope(self):
        p={'permissions':{'network':{'enabled':True}}}
        w=self.codex_wire([{'id':50,'method':'item/permissions/requestApproval','params':p}],[{'choice':'accept'}]);codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertEqual(w.sent[-1]['result'],{'permissions':p['permissions'],'scope':'turn'})
    def test_codex_question_and_mcp_elicitation(self):
        events=[{'id':10,'method':'item/tool/requestUserInput','params':{'questions':[{'id':'q','question':'Path?'}]}},{'id':11,'method':'mcpServer/elicitation/request','params':{'requestedSchema':{'type':'object'}}}]
        w=self.codex_wire(events,[{'choice':'submit','answers':{'q':'/tmp/test'}},{'choice':'decline'}]);codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertIn({'id':10,'result':{'answers':{'q':{'answers':['/tmp/test']}}}},w.sent);self.assertIn({'id':11,'result':{'action':'decline','content':None}},w.sent)
    def test_delivery_confirmation_requires_provider_acceptance(self):
        seen=[];w=self.codex_wire([]);w.delivery=seen.append
        codex(w,'P',{},lambda x:None,{},'/tmp');self.assertIn('confirmed',seen)
        seen=[];w=self.claude_wire([dict(type='assistant',message=dict(id='m',content=[]))]);w.delivery=seen.append
        claude(w,'P',{},lambda x:None);self.assertIn('confirmed',seen)
        seen=[];w=self.claude_wire([]);w.delivery=seen.append
        claude(w,'P',{},lambda x:None);self.assertNotIn('confirmed',seen)

    def test_codex_failed_terminal_never_counts_as_success(self):
        w=self.codex_wire([],status='failed')
        with self.assertRaises(NativeError):codex(w,'P',{},lambda x:None,{},'/tmp')
    def test_unknown_request_gets_error_instead_of_implicit_approval(self):
        w=self.codex_wire([{'id':90,'method':'new/unknown','params':{}}]);codex(w,'P',{},lambda x:None,{},'/tmp')
        self.assertEqual(w.sent[-1]['error']['code'],-32601)
    def claude_wire(self, controls, choices=None, error=False):
        return FakeWire([{'type':'control_response','response':{'request_id':'rc-init','subtype':'success'}},{'type':'system','subtype':'init','session_id':'own-claude','model':'claude-model','tools':['Bash','Read']},*controls,{'type':'result','subtype':'success','is_error':error,'result':'Result'}],choices)
    def test_claude_permission_response_preserves_exact_tool_input(self):
        tool={'subtype':'can_use_tool','tool_name':'Bash','input':{'command':'pwd'}}
        w=self.claude_wire([{'type':'control_request','request_id':'native-approval','request':tool}],[{'choice':'allow'}]);saved=[];r=claude(w,'P',{},saved.append)
        self.assertEqual(saved,['own-claude']);self.assertEqual(r['text'],'Result');response=w.sent[-1]['response'];self.assertEqual(response['request_id'],'native-approval');self.assertEqual(response['response'],{'behavior':'allow','updatedInput':{'command':'pwd'}})
    def test_claude_denial_and_user_question(self):
        w=self.claude_wire([{'type':'control_request','request_id':'q','request':{'subtype':'can_use_tool','tool_name':'AskUserQuestion','input':{'questions':[]}}}],[{'choice':'allow','answers':{'Question':'Answer'}}]);claude(w,'P',{},lambda x:None);self.assertEqual(w.sent[-1]['response']['response']['updatedInput']['answers'],{'Question':'Answer'})
        w=self.claude_wire([{'type':'control_request','request_id':'q','request':{'subtype':'can_use_tool','tool_name':'Write','input':{'file_path':'x'}}}],[{'choice':'deny'}]);claude(w,'P',{},lambda x:None);self.assertEqual(w.sent[-1]['response']['response']['behavior'],'deny')
    def test_claude_remembers_only_matching_tool_rules(self):
        tool=dict(subtype='can_use_tool',tool_name='Bash',input={'command':'git status'},permission_suggestions=[
            dict(type='addRules',behavior='allow',destination='localSettings',rules=[{'toolName':'Bash','ruleContent':'git status *'},{'toolName':'Read','ruleContent':'//Users/**'}]),
            dict(type='setMode',mode='bypassPermissions',destination='session')])
        options=permission_options(tool)
        self.assertEqual(set(options),{'allowSession','allowProject'})
        self.assertEqual(options['allowSession'][0]['rules'],[{'toolName':'Bash','ruleContent':'git status *'}])
        saved=[];w=self.claude_wire([dict(type='control_request',request_id='p',request=tool)],[{'choice':'allowSession'}])
        claude(w,'P',{},lambda x:None,save_permissions=saved.append)
        self.assertEqual(saved,[[{'toolName':'Bash','ruleContent':'git status *'}]])
        self.assertEqual(w.sent[-1]['response']['response']['updatedPermissions'],options['allowSession'])
        self.assertEqual(w.sent[-1]['response']['response']['behavior'],'allow')
    def test_claude_project_rules_use_only_offered_local_destination(self):
        tool=dict(tool_name='Read',subtype='can_use_tool',input={'file_path':'/research/a.md'},permission_suggestions=[dict(type='addRules',behavior='allow',destination='localSettings',rules=[{'toolName':'Read','ruleContent':'/research/**'}])])
        w=self.claude_wire([dict(type='control_request',request_id='p',request=tool)],[{'choice':'allowProject'}]);saved=[]
        claude(w,'P',{},lambda x:None,save_permissions=saved.append)
        self.assertEqual(w.sent[-1]['response']['response']['updatedPermissions'][0]['destination'],'localSettings');self.assertFalse(saved)
        tool['permission_suggestions'][0]['destination']='userSettings'
        self.assertNotIn('allowProject',permission_options(tool))
    def test_claude_ask_user_and_suppressed_requests_cannot_be_remembered(self):
        for tool in ('AskUserQuestion','Bash'):
            req=dict(tool_name=tool,suppressAlwaysAllowRule=True,permission_suggestions=[dict(type='addRules',behavior='allow',destination='session',rules=[{'toolName':tool,'ruleContent':'*'}])])
            self.assertEqual(permission_options(req),{})
        self.assertEqual(permission_options(dict(tool_name='Bash',permission_suggestions=[dict(type='addRules',behavior='allow',rules=[{'toolName':'Bash'}])])),{})
    def test_claude_reapplies_only_saved_rules_on_resume(self):
        with patch('native_cli.Wire') as wire,patch('native_cli.claude',return_value={}):
            run(None,{'provider':'claude'},'P',{},'official-cli',{},'/tmp',{'id':'saved','permissions':[{'toolName':'Read','ruleContent':'/research/**'}]},lambda x:None)
            args=wire.call_args.args[3]
            self.assertEqual(args[args.index('--allowedTools')+1],'Read(/research/**)')
            self.assertEqual(args[args.index('--permission-mode')+1],'auto')

    def test_saved_permissions_survive_reload_and_clear_only_selected_discussion(self):
        import tempfile,json
        from bridge import Council
        with tempfile.TemporaryDirectory() as directory:
            c=Council(directory,runner=lambda *args:{},auth=lambda p:{})
            a=dict(id='a',provider='claude',role='debater',model='default',effort='default')
            def native(*args,**kw):
                args[8]('cli-session')
                kw['save_permissions']([dict(toolName='Read',ruleContent='/research/**')])
                return {'text':'done'}
            with patch('bridge.locate',return_value='claude'),patch('bridge.validate_effort'),patch('native_cli.run',side_effect=native):
                c.native(a,'P',{'request':{'runId':'discussion-one'}})
            key=json.dumps(['discussion-one','a','debater','claude'])
            self.assertEqual(c.native_sessions[key]['permissions'],[dict(toolName='Read',ruleContent='/research/**')])
            c.native_sessions[json.dumps(['other','a','debater','claude'])]={'permissions':[dict(toolName='Read',ruleContent='/other/**')]}
            c.forget_permissions({'runId':'discussion-one'})
            self.assertNotIn('permissions',c.native_sessions[key])
            c.close();again=Council(directory,runner=lambda *args:{},auth=lambda p:{})
            self.assertEqual(again.native_sessions[json.dumps(['other','a','debater','claude'])]['permissions'][0]['ruleContent'],'/other/**')
            again.close()

    def test_claude_auto_failure_is_visible_before_any_user_turn(self):
        w=FakeWire([{'type':'control_response','response':{'request_id':'rc-init','subtype':'success','response':{'current_permission_mode':'manual'}}}])
        with self.assertRaises(NativeError) as error:claude(w,'P',{},lambda x:None)
        self.assertEqual(error.exception.code,'auto_approval_unavailable')
        self.assertFalse(any(x.get('type')=='user' for x in w.sent))
    def test_claude_auto_initializes_without_bypassing_checks(self):
        w=FakeWire([{'type':'control_response','response':{'request_id':'rc-init','subtype':'success','response':{'current_permission_mode':'auto'}}},{'type':'result','subtype':'success','result':'OK'}])
        self.assertEqual(claude(w,'P',{},lambda x:None)['text'],'OK')
        self.assertEqual(w.record[0]['permissionMode'],'auto')
        with patch('native_cli.Wire') as wire,patch('native_cli.claude',return_value={}):
            run(None,{'provider':'claude'},'P',{'request':{'claudePermissionMode':'manual'}},'cli',{},'/tmp',{},lambda x:None)
            args=wire.call_args.args[3];self.assertEqual(args[args.index('--permission-mode')+1],'manual')

    def test_queued_delivery_acknowledgement_survives_cancellation_before_dispatch(self):
        import json,os,sys,tempfile,threading,time
        from types import SimpleNamespace
        from native_cli import Wire
        for provider in ('claude','codex'):
            with tempfile.TemporaryDirectory() as directory:
                event={'type':'assistant','message':{'id':'m','content':[]}} if provider=='claude' else {'id':5,'result':{'turn':{'id':'t'}}}
                script='import sys,time;sys.stdin.readline();print('+repr(json.dumps(event))+',flush=True);time.sleep(10)'
                c=SimpleNamespace(timeout=10,lock=threading.RLock(),active={})
                job={'id':'queued','cancel':threading.Event()}
                w=Wire(c,dict(id='a',provider=provider),job,[sys.executable,'-u','-c',script],directory,os.environ.copy())
                seen=[];w.delivery_callback=seen.append
                try:
                    w.send({'type':'user','message':{}} if provider=='claude' else {'method':'turn/start','id':5})
                    deadline=time.monotonic()+2
                    while 'confirmed' not in seen and time.monotonic()<deadline:time.sleep(.01)
                    job['cancel'].set()
                    with self.assertRaises(NativeError):w.receive()
                    self.assertIn('confirmed',seen)
                finally:w.close()

    def test_native_launch_does_not_disable_cli_features(self):
        for provider in ('claude','codex'):
            with patch('native_cli.Wire') as wire,patch('native_cli.codex',return_value={}),patch('native_cli.claude',return_value={}):
                run(None,{'provider':provider},'P',{},'official-cli',{},'/tmp',{'id':'exact'},lambda x:None)
                args=wire.call_args.args[3]
                for forbidden in ('--restricted','--ignore-user-config','--ignore-rules','--ephemeral','--dangerously-skip-permissions','--dangerously-bypass-approvals-and-sandbox'):
                    self.assertNotIn(forbidden,args)
                if provider=='claude':self.assertIn('--resume',args);self.assertIn('exact',args)

if __name__=='__main__':unittest.main()
