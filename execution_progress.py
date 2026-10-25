"""Bounded, durable observable activity for native experiments; no reasoning traces."""
import copy

OUTPUT_LIMIT = 18000


def unlimited(request):
    return request.get('profile') == 'native' and request.get('kind') in ('execution', 'verification')


def plain(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(b['text'] for b in value if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    return ''


def update(job, event):
    if not unlimited(job.get('request', {})) or not event.get('agentId'):
        return
    tool = event.get('tool') or {}
    kind = event.get('type', '').replace('.', '/')
    start = tool.get('type') == 'tool_use' or kind == 'item/started'
    end = tool.get('type') == 'tool_result' or kind == 'item/completed'
    delta = kind == 'command_output'
    public = kind in ('public_message', 'task_progress')
    if not (start or end or delta or public):
        return
    state = job.setdefault('executionProgress', {}).setdefault(event['agentId'],
                dict(active={}, recent=[], output='', outputTruncated=False, message=''))
    state['updated'] = event['at']
    tid = str(tool.get('id') or tool.get('tool_use_id') or event.get('toolId') or 'tool')[:160]
    if start or end:
        previous = state['active'].get(tid, {})
        name = tool.get('name') or previous.get('name') or tool.get('type') or 'tool'
        raw = tool.get('input') or tool.get('arguments') or {}
        raw = raw if isinstance(raw, dict) else {}
        target = next((v for v in [raw.get('command'), tool.get('command'), raw.get('file_path'), raw.get('path'), raw.get('url'), raw.get('query'), tool.get('query')] if isinstance(v, str)), previous.get('detail', ''))
        failed = tool.get('is_error') or tool.get('status') in ('failed', 'cancelled') or tool.get('exitCode') not in (None, 0)
        step = dict(id=tid, name=str(name)[:80], detail=target[:1000], at=event['at'], status='failed' if failed else 'complete' if end else 'running')
        state['recent'] = [s for s in state['recent'] if s['id'] != tid][-15:]+[step]
        if end:
            state['active'].pop(tid, None)
        else:
            state['active'][tid] = step
            state['active'] = dict(list(state['active'].items())[-16:])
        output = plain(tool.get('content')) or plain(tool.get('aggregatedOutput')) or plain(tool.get('output'))
        if end and output and tid not in state.get('streamedTools', []):
            append_output(state, '\n['+str(name)+']\n'+output)
    if delta:
        if tid not in state.get('streamedTools', []):
            state['streamedTools'] = (state.get('streamedTools', [])+[tid])[-32:]
            append_output(state, '\n['+state['active'].get(tid, {}).get('name', 'command')+']\n')
        append_output(state, plain(event.get('output')))
    if public:
        state['message'] = plain(event.get('text'))[-4000:]


def append_output(state, value):
    combined = state['output']+value
    state['outputTruncated'] = state['outputTruncated'] or len(combined) > OUTPUT_LIMIT
    state['output'] = combined[-OUTPUT_LIMIT:]


def policies(job):
    result=copy.deepcopy(job.get('nativePolicies',{}))
    for event in job.get('events',[]):
        if event.get('type')=='native_session' and isinstance(event.get('policy'),dict) and event.get('agentId'):
            policy=event['policy'];result[event['agentId']]=dict(approvalPolicy=policy.get('approvalPolicy'),sandboxType=(policy.get('sandbox') or {}).get('type'),at=event.get('at'))
    return result


def activity(job):
    progress = job.get('executionProgress')
    if progress is None:
        # Older failed tasks remain inspectable without mutating their saved jobs.
        view = dict(request=job['request'])
        for event in job.get('events', []):
            update(view, event)
        progress = view.get('executionProgress', {})
    progress = copy.deepcopy(progress)
    if job['status'] in ('complete', 'failed', 'cancelled', 'interrupted'):
        for state in progress.values():
            pending = set(state.get('active', {}))
            for step in state.get('recent', []):
                if step['id'] in pending:
                    step['status'] = 'unfinished'
            state['active'] = {}
    return dict(id=job['id'], created=job['created'], updated=job.get('updated'),finishedAt=job.get('finishedAt'),status=job['status'],
                requestKind=job['request']['kind'], nativePolicies=policies(job),codexPermissionMode=job['request'].get('codexPermissionMode') if job['request'].get('profile')=='native' else None,unlimitedDuration=job.get('unlimitedDuration', False),
                agents=[dict(id=a['id'], name=a.get('name', a['id'])) for a in job['request']['agents']],
                results=[dict(agentId=r['agentId'],completedAt=r.get('completedAt')) for r in job.get('results', [])],failures=copy.deepcopy(job.get('failures',[])),
                approvals=[dict(agentId=a['agentId'], status=a['status']) for a in job.get('approvals', [])],
                error=copy.deepcopy(job.get('error')), managedExperiments=copy.deepcopy(job.get('managedExperiments',{})), executionProgress=progress)
