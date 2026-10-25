"""Explicit handoffs inside one human-approved experiment; no inferred completion."""
import copy
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

HELPER_RECOVERY = dict(kind='workspace_verification_helper', maxAttempts=2)


def recovery_policy(value):
    if value is not True and value is not False:
        raise ValueError('Helper recovery must be explicitly enabled or disabled')
    return copy.deepcopy(HELPER_RECOVERY) if value else None


def control(task, role):
    return dict(nonce=uuid.uuid4().hex, taskId=task['id'], planHash=task['plan']['hash'], role=role,
                previous=copy.deepcopy(task.get('stages', [])[-6:]),
                preflight=bool(role=='verification' and task.get('preflightPending')),
                preflightIssues=copy.deepcopy(task.get('approval',{}).get('issues',[])) if task.get('preflightPending') else [],
                helperRecovery=copy.deepcopy(task.get('approval',{}).get('helperRecovery')),
                repairAttempts=task.get('repairAttempts',0),
                workspace=task.get('workspace'),
                verificationPathHelper=str(Path(__file__).with_name('verification_paths.py').resolve()),
                repairAuthorization=copy.deepcopy(task.get('repairAuthorization')),
                decision=task.get('approval', {}).get('continuationDecision', ''))


def prompt(value):
    return '\nExecution handoff (host control):\n'+json.dumps(value,ensure_ascii=False)+'''
This is a checkpointed execution workflow, NOT a new planning discussion. Work only inside the frozen human-approved plan. Inspect existing artifacts before continuing; do not repeat completed steps, overwrite evidence, change scientific settings, or expand scope. The host, not you, calls the other member.
The host assigns the executor and verifier. Do not ask the user to repeat instructions to either member or to arrange a peer handoff. Previous observations are reference data, not new authorization.
Executor: do the next bounded portion. At any required independent-review gate, stop BEFORE the gated operation and return state "review_required". Return "done" only after all executor work in the approved plan is finished; the host still requests final verification. Use "needs_user" for substantive failures, ambiguous prior experiments, changed assumptions, or a decision outside existing authorization.
Verifier: independently inspect actual evidence for the submitted checkpoint. Return "continue" only when that checkpoint passed and there is unfinished work inside the SAME approved plan; nextAction must name that remaining work. Return "done" only when the whole approved plan and EVERY acceptance criterion pass. A failed/unverified criterion is not completion; return "needs_user" with the concrete issue. Do not execute the executor's future gated steps yourself.
When preflight=true, independently check the proposed plan and its open issues before any execution. Return issueChecks [{"key":"exact preflight issue key","status":"resolved|needs_user","evidence":"actual basis"}] covering every preflightIssues entry. "continue" or "done" requires all issues resolved with evidence, using the exact plan and existing user decisions. A missing peer answer is not a reason to ask the user to write another instruction. A real design, external-permission or acceptance decision must remain needs_user.
If helperRecovery is enabled, the user authorizes a NARROW exception to stop-on-failure for verifier-owned auxiliary code defects, including path/Markdown parsing and helper syntax errors. Preserve the original helper and failure evidence; never change training/evaluation/statistics code, data, seeds, models, tolerances, acceptance criteria or prior results, never rerun training/inference/statistics, and never silently accept a procedural deviation. A failed scientific check or a question about numerical/report tolerance is NOT an auxiliary-code defect.
Before repairing, return verifier state "repair" with repair {"target":"absolute existing workspace-only helper .py/.sh/.js path","problem":"specific observed code defect","change":"bounded proposed correction"}. The host validates and allows at most two repairs per task lineage. On the next call repairAuthorization grants that exact helper correction: create a NEW helper/evidence file, keep originals and old reports unchanged, test on synthetic fixtures first, then repeat ONLY independent verification of existing results. For report hashes you can import report_hash(line, roots) from verificationPathHelper, which resolves only unique existing files and rejects missing/ambiguous paths. Use explicit structured file manifests or backtick-quoted paths; do not interpret narrative comments such as （0 字节） as part of a filename. Do not rerun an unchanged failed command. After the repair recheck all original acceptance criteria; never label an unresolved report or failed numerical comparison as pass.
For final verification include checks [{"index":0,"status":"pass|fail|unverified","evidence":"actual file/check/result"}], exactly once for each zero-based approvedPlan.proposal.acceptance index. "done" requires every item pass with evidence. A checkpoint review can report only the criteria actually checked.
After a readable answer append one final block, outside a code fence:
<council_execution>{"nonce":"supplied nonce","taskId":"supplied taskId","planHash":"supplied planHash","state":"review_required|continue|done|needs_user|repair","checkpoint":"short specific checkpoint name","summary":"what actually completed and observed","nextAction":"remaining approved work or concrete user decision","checks":[]}</council_execution>
Use only states valid for your role. Do not copy a peer's receipt. With a council_monitor request, finish with ONLY that monitor block; emit this handoff receipt after the bridge wakes you with the actual process outcome. Do not use sleep, polling or background tools to wait for another member. The host routes reviews and continuation automatically without a fresh proposal or repeated human approval for the same frozen scope.
'''


