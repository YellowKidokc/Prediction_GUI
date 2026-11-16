"""Create and use a local-disk environment, independent of the clone location."""
from pathlib import Path
import argparse
import hashlib
import os
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
GUI = (ROOT / 'requirements-david-os.txt').is_file()


def environment_dir():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    identity = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    result = Path(os.environ.get('DAVID_OS_VENV', base / 'david-os' / 'venvs' / (ROOT.name + '-' + identity))).expanduser().resolve()
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(result.anchor)) != 3:
            raise SystemExit('The venv must be on a local fixed disk. Set DAVID_OS_VENV to a local path.')
    elif Path('/proc/mounts').exists():
        mounts = []
        for row in Path('/proc/mounts').read_text().splitlines():
            fields = row.split()
            mount = Path(fields[1].replace('\\040', ' '))
            if result == mount or mount in result.parents:
                mounts.append((len(str(mount)), fields[2]))
        if mounts and max(mounts)[1] in {'nfs', 'nfs4', 'cifs', 'smbfs', 'fuse.sshfs', '9p'}:
            raise SystemExit('The venv path is on a network filesystem. Set DAVID_OS_VENV to local disk.')
    return result


def python_path():
    return environment_dir() / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def setup():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', action='store_true', help='GUI: skip optional inference libraries')
    parser.add_argument('--test', action='store_true', help='David-OS: install test dependencies')
    args = parser.parse_args()
    target = environment_dir()
    venv.EnvBuilder(with_pip=True).create(target)
    py = str(python_path())
    subprocess.run([py, '-m', 'pip', 'install', '--upgrade', 'pip'], check=True, cwd=ROOT)
    if GUI:
        install = [py, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-david-os.txt')]
        if not args.core:
            install += ['-r', str(ROOT / 'requirements.txt')]
    else:
        install = [py, '-m', 'pip', 'install', str(ROOT) + ('[test]' if args.test else '')]
    subprocess.run(install, check=True, cwd=ROOT)
    print(f'Environment: {target}\nRun: python run.py')


def run():
    py = python_path()
    if not py.is_file():
        raise SystemExit('Run python setup_env.py first.')
    args = sys.argv[1:] or (['gui/app.py'] if GUI else ['-m', 'fis', '--help'])
    raise SystemExit(subprocess.call([str(py), *args], cwd=ROOT, env=os.environ.copy()))
