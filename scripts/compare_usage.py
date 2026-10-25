#!/usr/bin/env python3
"""Paired token/quality benchmark. Dry-run by default; --execute spends real usage."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import Council, cli_env, locate, prompt_for, validate_effort
import native_cli
from usage_accounting import FIELDS

FIXTURE = Path(__file__).resolve().parents[1]/'tests/fixtures/usage_comparison'


def config(path):
    value=json.loads(Path(path).read_text())
    agents=value.get('models',[])
    if len(agents)!=2 or {a.get('provider') for a in agents}!={'claude','codex'} or len({a.get('id') for a in agents})!=2:
        raise ValueError('Configure exactly one Claude and one Codex agent')
    for agent in agents:
        if any(not isinstance(agent.get(k),str) or not agent[k] or agent[k] in ('auto','default') for k in ('id','model','effort')):
            raise ValueError('Exact model and effort must be configured; no automatic substitution')
    if isinstance(value.get('repetitions'),bool) or not isinstance(value.get('repetitions'),int) or value['repetitions']<3:
        raise ValueError('At least 3 repetitions per group required')
    interval=value.get('followupIntervalSeconds')
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not 0<=interval<=3600:
        raise ValueError('Specify a follow-up interval from 0 to 3600 seconds')
    if value.get('claudePermissionMode','auto') not in ('auto','manual'):
        raise ValueError('Use the same native permission mode in both arms')
    return value


def plan(settings, fixture=FIXTURE):
    task=json.loads((fixture/'task.json').read_text())
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(fixture.iterdir()) if p.is_file()}
    runs=[]
    for rep in range(settings['repetitions']):
        for agent in settings['models']:
            arms=['native_single','rc_single'] if rep%2==0 else ['rc_single','native_single']
            runs += [dict(arm=arm,repetition=rep+1,agents=[copy.deepcopy(agent)],pair='single-'+agent['id']+'-'+str(rep+1)) for arm in arms]
        arms=['manual_dual','rc_dual'] if rep%2==0 else ['rc_dual','manual_dual']
        runs += [dict(arm=arm,repetition=rep+1,agents=copy.deepcopy(settings['models']),pair='dual-'+str(rep+1)) for arm in arms]
    return dict(version=1,mode='dry-run',task=task,fixtureHashes=files,settings=settings,runs=runs,
                plannedModelInvocations=sum(len(r['agents'])*2 for r in runs),
                scope='Native CLI protocol versus native Council adapter; two fixed turns per member, no GUI automation or automatic debate rounds.',
                qualityScope='Deterministic arithmetic/format checks plus an unscored limitations statement; blinded scientific-quality review remains manual.')


def quality(text, task):
    decoder=json.JSONDecoder();candidates=[]
    for i,char in enumerate(text):
        if char!='{':continue
        try:
            value,_=decoder.raw_decode(text[i:])
            if isinstance(value,dict) and all(k in value for k in task['expected']):candidates.append(value)
        except ValueError:pass
    answer=candidates[-1] if candidates else {}
    checks={k:isinstance(answer.get(k),(int,float)) and not isinstance(answer[k],bool) and
            abs(answer[k]-expected)<=task['tolerance'] for k,expected in task['expected'].items()}
    checks['limitationsPresent']=isinstance(answer.get('limitations'),str) and bool(answer['limitations'].strip())
    return dict(passed=all(checks.values()),checks=checks,humanReview='pending',answer=answer)


class NativeCalls:
    """Same official transports with bare task prompts, no Council prompt/context protocol."""
    def __init__(self):self.sessions={}
    def __call__(self,council,agent,request,job,text,context):
        binary=locate(agent['provider'])
        if not binary:raise RuntimeError('Missing CLI: '+agent['provider'])
        validate_effort(agent,binary)
        session=self.sessions.setdefault((context['runId'],agent['id']),{})
        def remember(sid):session['id']=sid
        return native_cli.run(council,agent,text,job,binary,cli_env(agent['provider']),context['workspace'],session,remember)


class CouncilCalls:
    def __call__(self,council,agent,request,job,text,context):
        return council.answer(job,agent,'')


def summarize(rows):
    groups={}
    for row in rows:
        for agent in row['agents']:
            key=row['arm']+':'+agent['provider']
            group=groups.setdefault(key,dict(samples=[],qualityPassed=0,modelMismatch=0))
            calls=[c for c in row.get('usageCalls',[]) if c['agentId']==agent['id']]
            totals={k:sum(c['tokens'][k] for c in calls) if calls and all(c['tokens'].get(k) is not None for c in calls) else None for k in FIELDS}
            group['samples'].append(dict(tokens=totals,elapsedSeconds=row['elapsedSeconds'],toolCalls=sum(c['toolCalls'] for c in calls)))
            group['qualityPassed']+=bool(row.get('quality',{}).get(agent['id'],{}).get('passed'))
            group['modelMismatch']+=any(x.get('effectiveModel') not in (None,agent['model']) for x in row.get('responses',[]) if x['agentId']==agent['id'])
    for group in groups.values():
        samples=group['samples'];group['count']=len(samples)
        group['meanTokens']={k:statistics.mean([s['tokens'][k] for s in samples if s['tokens'][k] is not None]) if any(s['tokens'][k] is not None for s in samples) else None for k in FIELDS}
        group['unknownTokenSamples']={k:sum(s['tokens'][k] is None for s in samples) for k in FIELDS}
        group['qualityEligible']=group['qualityPassed']==len(samples) and group['modelMismatch']==0
    return groups


def run(manifest, output, fixture=FIXTURE, clients=None, sleeper=time.sleep):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    clients=clients or {'native':NativeCalls(),'council':CouncilCalls()}
    settings, task = manifest['settings'],manifest['task']
    report=dict(manifest,mode='execution',startedAt=time.time(),results=[],notes=[
        'No quota percentages are used for comparison. Reasoning is included in output; cache is included in input.',
        'Fresh native sessions and paired counterbalanced order limit but cannot eliminate cache/latency variation.',
        'Quality checks are not a scientific peer-review score; review anonymized response files before interpreting savings.'])
    for index,case in enumerate(manifest['runs']):
        work=output/('run-'+str(index+1))
        workspace=work/'workspace';workspace.mkdir(parents=True,exist_ok=False)
        for p in fixture.iterdir():
            if p.is_file():(workspace/p.name).write_bytes(p.read_bytes())
        c=Council(work/'data')
        def approve(job,agent,method,payload,choices):
            if not sys.stdin.isatty():raise RuntimeError('Native permission requires an interactive terminal; no implicit approval')
            print(json.dumps(dict(agent=agent['id'],request=payload,choices=choices),ensure_ascii=False))
            choice=input('Exact approval choice: ').strip()
            if choice not in choices:raise RuntimeError('Approval declined or unavailable')
            return dict(choice=choice)
        c.wait_approval=approve
        run_id=uuid.uuid4().hex;transcript=[];responses=[];usage=[];last_finished={}
        row=dict(case,runId=run_id,startedAt=time.time(),responses=responses,usageCalls=usage,followupGapSeconds=None,followupGapsByAgent={},status='complete',quality={})
        client=clients['council' if case['arm'].startswith('rc_') else 'native']
        try:
            for stage in range(2):
                if stage:
                    before=time.monotonic();sleeper(settings['followupIntervalSeconds'])
                    row['followupGapSeconds']=time.monotonic()-before
                for agent in case['agents']:
                    q=(task['initial']+'\n\nmetrics.csv:\n'+(fixture/'metrics.csv').read_text()) if not stage else task['followup']
                    public=[] if not stage else copy.deepcopy(transcript)
                    req=dict(requestId=uuid.uuid4().hex,runId=run_id,sessionId=run_id,kind='independent' if not stage else 'debate',
                        question=q,agents=[agent],profile='native',workspace=str(workspace),lang='en',packet={},transcript=public,moderator=[],
                        claudePermissionMode=settings.get('claudePermissionMode','auto'))
                    if stage and case['arm'].startswith('rc_'):
                        req['control']=dict(nonce=uuid.uuid4().hex,plan=None,reviews={},blockers={},round=1)
                    job=dict(id=uuid.uuid4().hex,status='running',request=req,created=time.time(),results=[],events=[],cancel=threading.Event())
                    c.jobs[job['id']]=job;c.persist(job)
                    # Manual baseline pastes the same visible peer record, preserving separate private sessions.
                    peers=[turn for turn in public if turn['id']!=agent['id']]
                    bare=q+('\n\nPublished peer answers:\n'+json.dumps(peers,ensure_ascii=False) if stage and len(case['agents'])>1 else '')
                    call_started=time.monotonic()
                    if stage:
                        row['followupGapsByAgent'][agent['id']]=call_started-last_finished[agent['id']]
                    try:
                        result=client(c,agent,req,job,bare,dict(runId=run_id,workspace=str(workspace)))
                        job['results']=[dict(result,agentId=agent['id'],provider=agent['provider'])];job['status']='complete'
                    except Exception as exc:
                        job.update(status='failed',error=dict(code=type(exc).__name__,detail=str(exc)[:600]));raise
                    finally:
                        c.persist(job);usage.extend(copy.deepcopy(job.get('usageCalls',[])))
                    last_finished[agent['id']]=time.monotonic()
                    responses.append(dict(agentId=agent['id'],stage=stage,text=result['text'],effectiveModel=result.get('effectiveModel'),requestedModel=agent['model'],effort=agent['effort']))
                    transcript.append(dict(type='agent',id=agent['id'],text=result['text']))
            for agent in case['agents']:
                answer=next(x['text'] for x in reversed(responses) if x['agentId']==agent['id'])
                row['quality'][agent['id']]=quality(answer,task)
        except Exception as exc:
            row.update(status='failed',error=str(exc)[:600])
        finally:
            c.close();row['elapsedSeconds']=time.time()-row['startedAt'];report['results'].append(row)
            report['summary']=summarize(report['results'])
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fixture',type=Path,default=FIXTURE)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--execute',action='store_true');mode.add_argument('--dry-run',action='store_true')
    args=p.parse_args(argv);manifest=plan(config(args.config),args.fixture)
    args.output.mkdir(parents=True,exist_ok=True)
    destination=args.output/'manifest.json'
    if destination.exists():p.error('Output already contains a manifest; choose a fresh directory')
    destination.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    if args.execute:run(manifest,args.output,args.fixture)
    print(json.dumps(dict(mode='execution' if args.execute else 'dry-run',workflows=len(manifest['runs']),plannedModelInvocations=manifest['plannedModelInvocations'],manifest=str(destination))))

if __name__=='__main__':main()
