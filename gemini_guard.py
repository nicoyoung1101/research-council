"""App-scoped official Antigravity hooks; never handles OAuth credentials."""
import json
import os
from pathlib import Path
import sys
import ipaddress
from urllib.parse import urlsplit

SCOPE_FILE = '.rc-gemini-scope.json'
PROOF_FILE = '.rc-gemini-guard.json'
WEB_FILE = '.rc-gemini-web-files.json'


def decide(tool, allowed):
    name = tool.get('name', '')
    if name in allowed:
        return {'decision': 'auto_approve' if name in ('search_web', 'read_url_content') else 'allow'}
    return {'decision': 'deny', 'reason': 'Research Council permits only the configured research tools; local files, commands, browser control and delegation are disabled.'}


def handle(event, payload, workspace):
    workspace = Path(workspace).resolve()
    scope = json.loads((workspace/SCOPE_FILE).read_text(encoding='utf-8'))
    expected = ['search_web', 'read_url_content', 'view_file', 'finish'] if scope.get('web') else ['finish']
    paths = [str(Path(p).resolve()) for p in payload.get('workspacePaths', [])]
    if paths != [str(workspace)]:
        return {'decision': 'deny', 'reason': 'Research Council workspace does not match the invocation'}
    if event == 'start':
        proof = {'nonce': scope['nonce'], 'conversationId': payload['conversationId'],
                 'workspace': str(workspace), 'allowedTools': expected}
        (workspace/PROOF_FILE).write_text(json.dumps(proof), encoding='utf-8')
        return {}
    tool = payload.get('toolCall', {})
    name = tool.get('name', '')
    ledger = workspace/WEB_FILE
    if event == 'post':
        if scope.get('web') and name in ('search_web', 'read_url_content') and not payload.get('error'):
            target = cache_file(payload['conversationId'], payload['stepIdx'])
            if target.is_file() and target.resolve() == target:
                files = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
                files[str(target)] = {'tool': name, 'step': payload['stepIdx']}
                ledger.write_text(json.dumps(files), encoding='utf-8')
        return {}
    if name == 'view_file':
        try:
            target = Path(tool.get('args', {}).get('AbsolutePath', '')).resolve()
            files = json.loads(ledger.read_text(encoding='utf-8'))
            record = files[str(target)]
            if scope.get('web') and target == cache_file(payload['conversationId'], record['step']) and target.is_file():
                return {'decision': 'auto_approve'}
        except (OSError, ValueError, KeyError):
            pass
        return {'decision': 'deny', 'reason': 'Only this invocation’s completed public-web content cache may be read'}
    if name == 'read_url_content' and not public_url(tool.get('args', {}).get('Url', '')):
        return {'decision': 'deny', 'reason': 'Only public HTTP(S) evidence URLs may be fetched'}
    return decide(tool, expected)


def public_url(value):
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        if url.scheme not in ('http', 'https') or not host or url.username or url.password:
            return False
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def cache_file(conversation_id, step):
    import uuid
    # Strict CLI-owned layout: no traversal, other conversations, logs or credentials.
    conversation_id = str(uuid.UUID(str(conversation_id)))
    if type(step) is not int or step < 0:
        raise ValueError('Invalid web step')
    return Path.home().resolve()/'.gemini/antigravity-cli/brain'/conversation_id/'.system_generated/steps'/str(step)/'content.md'


def main():
    # The global registration itself no-ops outside this application's process.
    try:
        result = handle(sys.argv[1], json.load(sys.stdin), os.environ['RC_GEMINI_GUARD_WORKSPACE'])
    except Exception:
        result = {'decision': 'deny', 'reason': 'Research Council tool guard failed closed'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
