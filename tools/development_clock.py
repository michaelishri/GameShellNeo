"""Explicit development-directory admission for awake clock diagnostics only.

The original image, original reader build and newly executed adapter have
separate identities. Nothing in this module grants PM or clock-health admission.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile

from clock_deployment import FILES, bounded, configuration, digest, validate_contract
from clock_boundary import decoded_ns

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ('development_clock.py', 'capture-development-clock.py')
READER_INPUTS = ('tools/clock-boundary.c', 'tools/clock_boundary.py',
                 'tools/clock_provenance.py', 'tools/clock_deployment.py',
                 'tools/capture-clock-boundary.py', 'tools/build-clock-boundary.py',
                 'tools/check-clock-paths.py', 'build/sources.lock.json')
READER_OUTPUTS = ('clock-boundary.so', 'test-host', 'test-arm', 'reader-readelf.txt',
                  'reader-disassembly.txt', 'build.sh', 'build-output.txt',
                  'host-fixtures.txt', 'arm-fixtures.txt')
READER_ABI_FILES = ('arch/arm/tools/syscall.tbl', 'include/uapi/linux/time_types.h',
                    'include/uapi/asm-generic/posix_types.h', 'include/uapi/linux/time.h',
                    'arch/arm/include/uapi/asm/unistd.h', 'arch/arm/include/asm/elf.h',
                    'include/uapi/linux/elf.h', 'include/uapi/linux/elf-em.h',
                    'include/vdso/time32.h', 'include/linux/clocksource_ids.h')


def require(value, message):
    if not value:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def slot_id(value):
    require(isinstance(value, str) and len(value) <= 48 and
            re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', value) and value != 'recovery',
            'Expected a development directory slot')


def partuuid(value, partition):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{8}-' + partition, value),
            'Unexpected development partition identity')


def child(root, relative):
    require(isinstance(relative, str) and relative and not relative.startswith('/') and
            all(p not in ('', '.', '..') for p in relative.split('/')), 'Unsafe provenance path')
    path = Path(root)
    for component in relative.split('/'):
        path /= component
        require(not path.is_symlink(), 'Provenance path traverses a symlink')
    return path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(root, relative, maximum=2 * 1024 * 1024):
    path = child(Path(root), relative)
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum,
                'Expected bounded regular provenance file: ' + relative)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        require(len(raw) <= maximum, 'Provenance file grew while reading')
        return raw
    finally:
        os.close(fd)


def reader_fixtures(text):
    """Replay the actual saved ARM byte buffers, preserving negative readings."""
    records = [json.loads(line.removeprefix('NEO_BOUNDARY_FIXTURE '))
               for line in text.splitlines() if line.startswith('NEO_BOUNDARY_FIXTURE ')]
    expected = [(route, clock, n) for route in ('syscall64', 'syscall32', 'libc64')
                for clock in (1, 4, 7) for n in range(3)]
    require(len(records) == len(expected), 'Incomplete original ARM reader fixtures')
    for value, (route, clock, n) in zip(records, expected):
        sec, ns, converted = decoded_ns(value)
        require((value['route'], value['clock'], value['size']) ==
                (route, clock, 8 if route == 'syscall32' else 16), 'ARM fixture order/ABI changed')
        require((value['sec'], value['nsec']) == (sec, ns), 'ARM fixture raw decoding differs')
        wanted = (None, -1, 14, 0, -1) if n == 2 else (
            7_000_006_350 if n == 0 else 7_000_005_600, 0, 0, 1,
            7_000_006_350 if n == 0 else 7_000_005_600)
        require((converted, value['rc'], value['errno'], value['converted'], value['native_ns']) == wanted,
                'ARM fixture failure/regression was altered')
    return len(records)


def verify_reader_abi(files, archive, version):
    """The reviewed reader fixes the required headers, not the receipt's keys."""
    require(isinstance(files, dict) and set(files) == set(READER_ABI_FILES),
            'Original reader ABI requires the exact ten source files')
    require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in files.values()), 'Malformed original reader ABI source digest')
    actual = {}
    with tarfile.open(archive, 'r|xz') as source:
        for member in source:
            name = member.name.removeprefix('linux-' + version + '/')
            if name in READER_ABI_FILES:
                require(member.isfile(), 'Original reader ABI source is not a regular file')
                actual[name] = digest(source.extractfile(member).read())
            if len(actual) == len(READER_ABI_FILES):
                break
    require(actual == files, 'Original reader ABI headers differ from locked Linux')
    return actual


