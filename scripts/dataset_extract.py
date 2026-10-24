"""Verify bundled official assets, safely extract, then audit the target machine.

No training packages or GPU are needed. Never overwrites conflicting data.
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from audit_utils import digest_file
from audit_scope import PACKAGE_SCOPE


ARCHIVE_SHA256 = '2a1730ce3a772e34bd1089b1aec44597e75b94ab0d26fbe697cb1189a9155090'


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive/manifest path: '+name)
    return path


def ensure_no_links(path, stop):
    current = path
    while True:
        if current.is_symlink():
            raise ValueError('Refusing symlink destination: %s' % current)
        if current == stop:
            break
        if current.parent == current:
            raise ValueError('Destination is outside dataset root')
        current = current.parent


def extract_release(root):
    root = Path(root).absolute()
    manifest = json.loads((root/'download_manifest.json').read_text(encoding='utf-8'))
    for asset in manifest['assets']:
        path = root.joinpath(*safe_relative(asset['path']).parts)
        if not path.is_file() or path.stat().st_size != asset['size_bytes'] or digest_file(path) != asset['sha256']:
            raise ValueError('Source asset checksum failed: %s' % path)
    archive = root/'archives'/'pbcseg_final_v1.tar'
    if digest_file(archive) != ARCHIVE_SHA256:
        raise ValueError('Official archive SHA-256 mismatch')
    destination = root/'data'/'PBC'
    ensure_no_links(destination,root)
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive,'r:') as tar:
        members = tar.getmembers()
        seen = set()
        files = []
        for member in members:
            relative = safe_relative(member.name)
            if relative.parts == ('pbcseg_final_v1',) and member.isdir():
                continue
            if len(relative.parts) != 2 or relative.parts[0] != 'pbcseg_final_v1' or not member.isfile():
                raise ValueError('Unexpected archive member: '+member.name)
            if relative.name in seen:
                raise ValueError('Duplicate archive member: '+member.name)
            seen.add(relative.name)
            if not (relative.name.endswith('.jpg') or relative.name.endswith('_mask.png')):
                raise ValueError('Unexpected data extension: '+member.name)
            files.append((member,relative))
        if len(files) != 20596:
            raise ValueError('Expected 20596 image/mask files, got %d' % len(files))
        reused = 0
        for index,(member,relative) in enumerate(files,1):
            target = destination.joinpath(*relative.parts)
            ensure_no_links(target,root)
            target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(member) as source:
                contents = source.read()
            if len(contents) != member.size:
                raise ValueError('Short archive member: '+member.name)
            expected = hashlib.sha256(contents).hexdigest()
            if target.exists():
                if not target.is_file() or digest_file(target) != expected:
                    raise ValueError('Existing file differs; preserved without overwrite: '+str(target))
                reused += 1
            else:
                # Exclusive creation, so a concurrent deployment cannot be overwritten.
                with target.open('xb') as stream:
                    stream.write(contents)
            if index % 4000 == 0:
                print('Verified/extracted %d/%d files' % (index,len(files)),flush=True)
    print('Extraction complete; identical existing files reused:',reused,flush=True)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument('--root',type=Path,default=project/'datasets'/'WBCAttPlus')
    parser.add_argument('--output',type=Path,default=project/'output'/'pdf'/'wbcattplus_audit')
    parser.add_argument('--site',choices=('server','local'),default='server')
    args = parser.parse_args()
    if args.site == 'server' and platform.system() != 'Linux':
        raise ValueError('Expected the Linux Jupyter server; use --site local for a local dry run')
    count = extract_release(args.root)
    subprocess.run([sys.executable,str(project/'scripts'/'dataset_audit.py'),'--root',str(args.root.absolute()),
                    '--output',str(args.output.absolute()),'--site',args.site],check=True)
    summary_path = args.output/'audit_summary.json'
    report = json.loads(summary_path.read_text(encoding='utf-8'))
    if report['integrity_status'] != 'PASS' or report['fully_valid_image_mask_pairs'] != 10298:
        raise ValueError('Full audit failed; no acceptance receipt written')
    receipt = {'status':'DEPLOYMENT_FILE_INTEGRITY_PASS','execution_site':args.site,
               'hostname':socket.gethostname(),'platform':platform.platform(),
               'created_at_utc':datetime.now(timezone.utc).isoformat(),'dataset_root':str(args.root.absolute()),
               'verified_extracted_file_count':count,'valid_image_mask_pairs':10298,
               'archive_sha256':ARCHIVE_SHA256,'audit_summary_sha256':digest_file(summary_path),
               'source_grouping_status':report['source_grouping']['status'],
               'package_scope':PACKAGE_SCOPE,'not_implemented_features':report['not_implemented_features'],
               'strict_split_created':False,'note':'File integrity only; source independence remains unverified.'}
    receipt_name = 'server_deployment_receipt.json' if args.site == 'server' else 'local_deployment_receipt.json'
    (args.output/receipt_name).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Acceptance receipt:',args.output/receipt_name,flush=True)


if __name__ == '__main__':
    main()
