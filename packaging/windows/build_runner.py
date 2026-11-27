"""Build the Windows installer archive from an ordinary Windows CPython with Tcl/Tk."""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import distribution
import json
from pathlib import Path
import platform
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

SOURCE = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent
DISCARD_LIBRARY = shutil.ignore_patterns('__pycache__', 'site-packages', 'ensurepip', 'idlelib', 'turtledemo', 'test', 'tests')


def build(output: Path) -> None:
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64') or sys.version_info < (3, 10):
        raise ValueError('Run the build with 64-bit Windows CPython 3.10+ and Tcl/Tk.')
    import tkinter  # noqa: F401 — require the Windows Tcl/Tk binaries for the shortcut.

    python = Path(sys.base_prefix)
    version = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    abi = f'python{sys.version_info.major}{sys.version_info.minor}'
    with TemporaryDirectory(prefix='kolos-build-') as name:
        root = Path(name) / 'Kolos Setup'
        payload = root / 'payload'
        runtime = payload / 'runtime'
        runtime.mkdir(parents=True)
        binaries = ('python.exe', 'pythonw.exe', 'python3.dll', f'{abi}.dll', 'LICENSE.txt')
        for file in binaries:
            shutil.copy2(python / file, runtime / file)
        for file in python.glob('vcruntime*.dll'):
            shutil.copy2(file, runtime / file.name)
        shutil.copytree(python / 'Lib', runtime / 'Lib', ignore=DISCARD_LIBRARY)
        shutil.copytree(python / 'DLLs', runtime / 'DLLs', ignore=DISCARD_LIBRARY)
        shutil.copytree(python / 'tcl', runtime / 'tcl')
        (runtime / f'{abi}._pth').write_text('Lib\nDLLs\npackages\n../app\n', encoding='ascii')
        pillow = distribution('Pillow')  # Required by the existing StateEngine.
        for file in pillow.files or ():
            if file.parts[0] not in ('PIL', 'pillow.libs') and not file.parts[0].lower().endswith('.dist-info'):
                continue
            if '__pycache__' in file.parts:
                continue
            target = runtime / 'packages' / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pillow.locate_file(file), target)

        app = payload / 'app'
        for file in sorted((SOURCE / 'kolos_states').rglob('*.py')):
            target = app / file.relative_to(SOURCE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
        shutil.copytree(SOURCE / 'examples' / 'task_runner', app / 'examples' / 'task_runner')
        shutil.copy2(SOURCE / 'LICENSE', payload / 'LICENSE.txt')
        shutil.copy2(SOURCE / 'docs' / 'TASK_RUNNER.md', root / 'README.md')
        for file in ('Install.cmd', 'Install.ps1'):
            shutil.copy2(SCRIPTS / file, root / file)
        shutil.copy2(SCRIPTS / 'Kolos.cmd', payload / 'Kolos.cmd')

        fingerprint = sha256()
        for file in sorted(item for item in root.rglob('*') if item.is_file()):
            fingerprint.update(file.relative_to(root).as_posix().encode() + b'\0' + sha256(file.read_bytes()).digest())
        (payload / 'build.json').write_text(json.dumps({'version': f'{version}-{fingerprint.hexdigest()[:12]}'}), encoding='ascii')
        output.parent.mkdir(parents=True, exist_ok=True)
        scratch = output.with_name(output.name + '.tmp')
        try:
            with ZipFile(scratch, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
                for file in sorted(item for item in root.rglob('*') if item.is_file()):
                    archive.write(file, file.relative_to(root.parent))
            scratch.replace(output)
        finally:
            scratch.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output.resolve())
