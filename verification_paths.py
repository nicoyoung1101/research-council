"""Resolve report hash entries without treating prose annotations as filenames.

Independent verification helpers may import report_hash(line, roots). This only
reads existing filenames; missing or ambiguous entries are errors, never skipped.
"""
from pathlib import Path
import re


def report_hash(line, roots):
    match = re.fullmatch(r'\s*-\s+(.+?)\s+`?([a-fA-F0-9]{64})`?\s*', line)
    if not match:
        return None
    description, digest = match.groups()
    roots = [Path(root).resolve() for root in roots]
    if description.startswith('`'):
        quoted = re.match(r'`([^`]+)`(?:\s|（|\(|$)', description)
        if not quoted:
            raise ValueError('Malformed quoted hash path')
        names = [quoted[1]]
    else:
        # Spaces and annotations can be part of genuine names. Use an existing
        # unique file, and reject ambiguity rather than guessing the shortest.
        names = {description.strip()}
        names.update(description[:m.start()].strip() for m in re.finditer(r'\s|（|\(', description))
    candidates = set()
    for name in names:
        if not name:
            continue
        raw = Path(name)
        for root in roots:
            path = (raw if raw.is_absolute() else root/raw).resolve()
            if path.is_relative_to(root) and path.is_file():
                candidates.add(path)
    if len(candidates) != 1:
        raise ValueError('Missing or ambiguous report hash path: '+description)
    return next(iter(candidates)), digest.lower()