def offline_inputs(image_checkout, reader, runtime, release_path, *, boot_id, cid, store_uuid):
    """Read-only; finish every local artifact check before loading SSH access."""
    image_checkout, reader, runtime = map(lambda p: Path(p).resolve(strict=True),
                                        (image_checkout, reader, runtime))
    artifacts = image_checkout / '.local/artifacts'
    image_raw = regular(artifacts, 'image-manifest.json')
    image = json.loads(image_raw)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    require(image['sources'] == lock and image['version'] == lock['image_version'] and
            image['kernel'] == lock['linux']['tag'][1:] + lock['linux']['localversion'] and
            lock['experiments'].get('clock_provenance') is True and 'deployment' not in image,
            'Original source image differs from the selected instrumented source lock')
    require(sha(ROOT / 'build/sources.lock.json') == image['project_inputs_sha256']['build/sources.lock.json'],
            'Exact image source lock bytes differ')
    verify = json.loads(regular(artifacts, 'verification.json'))
    name = verify['image']
    require(isinstance(name, str) and Path(name).name == name and
            name == f'GameShellNeo-{image["version"]}-cpi31-{verify["sha256"][:12]}.img' and
            verify['offline_verification'] == 'passed', 'Original raw image was not verified')
    raw_path = artifacts / name
    require(raw_path.stat().st_size == verify['bytes'] == lock['layout']['image_bytes'] and
            sha(raw_path) == verify['sha256'], 'Original raw image hash/size changed')
    config = regular(artifacts, 'kernel.config')
    values = configuration(config)
    kernel = json.loads(regular(artifacts, 'kernel-completed.json'))
    require(kernel == json.loads(regular(image_checkout, '.local/build/kernel-completed.json')) and
            kernel['kernel_release'] == image['kernel'] and
            kernel['files']['.local/build/kernel/.config'] == digest(config),
            'Completed kernel/image receipts differ')
    for relative, expected in kernel['files'].items():
        require(sha(child(image_checkout, relative)) == expected, 'Kernel artifact changed: ' + relative)
    require(sha(image_checkout / 'kernel/gameshellneo.config') == kernel['fragment_sha256'],
            'Kernel fragment changed')
    spec = importlib.util.spec_from_file_location('development_clock_kernel_inputs', ROOT / 'tools/kernel-inputs.py')
    queue = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue)
    require({name: digest(raw) for name, raw in queue.patches()} == kernel['patches'],
            'Selected canonical kernel queue differs from the completed image')
    notes = subprocess.check_output(['readelf', '-n', str(image_checkout / '.local/build/kernel/vmlinux')],
                                    text=True, timeout=30)
    identities = re.findall(r'Build ID: ([0-9a-f]+)', notes)
    require(len(identities) == 1, 'Missing/ambiguous original kernel build ID')
    receipt_raw = regular(reader, 'build-receipt.json')
    receipt = json.loads(receipt_raw)
    require(receipt.get('schema') == 1 and receipt.get('operation') == 'clock-boundary-build' and
            receipt.get('complete') is True and receipt['builder'] == lock['builder'] and
            set(receipt['inputs']) == set(READER_INPUTS) and
            set(receipt['outputs']) == set(READER_OUTPUTS) and receipt['arm_raw_buffer_fixtures'] == 27 and
            receipt['tests'] == ['host-ubsan-fixtures', 'arm-qemu-fixtures', 'arm-production-layout-assertions'],
            'Incomplete original reader build')
    # The reader is not a kernel image. An explicit localversion difference is
    # allowed only after matching every other Linux lock field and actual ABI
    # source file. Preserve the original lock/receipt rather than relabel it.
    reader_lock = json.loads(regular(reader, 'build/sources.lock.json'))
    require({k: v for k, v in receipt['abi']['linux'].items() if k != 'localversion'} ==
            {k: v for k, v in lock['linux'].items() if k != 'localversion'} and
            reader_lock['linux'] == receipt['abi']['linux'] and reader_lock['builder'] == lock['builder'],
            'Reader ABI source or builder differs from the image')
    version = lock['linux']['tag'][1:]
    archive = image_checkout / '.local/downloads' / ('linux-' + version + '.tar.xz')
    require(sha(archive) == lock['linux']['tarball_sha256'], 'Original Linux ABI archive changed')
    verify_reader_abi(receipt['abi']['files'], archive, version)
    for relative, expected in receipt['inputs'].items():
        require(sha(child(reader, relative)) == expected, 'Original reader input changed: ' + relative)
        if relative != 'build/sources.lock.json':
            require(sha(ROOT / relative) == expected == image['project_inputs_sha256'].get(relative),
                    'Executed reader/image source differs: ' + relative)
    for relative, expected in receipt['outputs'].items():
        require(sha(child(reader, relative)) == expected, 'Original reader output changed: ' + relative)
    reader_fixtures(regular(reader, 'arm-fixtures.txt').decode())
    elf = regular(reader, 'reader-readelf.txt').decode()
    for marker in ('ELF32', 'little endian', 'ARM', 'Version5 EABI', 'hard-float ABI',
                   'DYN (Shared object file)', '__clock_gettime64@GLIBC_2.34', 'syscall@GLIBC_',
                   'neo_clock_read', 'neo_clock_layout', 'neo_clock_vdso', 'BIND_NOW', 'GNU_RELRO'):
        require(marker in elf, 'Original reader ELF lacks ' + marker)
    inventory = json.loads(regular(runtime, 'inventory.json'))
    summary = json.loads(regular(runtime, 'summary.json'))
    require(inventory.get('complete') is True and inventory.get('operation') == 'clock-runtime-inventory' and
            summary.get('complete') is True and summary.get('binaries_verified') is True,
            'Missing verified offline runtime ABI evidence')
    for role, item in inventory['files'].items():
        require((runtime / (role + '.elf')).stat().st_size == item['size'] and
                sha(runtime / (role + '.elf')) == item['sha256'], 'Saved runtime ELF changed')
    symbols = lambda text: set(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)@@?(GLIBC_[0-9.]+)\b', text))
    exports = subprocess.check_output(['readelf', '-Ws', str(runtime / 'libc.elf')], text=True, timeout=30)
    needed = symbols('\n'.join(line for line in elf.splitlines() if ' UND ' in line))
    require(needed and needed <= symbols(exports), 'Offline libc lacks reader imports')
    release_raw = Path(release_path).read_bytes()
    release = json.loads(release_raw)
    require(release_raw == json_bytes(release), 'Release manifest must retain its canonical exact bytes')
    slot_id(release['slot']); partuuid(release['store_partuuid'], '03')
    require(release['source_image_sha256'] == verify['sha256'] and
            release['source_manifest_sha256'] == digest(image_raw) and release['kernel'] == image['kernel'] and
            release['board'] == image['board'] == 'gameshellneo-cpi31', 'Release does not derive from the image')
    deployment = dict(image, deployment='development-directory', slot=release['slot'],
        source_image_sha256=release['source_image_sha256'], source_manifest_sha256=digest(image_raw),
        source_fstab_sha256=release['source_fstab_sha256'], root_partuuid=release['store_partuuid'])
    require(digest(json_bytes(deployment)) == release['deployment_manifest_sha256'] ==
            release['immutable_files']['etc/gameshellneo/image.json'], 'Deployment transformation differs')
    for item in inventory['files'].values():
        relative = item['path'].lstrip('/')
        if relative.startswith('lib/'):
            relative = 'usr/' + relative
        require(release['immutable_files'].get(relative) == item['sha256'],
                'Original ABI evidence differs from the release runtime')
    base = dict(schema=1, operation='clock-boundary-contract', boot_id=boot_id, kernel=image['kernel'],
        build_id=identities[0], image_sha256=release['deployment_manifest_sha256'],
        config_sha256=digest(config), source_id=1, time_namespaces=values.get('CONFIG_TIME_NS') == 'y',
        runtime=inventory['files'], files={name: receipt['outputs'][name] if name.endswith('.so') else
            receipt['inputs']['tools/' + name] for name in FILES})
    validate_contract(base)
    base['development'] = dict(schema=1, operation='development-directory-clock-admission',
        slot=release['slot'], store_partuuid=release['store_partuuid'], store_uuid=store_uuid,
        card_cid=cid, release_sha256=digest(release_raw), release=release, image=image,
        source_manifest_sha256=digest(image_raw), source_manifest_text=image_raw.decode(),
        source_image_sha256=verify['sha256'],
        adapter_files={name: sha(ROOT / 'tools' / name) for name in ADAPTERS},
        reader_receipt_sha256=digest(receipt_raw), reader_original_linux=receipt['abi']['linux'],
        offline_runtime_boot_id=inventory['boot_id'], pm_admission=False, clock_health_qualified=False)
    validate_development_contract(base)
    return base


