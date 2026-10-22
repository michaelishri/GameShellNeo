#!/usr/bin/env python3
"""Checkpoint the admitted development card off-device before growing its store.

Requires the original fixed recovery boot with the two installed releases and
all three flags at recovery. Cleanly unmounts boot/store, streams their exact
bytes and the reserved prefix over the established pinned SSH route, then
fully decompresses each host backup. Neither filesystem is remounted. Failed
or interrupted attempts retain every partial file and require inspection.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import sys
import time
import uuid

from dev_store import ADMIN_FILES
from dev_store_transport import load_hardware

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 1024 * 1024
LIMIT = 16 * CHUNK
REGISTRY = '/var/lib/gameshellneo-development-store-grow-backup'
PARENT = dict(cid='1b534d303030303010b1a30afb00e5e1', bytes=64013467648,
              sector_bytes=512, partuuid_prefix='b9dab681')
PARTITIONS = {
    'boot': dict(start_sector=32768, bytes=134217728, partuuid='b9dab681-01', filesystem_uuid='79EE-BC1E'),
    'recovery': dict(start_sector=294912, bytes=4143972352, partuuid='b9dab681-02',
                     filesystem_uuid='fc84f36c-79cc-441d-93e2-af1bca727996'),
    'store': dict(start_sector=8388608, bytes=4294967296, partuuid='b9dab681-03',
                  filesystem_uuid='905c31f6-8d2a-486c-8c57-ca1fd23ecd36'),
}
CATALOG = {
    'diag25': {'manifest_sha256': 'eb0969d7e8c757c4b72234426ffbfc957176bb05ac1a73dd440471ef6fff6bc0'},
    'diag27': {'manifest_sha256': 'ec5041df2e0321217273576b8a9b11f14b6e6d1096dce6c3b9c493eaa625cc9f'},
}
REGIONS = {
    'prefix': dict(file='prefix.img.gz', offset_bytes=0, raw_bytes=16777216, partition=None),
    'boot': dict(file='boot.img.gz', offset_bytes=16777216, raw_bytes=134217728, partition=1),
    'store': dict(file='store.img.gz', offset_bytes=4294967296, raw_bytes=4294967296, partition=3),
}


# Each remote phase is retained as its exact source on p2. No large archive is
# staged there; only metadata, logs and process identities occupy recovery.
COMMON = r'''import contextlib,fcntl,hashlib,json,os,re,stat,struct,subprocess,sys,time,traceback,zlib
from pathlib import Path

REGISTRY=Path('/var/lib/gameshellneo-development-store-grow-backup')
BOOT=Path('/boot')
STORE=Path('/mnt/neo-devstore')
KERNEL='6.18.54-gameshellneo24'
IMAGE_SHA='d45bcea1e79e9d2518c9e8632642183eb06387a0868cce75e78838f50fd0faf9'
FLAG_SHA='dce033ba9041858b244d2f15c1f1b3111057d93756f64b07f02c73ec0de1ef84'

def require(condition,message):
    if not condition:raise ValueError(message)

def real(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True)==path,
            'Expected an existing real absolute path: '+str(path))
    return path

def private_directory(path):
    path=real(path)
    for ancestor in (path,*path.parents):
        info=ancestor.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,
                'Checkpoint state ancestors must be root-owned and not writable by others')
    require(path.stat().st_dev==Path('/').stat().st_dev,'Checkpoint state must remain on recovery p2')
    return path

def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def save(path,value,*,replace=False):
    path=Path(path);temporary=path.with_name(path.name+'.new') if replace else path
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as output:
        json.dump(value,output,indent=2,sort_keys=True);output.write('\n');output.flush();os.fsync(output.fileno())
    if replace:os.replace(temporary,path)
    sync_directory(path.parent)

def read(path):
    path=real(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode),'Expected regular checkpoint metadata')
        data=source.read(16*1024*1024+1)
    require(len(data)<=16*1024*1024,'Metadata exceeds checkpoint bound')
    value=json.loads(data);require(isinstance(value,dict),'Expected a checkpoint metadata object')
    return value,data

def sha(path):
    path=real(path)
    require(path.is_file(),'Expected a regular pinned file')
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def settings_files(store,names):
    """Hash inactive regular settings through directory FDs, never symlinks."""
    store=real(store);pins={};scopes=('etc','root','home','var/lib')
    summary=dict(scope=list(scopes),releases={})
    directory_flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    for name in sorted(names):
        require(re.fullmatch(r'[a-z][a-z0-9-]*',name),'Unsafe settings release identifier')
        root=real(store/'systems'/name/'root')
        root_fd=os.open(root,directory_flags)
        try:
            device=os.fstat(root_fd).st_dev
            require(device==store.stat().st_dev,'Settings root crosses another filesystem')
            counts=dict(root='systems/'+name+'/root',files=0,bytes=0,symlinks_skipped=0)
            def safe_relative(relative):
                require(relative and '\\' not in relative and not any(ord(x)<32 for x in relative) and
                        all(part not in ('','.','..') for part in relative.split('/')),
                        'Settings path cannot be represented by the backup pin schema')
            def opened_directory(parent,child,expected):
                descriptor=os.open(child,directory_flags,dir_fd=parent)
                try:
                    actual=os.fstat(descriptor)
                    require(stat.S_ISDIR(actual.st_mode) and (actual.st_dev,actual.st_ino)==(expected.st_dev,expected.st_ino) and
                            actual.st_dev==device,'Settings directory changed or crosses another filesystem')
                except BaseException:
                    os.close(descriptor);raise
                return descriptor
            def descend(descriptor,relative):
                with os.scandir(descriptor) as entries:
                    names_here=sorted(entry.name for entry in entries)
                for child in names_here:
                    entry=relative+'/'+child;safe_relative(entry)
                    info=os.stat(child,dir_fd=descriptor,follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        counts['symlinks_skipped']+=1;continue
                    require(info.st_dev==device,'Settings object crosses another filesystem')
                    if stat.S_ISDIR(info.st_mode):
                        nested=opened_directory(descriptor,child,info)
                        try:descend(nested,entry)
                        finally:os.close(nested)
                    else:
                        require(stat.S_ISREG(info.st_mode),'Unsupported non-regular object in inactive settings')
                        fd=os.open(child,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
                        with os.fdopen(fd,'rb') as source:
                            before=os.fstat(source.fileno())
                            require(stat.S_ISREG(before.st_mode) and (before.st_dev,before.st_ino)==(info.st_dev,info.st_ino),
                                    'Settings file changed before hashing')
                            digest=hashlib.file_digest(source,'sha256').hexdigest()
                            after=os.fstat(source.fileno())
                            require((before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                                    (after.st_size,after.st_mtime_ns,after.st_ctime_ns),'Settings file changed while hashing')
                        pins['systems/'+name+'/root/'+entry]=digest
                        counts['files']+=1;counts['bytes']+=before.st_size
            for scope in scopes:
                current=os.dup(root_fd)
                try:
                    for component in scope.split('/'):
                        try:info=os.stat(component,dir_fd=current,follow_symlinks=False)
                        except FileNotFoundError:break
                        if stat.S_ISLNK(info.st_mode):
                            counts['symlinks_skipped']+=1;break
                        require(stat.S_ISDIR(info.st_mode),'Settings scope must be a directory when present')
                        nested=opened_directory(current,component,info)
                        os.close(current);current=nested
                    else:descend(current,scope)
                finally:os.close(current)
            summary['releases'][name]=counts
        finally:os.close(root_fd)
    summary['files']=sum(value['files'] for value in summary['releases'].values())
    summary['bytes']=sum(value['bytes'] for value in summary['releases'].values())
    return pins,summary

def command(arguments):
    return subprocess.check_output([str(x) for x in arguments],text=True,timeout=60)

def number(value):return f'{os.major(value)}:{os.minor(value)}'

def mounts(path=Path('/proc/self/mountinfo')):
    unescape=lambda value:re.sub(r'\\([0-7]{3})',lambda match:chr(int(match[1],8)),value)
    result=[]
    for line in path.read_text().splitlines():
        fields=line.split();separator=fields.index('-')
        result.append(dict(device=fields[2],root=unescape(fields[3]),point=unescape(fields[4]),
                           options=fields[5].split(','),filesystem=fields[separator+1],
                           source=unescape(fields[separator+2]),super_options=fields[separator+3].split(',')))
    return result

def other_mounts(devices,*,mounted,process_root=Path('/proc')):
    # Read every distinct mount namespace, so an alias hidden from the caller
    # cannot become a falsely admitted unmounted raw source.
    seen=set()
    for process in process_root.iterdir():
        if not process.name.isdecimal():continue
        try:
            namespace=os.readlink(process/'ns/mnt')
            if namespace in seen:continue
            records=mounts(process/'mountinfo');seen.add(namespace)
        except (FileNotFoundError,ProcessLookupError):continue
        for device,point in devices.items():
            selected=[x for x in records if x['device']==device]
            if mounted and selected:
                require(len(selected)==1 and selected[0]['point']==point and selected[0]['root']=='/',
                        'Boot/store has another mount namespace or bind alias')
            elif not mounted:require(not selected,'Checkpoint source remains mounted in a mount namespace')

def writer_handles(devices):
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal() or int(process.name)==os.getpid():continue
        try:entries=list((process/'fd').iterdir())
        except (FileNotFoundError,ProcessLookupError):continue
        for entry in entries:
            try:
                info=entry.stat()
                if not stat.S_ISBLK(info.st_mode) or number(info.st_rdev) not in devices:continue
                data=(process/'fdinfo'/entry.name).read_text()
                flags=next(int(line.split()[1],8) for line in data.splitlines() if line.startswith('flags:'))
                require(flags&os.O_ACCMODE==os.O_RDONLY,'A process has the card or checkpoint source open for writing')
            except (FileNotFoundError,ProcessLookupError):continue

def block(device):
    source=(Path('/sys/dev/block')/device).resolve(strict=True)
    node=real('/dev/'+source.name);info=node.stat()
    require(stat.S_ISBLK(info.st_mode) and number(info.st_rdev)==device,'Canonical block source differs')
    return dict(node=str(node),device=device,number=int((source/'partition').read_text()),
                parent=str(source.parent),start_sector=int((source/'start').read_text()),
                bytes=int((source/'size').read_text())*512)

def identity(v,*,unmounted=False):
    require(os.geteuid()==0,'Checkpoint requires root on fixed recovery')
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==v['boot_id'],'Recovery boot changed')
    image,data=read('/etc/gameshellneo/image.json')
    require(hashlib.sha256(data).hexdigest()==IMAGE_SHA and os.uname().release==KERNEL and
            image.get('kernel')==KERNEL and image.get('board')=='gameshellneo-cpi31' and
            image.get('root_partuuid')=='b9dab681-02' and 'deployment' not in image,
            'Expected the original fixed recovery image and kernel')
    for marker in ('/etc/gameshellneo/development-slot','/run/gameshellneo-development-slot'):
        require(not Path(marker).exists() and not Path(marker).is_symlink(),'Directory deployment is not admitted')
    cmdline=Path('/proc/cmdline').read_text().split()
    require(not any(x.startswith('neo.') for x in cmdline) and
            [x for x in cmdline if x.startswith('root=')]==['root=PARTUUID=b9dab681-02'],
            'Recovery command-line identity differs')
    records=mounts();roots=[x for x in records if x['point']=='/']
    require(len(roots)==1 and roots[0]['root']=='/' and roots[0]['filesystem']=='ext4' and
            roots[0]['device']==number(Path('/').stat().st_dev),'Running root is not a fixed partition mount')
    recovery=block(roots[0]['device']);require(recovery['number']==2,'Running root is not p2')
    parent=Path(recovery['parent'])
    actual=dict(cid=(parent/'device/cid').read_text().strip(),bytes=int((parent/'size').read_text())*512,
                sector_bytes=int((parent/'queue/logical_block_size').read_text()),partuuid_prefix='b9dab681')
    require(actual==v['parent'],'Physical card CID, capacity or sector size differs')
    parts={}
    for child in parent.iterdir():
        if not (child/'partition').is_file():continue
        part=block((child/'dev').read_text().strip())
        require(part['number'] not in parts,'Ambiguous card partition number');parts[part['number']]=part
    require(set(parts)=={1,2,3},'Expected exactly three card partitions')
    for index,name in ((1,'boot'),(2,'recovery'),(3,'store')):
        part,expected=parts[index],v['partitions'][name]
        require(part['parent']==str(parent) and all(part[key]==expected[key] for key in ('start_sector','bytes')),
                'Card partition geometry differs: '+name)
        fs=dict(line.split('=',1) for line in command(['blkid','-p','-o','export',part['node']]).splitlines() if '=' in line)
        require(fs.get('UUID')==expected['filesystem_uuid'] and fs.get('PART_ENTRY_UUID')==expected['partuuid'] and
                fs.get('TYPE')==('vfat' if index==1 else 'ext4'),'Filesystem/PARTUUID identity differs: '+name)
        matches=[]
        for event in Path('/sys/class/block').glob('*/uevent'):
            values=dict(line.split('=',1) for line in event.read_text().splitlines() if '=' in line)
            if values.get('PARTUUID')==expected['partuuid']:matches.append(event.parent.name)
        require(matches==[Path(part['node']).name],'Missing or duplicated card PARTUUID')
    devices={parts[1]['device']:str(BOOT),parts[3]['device']:str(STORE)}
    for index,path,kind in ((1,BOOT,'vfat'),(3,STORE,'ext4')):
        real(path)
        matching=[x for x in records if x['device']==parts[index]['device']]
        if unmounted:
            require(not matching and path.stat().st_dev==Path('/').stat().st_dev and not any(path.iterdir()),
                    'Checkpoint source mountpoint must remain empty and unmounted')
        else:
            require(len(matching)==1 and matching[0]['point']==str(path) and matching[0]['root']=='/' and
                    matching[0]['filesystem']==kind and number(path.stat().st_dev)==parts[index]['device'],
                    'Expected one exact mounted boot/store filesystem')
            options=matching[0]['options']+matching[0]['super_options']
            require('rw' in options and 'ro' not in options,'Expected writable boot/store for clean unmount')
            if index==1:require('shortname=mixed' in options,'Boot FAT requires shortname=mixed')
    other_mounts(devices,mounted=not unmounted)
    parent_node=real('/dev/'+parent.name)
    require(stat.S_ISBLK(parent_node.stat().st_mode) and number(parent_node.stat().st_rdev)==(parent/'dev').read_text().strip(),
            'Expected canonical card block device')
    writer_handles({*devices,number(parent_node.stat().st_rdev)})
    return parts,parent_node

def process_identity():
    data=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return dict(pid=os.getpid(),start_ticks=int(data[19]),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                started_boottime_ns=time.clock_gettime_ns(time.CLOCK_BOOTTIME))

def verify_mbr(mbr,v):
    require(len(mbr)==512 and mbr[510:]==b'\x55\xaa' and mbr[440:444].hex()=='81b6dab9',
            'Unexpected MBR signature or card disk identifier')
    for index,name in enumerate(('boot','recovery','store')):
        entry=mbr[446+16*index:462+16*index];expected=v['partitions'][name]
        require(int.from_bytes(entry[8:12],'little')==expected['start_sector'] and
                int.from_bytes(entry[12:16],'little')*512==expected['bytes'] and
                entry[4]==(14 if index==0 else 131),'MBR partition identity differs: '+name)
    require(mbr[494:510]==bytes(16),'Unexpected fourth MBR partition entry')

def terminal_unit(properties):
    return (properties.get('ActiveState')=='active' and properties.get('SubState')=='exited' and
            properties.get('Result')=='success' and properties.get('MainPID')=='0' and
            properties.get('Job') in ('','0') and properties.get('ExecMainPID','0').isdecimal() and
            int(properties.get('ExecMainPID','0'))>0 and properties.get('ExecMainCode')=='1' and
            properties.get('ExecMainStatus')=='0')

@contextlib.contextmanager
def lock():
    private_directory(REGISTRY)
    fd=os.open(REGISTRY/'backup.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o077,'Invalid checkpoint lock')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('Another checkpoint phase owns recovery') from error
        yield
    finally:os.close(fd)

def inactive_writers():
    for registry in (Path('/var/lib/gameshellneo-development-store-installer'),
                     Path('/var/lib/gameshellneo-development-store-grower')):
        if not registry.exists():continue
        private_directory(registry)
        for name in ('writer.lock','operation.lock'):
            path=registry/name
            if not path.exists() and not path.is_symlink():continue
            fd=os.open(real(path),os.O_RDWR|os.O_NOFOLLOW)
            try:
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as error:raise ValueError('Another store operation owns recovery') from error
            finally:os.close(fd)
        latest=registry/'latest.json'
        if latest.exists() or latest.is_symlink():
            value,_=read(latest);previous=private_directory(value['state']);record,_=read(previous/'state.json')
            require(not record.get('write_started') or record.get('completed') is True,
                    'Previous store writer is unresolved; inspect its original operation')
    active=command(['systemctl','list-units','--state=active,activating,reloading,deactivating','--no-legend','--plain','--no-pager'])
    for line in active.splitlines():
        name=line.split()[0] if line.strip() else ''
        if not (name.startswith('gameshellneo-') and any(x in name for x in ('bundle-import','store-install','store-grow'))):continue
        properties=('ActiveState','SubState','Result','MainPID','Job','ExecMainPID','ExecMainCode','ExecMainStatus')
        state=command(['systemctl','show',name,*['--property='+key for key in properties]])
        state=dict(line.split('=',1) for line in state.splitlines() if '=' in line)
        require(terminal_unit(state),'A development-store writer unit remains active or unresolved')

def phase(here,name,**fields):save(here/'phase.json',dict(phase=name,**fields),replace=True)
'''

ADMISSION = COMMON + r'''
def admit(v,sources):
    parts,parent=identity(v)
    private_directory(REGISTRY.parent)
    if not REGISTRY.exists():REGISTRY.mkdir(mode=0o700);sync_directory(REGISTRY.parent)
    with lock():
        inactive_writers()
        latest=REGISTRY/'latest.json'
        if latest.exists() or latest.is_symlink():
            previous,_=read(latest);old=private_directory(previous['directory'])
            result,_=read(old/'result.json')
            require(result.get('completed') is True,'Previous checkpoint is unresolved; inspect it without retrying')
        here=Path(v['remote'])
        require(here.parent==REGISTRY and not here.exists() and not here.is_symlink(),'Checkpoint path already exists')
        here.mkdir(mode=0o700);sync_directory(REGISTRY)
        save(here/'planned.json',v)
        save(here/'admission.started.json',process_identity())
        save(REGISTRY/'latest.json',dict(directory=str(here)),replace=True)
        for name,source in sources.items():
            require(name in ('admission.py','stream.py','finalize.py'),'Unexpected checkpoint source name')
            require(hashlib.sha256(source.encode()).hexdigest()==v['source_sha256'][name],
                    'Checkpoint source differs from the planned host receipt')
            path=here/name
            with path.open('xb') as output:
                os.fchmod(output.fileno(),0o600);output.write(source.encode());output.flush();os.fsync(output.fileno())
        sync_directory(here)
        try:
            phase(here,'verifying-releases')
            for relative,expected in v['admin_import_pins'].items():
                require(sha(STORE/relative)==expected,'Pinned card administration source differs: '+relative)
            selection=real(STORE/'.selection.lock')
            descriptor=os.open(selection,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                info=os.fstat(descriptor)
                require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,
                        'Invalid existing card selection lock')
                try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as error:raise ValueError('Another card selector owns the store') from error
                sys.path.insert(0,str(STORE/'admin/tools'))
                from dev_systems import Card,FLAGS
                card=Card(BOOT,STORE)
                require(card.releases==v['catalog'],'Expected exactly the pinned diag25 and diag27 releases')
                releases={name:card.verify(name) for name in sorted(card.releases)}
                flags={name:sha(BOOT/name) for name in FLAGS}
                require(set(flags.values())=={FLAG_SHA},'All boot flags must remain fixed recovery')
                require(card.record['recovery_partuuid']=='b9dab681-02' and card.record['store_partuuid']=='b9dab681-03',
                        'Card catalog partition identities differ')
                paths=set(v['admin_files'])|{'DEVBOOT.JSON','RELEASES.JSON'}
                paths|={'systems/'+name+'/'+item for name in releases for item in ('release.json','source-image.json','source-fstab')}
                pins={relative:sha(STORE/relative) for relative in sorted(paths)}
                boot_pins={relative:sha(BOOT/relative) for relative in ('DEVBOOT.JSON','boot.cmd','boot.scr',*FLAGS)}
                for name,release in releases.items():
                    for asset in release['boot_files']:
                        relative='systems/'+name+'/boot/'+asset;pins[relative]=sha(STORE/relative)
                settings,settings_summary=settings_files(STORE,releases)
                pins.update(settings)
                require(len(pins)<=100000,'Settings and administration pins exceed the backup schema bound')
                # No selector descriptor may remain open when unmounting p3.
                result=dict(schema=1,checkpoint=v['checkpoint'],root=dict(boot_id=v['boot_id'],root_partuuid='b9dab681-02',
                    directory_deployment=False,image_sha256=IMAGE_SHA,kernel=KERNEL),parent=v['parent'],
                    partitions=v['partitions'],card=card.record,catalog=card.releases,flags=flags,store_files=pins,
                    boot_files=boot_pins,releases=releases,settings_verification=settings_summary,
                    source_hashes={name:hashlib.sha256(source.encode()).hexdigest() for name,source in sources.items()})
            finally:os.close(descriptor)
            identity(v);inactive_writers()
            phase(here,'unmounting-boot-store')
            os.sync()
            for path in (BOOT,STORE):subprocess.run(['umount','--',str(path)],check=True,timeout=60)
            parts,parent=identity(v,unmounted=True)
            checks={}
            for index,name,arguments in ((1,'boot',['fsck.fat','-n']),(3,'store',['e2fsck','-f','-n'])):
                phase(here,'checking-'+name)
                checked=subprocess.run([*arguments,parts[index]['node']],capture_output=True,text=True,timeout=600)
                checks[name]=dict(exit_code=checked.returncode,stdout=checked.stdout,stderr=checked.stderr)
                save(here/(name+'.fsck.json'),checks[name])
                require(checked.returncode==0,'Unmounted read-only filesystem check failed: '+name)
            identity(v,unmounted=True)
            with parent.open('rb',buffering=0) as source:
                mbr=source.read(512);protected=hashlib.sha256();remaining=16777216-512
                while remaining:
                    data=source.read(min(1024*1024,remaining));require(bool(data),'Reserved prefix read was truncated')
                    protected.update(data);remaining-=len(data)
            verify_mbr(mbr,v)
            result.update(checks=checks,mbr_hex=mbr.hex(),protected_prefix_sha256=protected.hexdigest(),
                          source_unmounted=True,parent_node=str(parent),source_nodes={name:parts[index]['node'] for index,name in ((1,'boot'),(3,'store'))})
            save(here/'admission.json',result);phase(here,'admitted-unmounted')
            return result
        except BaseException as error:
            save(here/'admission.failed.json',dict(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc()))
            phase(here,'failed-admission');raise
'''

STREAM = COMMON + r'''
def stream(here,name):
    here=private_directory(here);v,_=read(here/'planned.json');admission,_=read(here/'admission.json')
    require(name in v['regions'],'Unknown checkpoint region')
    item=v['regions'][name]
    with lock():
        inactive_writers();parts,parent=identity(v,unmounted=True)
        require(not (here/(name+'.started.json')).exists(),'This original region was already submitted; inspect it without retrying')
        save(here/(name+'.started.json'),process_identity());phase(here,'streaming-'+name)
        try:
            node=parent if name=='prefix' else Path(parts[item['partition']]['node'])
            offset=item['offset_bytes'] if name=='prefix' else 0
            flags=os.O_RDONLY|os.O_NOFOLLOW|(0 if name=='prefix' else os.O_EXCL)
            fd=os.open(node,flags)
            try:
                info=os.fstat(fd)
                require(stat.S_ISBLK(info.st_mode) and info.st_rdev==node.stat().st_rdev,'Raw source descriptor identity differs')
                size=struct.unpack('Q',fcntl.ioctl(fd,0x80001272|(struct.calcsize('N')<<16),bytes(8)))[0]
                expected=v['parent']['bytes'] if name=='prefix' else item['raw_bytes']
                require(size==expected,'Raw source size differs')
                os.lseek(fd,offset,os.SEEK_SET)
                raw=hashlib.sha256();packed=hashlib.sha256();protected=hashlib.sha256();mbr=bytearray()
                count=packed_count=0;compress=zlib.compressobj(level=1,wbits=31)
                def send(data):
                    nonlocal packed_count
                    packed.update(data);packed_count+=len(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
                remaining=item['raw_bytes']
                while remaining:
                    data=os.read(fd,min(1024*1024,remaining));require(bool(data),'Raw checkpoint source ended before its exact boundary')
                    if name=='prefix':
                        first=min(len(data),max(0,512-count))
                        if first:mbr.extend(data[:first])
                        protected.update(data[first:])
                    raw.update(data);count+=len(data);remaining-=len(data);send(compress.compress(data))
                send(compress.flush())
                if name=='prefix':
                    require(mbr.hex()==admission['mbr_hex'] and protected.hexdigest()==admission['protected_prefix_sha256'],
                            'Reserved prefix changed after admission')
                identity(v,unmounted=True)
                result=dict(name=name,offset_bytes=item['offset_bytes'],raw_bytes=count,raw_sha256=raw.hexdigest(),
                            gzip_bytes=packed_count,gzip_sha256=packed.hexdigest(),source_unmounted=True,
                            checkpoint=v['checkpoint'],boot_id=v['boot_id'])
                save(here/(name+'.json'),result);phase(here,'streamed-'+name)
            finally:os.close(fd)
        except BaseException as error:
            save(here/(name+'.failed.json'),dict(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc()))
            phase(here,'failed-stream-'+name);raise

if __name__=='__main__':stream(Path(__file__).parent,sys.argv[1])
'''

FINALIZE = COMMON + r'''
def finalize(here):
    here=private_directory(here);v,_=read(here/'planned.json');admission,data=read(here/'admission.json')
    with lock():
        inactive_writers();identity(v,unmounted=True)
        save(here/'finalize.started.json',process_identity())
        regions={}
        for name in v['regions']:
            result,payload=read(here/(name+'.json'))
            require(result['checkpoint']==v['checkpoint'] and result['boot_id']==v['boot_id'] and
                    result['raw_bytes']==v['regions'][name]['raw_bytes'] and result['source_unmounted'] is True,
                    'Incomplete or mismatched original source receipt')
            regions[name]=dict(sha256=hashlib.sha256(payload).hexdigest(),result=result)
        result=dict(schema=1,checkpoint=v['checkpoint'],boot_id=v['boot_id'],completed=True,
                    admission_sha256=hashlib.sha256(data).hexdigest(),regions=regions,
                    source_unmounted=True,reboot_performed=False,selection_performed=False)
        save(here/'result.json',result);phase(here,'complete-source-streams')
        print(json.dumps(result),flush=True)

if __name__=='__main__':finalize(Path(__file__).parent)
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def save_once(path, value):
    data = value if isinstance(value, bytes) else json_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def checkpoint_plan(boot_id, output):
    require(str(uuid.UUID(boot_id)) == boot_id, 'Use the exact canonical current recovery boot UUID')
    require(Path(output).is_absolute(), 'Output must be an absolute path')
    output = Path(output).expanduser().absolute()
    require('..' not in output.parts and not output.exists() and not output.is_symlink(),
            'Output must be a new absolute directory; preserve previous and partial checkpoints')
    parent = output.parent
    require(parent.resolve(strict=True) == parent and parent.is_dir(), 'Output parent must exist without symlinks')
    local = ROOT / '.local'
    require(local.resolve(strict=True) == local and parent.is_relative_to(local),
            'Checkpoint output must be inside this checkout\'s .local directory')
    require(shutil.disk_usage(parent).free >= sum(item['raw_bytes'] for item in REGIONS.values()) + 64 * CHUNK,
            'Host lacks space for worst-case compressed backups and retained evidence')
    output.mkdir(mode=0o700)
    checkpoint = 'checkpoint-' + uuid.uuid4().hex
    plan = dict(schema=1, operation='development-store-growth-checkpoint', development_only=True,
                checkpoint=checkpoint, boot_id=boot_id, remote=REGISTRY + '/' + checkpoint,
                parent=PARENT, partitions=PARTITIONS, catalog=CATALOG, regions=REGIONS,
                admin_files=sorted(ADMIN_FILES), admin_import_pins={
                    'admin/tools/dev_systems.py': '0e777c167be738fd082b2c839d2eee84ed0c9375b92ec7f1c75221d0288b71f6',
                    'admin/tools/dev_boot_scripts.py': 'd045ae7906e496ff8cbe5a8efbf88a0bfe43f6def7ff5e89bdc50176410f2524',
                    'admin/tools/usb_poll_boot.py': '5a21f78e667493196a4d43a8966a316c38c44e346f76aded8d83118842819815'},
                state='planned-not-yet-submitted', output=str(output))
    plan['source_sha256'] = {name: hashlib.sha256(source.encode()).hexdigest() for name, source in
                            (('admission.py', ADMISSION), ('stream.py', STREAM), ('finalize.py', FINALIZE))}
    save_once(output / 'planned.json', plan)
    return plan, output


def get_remote(remote, client, directory, name):
    require(re.fullmatch(r'[a-z][a-z0-9.-]*', name), 'Invalid checkpoint receipt name')
    source = COMMON + '''
here=private_directory(sys.argv[1]);value,data=read(here/sys.argv[2]);sys.stdout.buffer.write(data)
'''
    return remote.run(client, **remote.python_command(source, directory, name), display=False, timeout=60)


def stream_region(remote, client, plan, name, output):
    item = plan['regions'][name]
    temporary = output / (item['file'] + '.part')
    errors = output / (name + '-stderr.txt')
    for path in (temporary, errors, output / item['file'], output / (name + '-source.json'),
                 output / (name + '-verified.json')):
        if path.exists() or path.is_symlink():
            raise FileExistsError('This original checkpoint region already has evidence; inspect without resubmission')
    started = previous = time.monotonic()
    packed, count = hashlib.sha256(), 0
    def receive(data, target):
        nonlocal count
        count += len(data)
        require(count <= item['raw_bytes'] + item['raw_bytes'] // 100 + CHUNK,
                'Compressed stream exceeds its source bound')
        target.write(data)
        packed.update(data)
    channel = client.get_transport().open_session(timeout=15)
    try:
        channel.settimeout(30)
        channel.exec_command(shlex.join(['sudo', '-n', 'python3', '-I', '-B', plan['remote'] + '/stream.py', name]))
        channel.shutdown_write()
        channel.settimeout(1)
        with temporary.open('xb') as target, errors.open('xb') as stderr:
            try:
                while True:
                    while channel.recv_stderr_ready():
                        stderr.write(channel.recv_stderr(65536))
                        stderr.flush()
                    if channel.recv_ready():
                        data = channel.recv(CHUNK)
                        if data:
                            receive(data, target)
                    elif channel.exit_status_ready():
                        break
                    else:
                        try:
                            data = channel.recv(CHUNK)
                            if not data:
                                break
                            receive(data, target)
                        except socket.timeout:
                            pass
                    now = time.monotonic()
                    if now - previous >= 10:
                        print(name + ': received ' + str(count // CHUNK) + ' compressed MiB', flush=True)
                        previous = now
                    require(now - started <= 7200, 'Observation timed out; inspect the original checkpoint before further action')
                while channel.recv_stderr_ready():
                    stderr.write(channel.recv_stderr(65536))
                code = channel.recv_exit_status()
                require(code == 0, 'Original checkpoint stream failed (exit ' + str(code) + '); retain partial and inspect')
            finally:
                target.flush()
                stderr.flush()
                os.fsync(target.fileno())
                os.fsync(stderr.fileno())
    finally:
        channel.close()
    payload = get_remote(remote, client, plan['remote'], name + '.json')
    save_once(output / (name + '-source.json'), payload)
    receipt = json.loads(payload)
    require(receipt['checkpoint'] == plan['checkpoint'] and receipt['boot_id'] == plan['boot_id'] and
            receipt['offset_bytes'] == item['offset_bytes'] and receipt['source_unmounted'] is True and
            (count, packed.hexdigest()) == (receipt['gzip_bytes'], receipt['gzip_sha256']),
            'Compressed checkpoint or original source identity differs')
    print(name + ': verifying the complete decompressed backup', flush=True)
    raw, raw_count, previous = hashlib.sha256(), 0, time.monotonic()
    protected, mbr = hashlib.sha256(), bytearray()
    with gzip.open(temporary, 'rb') as source:
        while data := source.read(CHUNK):
            if name == 'prefix':
                first = min(len(data), max(0, 512 - raw_count))
                if first:
                    mbr.extend(data[:first])
                protected.update(data[first:])
            raw.update(data)
            raw_count += len(data)
            require(raw_count <= item['raw_bytes'], 'Decompressed checkpoint exceeds the region boundary')
            now = time.monotonic()
            if now - previous >= 10:
                print(name + ': verified ' + str(raw_count // CHUNK) + ' raw MiB', flush=True)
                previous = now
    require((raw_count, raw.hexdigest()) == (item['raw_bytes'], receipt['raw_sha256']) and
            receipt['raw_bytes'] == raw_count, 'Full decompressed checkpoint differs from the original source')
    final = output / item['file']
    os.link(temporary, final, follow_symlinks=False)
    temporary.unlink()
    region = {key: receipt[key] for key in ('offset_bytes', 'raw_bytes', 'raw_sha256', 'gzip_bytes', 'gzip_sha256', 'source_unmounted')}
    region.update(file=item['file'], verified_full_decompressed=True)
    save_once(output / (name + '-verified.json'), dict(region, elapsed_seconds=time.monotonic() - started))
    print(name + ': complete backup verified (' + str(raw_count) + ' bytes)', flush=True)
    return region, (mbr.hex(), protected.hexdigest()) if name == 'prefix' else None


def run_logged(remote, client, source, arguments, output, label, timeout):
    """Bound an observation while retaining separate original stdout/stderr."""
    parameters = remote.python_command(source, *arguments)
    channel = client.get_transport().open_session(timeout=15)
    started = previous = time.monotonic()
    result = bytearray()
    try:
        channel.settimeout(30)
        channel.exec_command(parameters['command'])
        channel.sendall(parameters['input_data'])
        channel.shutdown_write()
        channel.settimeout(1)
        with (output / (label + '-output.txt')).open('xb') as stdout, \
                (output / (label + '-stderr.txt')).open('xb') as stderr:
            try:
                while True:
                    while channel.recv_stderr_ready():
                        stderr.write(channel.recv_stderr(65536))
                        stderr.flush()
                    if channel.recv_ready():
                        data = channel.recv(65536)
                    elif channel.exit_status_ready():
                        break
                    else:
                        try:
                            data = channel.recv(65536)
                        except socket.timeout:
                            data = None
                    if data:
                        stdout.write(data)
                        stdout.flush()
                        result.extend(data)
                        require(len(result) <= LIMIT, 'Remote checkpoint metadata exceeded its bound')
                    now = time.monotonic()
                    if now - previous >= 10:
                        print(label + ': original checkpoint still running (' + str(int(now - started)) + ' seconds)', flush=True)
                        previous = now
                    require(now - started <= timeout, 'Observation timed out; inspect the original checkpoint')
                while channel.recv_stderr_ready():
                    stderr.write(channel.recv_stderr(65536))
                code = channel.recv_exit_status()
                require(code == 0, 'Original ' + label + ' failed (exit ' + str(code) + '); preserve and inspect')
            finally:
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
    finally:
        channel.close()
    return bytes(result)


def status(remote, config, output):
    output = Path(output).absolute()
    require(output.resolve(strict=True) == output and output.is_dir(), 'Status requires the original checkpoint directory')
    plan = json.loads((output / 'planned.json').read_bytes())
    require(plan['operation'] == 'development-store-growth-checkpoint', 'Not an original growth checkpoint')
    source = COMMON + '''
v=json.loads(sys.argv[1]);here=private_directory(v['remote'])
actual=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
result=dict(checkpoint=v['checkpoint'],expected_boot_id=v['boot_id'],actual_boot_id=actual,files={},processes={})
for path in sorted(here.iterdir()):
    if path.suffix!='.json':continue
    value,data=read(path);result['files'][path.name]=value
    if path.name.endswith('.started.json'):
        live=False
        try:
            fields=Path('/proc/'+str(value['pid'])+'/stat').read_text().rsplit(')',1)[1].split()
            live=(actual==value['boot_id'] and int(fields[19])==value['start_ticks'])
        except (FileNotFoundError,ProcessLookupError):pass
        result['processes'][path.name]=dict(original_process_alive=live,identity=value)
print(json.dumps(result))
'''
    with remote.device(config, 'usb') as client:
        value = remote.run(client, **remote.python_command(source, json.dumps(plan)), display=False, timeout=60)
    save_once(output / ('observation-' + uuid.uuid4().hex + '.json'), value)
    print(value.decode(), end='')


def execute(remote, config, plan, output):
    sources = {'admission.py': ADMISSION, 'stream.py': STREAM, 'finalize.py': FINALIZE}
    for name, source in sources.items():
        save_once(output / name, source.encode())
    bootstrap = 'SOURCES=' + repr(sources) + '\n' + ADMISSION + '\nprint(json.dumps(admit(json.loads(sys.argv[1]),SOURCES)),flush=True)\n'
    save_once(output / 'submission-source.py', bootstrap.encode())
    try:
        print('Checkpoint ' + plan['checkpoint'] + ': verifying fixed recovery and both releases', flush=True)
        with remote.device(config, 'usb') as client:
            payload = run_logged(remote, client, bootstrap, [json.dumps(plan)], output, 'admission', 900)
            # Fetch exact durable bytes rather than hashing the transport's JSON
            # serialization. These are the evidence pins consumed by growth.
            admission_payload = get_remote(remote, client, plan['remote'], 'admission.json')
            admission = json.loads(admission_payload)
            require(json.loads(payload) == admission, 'Admission output and durable original receipt differ')
            save_once(output / 'admission.json', admission_payload)
            regions, prefix = {}, None
            for name in plan['regions']:
                regions[name], reserved = stream_region(remote, client, plan, name, output)
                if reserved is not None:
                    prefix = reserved
            require(prefix == (admission['mbr_hex'], admission['protected_prefix_sha256']),
                    'Host decompressed MBR/reserved prefix differs from source admission')
            source = 'import subprocess,sys\nsubprocess.run([sys.executable,"-I","-B",sys.argv[1]+"/finalize.py"],check=True)\n'
            run_logged(remote, client, source, [plan['remote']], output, 'finalize', 120)
            result_payload = get_remote(remote, client, plan['remote'], 'result.json')
            result = json.loads(result_payload)
            save_once(output / 'checkpoint-result.json', result_payload)
            require(result['checkpoint'] == plan['checkpoint'] and result['boot_id'] == plan['boot_id'] and
                    result['completed'] is True and result['source_unmounted'] is True and
                    result['admission_sha256'] == hashlib.sha256(admission_payload).hexdigest(),
                    'Original source completion receipt differs')
            for name in regions:
                require(result['regions'][name]['sha256'] == hashlib.sha256((output / (name + '-source.json')).read_bytes()).hexdigest(),
                        'Source region receipt changed before finalization')
        receipt = dict(schema=1, operation='development-store-growth-backup', development_only=True, verified=True,
                       root=admission['root'], parent=admission['parent'], partitions=admission['partitions'],
                       regions=regions, card=admission['card'], catalog=admission['catalog'], flags=admission['flags'],
                       store_files=admission['store_files'], mbr_hex=prefix[0], protected_prefix_sha256=prefix[1],
                       evidence=dict(admission_sha256=hashlib.sha256(admission_payload).hexdigest(),
                                     checkpoint_result_sha256=hashlib.sha256(result_payload).hexdigest()))
        save_once(output / 'backup-receipt.json', receipt)
        print('Verified fresh off-device backup: ' + str(output / 'backup-receipt.json'), flush=True)
        print('Boot and store remain unmounted. No selection, reboot or resize was performed.', flush=True)
        return 0
    except BaseException as error:
        save_once(output / 'host-failure.json', dict(checkpoint=plan['checkpoint'],
                  error=type(error).__name__ + ': ' + str(error), original_remote_completion_unknown=True,
                  instruction='Preserve all partials; inspect this checkpoint with --status. Do not remount or retry automatically.'))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware-checkout', default=os.environ.get('NEO_HARDWARE_CHECKOUT'), type=Path)
    parser.add_argument('--boot-id', help='Exact current original fixed recovery boot UUID')
    parser.add_argument('--output', type=Path, help='New absolute directory under this checkout\'s .local')
    parser.add_argument('--status', type=Path, metavar='DIRECTORY', help='Read the original checkpoint receipts and process identities')
    args = parser.parse_args()
    if args.status is not None:
        require(args.boot_id is None and args.output is None, 'Status does not start or repeat a checkpoint')
        directory = args.status.absolute()
        remote, config = load_hardware(args.hardware_checkout)
        status(remote, config, directory)
        return 0
    require(args.boot_id is not None and args.output is not None, 'Checkpoint requires --boot-id and --output')
    plan, output = checkpoint_plan(args.boot_id, args.output)
    remote, config = load_hardware(args.hardware_checkout)
    return execute(remote, config, plan, output)


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
