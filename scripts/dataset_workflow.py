"""Offline audit workflow after downloading the full GitHub Release package.

Local dry runs must be explicitly labelled and never produce a server receipt.
Unsupported source splitting, granule pixel masks, and physical calibration are
notes only: this workflow never tries to infer them or writes new splits.
"""

import argparse
import json
import os
import platform
import shlex
import socket
import subprocess
import sys
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from package_extract import clean_name, file_sha256, no_symlinks
from dataset_extract import ARCHIVE_SHA256, extract_release
from audit_scope import PACKAGE_SCOPE


def run_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:8]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(str(temporary), str(path))


def preflight(project, site='server'):
    project = Path(project).absolute()
    no_symlinks(project)
    if site == 'server':
        if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
            raise RuntimeError('Select the Linux x86_64 remote Jupyter kernel, not Windows/local Python')
        if sys.version_info[:2] != (3, 9):
            raise RuntimeError('Select Python (wbcattplus server), Python 3.9; do not use base Python 3.13')
        expected = Path('/home/jovyan/work/envs/wbcattplus').resolve()
        if Path(sys.prefix).resolve() != expected:
            raise RuntimeError('Wrong kernel/environment prefix: ' + sys.prefix)
        libc, libc_version = platform.libc_ver()
        if libc != 'glibc' or tuple(int(n) for n in libc_version.split('.')[:2]) < (2, 28):
            raise RuntimeError('Offline Pillow wheel requires glibc >= 2.28 (your reported Ubuntu 24.04 meets this)')
    print('Execution site:', site, '| Python:', sys.version.split()[0], '| Executable:', sys.executable, flush=True)
    print('Project:', project, flush=True)
    return project


