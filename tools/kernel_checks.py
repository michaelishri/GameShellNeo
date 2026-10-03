"""Shared locked-source and isolated kernel-object checks; never access devices."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

from kernel_sources import attach_source, ensure_source, locked, real_directory

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def archive_for(lock):
    version = lock['linux']['tag'].removeprefix('v')
    archive = ROOT / f'.local/downloads/linux-{version}.tar.xz'
    expected = lock['linux']['tarball_sha256']
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=archive.parent) as temporary:
            with urllib.request.urlopen(lock['linux']['tarball_url'], timeout=60) as source:
                shutil.copyfileobj(source, temporary)
            temporary.flush()
            if sha256(Path(temporary.name)) != expected:
                raise RuntimeError('Downloaded Linux archive hash mismatch')
            shutil.copyfile(temporary.name, archive)
    if sha256(archive) != expected:
        raise RuntimeError('Locked Linux archive hash mismatch')
    return archive


def check_overrides(config, overrides):
    # Kconfig omits some hidden disabled symbols entirely; both forms mean n.
    actual = dict(re.findall(r'^(CONFIG_\w+)=([^\n]+)$', config.read_text(), re.M))
    for setting in overrides:
        name, value = setting.split('=')
        if actual.get(name, 'n') != value:
            raise RuntimeError('Requested driver-check configuration was not applied: ' + setting)


def compile_objects(archive, lock, work, objects, *, extra_config=(), project_config=True):
    # Content-addressed scratch source/output; never overwrite diagnostic.3's
    # source tree, kernel objects, installed modules or completed image.
    if not objects or any(not re.fullmatch(r'(?:drivers/|kernel/|arch/arm/)[A-Za-z0-9_./-]+[.]o', name) or
                          '..' in Path(name).parts for name in objects):
        raise ValueError('Expected kernel object paths')
    if any(not re.fullmatch(r'CONFIG_[A-Z0-9_]+=[ymn]', line) for line in extra_config):
        raise ValueError('Expected boolean/tristate kernel configuration assignments')
    if type(project_config) is not bool or (not project_config and not extra_config):
        raise ValueError('Compile-only configurations require explicit overrides')
    with locked(work / '.source-lock'):
        return compile_locked(archive, lock, work, objects, extra_config, project_config)


def compile_locked(archive, lock, work, objects, extra_config, project_config):
    extra_text = ''.join(line + '\n' for line in extra_config)
    queue = work / 'patches'
    run(['python3', str(ROOT / 'tools/kernel-inputs.py'), '--export', str(queue)])
    identity_bytes = ((queue / 'manifest.json').read_bytes() +
                      (ROOT / 'kernel/gameshellneo.config').read_bytes() +
                      json.dumps(lock, sort_keys=True).encode() + extra_text.encode())
    if not project_config:
        identity_bytes += b'\0isolated-driver-configuration'
    identity = hashlib.sha256(identity_bytes).hexdigest()[:16]
    scratch = work / ('kernel-' + identity)
    scratch.mkdir(exist_ok=True)
    real_directory(scratch)
    if (scratch / 'extra.config').is_symlink():
        raise ValueError('Unexpected extra configuration symlink')
    (scratch / 'extra.config').write_text(extra_text)
    source, entries, metadata = ensure_source(
        ROOT, work, archive, lock, json.loads((queue / 'manifest.json').read_text()))
    real_directory(scratch)
    attach_source(scratch, source, entries)
    return build_objects(source, scratch, lock, objects, extra_config, project_config, metadata)


def build_objects(source, scratch, lock, objects, extra_config, project_config, metadata):
    builder = lock['builder']
    relative = scratch.relative_to(ROOT).as_posix()
    config_check = ('python3 /project/tools/check-kernel-config.py "$output/.config"\n'
                    if project_config else '')
    run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
         '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
         '-v', f'{source}:/kernel-source:ro',
         '-e', f'NEO_DRIVER_SCRATCH=/project/{relative}',
         '-e', f'NEO_DRIVER_CROSS={builder["cross_compile"]}',
         '-e', 'NEO_DRIVER_OBJECTS=' + ' '.join(objects),
         '-e', f'LOCALVERSION={lock["linux"]["localversion"]}',
         '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
         builder['image'], '-c',
         'set -euo pipefail\n'
         'export ARCH=arm CROSS_COMPILE="$NEO_DRIVER_CROSS"\n'
         'output="$NEO_DRIVER_SCRATCH/output"\n'
         'make -C /kernel-source O="$output" sunxi_defconfig\n'
         'cd "$output"\n'
         '/kernel-source/scripts/kconfig/merge_config.sh -m -O "$output" "$output/.config" '
         '/project/kernel/gameshellneo.config "$NEO_DRIVER_SCRATCH/extra.config"\n'
         'make -C /kernel-source O="$output" olddefconfig\n' + config_check +
         'read -ra objects <<< "$NEO_DRIVER_OBJECTS"\n'
         'make -C /kernel-source O="$output" -j1 "${objects[@]}"\n'
         '"${NEO_DRIVER_CROSS}gcc" --version > "$NEO_DRIVER_SCRATCH/compiler.txt"\n'
         'for object in "${objects[@]}"; do\n'
         '    "${NEO_DRIVER_CROSS}readelf" -h "$output/$object"\n'
         'done > "$NEO_DRIVER_SCRATCH/elf-info.txt"\n'])
    check_overrides(scratch / 'output/.config', extra_config)
    return dict(scratch=relative,
                objects={name: sha256(scratch / 'output' / name) for name in objects},
                config_sha256=sha256(scratch / 'output/.config'),
                extra_config=list(extra_config), builder=builder,
                shared_source=dict(path=str(source.relative_to(ROOT)), **metadata),
                configuration_scope='project' if project_config else 'driver-compilation-only')
