"""Native, persistent CLI transports. The installed clients own auth and tool policy."""
from __future__ import annotations
import copy
import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from usage_status import context_sample
from image_store import claude_content
from execution_progress import unlimited
from usage_accounting import Meter


class NativeError(Exception):
    def __init__(self, code, detail=''):
        self.code, self.detail = code, detail
        super().__init__(detail or code)


class Wire:
    def __init__(self, council, agent, job, args, cwd, env, session=None):
        self.council, self.agent, self.job = council, agent, job
        self.meter = Meter(council, agent, job, session)
        self.reader = None
        self.turn_request = None
        self.err = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=self.err, text=True,
                                         encoding='utf-8', errors='replace', start_new_session=True)
        except Exception:
            self.meter.finish('cli_failed'); self.err.close()
            raise
        self.queue = queue.Queue()
        self.deadline = None if unlimited(job.get('request', {})) else time.monotonic()+council.timeout
        with council.lock:
            council.active[self.proc.pid] = (self.proc, job['id'])
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        try:
            for line in self.proc.stdout:
                if len(line) > 4000000:
                    self.queue.put(NativeError('output_too_large')); break
                try:
                    event = json.loads(line)
                    self.meter.observe(event)
                    if self.agent.get('provider') == 'claude' and (event.get('type') == 'assistant' or event.get('type') == 'stream_event' and (event.get('event') or {}).get('type') == 'message_start'):
                        self.delivery('confirmed')
                    if self.agent.get('provider') == 'codex' and self.turn_request is not None and event.get('id') == self.turn_request and (event.get('result') or {}).get('turn', {}).get('id'):
                        self.delivery('confirmed')
                    self.queue.put(event)
                except ValueError:
                    continue
        finally:
            self.queue.put(None)

    def delivery(self, status):
        callback = getattr(self, 'delivery_callback', None)
        if callback:
            callback(status)

    def send(self, data):
        if data.get('method') == 'turn/start':
            self.turn_request = data.get('id')
        if data.get('method') == 'turn/start' or data.get('type') == 'user':
            self.delivery('sent_unconfirmed')
        try:
            self.proc.stdin.write(json.dumps(data, ensure_ascii=False)+'\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise NativeError('cli_failed', self.stderr())

    def stderr(self):
        self.err.seek(0)
        return self.err.read(6000).decode(errors='replace')

    def receive(self):
        while True:
            if self.job['cancel'].is_set():
                raise NativeError('cancelled')
            if self.deadline is not None and time.monotonic() > self.deadline:
                raise NativeError('timeout', self.agent.get('name', self.agent['id']))
            try:
                msg = self.queue.get(timeout=.15)
            except queue.Empty:
                continue
            if msg is None:
                raise NativeError('cli_failed', self.stderr() or 'CLI closed before a successful terminal result')
            if isinstance(msg, Exception):
                raise msg
            return msg

    def approval(self, method, payload, choices):
        # Human waiting time does not consume generation timeout.
        started = time.monotonic()
        try:
            return self.council.wait_approval(self.job, self.agent, method, payload, choices)
        finally:
            if self.deadline is not None:
                self.deadline += time.monotonic()-started

    def event(self, **data):
        self.council.event(self.job, {'agentId': self.agent['id'], **data})

    def close(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL); self.proc.wait()
            except ProcessLookupError:
                pass
        if self.reader:
            self.reader.join(timeout=3)
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.err.close()
        with self.council.lock:
            self.council.active.pop(self.proc.pid, None)


def codex(w, prompt, session, save_session, agent, cwd, images=(), access=None):
    sequence = 0
    def request(method, params):
        nonlocal sequence
        sequence += 1
        w.send({'id': sequence, 'method': method, 'params': params})
        while True:
            msg = w.receive()
            if msg.get('id') == sequence and 'method' not in msg:
                if msg.get('error'):
                    raise NativeError('cli_failed', str(msg['error']))
                return msg.get('result', {})
            handle(msg)

    texts, model, usage = {}, None, None
    def handle(msg):
        nonlocal usage
        method, p = msg.get('method', ''), msg.get('params') or {}
        if 'id' in msg and method:
            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                available = p.get('availableDecisions')
                choices = [x for x in (available or ['accept', 'acceptForSession', 'decline', 'cancel'])
                           if isinstance(x, str) and x in ('accept', 'acceptForSession', 'decline', 'cancel')]
                decision = w.approval(method, p, choices)
                response = {'decision': decision['choice']}
            elif method == 'item/permissions/requestApproval':
                decision = w.approval(method, p, ['accept', 'decline'])
                response = {'permissions': copy.deepcopy(p.get('permissions', {})) if decision['choice'] == 'accept' else {}, 'scope': 'turn'}
            elif method == 'item/tool/requestUserInput':
                decision = w.approval(method, p, ['submit', 'cancel'])
                if decision['choice'] == 'cancel':
                    raise NativeError('cancelled', 'User cancelled native question')
                response = {'answers': {q['id']: {'answers': [str(decision.get('answers', {}).get(q['id'], ''))]}
                                        for q in p.get('questions', [])}}
            elif method == 'mcpServer/elicitation/request':
                decision = w.approval(method, p, ['accept', 'decline', 'cancel'])
                response = {'action': decision['choice'], 'content': decision.get('content') if decision['choice'] == 'accept' else None}
            else:
                w.event(type='unsupported_request', method=method)
                w.send({'id': msg['id'], 'error': {'code': -32601, 'message': 'Research Council has no handler for '+method}})
                return
            w.send({'id': msg['id'], 'result': response})
            return
        if method == 'item/completed':
            item = p.get('item', {})
            if item.get('type') == 'agentMessage':
                texts[item['id']] = item.get('text', '')
                w.event(type='public_message', text=item.get('text', '')[:4000])
            elif item.get('type') in ('commandExecution','fileChange','mcpToolCall','dynamicToolCall','webSearch','imageView','collabAgentToolCall'):
                w.event(type=method, tool=item)
        elif method == 'item/started':
            item = p.get('item', {})
            if item.get('type') in ('commandExecution','fileChange','mcpToolCall','dynamicToolCall','webSearch','imageView','collabAgentToolCall'):
                w.event(type=method, tool=item)
        elif method == 'item/commandExecution/outputDelta':
            w.event(type='command_output', toolId=p.get('itemId'), output=str(p.get('delta', ''))[-18000:])
        elif method == 'thread/tokenUsage/updated':
            usage = p.get('tokenUsage')
            w.event(type='context_usage',context=context_sample('codex',usage))
        elif method in ('error', 'turn/failed'):
            w.event(type=method, error=p)
        return method, p

    request('initialize', {'clientInfo': {'name': 'research_council', 'title': 'Research Council', 'version': '0.11'},
                           'capabilities': {'experimentalApi': True}})
    w.send({'method': 'initialized'})
    params = {'cwd': str(cwd)}
    if access not in (None, 'read-only', 'full'):
        raise NativeError('invalid_request', 'Unknown Codex permission mode')
    if access:
        params.update(approvalPolicy='never' if access == 'full' else 'on-request',
                      sandbox='danger-full-access' if access == 'full' else 'read-only')
    if agent.get('model') not in (None, '', 'auto', 'default'):
        params['model'] = agent['model']
    if session.get('id'):
        params['threadId'] = session['id']
        params['excludeTurns'] = True
        result = request('thread/resume', params)
    else:
        result = request('thread/start', params)
    if access:
        expected_policy = 'never' if access == 'full' else 'on-request'
        expected_sandbox = 'dangerFullAccess' if access == 'full' else 'readOnly'
        if result.get('approvalPolicy') != expected_policy or (result.get('sandbox') or {}).get('type') != expected_sandbox:
            raise NativeError('codex_permission_unavailable', 'Codex did not apply the selected '+access+' mode; check local or managed policy')
    model = result.get('model')
    save_session(result['thread']['id'])
    w.event(type='native_session', sessionId=result['thread']['id'], model=model,
            policy={k: result.get(k) for k in ('approvalPolicy', 'sandbox', 'cwd', 'instructionSources')})
    params = {'threadId': result['thread']['id'], 'input': [{'type': 'text', 'text': prompt}]+[{'type':'localImage','path':im['path']} for im in images]}
    if access:
        params.update(approvalPolicy=expected_policy, sandboxPolicy={'type': expected_sandbox})
    if agent.get('effort') not in (None, '', 'default'):
        params['effort'] = agent['effort']
    turn = request('turn/start', params)
    turn_id = turn['turn']['id']
    if hasattr(w, 'delivery'):
        w.delivery('confirmed')
    while True:
        msg = w.receive()
        handle(msg)
        p = msg.get('params') or {}
        if msg.get('method') == 'turn/completed' and p.get('turn', {}).get('id') == turn_id:
            finished = p['turn']
            if finished.get('status') != 'completed':
                raise NativeError('cli_failed', str(finished.get('error') or finished.get('status')))
            text = '\n\n'.join(texts.values()).strip()
            if not text:
                raise NativeError('empty_output')
            return {'text': text, 'effectiveModel': model, 'usage': usage, 'context':context_sample('codex',usage), 'nativeSessionId': result['thread']['id']}


def permission_options(request):
    """Offer only same-tool, additive CLI suggestions; never synthesize blanket access."""
    if request.get('tool_name') == 'AskUserQuestion' or request.get('suppressAlwaysAllowRule') or (request.get('options') or {}).get('suppressAlwaysAllowRule'):
        return {}
    session, project = [], []
    for suggestion in request.get('permission_suggestions', []) or []:
        if not isinstance(suggestion, dict) or suggestion.get('type') != 'addRules' or suggestion.get('behavior') != 'allow':
            continue
        rules = [copy.deepcopy(rule) for rule in suggestion.get('rules', []) if isinstance(rule, dict)
                 and rule.get('toolName') == request.get('tool_name') and isinstance(rule.get('ruleContent'), str)
                 and rule['ruleContent'].strip() and len(rule['ruleContent']) <= 10000]
        if not rules:
            continue
        update = dict(type='addRules', rules=rules, behavior='allow', destination='session')
        session.append(update)
        if suggestion.get('destination') == 'localSettings':
            project.append({**copy.deepcopy(update), 'destination': 'localSettings'})
    return {k:v for k,v in [('allowSession', session), ('allowProject', project)] if v}


def claude(w, prompt, session, save_session, images=(), save_permissions=None, permission_mode='auto'):
    w.send({'type': 'control_request', 'request_id': 'rc-init', 'request': {'subtype': 'initialize'}})
    initialized = False
    model = usage = None
    last_message = None
    while True:
        event = w.receive()
        kind = event.get('type')
        if kind == 'assistant' or kind == 'stream_event' and (event.get('event') or {}).get('type') == 'message_start':
            if hasattr(w, 'delivery'):
                w.delivery('confirmed')
        if kind == 'control_response' and event.get('response', {}).get('request_id') == 'rc-init':
            if event['response'].get('subtype') == 'error':
                raise NativeError('cli_failed', str(event['response'].get('error')))
            actual_mode = event['response'].get('response', {}).get('current_permission_mode')
            if actual_mode:
                w.event(type='permission_policy', permissionMode=actual_mode, requestedMode=permission_mode)
                if permission_mode == 'auto' and actual_mode != 'auto':
                    raise NativeError('auto_approval_unavailable', 'Claude started in '+str(actual_mode)+' instead of Auto; check account, model and local policy')
            initialized = True
            w.send({'type': 'user', 'session_id': '', 'parent_tool_use_id': None,
                    'message': {'role': 'user', 'content': claude_content(prompt,images)}})
        elif kind == 'control_request':
            req = event.get('request', {})
            if req.get('subtype') != 'can_use_tool':
                w.send({'type': 'control_response', 'response': {'subtype': 'error', 'request_id': event['request_id'],
                                                                'error': 'Unsupported control request'}})
                continue
            tool = req.get('tool_name')
            options = permission_options(req)
            d = w.approval('can_use_tool', req, ['allow', *options, 'deny'])
            response = {'behavior': 'deny' if d['choice'] == 'deny' else 'allow'}
            if response['behavior'] == 'allow':
                if d['choice'] in options:
                    response['updatedPermissions'] = copy.deepcopy(options[d['choice']])
                    if d['choice'] == 'allowSession' and save_permissions:
                        save_permissions([rule for update in options[d['choice']] for rule in update['rules']])
                response['updatedInput'] = copy.deepcopy(req.get('input', {}))
                if tool == 'AskUserQuestion':
                    response['updatedInput']['answers'] = d.get('answers', {})
            else:
                response['message'] = 'User declined this tool request in Research Council'
            w.send({'type': 'control_response', 'response': {'subtype': 'success', 'request_id': event['request_id'], 'response': response}})
        elif kind == 'system' and event.get('subtype') == 'init':
            model = event.get('model')
            if event.get('session_id'):
                save_session(event['session_id'])
            w.event(type='native_session', sessionId=event.get('session_id'), model=model,
                    tools=event.get('tools'), mcpServers=event.get('mcp_servers'), permissionMode=event.get('permissionMode'))
            if permission_mode == 'auto' and event.get('permissionMode') not in (None, 'auto'):
                raise NativeError('auto_approval_unavailable', 'Claude did not retain Auto mode for the selected model')
        elif kind == 'system' and event.get('subtype') in ('task_started', 'task_progress', 'task_notification'):
            w.event(type='task_progress', text=str(event.get('summary') or event.get('description') or event.get('status') or '')[:4000])
        elif kind == 'rate_limit_event':
            info=event.get('rate_limit_info') or {}
            w.event(type='rate_limit_status',info={k:info[k] for k in ('status','resetsAt','rateLimitType','utilization') if k in info})
        elif kind in ('assistant', 'user'):
            if kind == 'assistant' and event.get('message',{}).get('usage'):
                last_message=event['message']['usage']
            content = event.get('message', {}).get('content', [])
            for block in content if isinstance(content, list) else []:
                if kind == 'assistant' and block.get('type') == 'text':
                    w.event(type='public_message', text=block.get('text', '')[:4000])
                if block.get('type') in ('tool_use', 'tool_result'):
                    w.event(type=kind, tool=block)
        elif kind == 'result':
            if not initialized or event.get('is_error') or event.get('subtype') != 'success':
                raise NativeError('cli_failed', str(event.get('result') or event.get('errors') or event.get('subtype')))
            text = event.get('result', '').strip()
            if not text:
                raise NativeError('empty_output')
            return {'text': text, 'effectiveModel': model, 'usage': event.get('usage'),
                    'context':context_sample('claude',event.get('usage'),last_message,event.get('modelUsage'),model),
                    'nativeSessionId': event.get('session_id') or session.get('id')}


def run(council, agent, prompt, job, binary, env, workspace, session, save_session, images=(), save_permissions=None, delivery_callback=None):
    if agent['provider'] == 'codex':
        args = [binary, 'app-server', '--listen', 'stdio://']
    else:
        args = [binary, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
                '--verbose', '--include-partial-messages', '--permission-prompt-tool', 'stdio',
                '--permission-mode', job.get('request', {}).get('claudePermissionMode', 'auto')]
        remembered = [rule['toolName']+'('+rule['ruleContent']+')' for rule in session.get('permissions', [])
                      if isinstance(rule, dict) and isinstance(rule.get('toolName'), str) and isinstance(rule.get('ruleContent'), str)]
        if remembered:
            args += ['--allowedTools', *remembered]
        if session.get('id'):
            args += ['--resume', session['id']]
        else:
            fresh = str(uuid.uuid4())
            args += ['--session-id', fresh]
            save_session(fresh)
        if agent.get('model') not in (None, '', 'default', 'auto'):
            args += ['--model', agent['model']]
        if agent.get('effort') not in (None, '', 'default'):
            args += ['--effort', agent['effort']]
    wire = Wire(council, agent, job, args, workspace, env, session=session)
    wire.delivery_callback = delivery_callback
    status = 'failed'
    try:
        result = codex(wire, prompt, session, save_session, agent, workspace,images,job.get('request',{}).get('codexPermissionMode')) if agent['provider'] == 'codex' else claude(wire, prompt, session, save_session,images,save_permissions,job.get('request',{}).get('claudePermissionMode','auto'))
        status = 'complete'
        return {**result, 'workspace': str(workspace), 'profile': 'native'}
    except NativeError as exc:
        status = exc.code
        raise
    finally:
        wire.close()
        if isinstance(wire.meter, Meter):
            wire.meter.finish(status)
            if wire.meter.latest_total is not None:
                session['usageTotal'] = wire.meter.latest_total
                save_session(session.get('id'))