def validate_development_contract(contract):
    validate_contract(contract)
    d = contract['development']
    require(d.get('schema') == 1 and d.get('operation') == 'development-directory-clock-admission' and
            d.get('pm_admission') is False and d.get('clock_health_qualified') is False,
            'Expected explicit awake-only development admission')
    slot_id(d['slot']); partuuid(d['store_partuuid'], '03')
    require(re.fullmatch('[0-9a-f]{32}', d['card_cid']) and
            re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', d['store_uuid']),
            'Malformed card/filesystem identity')
    require(set(d['adapter_files']) == set(ADAPTERS), 'Incomplete executed adapter inputs')
    for value in (*d['adapter_files'].values(), d['release_sha256'], d['reader_receipt_sha256'],
                  d['source_manifest_sha256'], d['source_image_sha256']):
        require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'Malformed provenance digest')
    r, image = d['release'], d['image']
    require(digest(json_bytes(r)) == d['release_sha256'] and
            digest(d['source_manifest_text'].encode()) == d['source_manifest_sha256'] and
            json.loads(d['source_manifest_text']) == image
            and r['slot'] == d['slot'] and r['store_partuuid'] == d['store_partuuid'] and
            r['source_image_sha256'] == d['source_image_sha256'] and
            r['source_manifest_sha256'] == d['source_manifest_sha256'] and
            r['deployment_manifest_sha256'] == contract['image_sha256'] and
            r['kernel'] == image['kernel'] == contract['kernel'], 'Inconsistent development provenance')
    expected = dict(image, deployment='development-directory', slot=d['slot'],
        source_image_sha256=d['source_image_sha256'], source_manifest_sha256=d['source_manifest_sha256'],
        source_fstab_sha256=r['source_fstab_sha256'], root_partuuid=d['store_partuuid'])
    require('deployment' not in image and image['board'] == r['board'] == 'gameshellneo-cpi31' and
            digest(json_bytes(expected)) == contract['image_sha256'] and
            r['immutable_files']['etc/gameshellneo/image.json'] == contract['image_sha256'],
            'Deployment is not the exact original-image transformation')
    for item in contract['runtime'].values():
        relative = item['path'].lstrip('/')
        relative = 'usr/' + relative if relative.startswith('lib/') else relative
        require(r['immutable_files'].get(relative) == item['sha256'], 'Runtime is absent from the release')


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=10).strip()


