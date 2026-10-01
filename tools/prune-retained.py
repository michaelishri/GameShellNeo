#!/usr/bin/env python3
"""Preview/prune old raw images and kernel snapshots, keeping verified recovery."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from recovery_image import digest, resolve, verify_expansion

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(r'GameShellNeo-(\d+)\.(\d+)\.(\d+)-diagnostic\.(\d+)-cpi31-([0-9a-f]{12})\.img')
SNAPSHOT = re.compile(r'\d{8}T\d{6}Z-\d+')
SOURCE = re.compile(r'linux-\d+\.\d+\.\d+')


def real(path, directory=False):
    if path.is_symlink() or not (path.is_dir() if directory else path.is_file()):
        raise ValueError('Expected a real ' + ('directory: ' if directory else 'file: ') + str(path))


def plan(root, keep):
    if type(keep) is not int or keep < 2:
        raise ValueError('KEEP must be at least 2')
    for name in ('.local', '.local/build', '.local/artifacts', '.local/flash', '.local/previous-kernels'):
        real(root / name, True)
    artifacts = root / '.local/artifacts'
    real(artifacts / 'verification.json')
    current = json.loads((artifacts / 'verification.json').read_text())
    if current.get('offline_verification') != 'passed' or not IMAGE.fullmatch(current['image']):
        raise ValueError('Expected a completed verified current image')
    real(artifacts / current['image'])
    images = list(artifacts.glob('*.img'))
    for path in images:
        if not IMAGE.fullmatch(path.name):
            raise ValueError('Unexpected raw image name: ' + path.name)
        real(path)
    images.sort(key=lambda p: (*map(int, IMAGE.fullmatch(p.name).groups()[:4]),
                               p.stat().st_mtime_ns, p.name), reverse=True)
    retained_images = set(images[:keep]) | {artifacts / current['image']}
    snapshots = sorted((root / '.local/previous-kernels').iterdir(), reverse=True)
    for path in snapshots:
        if not SNAPSHOT.fullmatch(path.name):
            raise ValueError('Unexpected kernel snapshot name: ' + path.name)
        real(path, True)
        children = list(path.iterdir())
        sources = [p for p in children if SOURCE.fullmatch(p.name)]
        if len(sources) != 1 or {p.name for p in children} - {
                sources[0].name, 'kernel', 'kernel-install', 'artifact-metadata.tar', 'kernel-completed.json'}:
            raise ValueError('Unexpected kernel snapshot layout: ' + path.name)
        for directory in (sources[0], path / 'kernel', path / 'kernel-install'):
            real(directory, True)
        real(path / 'artifact-metadata.tar')
    return dict(images=[p for p in images if p not in retained_images],
                retained_images=sorted(retained_images), snapshots=snapshots[keep:],
                retained_snapshots=snapshots[:keep])


def allocated(path):
    """Allocated blocks; count hard links once within each candidate."""
    seen, size = set(), 0
    def count(p):
        nonlocal size
        stat = p.lstat()
        key = stat.st_dev, stat.st_ino
        if key not in seen:
            seen.add(key)
            size += stat.st_blocks * 512
    count(path)
    if path.is_dir():
        for directory, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                count(Path(directory) / name)
    return size


def preserve_metadata(snapshot, destination):
    """Save compact provenance before removing reproducible source/output trees."""
    files = {'artifact-metadata.tar': snapshot / 'artifact-metadata.tar'}
    source = next(p for p in snapshot.iterdir() if SOURCE.fullmatch(p.name))
    for name, path in (
            ('kernel-completed.json', snapshot / 'kernel-completed.json'),
            ('kernel.config', snapshot / 'kernel/.config'),
            ('kernel.release', snapshot / 'kernel/include/config/kernel.release'),
            ('patches.json', source / '.gameshellneo-patches.json')):
        if path.exists() or path.is_symlink():
            real(path)
            files[name] = path
    hashes = {name: digest(path) for name, path in files.items()}
    if destination.exists() or destination.is_symlink():
        real(destination, True)
        for name, checksum in hashes.items():
            real(destination / name)
            if digest(destination / name) != checksum:
                raise ValueError('Retained kernel metadata differs: ' + name)
        return hashes
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / 'metadata'
        stage.mkdir()
        for name, path in files.items():
            shutil.copy2(path, stage / name)
            if digest(stage / name) != hashes[name]:
                raise ValueError('Kernel metadata copy failed verification')
        (stage / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
        stage.rename(destination)
    return hashes


def update_catalog(root, images):
    """The bundle's checksum list should describe the retained artifacts."""
    catalog = root / '.local/artifacts/SHA256SUMS'
    if not catalog.exists() and not catalog.is_symlink():
        return
    real(catalog)
    names = {path.name for path in images}
    lines = catalog.read_text().splitlines()
    if any(not re.fullmatch(r'[0-9a-f]{64}  .+', line) for line in lines):
        raise ValueError('Unexpected artifact checksum catalog')
    temporary = catalog.with_suffix('.retention-part')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('A prior checksum-catalog update needs inspection')
    with temporary.open('x') as stream:
        stream.write(''.join(line + '\n' for line in lines if line.split('  ', 1)[1] not in names))
    temporary.replace(catalog)


