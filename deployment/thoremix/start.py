"""Installed entrypoint; establishes only this bundle's import and binary paths."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'source'))
os.environ['PYTHONPATH'] = str(root / 'source')
os.environ['THOREMIX_ROOT'] = str(root)
os.environ['PYTHONUTF8'] = '1'
os.environ['PATH'] = str(root / 'runtime' / 'bin') + os.pathsep + os.environ.get('PATH', '')
args = sys.argv[1:] or ['desktop']
if args[0] in {'-h', '--help'}:
    from agent.thoremix.cli import main
    raise SystemExit(main(['--root', str(root), *args]))
args[0] = args[0].removeprefix('--')
(root / 'logs').mkdir(exist_ok=True)
with (root / 'logs' / 'launcher.log').open('a', encoding='utf-8', buffering=1) as log:
    sys.stdout = log
    sys.stderr = log
    try:
        from agent.thoremix.cli import main
        raise SystemExit(main(['--root', str(root), *args]))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - the desktop log must not expose credentials from provider errors.
        # Third party exception messages can include signed URLs.
        print('Launcher failed: ' + type(exc).__name__)
        raise SystemExit(2)