def deployment_snapshot(contract, *, store=Path('/run/gameshellneo-store'), root=Path('/')):
    """Prove the actual live directory root; never merely trust a boot label."""
    validate_development_contract(contract)
    d = contract['development']
    require(store.resolve(strict=True) == store and store.is_mount(), 'Store is not a real mount')
    mount = json.loads(command('findmnt', '-J', '-M', str(store), '-o', 'TARGET,SOURCE,FSTYPE,FSROOT,MAJ:MIN'))['filesystems']
    require(len(mount) == 1, 'Store mount is ambiguous')
    mount = mount[0]
    number = f'{os.major(store.stat().st_dev)}:{os.minor(store.stat().st_dev)}'
    require(mount == dict(target=str(store), source='/dev/mmcblk0p3', fstype='ext4', fsroot='/',
                          **{'maj:min': number}), 'Store is aliased or not the complete p3 filesystem')
    require(command('blkid', '-s', 'PARTUUID', '-o', 'value', '/dev/mmcblk0p3') == d['store_partuuid'] and
            command('blkid', '-s', 'UUID', '-o', 'value', '/dev/mmcblk0p3') == d['store_uuid'] and
            bounded('/sys/class/block/mmcblk0/device/cid').decode().strip() == d['card_cid'],
            'Live card/partition/filesystem identity differs')
    directory = child(store, 'systems/' + d['slot'])
    target = child(directory, 'root')
    actual, expected = root.stat(), target.stat()
    require((actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino) and actual.st_dev == store.stat().st_dev,
            'Selected directory is not the actual root')
    root_mount = json.loads(command('findmnt', '-J', '-M', str(root), '-o', 'TARGET,FSTYPE,FSROOT,MAJ:MIN'))['filesystems']
    require(root_mount == [dict(target='/', fstype='ext4', fsroot='/systems/' + d['slot'] + '/root',
                                **{'maj:min': number})], 'Root mount has a different filesystem root')
    tokens = bounded('/proc/cmdline').decode().split()
    for key, value in (('neo.dev', '1'), ('neo.slot', d['slot']), ('neo.store', 'PARTUUID=' + d['store_partuuid'])):
        require([x for x in tokens if x.startswith(key + '=')] == [key + '=' + value],
                'Development command line identity differs')
    release_raw = regular(directory, 'release.json')
    require(digest(release_raw) == d['release_sha256'] and json.loads(release_raw) == d['release'],
            'Live release manifest differs')
    require(json.loads(regular(store, 'RELEASES.JSON'))[d['slot']] == {'manifest_sha256': d['release_sha256']},
            'Live catalog does not select the expected release')
    require(digest(regular(directory, 'source-image.json')) == d['source_manifest_sha256'] and
            json.loads(regular(directory, 'source-image.json')) == d['image'] and
            digest(regular(directory, 'source-fstab')) == d['release']['source_fstab_sha256'],
            'Live original source provenance differs')
    image = regular(root, 'etc/gameshellneo/image.json')
    deployment = dict(d['image'], deployment='development-directory', slot=d['slot'],
        source_image_sha256=d['source_image_sha256'], source_manifest_sha256=d['source_manifest_sha256'],
        source_fstab_sha256=d['release']['source_fstab_sha256'], root_partuuid=d['store_partuuid'])
    require(image == json_bytes(deployment) and digest(image) == contract['image_sha256'],
            'Live deployment is not the exact source transformation')
    marker = f'schema=1\nid={d["slot"]}\nkernel={contract["kernel"]}\n'.encode()
    require(regular(root, 'etc/gameshellneo/development-slot') == marker and
            bounded('/run/gameshellneo-development-slot') == marker, 'Boot/root markers differ')
    # Battery protection is installed code, not the staged diagnostic. Preserve
    # its exact image identity; never silently replace it to make admission pass.
    for relative in ('usr/local/lib/gameshellneo/battery_guard.py',):
        require(digest(regular(root, relative)) == d['release']['immutable_files'][relative],
                'Installed battery guard differs from the release')
    return dict(slot=d['slot'], store_partuuid=d['store_partuuid'], store_uuid=d['store_uuid'],
        card_cid=d['card_cid'], root_device=actual.st_dev, root_inode=actual.st_ino,
        release_sha256=d['release_sha256'], source_image_sha256=d['source_image_sha256'],
        deployment_manifest_sha256=digest(image), pm_admission=False, clock_health_qualified=False)
