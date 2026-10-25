"""Read-only quota and context telemetry. Never infer a quota from token totals."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time


def number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0 else None


def codex_windows(raw):
    buckets=raw.get('rateLimitsByLimitId') or {'codex':raw.get('rateLimits')}
    rows=[]
    for key,bucket in buckets.items():
        if not isinstance(bucket,dict):continue
        for period in ('primary','secondary'):
            window=bucket.get(period)
            if not isinstance(window,dict):continue
            used=number(window.get('usedPercent'))
            rows.append(dict(bucket=bucket.get('limitName') or bucket.get('limitId') or key,
                             period=period,usedPercent=used,remainingPercent=max(0,100-used) if used is not None else None,
                             durationMinutes=number(window.get('windowDurationMins')),resetsAt=number(window.get('resetsAt'))))
    return rows


def timestamp(value):
    if number(value) is not None:return value
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.timestamp() if parsed.tzinfo else None
        except (ValueError,OverflowError):pass
    return None


def claude_windows(raw):
    """Only documented subscription windows; never return account or spend data."""
    limits=raw.get('rate_limits')
    if not raw.get('rate_limits_available') or not isinstance(limits,dict):return []
    rows=[]
    def append(bucket,period,window,minutes):
        if not isinstance(window,dict):return
        used=number(window.get('utilization'))
        rows.append(dict(bucket=bucket,period=period,usedPercent=used,
                         remainingPercent=max(0,100-used) if used is not None else None,
                         durationMinutes=minutes,resetsAt=timestamp(window.get('resets_at'))))
    for key,bucket,minutes in (('five_hour','Claude',300),('seven_day','Claude',10080),
                              ('seven_day_oauth_apps','Claude OAuth apps',10080),
                              ('seven_day_opus','Opus',10080),('seven_day_sonnet','Sonnet',10080)):
        append(bucket,key,limits.get(key),minutes)
    for window in limits.get('model_scoped') or []:
        if isinstance(window,dict) and isinstance(window.get('display_name'),str):
            append(window['display_name'],'model_weekly',window,10080)
    return rows


def gemini_windows(raw):
    """Accept only a built-in read-only slash-command reply, never generated prose."""
    command=raw.get('command') or {}
    if raw.get('status')!='SUCCESS' or raw.get('num_turns')!=0 or command.get('name') not in ('usage','quota'):return []
    rows=[]
    for group in (command.get('data') or {}).get('groups',[]):
        if not isinstance(group,dict):continue
        for window in group.get('buckets',[]):
            if not isinstance(window,dict):continue
            fraction=number(window.get('remaining_fraction'))
            remaining=fraction*100 if fraction is not None and fraction<=1 else None
            period=window.get('window')
            rows.append(dict(bucket=str(group.get('name') or window.get('id') or 'Antigravity'),
                             bucketId=window.get('id'),period=period,
                             remainingPercent=remaining,usedPercent=max(0,100-remaining) if remaining is not None else None,
                             durationMinutes={'5h':300,'weekly':10080,'daily':1440}.get(period),
                             resetsAt=timestamp(window.get('reset_time'))))
    return rows


def _stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=2)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    if proc.stdin:proc.stdin.close()
    proc.stdout.close()


def read_claude(binary,env,timeout=20):
    """SDK initialize + experimental get_usage only. No user turn or transcript scan."""
    source='Claude Code get_usage (experimental)'
    result=dict(provider='claude',available=False,windows=[],source=source,reason='cli_missing',observedAt=time.time())
    if not binary:return result
    proc=None
    try:
        with tempfile.TemporaryDirectory(prefix='council-quota-') as cwd:
            proc=subprocess.Popen([binary,'-p','--safe-mode','--input-format','stream-json','--output-format','stream-json',
                '--verbose','--no-session-persistence','--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}'],
                cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,encoding='utf-8',errors='replace',start_new_session=True)
            inbox=queue.Queue()
            def reader():
                try:
                    for line in proc.stdout:
                        try:inbox.put(json.loads(line))
                        except ValueError:pass
                finally:inbox.put(None)
            threading.Thread(target=reader,daemon=True).start()
            deadline=time.monotonic()+timeout
            def request(rid,payload):
                proc.stdin.write(json.dumps(dict(type='control_request',request_id=rid,request=payload))+'\n');proc.stdin.flush()
                while True:
                    try:message=inbox.get(timeout=max(.01,deadline-time.monotonic()))
                    except queue.Empty:raise TimeoutError()
                    if message is None:raise ValueError('closed')
                    if message.get('type')=='control_response' and message.get('response',{}).get('request_id')==rid:
                        response=message['response']
                        if response.get('subtype')=='error':raise ValueError('unavailable')
                        return response.get('response') or {}
                    if time.monotonic()>=deadline:raise TimeoutError()
            try:
                request('init',{'subtype':'initialize'})
                windows=claude_windows(request('quota',{'subtype':'get_usage','skip_behaviors':True}))
                result.update(available=bool(windows),windows=windows,reason=None if windows else 'unavailable')
            finally:_stop(proc);proc=None
    except (OSError,ValueError,TimeoutError) as exc:
        result['reason']='timeout' if isinstance(exc,TimeoutError) else 'unavailable'
    finally:
        if proc is not None:_stop(proc)
    result['observedAt']=time.time()
    return result


def read_gemini(binary,env,timeout=20):
    """Antigravity's built-in print-mode /usage; does not invoke an agent."""
    result=dict(provider='gemini',available=False,windows=[],source='Antigravity /usage (JSON)',reason='cli_missing',observedAt=time.time())
    if not binary:return result
    try:
        with tempfile.TemporaryDirectory(prefix='council-quota-') as cwd:
            version=subprocess.run([binary,'--version'],cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=min(timeout,5))
            match=re.fullmatch(r'\s*(\d+)\.(\d+)\.(\d+)\s*',version.stdout)
            if version.returncode or not match or tuple(map(int,match.groups()))<(1,1,11):
                result['reason']='unsupported_version'
                return result
            proc=subprocess.Popen([binary,'-p','/usage','--output-format','json'],cwd=cwd,env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,encoding='utf-8',errors='replace',start_new_session=True)
            try:
                stdout,_=proc.communicate(timeout=timeout)
                windows=gemini_windows(json.loads(stdout)) if proc.returncode==0 else []
                result.update(available=bool(windows),windows=windows,reason=None if windows else 'unavailable')
            finally:_stop(proc)
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        result['reason']='timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'unavailable'
    result['observedAt']=time.time()
    return result