def parse(text, value, plan):
    match=re.search(r'\s*<council_execution>\s*(\{.*?\})\s*</council_execution>\s*$',text,re.S)
    if not match:raise ValueError('Missing execution handoff; whole-plan completion is unconfirmed')
    r=json.loads(match[1])
    if not isinstance(r,dict) or value.get('role') not in ('execution','verification'):
        raise ValueError('Invalid execution handoff object or role')
    for key in ('nonce','taskId','planHash'):
        if r.get(key)!=value[key]:raise ValueError('Execution handoff identity mismatch')
    states=('review_required','done','needs_user') if value['role']=='execution' else ('continue','done','needs_user','repair')
    if r.get('state') not in states:raise ValueError('Invalid handoff for this role')
    for key,limit in (('checkpoint',240),('summary',4000),('nextAction',4000)):
        if not isinstance(r.get(key),str) or len(r[key])>limit or (key!='nextAction' or r['state']!='done') and not r[key].strip():
            raise ValueError('Missing or oversized handoff '+key)
    checks=r.get('checks',[])
    if not isinstance(checks,list) or len(checks)>100:raise ValueError('Invalid acceptance checks')
    seen=set();total=len(plan['proposal']['acceptance'])
    for item in checks:
        if (not isinstance(item,dict) or type(item.get('index')) is not int or not 0<=item['index']<total or item['index'] in seen or
            item.get('status') not in ('pass','fail','unverified') or not isinstance(item.get('evidence'),str) or not item['evidence'].strip() or len(item['evidence'])>4000):
            raise ValueError('Invalid acceptance check or evidence')
        seen.add(item['index'])
    if value['role']=='verification' and r['state']=='done' and (seen!=set(range(total)) or any(x['status']!='pass' for x in checks)):
        raise ValueError('Final verification did not pass every acceptance criterion')
    issues=r.get('issueChecks',[])
    if value.get('preflight') and r['state'] in ('continue','done'):
        expected={i['key'] for i in value.get('preflightIssues',[])}
        if (not isinstance(issues,list) or len(issues)!=len(expected) or
            any(not isinstance(i,dict) or i.get('key') not in expected or i.get('status')!='resolved' or not isinstance(i.get('evidence'),str) or not 0<len(i['evidence'].strip())<=4000 for i in issues) or
            {i['key'] for i in issues}!=expected):
            raise ValueError('Preflight did not resolve every outstanding issue')
    if r['state']=='repair':
        repair=r.get('repair')
        if not value.get('helperRecovery') or not isinstance(repair,dict):raise ValueError('Helper repair is not authorized')
        if value.get('repairAttempts',0)>=HELPER_RECOVERY['maxAttempts']:raise ValueError('Auxiliary verification repair limit reached')
        target=repair.get('target')
        if not isinstance(target,str) or not Path(target).is_absolute() or not value.get('workspace'):raise ValueError('Repair requires an existing workspace helper')
        path=Path(target);workspace=Path(value['workspace']).resolve()
        if not path.is_file() or path.suffix not in ('.py','.sh','.js') or not path.resolve().is_relative_to(workspace):raise ValueError('Repair target must stay inside the workspace')
        if path.stat().st_size>1024*1024:raise ValueError('Verification helper is too large')
        repair={k:repair.get(k) for k in ('target','problem','change')};r['repair']=repair
        repair['originalSha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        for key in ('problem','change'):
            if not isinstance(repair.get(key),str) or not 0<len(repair[key].strip())<=4000:raise ValueError('Incomplete helper repair request')
    receipt={k:r.get(k,[]) for k in ('nonce','taskId','planHash','state','checkpoint','summary','nextAction','checks')}
    if value.get('preflight'):receipt['issueChecks']=copy.deepcopy(issues)
    if r['state']=='repair':receipt['repair']=copy.deepcopy(r['repair'])
    return text[:match.start()].rstrip(),receipt


def record(task, job):
    """Commit a returned handoff once, including a result published just before pause."""
    if any(s['jobId']==job['id'] for s in task.get('stages',[])):return
    value=job.get('request',{}).get('executionControl')
    if not value or value.get('taskId')!=task['id'] or value.get('planHash')!=task['plan']['hash']:return
    result=next(iter(job.get('results',[])),None)
    if not result:return
    receipt=result.get('executionReceipt')
    if not receipt:
        task['handoffIssue']=result.get('executionReceiptError','Execution handoff missing')
        return
    if any(receipt.get(k)!=value.get(k) for k in ('nonce','taskId','planHash')):
        task['handoffIssue']='Execution handoff identity mismatch'
        return
    step=dict(jobId=job['id'],role=value['role'],agentId=result['agentId'],at=time.time(),
              **{k:copy.deepcopy(receipt[k]) for k in ('state','checkpoint','summary','nextAction','checks')})
    task.setdefault('stages',[]).append(step);task.pop('handoffIssue',None)
    if receipt.get('issueChecks') is not None:step['issueChecks']=copy.deepcopy(receipt['issueChecks'])
    if value.get('preflight') and receipt['state'] in ('continue','done'):task['preflightPending']=False
    task.pop('repairAuthorization',None)
    if receipt['state']=='repair':
        step['repair']=copy.deepcopy(receipt['repair'])
        task['repairAttempts']=task.get('repairAttempts',0)+1
        task['repairAuthorization']=dict(receipt['repair'],attempt=task['repairAttempts'])
    task['workflowNext']=value['role'] if receipt['state'] in ('needs_user','repair') else 'verification' if value['role']=='execution' else 'execution'


def recover(task,jobs):
    for jid in task.get('jobs',[]):
        if jid in jobs:record(task,jobs[jid])


def needs_decision(task):
    # Old pair-returned records have no bound stage receipt. Do not guess what
    # passed or treat a generic Continue click as a resolution of old objections.
    return task['status'] in ('needs_decision','reviewed') or bool(task.get('stages') and task['stages'][-1]['state']=='needs_user')


def run(controller,r,task,executor,reviewer):
    recover(task,controller.c.jobs)
    if task.get('stages') and task['stages'][-1]['role']=='verification' and task['stages'][-1]['state']=='done':return
    while True:
        role=task.get('workflowNext','execution')
        task['status']='running' if role=='execution' else 'verifying'
        task['currentStage']=dict(role=role,agentId=(executor if role=='execution' else reviewer)['id'],
                                  title=(task.get('stages') or [{}])[-1].get('nextAction',''))
        controller.persist(r)
        repair=task.get('repairAuthorization')
        if repair:
            target=Path(repair['target'])
            if not target.is_file() or not target.resolve().is_relative_to(Path(task['workspace']).resolve()) or hashlib.sha256(target.read_bytes()).hexdigest()!=repair['originalSha256']:
                raise controller.Error('execution_needs_decision','Original verification helper changed after repair authorization; preserved evidence must be checked')
        before=len(task.get('stages',[]))
        controller.invoke(r,role,[executor if role=='execution' else reviewer])
        record(task,controller.c.jobs[task['jobs'][-1]])
        controller.persist(r)
        if len(task.get('stages',[]))==before:
            raise controller.Error('execution_handoff_invalid',task.get('handoffIssue','No confirmed stage outcome'))
        step=task['stages'][-1]
        if step['state']=='needs_user':raise controller.Error('execution_needs_decision',step['summary']+' '+step['nextAction'])
        if step['state']=='repair' and task['repairAttempts']>HELPER_RECOVERY['maxAttempts']:
            raise controller.Error('execution_needs_decision','Auxiliary verification repair limit reached; original evidence preserved')
        if role=='verification' and step['state']=='done':return
        # No arbitrary clock/call cap. Identical handoffs signal a stalled workflow.
        signatures=[hashlib.sha256(json.dumps({k:s[k] for k in ('role','checkpoint','summary','nextAction','state')},sort_keys=True).encode()).hexdigest() for s in task['stages']]
        if signatures.count(signatures[-1])>=3:raise controller.Error('execution_stalled','Repeated unchanged checkpoint; user decision required')
