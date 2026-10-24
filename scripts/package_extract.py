"""Standard-library-only, fail-closed extraction for the one-upload package."""

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


def file_sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def clean_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or
            '\\' in name or ':' in name or path.as_posix() != name):
        raise ValueError('Unsafe package path: ' + name)
    return path


def no_symlinks(path):
    for item in (path,) + tuple(path.parents):
        if item.is_symlink():
            raise ValueError('Refusing symlink destination: ' + str(item))


def unpack_package(archive, project, manifest_sha256):
    """Validate all entries before writing; reuse identical files, never clobber."""
    archive, project = Path(archive), Path(project).absolute()
    if not archive.is_file():
        raise FileNotFoundError('Download the full GitHub Release asset first: ' + str(archive))
    no_symlinks(project)
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [entry.filename for entry in infos]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP entries')
        for entry in infos:
            clean_name(entry.filename)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unexpected directory/link ZIP entry')
        manifest_bytes = bundle.read('package_manifest.json')
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
            raise ValueError('Package manifest SHA-256 mismatch; do not continue')
        manifest = json.loads(manifest_bytes)
        entries = manifest['files']
        checks = {item['path']: item for item in entries}
        if len(checks) != len(entries):
            raise ValueError('Duplicate manifest paths')
        extras = {'package_manifest.json', 'WBCAttPlus_Setup.ipynb', 'README.md'}
        if set(names) != set(checks) | extras:
            raise ValueError('ZIP members differ from the fixed package manifest')
        # Validate CRC, size, digest and all existing destination conflicts first.
        for entry in infos:
            target = project.joinpath(*clean_name(entry.filename).parts)
            no_symlinks(target)
            expected = checks.get(entry.filename)
            value, size = hashlib.sha256(), 0
            with bundle.open(entry) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
                    size += len(block)
            digest = value.hexdigest()
            if expected and (size != expected['size_bytes'] or digest != expected['sha256']):
                raise ValueError('Payload checksum failed: ' + entry.filename)
            if target.exists() and (not target.is_file() or file_sha256(target) != digest):
                raise ValueError('Existing file differs and was preserved: ' + str(target))
        reused = 0
        for entry in infos:
            target = project.joinpath(*clean_name(entry.filename).parts)
            if target.exists():
                reused += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, target.open('xb') as destination:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    destination.write(block)
    print('Package verified and unpacked:', project, flush=True)
    print('Identical existing files reused:', reused, flush=True)
    return project
