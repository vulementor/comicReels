"""Local validation must exercise current edits, additions and removals, not stale HEAD."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def module():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'source_snapshot.py'
    assert path.exists(), 'Working-tree snapshot helper is required'
    spec = importlib.util.spec_from_file_location('source_snapshot', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init')
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / '.gitignore').write_text('.env\nprofiles/\n')
    (root / 'app.py').write_text('old code')
    (root / 'removed.py').write_text('remove me')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'baseline')
    return root


def test_snapshot_includes_edits_intent_to_add_and_removals(repository, tmp_path):
    root = repository
    (root / 'app.py').write_text('new code')
    (root / 'added.py').write_text('new module')
    (root / 'removed.py').unlink()
    (root / '.env').write_text('secret')
    git(root, 'add', '-N', 'added.py')
    destination = tmp_path / 'snapshot'
    result = module().create_snapshot(root, destination)
    assert (destination / 'app.py').read_text() == 'new code'
    assert (destination / 'added.py').read_text() == 'new module'
    assert not (destination / 'removed.py').exists()
    assert not (destination / '.env').exists()
    assert not (destination / '.git').exists()
    assert result['source_kind'] == 'working_tree'
    assert result['base_sha'] == git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    assert result['file_count'] == 3
    manifest = json.loads((destination / '.comicreels-source.json').read_text())
    assert result['source_digest'] == manifest['source_digest']
    (root / 'app.py').write_text('third version')
    assert module().source_manifest(root)['source_digest'] != result['source_digest']


def test_untracked_source_cannot_be_silently_omitted(repository, tmp_path):
    (repository / 'new.py').write_text('untracked implementation')
    with pytest.raises(ValueError, match='UNTRACKED_SOURCE'):
        module().create_snapshot(repository, tmp_path / 'snapshot')


def test_snapshot_refuses_existing_destination(repository, tmp_path):
    destination = tmp_path / 'snapshot'
    destination.mkdir()
    (destination / 'keep.txt').write_text('keep')
    with pytest.raises(ValueError, match='DESTINATION_EXISTS'):
        module().create_snapshot(repository, destination)
    assert (destination / 'keep.txt').read_text() == 'keep'


def test_snapshot_cannot_write_inside_source(repository):
    with pytest.raises(ValueError, match='DESTINATION_INSIDE_SOURCE'):
        module().create_snapshot(repository, repository / 'snapshot')
