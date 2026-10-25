"""Bridge-owned process wrapper. Writes an exit receipt even if the GUI disconnects."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def atomic(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    os.replace(temp, path)


def main(spec_path, state_path):
    spec, state = json.loads(spec_path.read_text()), json.loads(state_path.read_text())
    child = None
    def stop(signum, frame):
        if child is not None and child.poll() is None:
            child.terminate()
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with Path(spec['logPath']).open('ab', buffering=0) as log:
            child = subprocess.Popen(spec['command'], cwd=spec['cwd'], stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL)
            state.update(pid=child.pid, startedAt=time.time(), status='running')
            atomic(state_path, state)
            code = child.wait()
            state.update(exitCode=code, status='complete' if code == 0 else 'failed')
    except BaseException as exc:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        state.update(status='cancelled' if isinstance(exc,SystemExit) else 'failed',
                     error=str(exc)[:400], exitCode=child.returncode if child is not None else None)
    finally:
        state['endedAt'] = time.time()
        atomic(state_path, state)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
