#!/usr/bin/env python3
"""Read-only job usage audit. Missing historical observations remain unknown."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_accounting import audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', type=Path, required=True)
    p.add_argument('--run-id')
    args = p.parse_args()
    jobs = [json.loads(x.read_text()) for x in (args.data_dir/'jobs').glob('*.json')]
    if args.run_id:
        record = args.data_dir/'discussions'/(args.run_id+'.json')
        ids = set(json.loads(record.read_text()).get('jobs', [])) if record.exists() else set()
        jobs = [j for j in jobs if j['id'] in ids or j.get('request', {}).get('runId') == args.run_id]
    print(json.dumps(audit(jobs), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
