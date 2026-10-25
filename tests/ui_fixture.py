"""Test-only server. Production has no fake-CLI HTTP endpoint or fixture mode."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import CouncilError, make_server
from tracking_fixture import output as tracking_output

READING_SAMPLE = """# 先明确问题，再核验证据

## 本轮判断

**需要分别验证两个问题：方法是否有效，以及设备是否带来额外收益。** 这两件事需要不同的比较条件，不能只凭主观感受作出结论。

下面整理已公开的观点、证据缺口和下一步验证方式。这里使用测试资料展示阅读排版，不代表真实研究结论。

### 如何比较不同方案

| 研究方向 | 需要回答的问题 | 建议的验证方式 |
| --- | --- | --- |
| 简单引导 | 使用者能否更容易执行方法？ | 与相同内容的普通音频比较 |
| 实时反馈 | 数据反馈是否增加使用负担？ | 比较显示与隐藏数据的条件 |
| 自动调节 | 调整节奏能否带来额外效果？ | 保持其他条件一致，预先定义指标 |

### 下一步

1. 明确目标人群和测量指标。
2. 保留相互矛盾的证据。
   - 区分已验证结论与待检验假设。
   - 记录原始来源与适用范围。
3. 让另一位 Agent 针对上述判断提出反例。

> 观点一致仍需要证据支持。请在讨论中保留不确定性。

