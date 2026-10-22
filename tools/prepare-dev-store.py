#!/usr/bin/env python3
"""Package one complete inactive ext4 store from a verified regular development card."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import uuid

from dev_card import attached, mounted, run
from dev_systems import Card, atomic_write
import dev_store

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 8 * 1024 * 1024


def _receipt(image, receipt, image_sha256, receipt_sha256):
    for value in (image_sha256, receipt_sha256):
        dev_store._digest(value)
    if dev_store.sha(receipt) != receipt_sha256 or dev_store.sha(image) != image_sha256:
        raise ValueError('Development source card/receipt checksum differs')
    report = dev_store.load_json(receipt)
    spec = importlib.util.spec_from_file_location('pack_dev_card', ROOT / 'tools/pack-dev-card.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.validate_receipt(report, image.name, image.stat().st_size)
    if report['sha256'] != image_sha256:
        raise ValueError('Development source image receipt differs')
    with image.open('rb') as stream:
        mbr = stream.read(512)
    if mbr[510:] != b'\x55\xaa' or any(mbr[494:510]):
        raise ValueError('Expected exactly three development MBR partitions')
    disk = f'{struct.unpack("<I",mbr[440:444])[0]:08x}'
    partitions = {}
    for index, name in enumerate(('boot', 'recovery', 'store')):
        flag, _, kind, _, start, sectors = struct.unpack('<B3sB3sII', mbr[446+16*index:462+16*index])
        if (flag, kind) != ((0x80, 0x0e) if index == 0 else (0, 0x83)):
            raise ValueError('Unexpected development partition type/boot flag')
        partitions[name] = dict(start_sector=start, bytes=sectors*512, partuuid=disk+f'-{index+1:02}')
    plan = report['plan']
    if (disk == '00000000' or disk != plan['disk_id'] or
            report['bytes'] != plan['output_bytes'] or
            partitions['store']['start_sector'] != plan['store_start_sector'] or
            partitions['store']['bytes'] != plan['store_sectors']*512 or
            partitions['store']['partuuid'] != plan['store_partuuid'] or
            partitions['recovery']['start_sector'] != plan['recovery_start_sector'] or
            partitions['recovery']['bytes'] != plan['recovery_sectors']*512 or
            partitions['store']['start_sector']*512 != plan['bytes']):
        raise ValueError('Development source receipt/MBR geometry differs')
    return report, dict(parent_minimum_bytes=report['bytes'],sector_bytes=512,
                       parent_partuuid_prefix=disk,partitions=partitions)


def _copy_region(source, target, offset, size):
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        incoming.seek(offset)
        remaining = size
        while remaining:
            data = incoming.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('Source card region is truncated')
            outgoing.write(data)
            remaining -= len(data)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    target.chmod(0o600)


def _filesystem_uuid(raw):
    with raw.open('rb') as stream:
        stream.seek(1024)
        block = stream.read(1024)
    if len(block) != 1024 or block[56:58] != b'\x53\xef':
        raise ValueError('Copied store is not ext4')
    log_block = struct.unpack_from('<I',block,24)[0]
    if log_block > 6:
        raise ValueError('Invalid ext4 block size')
    blocks = struct.unpack_from('<I',block,4)[0]
    if struct.unpack_from('<I',block,96)[0] & 0x80:
        blocks |= struct.unpack_from('<I',block,336)[0] << 32
    if blocks*(1024 << log_block) != raw.stat().st_size:
        raise ValueError('Ext4 filesystem size differs from its copied partition')
    value = uuid.UUID(bytes=block[104:120])
    if not value.int:
        raise ValueError('Ext4 store has no filesystem UUID')
    return str(value)


def _gzip(raw, archive):
    digest, size = hashlib.sha256(), 0
    with raw.open('rb') as source, archive.open('xb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=1, mtime=0) as compressed:
            while data := source.read(CHUNK):
                digest.update(data); size += len(data)
                compressed.write(data)
        output.flush(); os.fsync(output.fileno())
    check, count = hashlib.sha256(), 0
    with gzip.open(archive,'rb') as stream:
        while data := stream.read(CHUNK):
            count += len(data)
            if count > size:
                raise ValueError('Store gzip expands beyond its raw size')
            check.update(data)
    if count != size or check.digest() != digest.digest():
        raise ValueError('Store gzip full decompressed verification differs')
    return dict(file=archive.name,bytes=archive.stat().st_size,sha256=dev_store.sha(archive)), size, digest.hexdigest()


def _store_files(store, name):
    paths = [path for path in (store/'admin').rglob('*') if path.is_file() or path.is_symlink()]
    paths += [store/filename for filename in ('DEVBOOT.JSON','RELEASES.JSON','assembly.json')]
    directory = store/'systems'/name
    paths += [directory/filename for filename in ('release.json','source-image.json','source-fstab')]
    paths += list((directory/'boot').iterdir())
    return {str(path.relative_to(store)):dev_store.sha(path) for path in sorted(paths)}


def _fresh(output):
    if output.exists() or output.is_symlink():
        raise FileExistsError('Store package output directory must be fresh')
    for path in output.absolute().parents:
        if path.is_symlink():
            raise ValueError('Store package output parents cannot be symlinks')


def prepare(args):
    image, receipt, output = args.image, args.receipt, args.output
    _fresh(output)
    report, target = _receipt(image,receipt,args.image_sha256,args.receipt_sha256)
    output.mkdir(parents=True, mode=0o700)
    raw, archive = output/'store.ext4', output/'store.ext4.gz'
    with tempfile.TemporaryDirectory(prefix='gameshellneo-devstore-') as temporary:
        work = Path(temporary)
        with attached(image,True) as source:
            boot = work/'boot'; boot.mkdir()
            run('mount','-t','vfat','-o','ro,shortname=mixed',source+'p1',boot)
            try:
                with mounted(source+'p3',work/'source-store',readonly=True,filesystem='ext4') as store:
                    card = Card(boot,store)
                    state = card.status()
                    name = report['initial_system']
                    if (set(card.releases) != {name} or
                            {path.name for path in (store/'systems').iterdir()} != {name} or
                            state['next_system'] != name or state['confirmed_system'] != 'recovery'):
                        raise ValueError('Expected one complete, selected but unconfirmed source system')
                    release = card.verify(name)
                    if release['source_image_sha256'] != report['source_release_sha256']:
                        raise ValueError('Source release provenance differs from card receipt')
                    for relative in dev_store.ADMIN_FILES - {'admin/loader/uInitrd','admin/loader/uInitrd.json'}:
                        if dev_store.sha(dev_store.child(store,relative)) != dev_store.sha(ROOT/relative.removeprefix('admin/')):
                            raise ValueError('Source card administration differs from current frozen source')
                    boot_files = {item:dev_store.sha(boot/item) for item in ('DEVBOOT.JSON','boot.cmd','boot.scr',*dev_store.FLAGS)}
                    boot_files.update({'systems/recovery/'+item:value for item,value in card.record['recovery_boot_files'].items()})
                    for flag in dev_store.FLAGS:
                        boot_files[flag] = dev_store.sha(boot/'recover.scr')
                    original_catalog = card.releases
                    card_record = card.record
                    region = target['partitions']['store']
                    _copy_region(image,raw,region['start_sector']*512,region['bytes'])
            finally:
                run('umount',boot)
        filesystem_uuid = _filesystem_uuid(raw)
        with attached(raw,False) as copied:
            with mounted(copied,work/'inactive-store',filesystem='ext4') as store:
                if dev_store.load_json(store/'RELEASES.JSON') != original_catalog:
                    raise ValueError('Copied source catalog differs before modification')
                atomic_write(store/'RELEASES.JSON',dev_store.json_bytes({}))
                manifest = dict(schema=1,operation='development-store-package',development_only=True,
                    archive=None,
                    raw=dict(file=raw.name,bytes=region['bytes'],sha256=None,filesystem_uuid=filesystem_uuid),
                    source_card=dict(image=image.name,bytes=report['bytes'],sha256=args.image_sha256,
                                     receipt_sha256=args.receipt_sha256),
                    target=target,card=card_record,
                    slot=dict(id=name,kernel=release['kernel'],manifest_sha256=original_catalog[name]['manifest_sha256'],
                              **{key:release[key] for key in ('source_image_sha256','source_manifest_sha256',
                                 'source_fstab_sha256','deployment_manifest_sha256')}),
                    original_catalog=original_catalog,catalog={},boot_files=boot_files,
                    store_files=_store_files(store,name))
            run('e2fsck','-fn',copied)
    manifest['archive'],size,digest = _gzip(raw,archive)
    if size != region['bytes'] or _filesystem_uuid(raw) != filesystem_uuid:
        raise ValueError('Final raw store size/UUID changed')
    manifest['raw']['sha256'] = digest
    dev_store.validate_manifest(manifest)
    with tempfile.TemporaryDirectory(prefix='gameshellneo-store-check-') as temporary:
        with attached(raw,True) as device:
            with mounted(device,Path(temporary)/'store',readonly=True,filesystem='ext4') as store:
                dev_store.verify_store(store,manifest)
    if dev_store.sha(image) != args.image_sha256 or dev_store.sha(receipt) != args.receipt_sha256:
        raise ValueError('Original development card/receipt changed while packing')
    with (output/'store.json').open('xb') as stream:
        stream.write(dev_store.json_bytes(manifest)); stream.flush(); os.fsync(stream.fileno())
    shutil.copyfile(receipt,output/'source-card.json')
    uid, gid = int(os.environ['NEO_ARTIFACT_UID']),int(os.environ['NEO_ARTIFACT_GID'])
    for path in output.iterdir():
        path.chmod(0o600); os.chown(path,uid,gid)
    os.chown(output,uid,gid)
    fd = os.open(output,os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--image-sha256',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--receipt-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True,help='Fresh private package directory')
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.absolute()
    if not args.output.resolve().is_relative_to(ROOT/'.local'):
        raise ValueError('Store package output must stay in this checkout .local directory')
    _fresh(args.output)
    if args.inside:
        print(json.dumps(prepare(args),indent=2)); return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved development-store pack Task for managed Docker ownership')
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    builder = json.loads((ROOT/'build/sources.lock.json').read_text())['builder']
    subprocess.run(['docker','run','--rm','--network=none','--pull=never','--privileged',
        '--platform='+builder['platform'],'--entrypoint=python3',
        '-e','NEO_ARTIFACT_UID='+str(os.getuid()),'-e','NEO_ARTIFACT_GID='+str(os.getgid()),
        '-v',str(ROOT)+':/project','-v',str(args.image.resolve().parent)+':/source-image:ro',
        '-v',str(args.receipt.resolve().parent)+':/source-receipt:ro',builder['image'],
        '/project/tools/prepare-dev-store.py','--inside','--image','/source-image/'+args.image.name,
        '--image-sha256',args.image_sha256,'--receipt','/source-receipt/'+args.receipt.name,
        '--receipt-sha256',args.receipt_sha256,'--output','/project/'+str(args.output.relative_to(ROOT))],check=True)


if __name__ == '__main__':
    main()
