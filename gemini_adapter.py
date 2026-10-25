"""Gemini membership via Google's supported Antigravity CLI. CLI owns OAuth."""
import json
import fcntl
import hashlib
import os
import secrets
import shlex
import sys
import tempfile
import time
from gemini_guard import SCOPE_FILE, PROOF_FILE, WEB_FILE, cache_file
from pathlib import Path

WEB_TOOLS = ("search_web", "read_url_content")


def model_list(text):
    models = []
    for line in text.splitlines():
        parts = line.strip().split('\t', 1)
        if parts[0].startswith('gemini-') and len(parts) == 2:
            models.append({"id": parts[0], "name": parts[1]})
    return models


def prepare(workspace, web=False, home=None):
    # This CLI release discovers primary agents from its global agent registry.
    # Use separate immutable definitions so parallel text/web calls cannot race.
    name = 'research-council-web-v2' if web else 'research-council-text-v1'
    folder = Path(home or Path.home())/'.gemini/config/agents'/name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'agent.md'
    content = ('---\nname: '+name+'\ndescription: Research Council research-only agent\n'
               'mainAgent: true\nsubagent: false\ncommandExecutionPolicy: "off"\n'
               'tools: '+json.dumps(list(WEB_TOOLS)+['view_file', 'finish'] if web else ['finish'])+'\n'
               'skills: []\nplugins: []\nmcpServers: []\n---\n'
               'Use only research instructions and evidence in the user message. '
               'Do not run commands, read local files, create artifacts, or delegate. '
               'Return your research answer directly.\n')
    if web:
        content = content.replace('read local files', 'read unrelated local files')
        content += 'For web evidence, use view_file only to read content.md produced by your own completed search_web/read_url_content call. All other local paths are blocked. Distinguish snippets, cached full content and failures; never treat a cache placeholder title as the source title.\n'
    immutable_file(path, content)
    register_guard(home)
    (Path(workspace)/SCOPE_FILE).write_text(json.dumps({'nonce': secrets.token_hex(24), 'web': bool(web)}), encoding='utf-8')
    return path


def immutable_file(path, content):
    # Atomic exclusive publication also handles simultaneous first calls.
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(content)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding='utf-8') != content:
                raise ValueError('Research Council agent definition was modified; refusing to overwrite it')
    finally:
        os.unlink(temporary)


def register_guard(home=None):
    root = str(Path(__file__).resolve().parent)
    guard = str(Path(root)/'gemini_guard.py')
    # No-op before loading our file unless this exact app launched the process.
    wrapper = "import os,runpy;runpy.run_path("+repr(guard)+",run_name='__main__') if os.environ.get('RC_GEMINI_GUARD_ROOT')=="+repr(root)+" else print('{}')"
    command = shlex.join([sys.executable, '-c', wrapper])
    key = 'research-council-'+hashlib.sha256(root.encode()).hexdigest()[:12]
    entry = {'SessionStart': [{'type': 'command', 'command': command+' start', 'timeout': 10}],
             'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': command+' tool', 'timeout': 10}]}],
             'PostToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': command+' post', 'timeout': 10}]}]}
    folder = Path(home or Path.home())/'.gemini/config'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'hooks.json'
    with (folder/'.research-council-hooks.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if key in data:
            if data[key] == entry:
                return
            previous = {k:v for k,v in entry.items() if k != 'PostToolUse'}
            if data[key] != previous:
                raise ValueError('Research Council hook was modified; refusing to overwrite it')
        data[key] = entry
        fd, temporary = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(data, out, indent=2)
                out.write('\n')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def verify_guard(workspace, conversation_id, web=False, timeout=3):
    folder = Path(workspace)
    expected = list(WEB_TOOLS)+['view_file', 'finish'] if web else ['finish']
    scope = json.loads((folder/SCOPE_FILE).read_text(encoding='utf-8'))
    deadline = time.monotonic()+timeout
    while True:
        try:
            proof = json.loads((folder/PROOF_FILE).read_text(encoding='utf-8'))
            if (proof.get('nonce') == scope['nonce'] and proof.get('conversationId') == conversation_id
                    and proof.get('workspace') == str(folder.resolve()) and proof.get('allowedTools') == expected):
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError('Antigravity research hook did not confirm this invocation')
        time.sleep(.05)


def cached_output(workspace, event):
    step = event.get('step_update', {})
    if step.get('state') != 'DONE' or step.get('tool_name') not in WEB_TOOLS:
        return None
    try:
        target = cache_file(event.get('conversation_id') or step.get('conversation_id'), step['step_index'])
        ledger = json.loads((Path(workspace)/WEB_FILE).read_text(encoding='utf-8'))
        if str(target) not in ledger or target.resolve() != target:
            return None
        with target.open(encoding='utf-8', errors='replace') as source:
            return source.read(50000)
    except (OSError, ValueError, KeyError):
        return None


def check_settings(home=None):
    path = Path(home or Path.home())/'.gemini/antigravity-cli/settings.json'
    if not path.is_file():
        return
    settings = json.loads(path.read_text(encoding='utf-8'))
    if settings.get('useG1Credits') or settings.get('modelProvider'):
        raise ValueError('Use account authentication and turn off AI credit overage in Antigravity settings for membership-only calls')


def without_tool_metadata(text):
    # CLI 1.4.2 sometimes includes finish's UI metadata as a prose line.
    lines = []
    for line in text.splitlines(keepends=True):
        try:
            value = json.loads(line)
            if isinstance(value, dict) and set(value) == {'toolAction', 'toolSummary'} and all(isinstance(v, str) for v in value.values()):
                continue
        except ValueError:
            pass
        lines.append(line)
    return ''.join(lines)


def parse(event):
    kind = event.get('event')
    update = {}
    if kind == 'init':
        info = event.get('init', {})
        update['model'] = info.get('model')
        update['tools'] = info.get('tools', [])
    elif kind == 'step_update':
        step = event.get('step_update', {})
        if step.get('step_type') == 'agent_response':
            update['delta'] = step.get('text_delta', '')
        if step.get('step_type') == 'tool':
            tool = step.get('tool_info', {})
            ident = str(step.get('step_index'))
            update['tool'] = ({'type':'tool_result','tool_use_id':ident,'name':step.get('tool_name') or tool.get('name'),'state':step.get('state'),'output':tool.get('output'),'outputAvailable':'output' in tool,'error':tool.get('error')}
                              if step.get('state') in ('DONE', 'ERROR') else
                              {'type':'tool_use','id':ident,'name':step.get('tool_name'),'input':tool.get('parameters',{})})
    elif kind == 'result':
        result = event.get('result', {})
        update['usage'] = result.get('usage')
        if result.get('status') == 'SUCCESS':
            update['text'] = result.get('response', '')
        else:
            update['error'] = str(result.get('error') or result.get('status') or 'Incomplete Antigravity result')
    return update