参考资料：[研究资料示例](https://example.org/research)；记录格式为 `research-notes.md`。
"""

failed_once = set()
approval_issued = set()

def runner(agent, prompt, job):
    if 'PROGRAM_MONITOR_TEST' in agent.get('rules','') and job['request']['kind']=='execution':
        job['fixtureExecutorInvocations']=job.get('fixtureExecutorInvocations',0)+1
        if job.get('lastMonitorWake'):
            return dict(text='Verified program-owned fixture output.')
        root=Path(job['request']['workspace'])
        spec=dict(action='start',key='program-fixture',command=[sys.executable,'-u','-c',"import time;print('epoch=1',flush=True);time.sleep(3);print('DONE',flush=True)"],
                  cwd=str(root),logPath=str(root/'program-fixture.log'),completionMarker='DONE',failurePatterns=['Traceback'],expectedSeconds=20)
        return dict(text='Requesting bridge launch.\n<council_monitor>'+json.dumps(spec)+'</council_monitor>')
    if 'ACTIVITY_TEST' in agent.get('rules','') and job['request']['kind']=='question':
        for index,name in enumerate(['WebSearch','Read','Bash']):
            tool=dict(type='tool_use',id='activity-'+str(index),name=name,input={'query':'published evidence','file_path':'research-notes.md','command':'python verify.py'})
            server.council.event(job,dict(agentId=agent['id'],type='assistant',tool=tool))
            if job['cancel'].wait(.9):raise CouncilError('cancelled')
            server.council.event(job,dict(agentId=agent['id'],type='user',tool={'type':'tool_result','tool_use_id':tool['id']}))
    if 'EXPERIMENT_LIVE_TEST' in agent.get('rules','') and job['request']['kind'] in ('execution','verification'):
        kind=job['request']['kind'];tid=kind+'-command'
        if agent['provider']=='codex':
            full=job['request'].get('codexPermissionMode')=='full'
            server.council.event(job,dict(agentId=agent['id'],type='native_session',policy=dict(approvalPolicy='never' if full else 'on-request',sandbox=dict(type='dangerFullAccess' if full else 'readOnly'))))
        tool=dict(id=tid,type='commandExecution',command='python -u train_fixture.py' if kind=='execution' else 'python -u verify_fixture.py')
        server.council.event(job,dict(agentId=agent['id'],type='item/started',tool=tool))
        server.council.event(job,dict(agentId=agent['id'],type='public_message',text='Checking actual '+kind+' output'))
        for epoch in range(1,11):
            text='epoch='+str(epoch)+' loss=0.'+str(100-epoch)+'\n'+''.join('measured step '+str(i)+'\n' for i in range(20))
            server.council.event(job,dict(agentId=agent['id'],type='command_output',toolId=tid,output=text))
            if job['cancel'].wait(.45):raise CouncilError('cancelled')
        server.council.event(job,dict(agentId=agent['id'],type='item/completed',tool={**tool,'aggregatedOutput':'fixture check saved','exitCode':0}))
    if "PROGRESS_TEST" in agent.get("rules", "") and job['request']['kind']=='independent':
        for kind in ('commandExecution','webSearch'):
            tool=dict(id='fixture-'+kind,type=kind)
            server.council.event(job,dict(agentId=agent['id'],type='item/started',tool=tool))
            if job['cancel'].wait(1.6): raise CouncilError('cancelled')
            server.council.event(job,dict(agentId=agent['id'],type='item/completed',tool=tool))
    for _ in range(120 if job["request"]["kind"] == "execution" and "EXECUTION_WAIT_TEST" in agent.get("rules", "") else 60 if "SLOW_TEST" in agent.get("rules", "") else 15):
        if job["cancel"].wait(.04):
            raise CouncilError("cancelled")
    if "TRIGGER_FAILURE" in prompt:
        raise CouncilError("cli_failed", "fixture model rejected")
    if "FAIL_ONCE" in agent.get("rules", "") and agent["id"] not in failed_once:
        failed_once.add(agent["id"])
        raise CouncilError("cli_failed", "fixture transient failure")
    if job['request']['kind'] == 'title':
        if 'SLOW_TEST' in job['request']['question']: job['cancel'].wait(1)
        return {'text':json.dumps({'title':'Focused research plan','summary':'Validate the research idea and define its scope.'}) if job['request'].get('titleFormat') == 'metadata' else 'Focused research plan','effectiveModel':'fixture-gemini'}
    if "CLAUDE_PERMISSION_TEST" in agent.get("rules", "") and agent['provider']=='claude' and job['request']['kind']=='independent':
        from native_cli import permission_options
        request=dict(subtype='can_use_tool',tool_name='Bash',input={'command':'cat sample-local.md'},permission_suggestions=[dict(type='addRules',behavior='allow',destination='localSettings',rules=[dict(toolName='Bash',ruleContent='cat sample-local.md'),dict(toolName='Read',ruleContent='//Users/**')])])
        server.council.wait_approval(job,agent,'can_use_tool',request,['allow',*permission_options(request),'deny'])
    if job['request']['kind']=='sidechat' and job['request'].get('sideContext') and 'SIDE_SOURCE_TEST' in job['request']['question']:
        import re
        nonce=re.search(r'<council_read nonce="([a-f0-9]+)">',prompt)[1]
        if job.get('modelCalls', 1)==1:
            specs=[dict(op='search_discussion',query='EARLY_MAIN_EVIDENCE'),dict(op='read_file',source='R1/plan.md',start=2,count=2)]
            return {'text':'<council_read nonce="'+nonce+'">'+json.dumps(specs)+'</council_read>'}
        if 'CANCEL_READ' in job['request']['question'] and job['cancel'].wait(8):raise CouncilError('cancelled')
        return {'text':'Verified FILE_SENTINEL_VERIFIED from [R1/plan.md L2–3]. EARLY_MAIN_EVIDENCE is a main-discussion excerpt, not independent proof.', 'effectiveModel':'fixture-'+agent['provider']}
    if job['request']['kind']=='question' and 'QUESTION_APPROVAL_TEST' in job['request']['question']:
        server.council.wait_approval(job,agent,'item/commandExecution/requestApproval',
                                   {'command':'python3 inspect_question.py','reason':'Inspect saved results without training.'},['accept','cancel'])
    if job['request']['kind'] in ('sidechat','question'):
        return {'text':'## Explanation\n'+job['request']['question']+'\n\nPrior side messages: '+str(len(job['request'].get('transcript',[]))), 'effectiveModel':'fixture-'+agent['provider']}
    if job["request"]["kind"] == "tracking":
        return {"text": tracking_output(job["request"]["trackingInput"]), "effectiveModel": "fixture-model", "usage": {}}
    if "READING_TEST" in agent.get("rules", ""):
        return {"text": READING_SAMPLE, "effectiveModel": "fixture-model", "usage": {"last":{"totalTokens":2500},"modelContextWindow":10000} if agent["provider"]=="codex" else {"input_tokens":24000,"output_tokens":400}}
    if job['request'].get('executionControl'):
        c=job['request']['executionControl'];count=len(c['previous'])
        role=c['role'];state=('review_required' if count==0 else 'done') if role=='execution' else ('continue' if count==1 else 'done')
        if c.get('preflight'):state='continue'
        receipt={k:c[k] for k in ('nonce','taskId','planHash')}
        if c.get('preflight'):receipt['issueChecks']=[dict(key=i['key'],status='resolved',evidence='Isolated fixture preflight') for i in c['preflightIssues']]
        receipt.update(state=state,checkpoint='Prepare' if count<2 else 'Final artifact',summary='Verified fixture stage '+str(count),nextAction='Continue approved fixture work',checks=[dict(index=i,status='pass',evidence='Isolated fixture artifact matches') for i,_ in enumerate(job['request']['approvedPlan']['proposal']['acceptance'])])
        return dict(text='Fixture checkpoint '+str(count)+'\n<council_execution>'+json.dumps(receipt)+'</council_execution>',effectiveModel='fixture-model')
    if job["request"].get("control"):
        control = job["request"]["control"]
        if 'PENDING_ATTRIBUTION_TEST' in job['request']['question'] and agent['provider']=='codex':
            if job['cancel'].wait(5):raise CouncilError('cancelled')
        if "APPROVAL_TEST" in agent.get("rules", "") and agent["provider"] == "codex" and (job["request"].get("runId"),agent["id"]) not in approval_issued:
            approval_issued.add((job["request"].get("runId"),agent["id"]))
            server.council.wait_approval(job, agent, "item/commandExecution/requestApproval",
                                       {"command": "python3 verify_fixture.py", "cwd": job["request"].get("workspace")}, ["accept", "decline"])
        receipt = dict(nonce=control["nonce"], decision="ready", reviewedPlanHash=control["plan"]["hash"] if control["plan"] else "proposed",
                       proposal=None if control["plan"] else dict(title="A reproducible fixture plan", body="## Plan\nCreate and verify a fixture artifact.", acceptance=["Exact expected file bytes"]),
                       blockers=[], nextAction="Execute and verify the reviewed plan", researchStage="confirmation", focus=["interpretation","planning"] if any(t.get("kind")=="execution" for t in job["request"].get("transcript",[])) else ["exploration","evidence"], focusReason="Testing adaptive focus in the normal answer")
        if 'NEED_USER_ROUND_TEST' in job['request']['question']:
            receipt.update(decision='need_user', blockers=[dict(id='gpu', text='Confirm GPU before execution')],
                           nextAction='Confirm the GPU after all members finish reviewing')
        return {"text": "## Review\nI reviewed the published peer answer and this exact plan.\n<council_control>"+json.dumps(receipt)+"</council_control>", "effectiveModel": "fixture-model"}
    return {"text": "## "+agent["role"]+"\nActual fixture answer by "+agent["name"]+". Evidence: sample-local.md.", "effectiveModel": "fixture-model", "usage": {}}


def auth(provider):
    result={"provider":provider,"installed":True,"loggedIn":True,"version":"fixture"}
    if provider in ('codex','claude'):
        result.update(modelCatalogSource='installed_cli',models=(
            [{'id':'gpt-6.1-sol','name':'GPT 6.1 Sol','efforts':['low','medium','high','xhigh','max','ultra']},
             {'id':'gpt-6-luna','name':'GPT 6 Luna','efforts':['low','medium','high','xhigh','max']}] if provider=='codex' else
            [{'id':'opus','resolvedModel':'claude-opus-5-5','name':'Opus','efforts':['low','medium','high','xhigh','max']},
             {'id':'sonnet','resolvedModel':'claude-sonnet-5','name':'Sonnet','efforts':['low','medium','high','xhigh','max']},
             {'id':'haiku','resolvedModel':'claude-haiku-4-5-20251001','name':'Haiku','efforts':[]}]))
    if provider == 'gemini':
        result.update(client='Antigravity CLI',authVerified=True,models=[{'id':'gemini-account-visible','name':'Account Gemini fixture'}])
    return result

server = make_server(0, sys.argv[1], runner=runner, auth=auth, usage_reader=lambda:[{'provider':'codex','available':True,'source':'Fixture account data','observedAt':time.time(),'windows':[{'bucket':'shared','usedPercent':25,'remainingPercent':75,'durationMinutes':300,'resetsAt':time.time()+3600}]}])
# Isolate fixture delivery settings from the real packaged recipient.
feedback_config=Path(sys.argv[1])/'feedback-test-bundle.json';feedback_config.write_text('{}')
server.council.feedback.bundled_config=feedback_config
# Feedback transport is injected only in this test server; production never has a fake endpoint.
def feedback_sender(endpoint, body):
    directory=Path(sys.argv[1])
    if (directory/'feedback-fail').exists():raise TimeoutError('fixture delivery unavailable')
    path=directory/'feedback-captures.json'
    rows=json.loads(path.read_text()) if path.exists() else []
    rows.append(dict(endpoint=endpoint,body=body));path.write_text(json.dumps(rows))
server.council.feedback.sender=feedback_sender
print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/index.html"}), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.council.close()
    server.server_close()
