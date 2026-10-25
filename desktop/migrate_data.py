#!/usr/bin/env python3
"""Move existing local data with a verified backup and a compatibility symlink.
Stop the local service first. Refuses active jobs and never merges/overwrites a destination.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def manifest(root):
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            result[str(p.relative_to(root))] = ['symlink', os.readlink(p)]
        elif p.is_file():
            result[str(p.relative_to(root))] = ['file', hashlib.sha256(p.read_bytes()).hexdigest()]
    return result


def migrate(source, destination, backup):
    source, destination, backup = [Path(p).expanduser().absolute() for p in (source,destination,backup)]
    if source.is_symlink() and source.resolve() == destination.resolve():
        return {'status':'already_migrated','dataDirectory':str(destination)}
    if not source.is_dir() or source.is_symlink():
        raise ValueError('Source must be the original data directory')
    if destination.exists() or destination.is_symlink() or backup.exists() or backup.is_symlink():
        raise ValueError('Destination/backup already exists; no data was changed')
    for p in (source/'jobs').glob('*.json'):
        if json.loads(p.read_text())['status'] not in ('complete','failed','cancelled','interrupted'):
            raise ValueError('A discussion is still running; finish or cancel it before migration')
    before = manifest(source)
    destination.parent.mkdir(parents=True,exist_ok=True)
    backup.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.council-migration-',dir=destination.parent))
    try:
        # Preserve symlinks as symlinks; do not crawl files outside a workspace.
        shutil.copytree(source,staging,dirs_exist_ok=True,symlinks=True)
        staging.chmod(0o700)
        if manifest(staging) != before or manifest(source) != before:
            raise ValueError('Data changed during migration; original remains untouched')
        staging.rename(destination)
        source.rename(backup)
        try:
            source.symlink_to(destination,target_is_directory=True)
        except OSError:
            backup.rename(source)
            raise
        return {'status':'migrated','files':len(before),'dataDirectory':str(destination),'backup':str(backup)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    print(json.dumps(migrate(args.source,args.destination,args.backup),ensure_ascii=False))
