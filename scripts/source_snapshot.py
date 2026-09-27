"""Snapshot explicitly tracked working files for local validation, without touching runtime.

New implementation files must be staged or registered with git add -N first. Untracked files
are never swept into a deployment, nor silently omitted from its validation claims.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def _git(source, *args):
    return subprocess.run(['git', '-C', str(source), *args], check=True,
                          capture_output=True).stdout


def _files(source):
    if _git(source, 'ls-files', '--others', '--exclude-standard', '-z'):
        raise ValueError('UNTRACKED_SOURCE: inspect new files and use git add -N before snapshot')
    names = sorted(set(_git(source, 'ls-files', '--cached', '-z').decode('utf-8').split('\0')) - {''})
    files = {}
    for name in names:
        path = source / name
        if path.is_symlink():
            raise ValueError('SYMLINK_SOURCE_NOT_SUPPORTED')
        if not path.exists():
            continue  # Respect working-tree deletions.
        if not path.resolve().is_relative_to(source) or not path.is_file():
            raise ValueError('NON_FILE_SOURCE_NOT_SUPPORTED')
        files[name] = path
    return files


def source_manifest(source):
    source = Path(source).resolve(strict=True)
    files = {name: hashlib.sha256(path.read_bytes()).hexdigest()
             for name, path in _files(source).items()}
    payload = json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'source_kind': 'working_tree',
                'base_sha': _git(source, 'rev-parse', 'HEAD').decode().strip(),
                'source_digest': hashlib.sha256(payload).hexdigest(),
                'file_count': len(files), 'files': files}


def create_snapshot(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.is_relative_to(source):
        raise ValueError('DESTINATION_INSIDE_SOURCE')
    if destination.exists():
        raise ValueError('DESTINATION_EXISTS')
    before = source_manifest(source)
    destination.mkdir(parents=True, exist_ok=False)
    for name, expected in before['files'].items():
        content = (source / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('SOURCE_CHANGED_DURING_SNAPSHOT')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    after = source_manifest(source)
    if before != after:
        raise ValueError('SOURCE_CHANGED_DURING_SNAPSHOT')
    (destination / '.comicreels-source.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    return {key: value for key, value in before.items() if key != 'files'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    result = create_snapshot(args.source, args.destination) if args.destination else source_manifest(args.source)
    print(json.dumps({key: value for key, value in result.items() if key != 'files'}))