def verify_package(project):
    project = Path(project)
    manifest = json.loads((project / 'package_manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path = project.joinpath(*clean_name(entry['path']).parts)
        no_symlinks(path)
        if (not path.is_file() or path.stat().st_size != entry['size_bytes'] or
                file_sha256(path) != entry['sha256']):
            raise ValueError('Package payload missing/modified: ' + str(path))
    archive = project / 'datasets/WBCAttPlus/archives/pbcseg_final_v1.tar'
    if file_sha256(archive) != ARCHIVE_SHA256:
        raise ValueError('Official data archive SHA-256 mismatch')
    print('Payload SHA-256 checks: PASS (%d files)' % len(manifest['files']), flush=True)
    return manifest


def offline_install_command(project):
    project = Path(project)
    return [sys.executable, '-u', '-m', 'pip', 'install', '--no-index',
            '--find-links', str(project / 'wheelhouse'), '--only-binary=:all:',
            '--disable-pip-version-check', '--no-input',
            '-r', str(project / 'requirements.txt')]


def run_logged(project, command, label):
    project = Path(project)
    logs = project / 'output/logs'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / (run_id() + '_' + label + '.log')
    tail = deque(maxlen=40)
    print('Log:', log, flush=True)
    environment = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONUTF8='1')
    with log.open('w', encoding='utf-8') as stream:
        stream.write('COMMAND: ' + shlex.join([str(arg) for arg in command]) + '\n')
        stream.flush()
        with subprocess.Popen([str(arg) for arg in command], cwd=str(project), env=environment,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace', bufsize=1) as process:
            for line in process.stdout:
                print(line.rstrip(), flush=True)
                stream.write(line)
                stream.flush()
                tail.append(line.rstrip())
            code = process.wait()
    if code:
        raise RuntimeError('Step failed: %s; exit=%d\nFull log: %s\nLast output:\n%s' %
                           (label, code, log, '\n'.join(tail)))
    return log


def install(project):
    preflight(project, 'server')
    verify_package(project)
    return run_logged(project, offline_install_command(project), 'offline_install')


def test(project):
    return run_logged(project, [sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 'tests')


def audit(project, site='server', no_pdf=False):
    project = preflight(project, site)
    identity = run_id()
    output = project / 'output/pdf/runs' / identity
    output.mkdir(parents=True, exist_ok=False)
    state = {'status': 'RUNNING', 'run_id': identity, 'execution_site': site,
             'output': str(output), 'strict_split_created': False}
    latest = project / 'output/latest_run.json'
    write_json(latest, state)
    try:
        verify_package(project)
        command = [sys.executable, '-u', str(project / 'scripts/dataset_audit.py'),
                   '--root', str(project / 'datasets/WBCAttPlus'), '--output', str(output), '--site', site]
        if no_pdf:
            command.append('--no-pdf')
        log = run_logged(project, command, 'audit')
        summary_path = output / 'audit_summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if summary['integrity_status'] != 'PASS' or summary['fully_valid_image_mask_pairs'] != 10298:
            raise ValueError('Data integrity/valid-pair count failed; no acceptance receipt')
        if summary.get('package_scope') != PACKAGE_SCOPE:
            raise ValueError('Wrong report scope; expected supported-only audit')
        if summary['source_grouping']['strict_split_created'] or any(
                item['status'] != 'NOT_IMPLEMENTED' for item in summary['not_implemented_features']):
            raise ValueError('Unsupported features must remain unimplemented, not silently estimated')
        versions = {}
        for name in ('numpy', 'Pillow', 'reportlab', 'pypdfium2', 'pickleshare', 'chardet'):
            try:
                versions[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                versions[name] = 'NOT_INSTALLED'
        if site == 'server':
            for line in (project / 'requirements.txt').read_text(encoding='utf-8').splitlines():
                if '==' in line and not line.startswith('#'):
                    name, version = line.strip().split('==')
                    if versions.get(name) != version:
                        raise RuntimeError('Dependency version mismatch; rerun offline install: ' + name)
        receipt = {**state, 'status': 'FILE_INTEGRITY_PASS', 'hostname': socket.gethostname(),
                   'platform': platform.platform(), 'python': sys.version.split()[0], 'versions': versions,
                   'archive_sha256': ARCHIVE_SHA256, 'audit_summary_sha256': file_sha256(summary_path),
                   'manifest_sha256': file_sha256(project / 'package_manifest.json'),
                   'valid_image_mask_pairs': 10298, 'pdf_created': not no_pdf,
                   'source_grouping_status': summary['source_grouping']['status'],
                   'package_scope': PACKAGE_SCOPE,
                   'not_implemented_features': summary['not_implemented_features'],
                   'official_split_leakage_status': summary['official_split_leakage_status'],
                   'note': 'File integrity only. Not proof of patient/slide independence or training completion.'}
        receipt_path = output / (site + '_deployment_receipt.json')
        write_json(receipt_path, receipt)
        state.update(status='PASS', receipt=str(receipt_path), log=str(log),
                     source_grouping_status=receipt['source_grouping_status'],
                     official_split_leakage_status=receipt['official_split_leakage_status'])
        write_json(latest, state)
        print('FILE INTEGRITY: PASS (supported-only scope). Unsupported features: notes only.', flush=True)
        print('Receipt:', receipt_path, flush=True)
        return output
    except BaseException as error:
        state.update(status='FAILED', error=str(error))
        write_json(latest, state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('check', 'verify', 'extract', 'install', 'test', 'audit', 'run', 'status'))
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--site', choices=('server', 'local'), default='server')
    parser.add_argument('--skip-install', action='store_true', help='LOCAL dry runs only')
    parser.add_argument('--no-pdf', action='store_true', help='Diagnostic/local run; not the full deliverable')
    args = parser.parse_args()
    project = preflight(args.project, args.site)
    if args.skip_install and args.site != 'local':
        raise ValueError('--skip-install is reserved for explicit local dry runs')
    if args.step in ('verify', 'extract', 'run'):
        verify_package(project)
    if args.step in ('extract', 'run'):
        extract_release(project / 'datasets/WBCAttPlus')
    if args.step in ('install', 'run') and not args.skip_install:
        if args.site != 'server':
            raise ValueError('Linux CPython 3.9 wheels cannot be installed into a local Windows/Python 3.12 runtime')
        install(project)
    if args.step in ('test', 'run'):
        test(project)
    if args.step in ('audit', 'run'):
        audit(project, args.site, args.no_pdf)
    if args.step == 'status':
        path = project / 'output/latest_run.json'
        print(path.read_text(encoding='utf-8') if path.exists() else 'No audit run yet')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
