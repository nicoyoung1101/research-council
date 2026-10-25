"""Read effort choices from installed CLIs without starting an inference turn.

Only whitelisted model metadata leaves this module. No credentials or account fields
from initialization responses are returned or persisted.
"""
import copy
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time

_CACHE = {}
_LOCK = threading.Lock()


def normalize(provider, rows):
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if provider == 'codex':
            model_id = row.get('model') or row.get('id')
            efforts = [e.get('reasoningEffort') for e in row.get('supportedReasoningEfforts', []) if isinstance(e, dict)]
            model = {'id': model_id, 'name': row.get('displayName', model_id),
                     'defaultEffort': row.get('defaultReasoningEffort'), 'isDefault': bool(row.get('isDefault'))}
        else:
            model_id = row.get('value')
            efforts = row.get('supportedEffortLevels', []) if row.get('supportsEffort') else []
            model = {'id': model_id, 'name': row.get('displayName', model_id),
                     'resolvedModel': row.get('resolvedModel'), 'description': row.get('description', '')}
        if not isinstance(model_id, str) or not model_id:
            continue
        model['efforts'] = list(dict.fromkeys(e for e in efforts if isinstance(e, str) and e and len(e) < 40))
        result.append(model)
    return result


def find_model(models, model_id):
    return next((m for m in models if m.get('id') == model_id), None) or next(
        (m for m in models if m.get('resolvedModel') == model_id), None)


def validate(models, model_id, effort):
    """Unknown/custom models remain the CLI's responsibility; never downgrade."""
    if effort in (None, '', 'default'):
        return
    model = find_model(models, model_id)
    if model is not None and effort not in model.get('efforts', []):
        raise ValueError(f'{model_id}: unsupported reasoning effort {effort}; choose default or one of: '
                         + ', '.join(model.get('efforts', [])))


def _probe(provider, binary, env, timeout):
    if provider not in ('codex', 'claude'):
        return []
    with tempfile.TemporaryDirectory(prefix='council-models-') as cwd:
        args = ([binary, 'app-server', '--listen', 'stdio://'] if provider == 'codex' else
                [binary, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
                 '--verbose', '--no-session-persistence', '--tools', '', '--strict-mcp-config',
                 '--mcp-config', '{"mcpServers":{}}'])
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                encoding='utf-8', errors='replace', start_new_session=True)
        inbox = queue.Queue()
        def read():
            try:
                for line in proc.stdout:
                    try:
                        inbox.put(json.loads(line))
                    except ValueError:
                        pass
            finally:
                inbox.put(None)
        threading.Thread(target=read, daemon=True).start()
        def send(message):
            proc.stdin.write(json.dumps(message)+'\n')
            proc.stdin.flush()
        try:
            request_id, rows = 2, []
            if provider == 'codex':
                send({'id': 1, 'method': 'initialize', 'params': {
                    'clientInfo': {'name': 'research_council_models', 'version': '0.11'},
                    'capabilities': {'experimentalApi': True}}})
            else:
                send({'type': 'control_request', 'request_id': 'models', 'request': {'subtype': 'initialize'}})
            deadline = time.monotonic()+timeout
            while True:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Model catalog timed out')
                try:
                    message = inbox.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError('Model catalog timed out') from exc
                if message is None:
                    raise RuntimeError('CLI model catalog closed')
                if provider == 'codex':
                    if message.get('id') == 1:
                        if message.get('error'):
                            raise RuntimeError('CLI initialization failed')
                        send({'method': 'initialized'})
                        send({'id': request_id, 'method': 'model/list', 'params': {'limit': 100, 'includeHidden': False}})
                    elif message.get('id') == request_id:
                        if message.get('error'):
                            raise RuntimeError('CLI model catalog failed')
                        result = message.get('result', {})
                        rows.extend(result.get('data', []))
                        cursor = result.get('nextCursor')
                        if not cursor:
                            return normalize(provider, rows)
                        request_id += 1
                        send({'id': request_id, 'method': 'model/list', 'params': {'limit': 100, 'includeHidden': False, 'cursor': cursor}})
                elif message.get('type') == 'control_response' and message.get('response', {}).get('request_id') == 'models':
                    response = message.get('response', {})
                    if response.get('subtype') == 'error':
                        raise RuntimeError('CLI initialization failed')
                    return normalize(provider, response.get('response', {}).get('models', []))
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            proc.stdin.close()
            proc.stdout.close()


def catalog(provider, binary, env, timeout=20):
    try:
        stamp = Path(binary).stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = (provider, binary, stamp)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic()-cached[0] < (600 if cached[1].get('models') else 30):
            return copy.deepcopy(cached[1])
    try:
        result = {'models': _probe(provider, binary, env, timeout), 'modelCatalogSource': 'installed_cli',
                  'modelCatalogObservedAt': time.time()}
    except (OSError, RuntimeError, TimeoutError, ValueError, TypeError) as exc:
        result = {'models': [], 'modelCatalogSource': 'unavailable', 'modelCatalogError': type(exc).__name__}
    with _LOCK:
        _CACHE[key] = (time.monotonic(), result)
    return copy.deepcopy(result)