def read_all(locate,env):
    # Independent readers: one provider timing out must not hide another's quota.
    def read(provider,reader):
        try:return reader(locate(provider),env(provider))
        except Exception:return dict(provider=provider,available=False,windows=[],reason='unavailable',observedAt=time.time())
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks=[pool.submit(read,p,r) for p,r in (('claude',read_claude),('codex',read_codex),('gemini',read_gemini))]
        return [task.result() for task in tasks]


def read_codex(binary,env,timeout=12):
    """Start only app-server metadata RPCs; no thread/start or turn/start."""
    if not binary:return {'provider':'codex','available':False,'reason':'cli_missing','windows':[],'source':'Codex app-server'}
    proc=subprocess.Popen([binary,'app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=env)
    messages=queue.Queue()
    def reader():
        try:
            for line in proc.stdout:
                try:messages.put(json.loads(line))
                except ValueError:pass
        finally:messages.put(None)
    threading.Thread(target=reader,daemon=True).start()
    deadline=time.monotonic()+timeout
    def send(obj):proc.stdin.write(json.dumps(obj)+'\n');proc.stdin.flush()
    def response(rid):
        while True:
            try:msg=messages.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:raise TimeoutError()
            if msg is None:raise ValueError('closed')
            if msg.get('id')==rid and 'method' not in msg:
                if msg.get('error'):raise ValueError('unsupported_or_unavailable')
                return msg.get('result',{})
            if msg.get('method') and 'id' in msg:send({'id':msg['id'],'error':{'code':-32601,'message':'Metadata reader does not handle requests'}})
            if time.monotonic()>=deadline:raise TimeoutError()
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'research_council_usage','version':'0.11'},'capabilities':{'experimentalApi':True}}});response(1)
        send({'method':'initialized'});send({'id':2,'method':'account/rateLimits/read'});raw=response(2)
        windows=codex_windows(raw)
        return dict(provider='codex',available=bool(windows),windows=windows,ordinaryUsageAllowed=raw.get('ordinaryUsageAllowed'),source='Codex account/rateLimits/read',observedAt=time.time())
    except (OSError,ValueError,TimeoutError) as exc:
        return dict(provider='codex',available=False,windows=[],reason='timeout' if isinstance(exc,TimeoutError) else 'unavailable',source='Codex account/rateLimits/read',observedAt=time.time())
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        proc.stdin.close();proc.stdout.close()


