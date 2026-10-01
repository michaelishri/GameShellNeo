"""Resolve a checkpoint's own manifests and reverify its retained artifacts."""
import gzip
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_expansion(path, expected_bytes, expected_sha256):
    """Check a gzip's complete image without materializing a second raw copy."""
    if type(expected_bytes) is not int or expected_bytes <= 0:
        raise ValueError('Invalid uncompressed image size')
    checksum, size = hashlib.sha256(), 0
    try:
        with gzip.open(path, 'rb') as stream:
            while data := stream.read(min(4 * 1024 * 1024, expected_bytes - size + 1)):
                size += len(data)
                if size > expected_bytes:
                    raise ValueError('Recovery archive expands beyond the recorded image size')
                checksum.update(data)
    except (OSError, EOFError) as error:
        raise ValueError('Invalid recovery gzip archive') from error
    if size != expected_bytes or checksum.hexdigest() != expected_sha256:
        raise ValueError('Recovery archive expansion does not match the image')


def safe_path(root, value):
    path = root / value
    if Path(value).is_absolute() or '..' in Path(value).parts or path.is_symlink():
        raise ValueError('Invalid recovery path')
    path.resolve().relative_to(root.resolve())
    return path


def resolve(root, name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name):
        raise ValueError('Supply a checkpoint NAME using lowercase letters, numbers and hyphens')
    directory = safe_path(root / '.local/recovery', name)
    hashes = json.loads((directory / 'metadata-sha256.json').read_text())
    required = {'artifacts.json', 'verification.json', 'transfer.json', 'image-manifest.json',
                'kernel-completed.json', 'sources.lock.json', 'kernel.config'}
    if not required <= hashes.keys():
        raise ValueError('Incomplete recovery metadata')
    for path, expected in hashes.items():
        if digest(safe_path(directory, path)) != expected:
            raise ValueError('Recovery metadata checksum mismatch: ' + path)
    def read(filename):
        return json.loads((directory / filename).read_text())
    artifacts, report, transfer = read('artifacts.json'), read('verification.json'), read('transfer.json')
    image, kernel, lock = read('image-manifest.json'), read('kernel-completed.json'), read('sources.lock.json')
    raw = safe_path(root / '.local/artifacts', Path(artifacts['image']).name)
    compressed = safe_path(root / '.local/flash', Path(artifacts['compressed']).name)
    if (str(raw.relative_to(root)) != artifacts['image'] or
            str(compressed.relative_to(root)) != artifacts['compressed'] or
            report['offline_verification'] != 'passed' or image['sources'] != lock or
            image['version'] != lock['image_version'] or image['kernel'] != kernel['kernel_release'] or
            report['image'] != raw.name or transfer['image'] != raw.name or
            transfer['compressed_file'] != compressed.name or
            transfer['image_bytes'] != report['bytes'] or
            transfer['image_sha256'] != report['sha256'] or
            artifacts['image_sha256'] != report['sha256'] or
            artifacts['compressed_sha256'] != transfer['compressed_sha256'] or
            compressed.stat().st_size != transfer['compressed_bytes'] or
            digest(compressed) != transfer['compressed_sha256']):
        raise ValueError('Recovery artifacts and their matching manifests do not agree')
    if raw.exists():
        # A present but damaged raw copy is still an error, never a silent fallback.
        if raw.stat().st_size != report['bytes'] or digest(raw) != report['sha256']:
            raise ValueError('Recovery raw image does not match its manifest')
    else:
        verify_expansion(compressed, report['bytes'], report['sha256'])
    return compressed, directory / 'transfer.json', transfer
