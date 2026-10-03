"""Verified, per-suite kernel sources shared by isolated object builds."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def real_directory(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Expected real directory: ' + str(path))


def real_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected regular file: ' + str(path))


def checked_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise ValueError('Unsafe relative file path')
    parent = root
    real_directory(parent)
    for part in relative.parts[:-1]:
        parent /= part
        real_directory(parent)
    result = root / relative
    real_file(result)
    return result


@contextmanager
def locked(path, *, existing=False):
    real_directory(path.parent)
    flags = os.O_RDWR | os.O_NOFOLLOW
    if not existing:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'r+') as guard:
        if not stat.S_ISREG(os.fstat(guard.fileno()).st_mode):
            raise ValueError('Expected regular lock file')
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    if path.is_symlink():
        raise ValueError('Refusing symlink metadata')
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(value, sort_keys=True, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def inventory(tree):
    """Hash entries without following links; track owner execution, independent of umask."""
    real_directory(tree)
    entries = {}

    def visit(directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(tree).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries[relative] = ['link', os.readlink(path)]
            elif stat.S_ISDIR(mode):
                entries[relative] = ['directory']
                visit(path)
            elif stat.S_ISREG(mode):
                entries[relative] = ['file', mode & 0o100, sha256(path)]
            else:
                raise ValueError('Unexpected source entry: ' + str(path))

    visit(tree)
    return entries


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_spec(lock, manifest):
    return dict(schema=1, linux={key: lock['linux'][key] for key in
                                ('tag', 'tarball_sha256', 'defconfig_sha256')}, patches=manifest)


def ensure_source(root, work, archive, lock, manifest):
    """Call under work/.source-lock. Never trust a patch stamp alone."""
    real_directory(work)
    spec = source_spec(lock, manifest)
    identity = digest(spec)
    store = work / '.sources'
    store.mkdir(exist_ok=True)
    real_directory(store)
    entry = store / ('source-' + identity)
    entries = None
    if not entry.exists() and not entry.is_symlink():
        if sha256(archive) != lock['linux']['tarball_sha256']:
            raise ValueError('Locked archive hash mismatch')
        print('Preparing verified shared kernel source...', flush=True)
        with tempfile.TemporaryDirectory(prefix='.prepare-', dir=store) as temporary:
            stage = Path(temporary)
            source = stage / 'source'
            source.mkdir()
            subprocess.run(['tar', '-xJf', str(archive), '--strip-components=1', '-C', str(source)], check=True)
            subprocess.run(['python3', str(root / 'tools/kernel-inputs.py'), '--apply', str(source)],
                           check=True, stdout=subprocess.DEVNULL)
            if json.loads((source / '.gameshellneo-patches.json').read_text()) != manifest:
                raise ValueError('Patch queue changed during source preparation')
            entries = inventory(source)
            atomic_json(stage / 'metadata.json', dict(spec=spec, tree_sha256=digest(entries)))
            stage.rename(entry)
            sync_directory(store)
    real_directory(entry)
    if {p.name for p in entry.iterdir()} != {'source', 'metadata.json'}:
        raise ValueError('Unexpected cache contents')
    real_file(entry / 'metadata.json')
    metadata = json.loads((entry / 'metadata.json').read_text())
    if entries is None:
        entries = inventory(entry / 'source')
    if metadata != dict(spec=spec, tree_sha256=digest(entries)):
        raise ValueError('Shared kernel source verification failed')
    return entry / 'source', entries, metadata


def source_link(scratch, source):
    return os.path.relpath(source, scratch)


def verify_link(path, source):
    if not path.is_symlink() or os.readlink(path) != source_link(path.parent, source):
        raise ValueError('Unexpected shared source link: ' + str(path))


def attach_source(scratch, source, entries):
    if any((scratch / name).exists() or (scratch / name).is_symlink() for name in
           ('.source-retired', '.source-migration.json')):
        raise ValueError('Interrupted source compaction; rerun the compaction task first')
    path = scratch / 'source'
    if path.is_symlink():
        verify_link(path, source)
    elif path.exists():
        if inventory(path) != entries:
            raise ValueError('Legacy kernel source differs from locked source')
        # Only the explicit compaction task removes legacy copies.
    else:
        path.symlink_to(source_link(scratch, source), target_is_directory=True)