def context_sample(provider,usage=None,last_message=None,model_usage=None,model=None):
    usage=usage or {}
    if provider=='codex':
        last=usage.get('last') or {};used=number(last.get('totalTokens'));window=number(usage.get('modelContextWindow'))
        return dict(usedTokens=used,windowTokens=window,usedPercent=used/window*100 if used is not None and window else None,source='codex_thread_last',basis='input_and_output')
    if provider=='claude':
        detail=(model_usage or {}).get(model) or {}
        if not detail and len(model_usage or {})==1:detail=next(iter(model_usage.values()))
        window=number(detail.get('contextWindow'))
        keys=('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')
        counts=[number((last_message or {}).get(k)) for k in keys]
        used=sum(x or 0 for x in counts) if any(x is not None for x in counts) else None
        return dict(usedTokens=used,windowTokens=window,usedPercent=used/window*100 if used is not None and window else None,source='claude_last_message',basis='input_with_cache')
    return dict(usedTokens=None,windowTokens=None,usedPercent=None,source='not_reported',basis=None)


def snapshot(council,session_id,run_id=''):
    # Cache account reads; opening this view repeatedly must not create subprocess storms.
    with council.usage_lock:
        if not council.usage_cache or time.time()-council.usage_cache['observedAt']>=60:
            try:providers=council.usage_reader()
            except Exception:providers=[]
            council.usage_cache={'observedAt':time.time(),'providers':providers}
        providers=copy.deepcopy(council.usage_cache['providers'])
    known={p.get('provider') for p in providers}
    for p in ('claude','codex','gemini'):
        if p not in known:providers.append(dict(provider=p,available=False,windows=[],reason='interactive_cli_only',source=p+' /usage',observedAt=None))
    with council.lock:
        parent=next((s for s in (council.state or {}).get('sessions',[]) if s.get('id')==session_id),{})
        side_ids={'side-'+c['id'] for c in parent.get('subChats',[]) if isinstance(c.get('id'),str)}
        jobs=[]
        for j in council.jobs.values():
            q=j['request'];sid=q.get('sessionId')
            if not (sid in side_ids or sid==session_id and (not run_id or q.get('runId')==run_id)):continue
            jobs.append(copy.deepcopy(dict(id=j['id'],status=j['status'],created=j.get('created'),updated=j.get('updated',j.get('created')),
                request={k:q[k] for k in ('agents','contextAgent','profile') if k in q},
                results=[{k:r[k] for k in ('agentId','effectiveModel','usage','context') if k in r} for r in j.get('results',[])],
                events=[e for e in j.get('events',[]) if e.get('type')=='context_usage'])))
    latest={}
    for j in sorted(jobs,key=lambda x:x.get('updated',x.get('created',0))):
        results={a['agentId']:a for a in j.get('results',[])}
        for a in j['request'].get('agents',[])+([j['request']['contextAgent']] if j['request'].get('contextAgent') else []):
            r=results.get(a['id'],{});u=r.get('usage') or {};context=r.get('context') or context_sample(a['provider'],u)
            for event in j.get('events',[]):
                if event.get('agentId')==a['id'] and event.get('type')=='context_usage':context=event['context']
            latest[(a['id'],a['provider'],a.get('role'))]=dict(agentId=a['id'],name=a.get('name',a['id']),provider=a['provider'],role=a.get('role'),model=r.get('effectiveModel') or a.get('model','default'),
                context=context,usage=u,profile=j['request'].get('profile','restricted'),observedAt=j.get('updated',j.get('created')),jobId=j['id'],status=j['status'])
    roster=(parent.get('live') or {}).get('roster') or parent.get('agentRoster') or []
    for a in roster:
        if not a.get('enabled'):continue
        key=(a['id'],a['provider'],a.get('role'))
        if key not in latest:latest[key]=dict(agentId=a['id'],name=a.get('name',a['id']),provider=a['provider'],model=a.get('model','default'),role=a.get('role'),context=context_sample(a['provider']),usage={},observedAt=None,status='not_called')
    return dict(providers=providers,agents=list(latest.values()),observedAt=time.time(),cachedSeconds=60)