def prune(root, keep=3, apply=False):
    for directory in (root / '.local', root / '.local/build'):
        real(directory, True)
    lock = root / '.local/build/workflow.lock'
    real(lock)
    with lock.open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = plan(root, keep)
        result = dict(keep=keep, apply=apply,
                      **{key: [str(p.relative_to(root)) for p in paths]
                         for key, paths in selected.items()}, removed=[], verified_images=[])
        result['candidate_allocated_bytes'] = {
            str(p.relative_to(root)): allocated(p) for key in ('images', 'snapshots') for p in selected[key]}
        print(json.dumps(result, indent=2), flush=True)
        if not apply:
            return result
        records = root / '.local/retention'
        records.mkdir(mode=0o700, exist_ok=True)
        real(records, True)
        metadata = records / 'kernel-metadata'
        metadata.mkdir(mode=0o700, exist_ok=True)
        real(metadata, True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        report = records / ('prune-' + stamp + '.json')
        def save():
            temporary = report.with_suffix('.json.part')
            temporary.write_text(json.dumps(result, indent=2) + '\n')
            temporary.replace(report)
        result['free_bytes_before'] = shutil.disk_usage(root).free
        save()
        try:
            # Check every named checkpoint before deleting any artifact. Pruned
            # checkpoints resolve through their verified compressed image.
            recovery = root / '.local/recovery'
            if recovery.exists() or recovery.is_symlink():
                real(recovery, True)
                for checkpoint in sorted(recovery.iterdir()):
                    resolve(root, checkpoint.name)
            for raw in selected['images']:
                compressed = root / '.local/flash' / (raw.name + '.gz')
                real(compressed)
                size, checksum = raw.stat().st_size, digest(raw)
                if not checksum.startswith(IMAGE.fullmatch(raw.name)[5]):
                    raise ValueError('Raw image filename checksum mismatch: ' + raw.name)
                verify_expansion(compressed, size, checksum)
                result['verified_images'].append(dict(
                    image=str(raw.relative_to(root)), image_bytes=size, image_sha256=checksum,
                    compressed=str(compressed.relative_to(root)), compressed_bytes=compressed.stat().st_size,
                    compressed_sha256=digest(compressed)))
                save()
                print('Verified recovery archive:', raw.name, flush=True)
            result['kernel_metadata'] = {}
            for snapshot in selected['snapshots']:
                result['kernel_metadata'][snapshot.name] = preserve_metadata(snapshot, metadata / snapshot.name)
                save()
            # Verification and provenance preservation finish before any deletion.
            # Publishing the retained subset first also leaves a valid catalog
            # if unlink/rmtree is interrupted; extra old files can be retried.
            update_catalog(root, selected['images'])
            for raw in selected['images']:
                raw.unlink()
                result['removed'].append(str(raw.relative_to(root)))
                save()
            for snapshot in selected['snapshots']:
                shutil.rmtree(snapshot)
                result['removed'].append(str(snapshot.relative_to(root)))
                save()
            result['completed'] = True
        finally:
            result['free_bytes_after'] = shutil.disk_usage(root).free
            save()
        print('Cleanup evidence:', report.relative_to(root), flush=True)
        return result


def main():
    os.umask(0o077)
    apply = os.environ.get('NEO_RETENTION_APPLY', '0')
    if apply not in ('0', '1'):
        raise ValueError('APPLY must be 0 or 1')
    prune(ROOT, int(os.environ.get('NEO_RETENTION_KEEP', '3')), apply == '1')


if __name__ == '__main__':
    main()
