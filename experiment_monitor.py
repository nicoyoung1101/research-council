"""Program-owned launch/monitor loop. No inference while waiting for a process."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

BLOCK = re.compile(r'\s*<council_monitor>\s*(\{.*?\})\s*</council_monitor>\s*$', re.S)
TERMINAL = ('complete', 'failed', 'cancelled', 'interrupted')


def parse(text):
    match = BLOCK.search(text)
    if not match:
        return None
    if len(match[1]) > 50000:
        raise ValueError('Monitor description too large')
    raw = json.loads(match[1])
    if not isinstance(raw, dict) or raw.get('action', 'start') not in ('start', 'wait'):
        raise ValueError('Unknown monitor action')
    return raw


def identity(pid):
    result = subprocess.run(['ps','-p',str(pid),'-o','lstart=','-o','command='], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    # macOS Python launchers exec the framework binary without changing PID/start time.
    # Match birth time and the unique wrapper/spec arguments, not that executable alias.
    parts=result.stdout.strip().split(maxsplit=5)
    return ' '.join(parts[:5])+' '+parts[5].partition(' ')[2] if len(parts)==6 else None


def tail(path, lines=30, offset=0):
    try:
        with Path(path).open('rb') as f:
            size = f.seek(0, 2)
            f.seek(max(offset, size-12000))
            return f.read(12000).decode('utf-8',errors='replace').splitlines()[-lines:]
    except OSError:
        return []


def validate(raw):
    command = raw.get('command')
    if not isinstance(command, list) or not command or len(command)>100 or any(not isinstance(x,str) or not x or '\0' in x or len(x)>16000 for x in command):
        raise ValueError('command must be an argv list')
    if re.search(r'\b(?:nohup|setsid|Monitor)\b', ' '.join(command)):
        raise ValueError('Only bridge may own background processes')
    cwd, log = Path(raw.get('cwd','')), Path(raw.get('logPath',''))
    if not cwd.is_absolute() or not cwd.is_dir() or not log.is_absolute() or not log.parent.is_dir() or log.exists() and not log.is_file():
        raise ValueError('Existing absolute cwd and log parent are required')
    key, marker, failures, expected = raw.get('key'), raw.get('completionMarker'), raw.get('failurePatterns', []), raw.get('expectedSeconds')
    if not isinstance(key,str) or not 1<=len(key)<=100 or not isinstance(marker,str) or len(marker)>500:
        raise ValueError('Stable step key and completion marker string required; empty marker means exit code only')
    if not isinstance(failures,list) or len(failures)>20 or any(not isinstance(x,str) or not 1<=len(x)<=500 for x in failures):
        raise ValueError('failurePatterns must be bounded literal strings')
    if expected is not None and (isinstance(expected,bool) or not isinstance(expected,(int,float)) or not math.isfinite(expected) or expected<=0):
        raise ValueError('expectedSeconds must be positive or null')
    return dict(command=command,cwd=str(cwd.resolve()),logPath=str(log.resolve()),key=key,
                completionMarker=marker,failurePatterns=failures,expectedSeconds=expected)


class Monitor:
    def __init__(self, council, atomic, error):
        self.c, self.atomic, self.Error = council, atomic, error
        self.root = council.data_dir/'managed-experiments'
        self.records = {}
        self.children = {}
        self.gate = threading.RLock()
        for p in self.root.glob('*/owner.json'):
            entry = json.loads(p.read_text())
            self.records[entry['id']] = entry

    def save(self, entry):
        self.atomic(self.root/entry['id']/'owner.json', entry)

    def scope(self, job, agent):
        q=job['request']; plan=q.get('approvedPlan') or {}; approval=q.get('executionApproval') or {}
        if q.get('profile')!='native' or q.get('kind') not in ('execution','verification') or not plan.get('hash') or not approval:
            raise self.Error('invalid_request','Managed execution requires an explicitly approved native experiment')
        return dict(runId=q.get('runId'),agentId=agent['id'],planHash=plan['hash'],
                    experimentId=q.get('experimentId') or job['id'])

    def launch(self, raw, job, agent):
        owner=self.scope(job,agent)
        if raw.get('action')=='wait':
            entry=self.records.get(raw.get('monitorId'))
            source=(job['request'].get('resumeExperiment') or {}).get('sourceTaskId')
            if not entry or any(entry[k]!=owner[k] for k in ('runId','agentId','planHash')) or entry['experimentId'] not in (owner['experimentId'],source):
                raise self.Error('invalid_request','Monitor does not belong to this approved executor/experiment')
            return entry
        try:spec=validate(raw)
        except (ValueError,TypeError) as exc:raise self.Error('invalid_request',str(exc)) from exc
        digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
        source=(job['request'].get('resumeExperiment') or {}).get('sourceTaskId')
        with self.gate:
            for entry in self.records.values():
                if entry['specHash']==digest and all(entry[k]==owner[k] for k in ('runId','agentId','planHash')) and entry['experimentId'] in (owner['experimentId'],source):
                    return entry
            # A changed command for a reused step key is never an idempotent replay.
            for entry in self.records.values():
                if entry['key']==spec['key'] and all(entry[k]==owner[k] for k in owner):
                    raise self.Error('invalid_request','Use a distinct step key for a changed command')
            decision=self.c.wait_approval(job,agent,'host/experimentLaunch',
                dict(reason='启动由 Research Council 管理的后台实验；仅执行本次已批准方案。',command=spec['command'],cwd=spec['cwd'],logPath=spec['logPath'],planHash=owner['planHash']),['accept','cancel'])
            if decision['choice']!='accept' or job['cancel'].is_set():
                raise self.Error('cancelled','Experiment launch not approved')
            entry=dict(owner,id=uuid.uuid4().hex,specHash=digest,key=spec['key'],spec=spec,status='starting',
                       jobId=job['id'],agentName=agent.get('name',agent['id']),created=time.time(),notified=[],lastLog='',logOffset=Path(spec['logPath']).stat().st_size if Path(spec['logPath']).exists() else 0)
            self.records[entry['id']]=entry;self.save(entry)
            folder=self.root/entry['id']
            self.atomic(folder/'spec.json',spec)
            self.atomic(folder/'process.json',dict(id=entry['id'],status='starting'))
            # The wrapper, not an LLM shell command, owns launch through exit receipt.
            env=os.environ.copy()
            for name in ('OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'):
                env.pop(name,None)
            proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('experiment_worker.py')),str(folder/'spec.json'),str(folder/'process.json')],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,env=env)
            entry.update(runnerPid=proc.pid,runnerIdentity=identity(proc.pid));self.children[entry['id']]=proc;self.save(entry)
            self.c.event(job,dict(agentId=agent['id'],type='item/started',tool=dict(id='managed-'+entry['id'],type='commandExecution',command=' '.join(spec['command']),name='bridge command')))
            return entry

    def process(self, entry):
        path=self.root/entry['id']/'process.json'
        try:state=json.loads(path.read_text())
        except (OSError,ValueError):state={}
        proc=self.children.get(entry['id'])
        if proc is not None:proc.poll()
        if state.get('status') not in TERMINAL and entry.get('runnerPid') and identity(entry['runnerPid'])!=entry.get('runnerIdentity'):
            # Neither PID disappearance nor an absent receipt establishes success.
            state.update(status='interrupted',exitCode=None,error='Managed process disappeared without a matching exit receipt')
        return state

    def scan(self, entry):
        spec=entry['spec']; patterns=spec['failurePatterns']+[spec['completionMarker']]
        overlap=max([len(x) for x in patterns]+[1])
        found=set(entry.get('matchedErrors',[]));marker=entry.get('completionMarkerFound',not spec['completionMarker'])
        try:
            with Path(spec['logPath']).open('rb') as f:
                f.seek(entry.get('scanOffset',entry.get('logOffset',0)))
                prefix=entry.get('scanPrefix','')
                while True:
                    chunk=f.read(65536)
                    if not chunk:break
                    text=prefix+chunk.decode('utf-8',errors='replace')
                    for pattern in spec['failurePatterns']:
                        if pattern.casefold() in text.casefold():found.add(pattern)
                    marker=marker or spec['completionMarker'] in text
                    prefix=text[-overlap:]
                offset=f.tell()
            if offset!=entry.get('scanOffset'):
                entry.update(scanOffset=offset,scanPrefix=prefix,matchedErrors=sorted(found),completionMarkerFound=marker)
                self.save(entry)
        except OSError:pass
        return sorted(found),marker

    def summary(self, entry):
        state=self.process(entry);spec=entry['spec']
        logs=tail(spec['logPath'],offset=entry.get('logOffset',0))
        matched,marker=self.scan(entry)
        return dict(monitorId=entry['id'],status=state.get('status','starting'),pid=state.get('pid'),runnerPid=entry.get('runnerPid'),
                    logPath=spec['logPath'],exitCode=state.get('exitCode'),lastLines=logs,matchedErrors=matched,
                    completionMarkerFound=marker,
                    elapsedSeconds=max(0,time.time()-entry['created']),expectedSeconds=spec['expectedSeconds'])

    def publish(self, entry, job, agent, summary):
        with self.c.lock:
            values=job.setdefault('managedExperiments',{})
            values[entry['id']]=dict(summary,agentId=agent['id'])
            self.c.persist(job)
        text='\n'.join(summary['lastLines'])
        if text!=entry.get('lastLog'):
            entry['lastLog']=text
            self.c.event(job,dict(agentId=agent['id'],type='command_output',toolId='managed-'+entry['id'],output='\n'+text))
            self.save(entry)

    def stop(self, entry):
        pid=entry.get('runnerPid')
        if pid and entry.get('runnerIdentity') and identity(pid)==entry['runnerIdentity']:
            try:os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError:pass
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and identity(pid)==entry['runnerIdentity']:
                proc=self.children.get(entry['id'])
                if proc is not None:proc.poll()
                time.sleep(.02)
            if identity(pid)==entry['runnerIdentity']:
                try:os.killpg(pid,signal.SIGKILL)
                except ProcessLookupError:pass
        proc=self.children.get(entry['id'])
        if proc is not None:
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:pass

    def wait(self, entry, job, agent, interval=.25):
        while True:
            if job['cancel'].is_set():
                self.stop(entry)
                view=self.summary(entry);self.publish(entry,job,agent,view)
                raise self.Error('cancelled','Managed experiment stopped by user')
            view=self.summary(entry);self.publish(entry,job,agent,view)
            terminal=view['status'] in TERMINAL
            if terminal:
                if view['status']=='complete' and (not view['completionMarkerFound'] or view['matchedErrors']):
                    view.update(status='failed',error='Missing completion marker or matched failure feature')
                reason='finished'
            elif view['matchedErrors']:
                reason='failure:'+hashlib.sha256(json.dumps(view['matchedErrors']).encode()).hexdigest()
            elif view['expectedSeconds'] and view['elapsedSeconds']>view['expectedSeconds']:
                reason='expected_duration_exceeded'
            else:reason=None
            if reason and reason not in entry['notified']:
                entry['notified'].append(reason);entry['status']=view['status'];self.save(entry)
                self.publish(entry,job,agent,view)
                if terminal:
                    self.c.event(job,dict(agentId=agent['id'],type='item/completed',tool=dict(id='managed-'+entry['id'],type='commandExecution',name='bridge command',exitCode=view['exitCode'],status='completed' if view['status']=='complete' else 'failed')))
                return dict(view,reason=reason)
            if terminal:
                # Explicit recovery may read an already delivered receipt, but never rerun it.
                return dict(view,reason='already_finished')
            job['cancel'].wait(interval)
