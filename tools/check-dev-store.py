#!/usr/bin/env python3
"""Qualify an inactive packaged store against an old FAT checkpoint on private copies."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import traceback
import uuid

import dev_store

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('tools/check-dev-store.py', 'tools/dev_store.py', 'tools/dev_card.py',
          'tools/dev_systems.py', 'tools/dev_boot_scripts.py', 'tools/usb_poll_boot.py')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_path(value):
    path = Path(value)
    require('..' not in path.parts and not any(c in str(path) for c in (':', '\n', '\r', '\0')),
            'Unsupported compatibility fixture path')
    path = path.absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Fixture paths cannot traverse symlinks')
    return path


def regular_input(path):
    path = input_path(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'Expected a regular fixture input: ' + str(path))
    return path


def save(path, value):
    temporary = path.with_name(path.name + '.part')
    with temporary.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def command(arguments, log):
    log.write((json.dumps([str(value) for value in arguments]) + '\n').encode())
    result = subprocess.run([str(value) for value in arguments], capture_output=True, check=False)
    log.write(result.stdout)
    log.write(result.stderr)
    log.flush()
    os.fsync(log.fileno())
    require(result.returncode == 0, 'Fixture command failed: ' + str(arguments[0]) +
            ' (exit ' + str(result.returncode) + ')')
    return result.stdout


@contextlib.contextmanager
def mounted(device, path, filesystem, log):
    path.mkdir()
    options = 'rw,shortname=mixed' if filesystem == 'vfat' else 'rw,noatime'
    command(['mount', '-t', filesystem, '-o', options, '--', device, path], log)
    try:
        yield path
    finally:
        command(['umount', '--', path], log)


def flags(boot):
    return {name: dev_store.read_file(dev_store.child(boot, name), 65536) for name in dev_store.FLAGS}


def reject_nested_mounts(root, mountinfo=Path('/proc/self/mountinfo')):
    for line in mountinfo.read_text().splitlines():
        fields = line.split()
        point = Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4]))
        require(point == root or not point.is_relative_to(root), 'Nested mount in complete development root')


def root_metadata(root):
    """Record metadata only, without following links or exporting inode numbers."""
    root = Path(root).absolute()
    require(root.resolve(strict=True) == root and stat.S_ISDIR(root.lstat().st_mode),
            'Expected a real complete development-root directory')
    reject_nested_mounts(root)
    device = root.lstat().st_dev
    entries, links = {}, {}
    stable = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_rdev',
              'st_mtime_ns', 'st_ctime_ns', 'st_nlink')

    def visit(path, relative):
        before = path.lstat()
        require(before.st_dev == device, 'Nested filesystem in complete development root')
        record = dict(uid=before.st_uid, gid=before.st_gid, mode=before.st_mode,
                      rdev=before.st_rdev, mtime_ns=before.st_mtime_ns,
                      xattrs={name: os.getxattr(path, name, follow_symlinks=False).hex()
                              for name in sorted(os.listxattr(path, follow_symlinks=False))})
        if stat.S_ISLNK(before.st_mode):
            record['symlink'] = os.readlink(path)
        if not stat.S_ISDIR(before.st_mode):
            record['nlink'] = before.st_nlink
            links.setdefault((before.st_dev, before.st_ino), []).append(relative)
        entries[relative] = record
        if stat.S_ISDIR(before.st_mode):
            with os.scandir(path) as children:
                names = sorted(child.name for child in children)
            for name in names:
                visit(path / name, name if relative == '.' else relative + '/' + name)
        after = path.lstat()
        require(all(getattr(after, key) == getattr(before, key) for key in stable),
                'Root metadata changed during capture: ' + relative)

    visit(root, '.')
    reject_nested_mounts(root)
    return dict(entries=entries, hardlink_groups=sorted(sorted(group) for group in links.values() if len(group) > 1))


def metadata_summary(snapshot):
    entries = snapshot['entries']
    modes = [record['mode'] for record in entries.values()]
    return dict(sha256=hashlib.sha256(dev_store.json_bytes(snapshot)).hexdigest(), entries=len(entries),
                directories=sum(stat.S_ISDIR(mode) for mode in modes),
                regular_files=sum(stat.S_ISREG(mode) for mode in modes),
                symlinks=sum(stat.S_ISLNK(mode) for mode in modes),
                special_files=sum(not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode))
                                  for mode in modes),
                hardlink_groups=len(snapshot['hardlink_groups']),
                xattrs=sum(len(record['xattrs']) for record in entries.values()),
                acls=sum(name.startswith('system.posix_acl_') for record in entries.values()
                         for name in record['xattrs']))


def verify_root_metadata(before, after):
    changed = sorted(path for path in before['entries'].keys() | after['entries'].keys()
                     if before['entries'].get(path) != after['entries'].get(path))
    require(not changed and before['hardlink_groups'] == after['hardlink_groups'],
            'Complete root metadata changed during administration: ' +
            (', '.join(changed[:5]) if changed else 'hardlink groups'))


def exercise(boot, store, manifest, log, metadata_path):
    from dev_systems import Card

    dev_store.verify_boot(boot, manifest)
    dev_store.verify_store(store, manifest)
    before = Card(boot, store).status()
    require(before['systems'] == {} and before['confirmed_system'] == 'recovery' and
            before['next_system'] == 'recovery' and before['trial_pending'] is False,
            'Old FAT and inactive store do not start at fixed recovery with an empty catalog')
    original_flags = flags(boot)
    require(len(set(original_flags.values())) == 1, 'All original flags must equal recovery')
    selected_slot = manifest['slot']['id']
    root = dev_store.child(store, 'systems/' + selected_slot + '/root')
    release = dev_store.load_json(dev_store.child(store, 'systems/' + selected_slot + '/release.json'))
    fping_relative = 'usr/bin/fping'
    fping = dev_store.child(root, fping_relative)
    content_sha256 = dev_store.sha(fping)
    require(release['immutable_files'].get(fping_relative) == content_sha256,
            'fping content differs from the immutable source-release metadata')
    capability = os.getxattr(fping, 'security.capability', follow_symlinks=False)
    require(bool(capability), 'Packaged fping has no security.capability value')
    capability_record = dict(path=fping_relative, security_capability_hex=capability.hex(),
        security_capability_bytes=len(capability), immutable_sha256=content_sha256,
        source_metadata_records_capability_value=False,
        raw_image_sha256=manifest['raw']['sha256'])

    metadata_before = root_metadata(root)
    metadata_record = dict(before=metadata_summary(metadata_before), after=None, unchanged=None)
    save(metadata_path, metadata_record)
    registered = Card(boot, store).register(selected_slot)
    require(flags(boot) == original_flags, 'Registration changed a boot selection flag')
    card = Card(boot, store)
    require(card.verify(selected_slot) == release, 'Registered complete release differs')
    after_register = card.status()
    require(set(after_register['systems']) == {selected_slot} and
            after_register['confirmed_system'] == 'recovery' and after_register['next_system'] == 'recovery',
            'Registration changed the default or failed to publish the complete release')
    card.select(selected_slot)
    selected = Card(boot, store).status()
    require(selected['next_system'] == selected_slot and selected['trial_pending'] is True and
            selected['confirmed_system'] == 'recovery', 'New slot was not selected as a one-shot trial')
    trial_flags = flags(boot)
    require(trial_flags['next.scr'] != original_flags['next.scr'] and
            all(trial_flags[name] == original_flags[name] for name in ('good.scr', 'recover.scr')),
            'Trial selection changed confirmed/fixed recovery')
    card.select_recovery()
    restored = Card(boot, store).status()
    require(flags(boot) == original_flags and restored['next_system'] == 'recovery' and
            restored['trial_pending'] is False, 'Recovery did not restore the exact original flags')

    tools = dev_store.child(store, 'admin/tools')
    bootstrap = ('import runpy,sys; directory=sys.argv.pop(1); '
                 'sys.path.insert(0,directory); runpy.run_path(directory+"/dev-systems.py",run_name="__main__")')
    copied = json.loads(command([sys.executable, '-I', '-c', bootstrap, tools,
                                '--boot', boot, '--store', store, 'status'], log))
    require(copied == restored, 'Copied administration status differs from the verified fixture')
    loader_code = ('import json,sys;sys.path.insert(0,sys.argv[1]); '
                   'from dev_initramfs import verify_u_initrd; '
                   'print(json.dumps(verify_u_initrd(sys.argv[2]),sort_keys=True))')
    loader = json.loads(command([sys.executable, '-I', '-c', loader_code, tools,
                                dev_store.child(store, 'admin/loader/uInitrd')], log))
    require(flags(boot) == original_flags, 'Copied administration or loader verification changed flags')
    metadata_after = root_metadata(root)
    metadata_record.update(after=metadata_summary(metadata_after), unchanged=metadata_before == metadata_after)
    save(metadata_path, metadata_record)
    verify_root_metadata(metadata_before, metadata_after)
    return dict(before=before, registered=registered, after_register=after_register,
                trial=selected, restored=restored, copied_admin_status=copied,
                copied_loader=loader, fping=capability_record, root_metadata=metadata_record,
                original_flags_sha256={name: hashlib.sha256(value).hexdigest()
                                       for name, value in original_flags.items()})


def worker(work, boot_sha256):
    from dev_card import attached

    require(os.geteuid() == 0, 'Fixture requires the isolated managed root builder')
    require(work == Path('/fixture'), 'Expected the managed private fixture directory')
    os.umask(0o022)
    boot_source = regular_input('/inputs/boot.fat')
    store_source = regular_input('/inputs/store.ext4')
    manifest_source = regular_input('/inputs/store.json')
    state = dict(schema=1, operation='development-store-compatibility', development_only=True,
                 passed=False, hardware_qualified=False, phase='admission', phases=[])
    with (work / 'operation.log').open('xb', buffering=0) as log:
        def phase(name, **values):
            state.update(values, phase=name)
            state['phases'].append(name)
            save(work / 'state.json', state)
        try:
            phase('admission')
            manifest = dev_store.load_json(manifest_source)
            dev_store.validate_manifest(manifest)
            require(boot_source.stat().st_size == manifest['target']['partitions']['boot']['bytes'] and
                    dev_store.sha(boot_source) == boot_sha256, 'Old FAT checkpoint size or SHA-256 differs')
            require(store_source.stat().st_size == manifest['raw']['bytes'] and
                    dev_store.sha(store_source) == manifest['raw']['sha256'], 'Packaged raw store size or SHA-256 differs')
            source_hashes = dict(boot=boot_sha256, store=manifest['raw']['sha256'],
                                 manifest=dev_store.sha(manifest_source))
            input_hashes = {name: dev_store.sha(ROOT / name) for name in INPUTS}
            phase('sources-verified', source_hashes=source_hashes, inputs=input_hashes)
            boot_copy, store_copy = work / 'disposable-boot.fat', work / 'disposable-store.ext4'
            for source, target in ((boot_source, boot_copy), (store_source, store_copy)):
                command(['cp', '--reflink=auto', '--sparse=always', '--', source, target], log)
                target.chmod(0o600)
                require(dev_store.sha(target) == source_hashes['boot' if source == boot_source else 'store'],
                        'Disposable copy differs from its verified source')
            phase('copies-verified')
            with attached(boot_copy, False) as boot_device, attached(store_copy, False) as store_device:
                filesystem_uuid = command(['blkid', '-p', '-s', 'UUID', '-o', 'value', store_device], log).decode().strip()
                require(filesystem_uuid == manifest['raw']['filesystem_uuid'], 'Copied store filesystem UUID differs')
                with mounted(boot_device, work / 'boot', 'vfat', log) as boot, \
                        mounted(store_device, work / 'store', 'ext4', log) as store:
                    phase('mounted')
                    observed = exercise(boot, store, manifest, log, work / 'root-metadata.json')
                    phase('administration-verified', observed=observed)
                    os.sync()
                phase('unmounted')
                checks = dict(boot=command(['fsck.fat', '-n', boot_device], log).decode(),
                              store=command(['e2fsck', '-f', '-n', store_device], log).decode())
            phase('filesystems-verified', filesystem_reports=checks)
            require(source_hashes == dict(boot=dev_store.sha(boot_source), store=dev_store.sha(store_source),
                                           manifest=dev_store.sha(manifest_source)), 'An original source changed')
            require(input_hashes == {name: dev_store.sha(ROOT / name) for name in INPUTS},
                    'Fixture source inputs changed while running')
            phase('complete', passed=True, original_sources_unchanged=True,
                  scope='Native ext4/FAT and copied administration on disposable regular-image loops only; '
                        'no vendor bootloader, physical SD card, board boot, PM or energy qualification.')
        except BaseException as error:
            log.write(traceback.format_exc().encode())
            os.fsync(log.fileno())
            if (work / 'root-metadata.json').is_file():
                state['root_metadata'] = dev_store.load_json(work / 'root-metadata.json')
            phase('failed', error=type(error).__name__ + ': ' + str(error))
            raise
        finally:
            save(work / 'result.json', state)
    return state


def fresh_output(value):
    output = input_path(value)
    require(output.is_relative_to(ROOT / '.local') and output.suffix == '.json',
            'Output must be a fresh JSON under this checkout .local')
    require(not output.exists(), 'Refusing to overwrite an existing fixture result')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-image', type=Path)
    parser.add_argument('--boot-sha256', required=True)
    parser.add_argument('--store-image', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    dev_store._digest(args.boot_sha256)
    if args.inside:
        worker(args.inside, args.boot_sha256)
        return
    require(all((args.boot_image, args.store_image, args.manifest, args.output)),
            'Supply --boot-image, --store-image, --manifest and --output')
    require(bool(os.environ.get('NEO_BUILD_STAGE')), 'Use the saved check:dev-store Task')
    boot, store, manifest_path = map(regular_input, (args.boot_image, args.store_image, args.manifest))
    manifest = dev_store.load_json(manifest_path)
    dev_store.validate_manifest(manifest)
    require(boot.stat().st_size == manifest['target']['partitions']['boot']['bytes'] and
            dev_store.sha(boot) == args.boot_sha256, 'Old FAT checkpoint size or SHA-256 differs')
    require(store.stat().st_size == manifest['raw']['bytes'] and
            dev_store.sha(store) == manifest['raw']['sha256'], 'Packaged raw store size or SHA-256 differs')
    output = fresh_output(args.output)
    work = ROOT / '.local/build/dev-store-compatibility' / uuid.uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    save(work / 'request.json', dict(boot_image=str(boot), boot_sha256=args.boot_sha256,
        store_image=str(store), manifest=str(manifest_path), manifest_sha256=dev_store.sha(manifest_path),
        output=str(output)))
    print('Retained development-store compatibility fixture:', work.relative_to(ROOT), flush=True)
    from managed_container import execute
    builder = dev_store.load_json(ROOT / 'build/sources.lock.json')['builder']
    try:
        execution = execute('dev-store-compatibility', ['--pull=never', '--network=none', '--privileged',
            '--platform=' + builder['platform'], '--memory=1g', '--cpus=1', '--pids-limit=128',
            '--entrypoint=python3', '-v', f'{ROOT}:/project:ro', '-v', f'{work}:/fixture',
            '-v', f'{boot}:/inputs/boot.fat:ro', '-v', f'{store}:/inputs/store.ext4:ro',
            '-v', f'{manifest_path}:/inputs/store.json:ro', builder['image'],
            '/project/tools/check-dev-store.py', '--inside', '/fixture', '--boot-sha256', args.boot_sha256],
            work / 'managed', timeout=1200)
        result = dev_store.load_json(work / 'result.json')
        require(result.get('passed') is True and result['inputs'] == {name: dev_store.sha(ROOT / name) for name in INPUTS},
                'Compatibility fixture did not pass against the current source')
        require(result['source_hashes'] == dict(boot=dev_store.sha(boot), store=dev_store.sha(store),
                                               manifest=dev_store.sha(manifest_path)),
                'Original sources differ after managed completion')
        result = dict(result, managed_run=execution['job']['run'], evidence=str(work.relative_to(ROOT)),
                      worker_result_sha256=dev_store.sha(work / 'result.json'))
    except BaseException as error:
        result = dict(schema=1, operation='development-store-compatibility', development_only=True,
                      passed=False, hardware_qualified=False, evidence=str(work.relative_to(ROOT)),
                      error=type(error).__name__ + ': ' + str(error))
        if (work / 'result.json').is_file():
            result['worker_result'] = dev_store.load_json(work / 'result.json')
        with output.open('x') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
        output.chmod(0o600)
        raise
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(0o600)
    print('Development-store compatibility passed:', output, flush=True)


if __name__ == '__main__':
    main()
