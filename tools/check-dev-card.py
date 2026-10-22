#!/usr/bin/env python3
"""Qualify development bundle import on a disposable regular-image copy, never a disk."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from dev_card import ROOT, attached, mounted, run
from dev_systems import Card, sha


def qualify(args):
    from dev_bundle import unpack_release
    from dev_initramfs import verify_u_initrd
    if not args.image.is_file() or args.image.is_symlink():
        raise ValueError('Expected a regular prepared image')
    receipt = json.loads(args.image.with_suffix('.json').read_text())
    original = sha(args.image)
    if (receipt.get('operation') != 'development-card-assembly' or
            receipt.get('development_only') is not True or receipt['sha256'] != original):
        raise ValueError('Prepared image receipt differs')
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    with tempfile.TemporaryDirectory(prefix='gameshellneo-devcard-check-') as temporary:
        work = Path(temporary)
        copy = work / 'disposable.img'
        run('cp', '--reflink=auto', '--sparse=always', '--', args.image, copy)
        with attached(copy, False) as device:
            with mounted(device + 'p1', work / 'boot') as boot, \
                    mounted(device + 'p3', work / 'store', filesystem='ext4') as store:
                before = Card(boot, store).status()
                previous = {name: (boot / name).read_bytes() for name in ('next.scr', 'good.scr')}
                with Card(boot, store).lock():
                    imported = unpack_release(args.bundle, store / 'systems' / args.system,
                        expected_hash=args.sha256, store_partuuid=before['store_partuuid'])
                Card(boot, store).register(args.system)
                if previous != {name: (boot / name).read_bytes() for name in previous}:
                    raise ValueError('Inactive import changed selection')
                after_import = Card(boot, store).status()
                Card(boot, store).select(args.system)
                selected = Card(boot, store).status()
                if selected['next_system'] != args.system or not selected['trial_pending']:
                    raise ValueError('New imported version was not selected as a trial')
                Card(boot, store).select_recovery()
                recovery = Card(boot, store).status()
                if recovery['next_system'] != 'recovery':
                    raise ValueError('Fixed recovery selection failed')
                # Execute the actual copied administration tree and check its
                # retained loader with that tree's source/dependency pins.
                copied = json.loads(run('python3', store / 'admin/tools/dev-systems.py',
                    '--boot', boot, '--store', store, 'status'))
                if copied != recovery:
                    raise ValueError('Copied administration program differs')
                code = ('import sys; sys.path.insert(0,sys.argv[1]); '
                        'from dev_initramfs import verify_u_initrd; '
                        'verify_u_initrd(sys.argv[2])')
                run('python3', '-c', code, store / 'admin/tools', store / 'admin/loader/uInitrd')
                verify_u_initrd(store / 'admin/loader/uInitrd')
                os.sync()
            checks = {'boot': run('fsck.fat', '-n', device + 'p1'),
                      'recovery': run('e2fsck', '-fn', device + 'p2'),
                      'store': run('e2fsck', '-fn', device + 'p3')}
    if sha(args.image) != original:
        raise ValueError('Qualification changed the original artifact')
    result = dict(development_only=True, image_sha256=original, bundle_sha256=args.sha256,
        before=before, imported=imported['slot'], after_import=after_import,
        selected=selected, recovery=recovery, copied_admin_and_loader='passed',
        original_artifact_unchanged=True, filesystem_reports=checks, hardware_qualified=False)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    os.chown(args.output, int(os.environ['NEO_ARTIFACT_UID']), int(os.environ['NEO_ARTIFACT_GID']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--system', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    from dev_systems import slot_id
    slot_id(args.system)
    for path in (args.image, args.bundle, args.output):
        if not path.resolve().is_relative_to(ROOT / '.local'):
            raise ValueError('Qualification artifacts must stay in this checkout .local')
    if args.inside:
        print(json.dumps(qualify(args), indent=2))
        return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved check:dev-card Task')
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    command = ['docker', 'run', '--rm', '--network=none', '--pull=never', '--privileged',
        '--platform=' + builder['platform'], '--entrypoint=python3',
        '-e', 'NEO_ARTIFACT_UID=' + str(os.getuid()), '-e', 'NEO_ARTIFACT_GID=' + str(os.getgid()),
        '-v', str(ROOT) + ':/project', builder['image'], '/project/tools/check-dev-card.py', '--inside',
        '--sha256', args.sha256, '--system', args.system]
    for option in ('image', 'bundle', 'output'):
        command.extend(('--' + option, '/project/' + str(getattr(args, option).resolve().relative_to(ROOT))))
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
