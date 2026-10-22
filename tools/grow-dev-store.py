#!/usr/bin/env python3
"""Inspect, submit once, or observe an explicit development-store expansion."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 16 * 1024 * 1024
DEPENDENCIES = ('dev_store_grow.py', 'install-dev-store.py', 'dev_store.py')

INSPECT = r'''import hashlib,json,os,subprocess
from pathlib import Path
def call(args):return subprocess.check_output(args,text=True,timeout=30).strip()
def fs(node):return dict(x.split('=',1) for x in call(['blkid','-p','-o','export',node]).splitlines() if '=' in x)
root_info=Path('/').stat()
root=Path('/sys/dev/block')/f'{os.major(root_info.st_dev)}:{os.minor(root_info.st_dev)}'
root=root.resolve(strict=True)
if not (root/'partition').is_file():raise ValueError('Root is not on a physical card partition')
parent=root.parent;node='/dev/'+parent.name
if not parent.name.startswith('mmcblk'):raise ValueError('Expected the GameShell MMC card')
parts={}
for p in parent.iterdir():
 if not (p/'partition').is_file():continue
 n=int((p/'partition').read_text());v=fs('/dev/'+p.name)
 parts[{1:'boot',2:'recovery',3:'store'}.get(n,str(n))]={'start_sector':int((p/'start').read_text()),'bytes':int((p/'size').read_text())*512,'partuuid':v.get('PART_ENTRY_UUID'),'filesystem_uuid':v.get('UUID')}
with open(node,'rb',buffering=0) as f:mbr=f.read(512)
image=Path('/etc/gameshellneo/image.json');identity=json.loads(image.read_text())
mounts=[]
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 fields=line.split();sep=fields.index('-');mounts.append({'device':fields[2],'root':fields[3],'point':fields[4],'options':fields[5],'filesystem':fields[sep+1]})
print(json.dumps({'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'root_partition':int((root/'partition').read_text()),'kernel':os.uname().release,'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'directory_deployment':'deployment' in identity or Path('/run/gameshellneo-development-slot').exists(),'parent':{'cid':(parent/'device/cid').read_text().strip(),'bytes':int((parent/'size').read_text())*512,'sector_bytes':int((parent/'queue/logical_block_size').read_text()),'partuuid_prefix':mbr[440:444][::-1].hex()},'partitions':parts,'mbr_hex':mbr.hex(),'mounts':mounts}))
'''

SUBMIT = r'''import base64,hashlib,json,os,stat,subprocess,sys
from pathlib import Path
v=PAYLOAD;receipt=v['backup'];here=Path(v['remote_directory'])
if os.geteuid()!=0:raise ValueError('Root staging is required')
if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=receipt['root']['boot_id']:raise ValueError('Recovery boot changed before submission')
root_info=Path('/').stat()
root=Path('/sys/dev/block')/f'{os.major(root_info.st_dev)}:{os.minor(root_info.st_dev)}'
root=root.resolve(strict=True)
if not (root/'partition').is_file() or int((root/'partition').read_text())!=2:raise ValueError('Submission requires fixed recovery p2')
image=Path('/etc/gameshellneo/image.json');identity=json.loads(image.read_text())
if 'deployment' in identity or hashlib.sha256(image.read_bytes()).hexdigest()!=receipt['root']['image_sha256'] or os.uname().release!=receipt['root']['kernel']:raise ValueError('Recovery provenance differs')
for p in (here.parent,*here.parent.parents):
 s=p.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Unsafe private recovery staging parent')
if here.parent.stat().st_dev!=Path('/').stat().st_dev:raise ValueError('Staging is outside recovery p2')
here.mkdir(mode=0o700)
def save(name,data):
 with (here/name).open('xb') as f:os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
for name,item in v['sources'].items():
 if name not in ('dev_store_grow.py','install-dev-store.py','dev_store.py'):raise ValueError('Unexpected staged source')
 data=base64.b64decode(item['base64'],validate=True)
 if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Source hash differs')
 save(name,data)
save('backup-receipt.json',json.dumps(receipt,sort_keys=True,indent=2).encode()+b'\n')
save('submission.json',json.dumps({k:x for k,x in v.items() if k!='sources'},sort_keys=True,indent=2).encode()+b'\n')
fd=os.open(here,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
cmd=['systemd-run','--no-block','--unit='+v['unit'],'--property=Type=oneshot','--property=RemainAfterExit=yes','--property=Restart=no','--property=TimeoutStartSec=infinity','--property=UMask=0077','--property=WorkingDirectory='+str(here),'--property=StandardOutput=append:'+str(here/'unit.stdout'),'--property=StandardError=append:'+str(here/'unit.stderr'),'/usr/bin/unshare','--mount','--propagation','private','/usr/bin/python3',str(here/'dev_store_grow.py'),'--apply','--backup-receipt',str(here/'backup-receipt.json'),'--state',str(here/'operation')]
p=subprocess.run(cmd,capture_output=True,text=True)
save('systemd-submission.json',json.dumps({'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr},indent=2).encode()+b'\n')
if p.returncode:raise ValueError('Unit submission failed; inspect original receipt')
print(json.dumps({'submitted':True,'unit':v['unit'],'remote_directory':str(here),'boot_id':receipt['root']['boot_id']}))
'''

OBSERVE = r'''import hashlib,json,subprocess,sys
from pathlib import Path
v=json.loads(sys.argv[1]);here=Path(v['remote_directory'])
properties=['Id','LoadState','ActiveState','SubState','MainPID','ExecMainPID','ExecMainCode','ExecMainStatus','ExecMainStartTimestamp','ExecMainExitTimestamp','Result','Job','Restart','TimeoutStartUSec']
p=subprocess.run(['systemctl','show',v['unit'],'--no-pager',*[f'--property={x}' for x in properties]],capture_output=True,text=True,timeout=30)
state=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
files={}
for name in ['systemd-submission.json','operation/state.json','unit.stdout','unit.stderr','operation/operation.log']:
 path=here/name
 if path.exists():
  if path.is_symlink() or not path.is_file():raise ValueError('Unexpected observation path type')
  raw=path.read_bytes()
  if len(raw)>16*1024*1024:raise ValueError('Observation file exceeds bound')
  files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'text':raw.decode(errors='replace')}
print(json.dumps({'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'unit':v['unit'],'systemctl_exit_code':p.returncode,'systemctl_stderr':p.stderr,'properties':state,'files':files}))
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'Expected a real JSON file')
    raw = path.read_bytes()
    require(len(raw) <= LIMIT, 'JSON exceeds its size bound')
    value = json.loads(raw)
    require(isinstance(value, dict), 'Expected a JSON object')
    return value


def save_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def submission_source(payload):
    """Keep worker sources and the backup receipt off argv and sudo's audit log."""
    packed = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode('ascii')
    source = ('import base64,json,zlib\nPAYLOAD_B64=' + repr(packed) +
              '\nPAYLOAD=json.loads(zlib.decompress(base64.b64decode(PAYLOAD_B64)))\n' + SUBMIT)
    require(len(source.encode()) <= 1024 * 1024,
            'Submission exceeds the established SSH stdin helper bound')
    return source


def load_worker():
    spec = importlib.util.spec_from_file_location('development_store_growth', ROOT / 'tools/dev_store_grow.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def plan(remote, config, backup=None):
    with remote.device(config, 'usb') as client:
        live = json.loads(remote.run(client, **remote.python_command(INSPECT), display=False, timeout=120))
    require(set(live['partitions']) == {'boot', 'recovery', 'store'}, 'Expected exactly three card partitions')
    parent, store = live['parent'], live['partitions']['store']
    require(parent['sector_bytes'] == 512 and parent['bytes'] % 512 == 0, 'Unexpected card sector geometry')
    desired = parent['bytes'] - store['start_sector'] * 512
    require(desired >= store['bytes'] and desired // 512 <= 0xffffffff, 'Growth would shrink or exceed MBR addressing')
    result = {'schema': 1, 'operation': 'development-store-growth-plan', 'read_only': True,
              'executed': False, 'live': live, 'current_store_bytes': store['bytes'],
              'proposed_store_bytes': desired, 'proposed_store_sectors': desired // 512,
              'growth_required': desired > store['bytes'],
              'requires': ['matching fixed recovery p2 boot', 'fresh verified off-device backup',
                           'unmounted boot and store', 'exclusive operation ownership']}
    if backup is not None:
        worker = load_worker()
        worker.validate_backup(backup)
        result['backup_plan'] = worker.growth_plan(backup)
        require(parent == backup['parent'] and live['partitions'] == backup['partitions'],
                'Live card differs from backup geometry or filesystem identities')
        require(live['boot_id'] == backup['root']['boot_id'] and not live['directory_deployment'] and
                live['root_partition'] == 2 and live['kernel'] == backup['root']['kernel'] and
                live['image_sha256'] == backup['root']['image_sha256'], 'Backup is not from this fixed recovery boot')
        require(live['mbr_hex'] == backup['mbr_hex'], 'Live MBR differs from the backup')
        result['backup_identity_matches'] = True
    return result


def validate_submission(value):
    token = value.get('id', '')
    require(isinstance(token, str) and re.fullmatch('[0-9a-f]{32}', token), 'Invalid operation ID')
    require(value.get('unit') == 'gameshellneo-store-grow-' + token, 'Unexpected operation unit')
    require(value.get('remote_directory') == '/var/lib/gameshellneo/development-store-growth-' + token,
            'Unexpected recovery operation directory')
    boot_id = value.get('boot_id', '')
    require(isinstance(boot_id, str) and str(uuid.UUID(boot_id)) == boot_id, 'Invalid operation boot ID')
    return value


def observe(remote, config, directory):
    submission = validate_submission(read_json(directory / 'planned.json'))
    with remote.device(config, 'usb') as client:
        observation = json.loads(remote.run(client, **remote.python_command(OBSERVE, json.dumps(submission)),
                                            display=False, timeout=120))
    props = observation['properties']
    loaded = props.get('LoadState') == 'loaded'
    terminal = loaded and props.get('MainPID') == '0' and props.get('Job', '') in ('', '0') and (
        props.get('ActiveState') == 'failed' or
        (props.get('ActiveState'), props.get('SubState')) in (('active', 'exited'), ('inactive', 'dead')))
    worker_state = observation['files'].get('operation/state.json')
    state = json.loads(worker_state['text']) if worker_state else {}
    checks = {'matching_boot': observation['boot_id'] == submission['boot_id'],
              'matching_unit': observation['unit'] == submission['unit'] and
                               props.get('Id') == submission['unit'] + '.service', 'loaded': loaded,
              'executed': props.get('ExecMainPID', '0') not in ('', '0') and bool(props.get('ExecMainStartTimestamp')),
              'terminal': terminal,
              'successful_exit': props.get('ExecMainCode') == '1' and props.get('ExecMainStatus') == '0' and
                                 props.get('Result') == 'success',
              'worker_complete': state.get('operation') == 'development-store-growth' and
                                 state.get('completed') is True and state.get('write_started') is True and
                                 state.get('admission', {}).get('boot_id') == submission['boot_id']}
    observation['acceptance_checks'] = checks
    observation['accepted_success'] = all(checks.values())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    save_new(directory / ('observation-' + stamp + '.json'), observation)
    print(json.dumps({'directory': str(directory), 'unit': submission['unit'], 'properties': props,
                      'checks': checks, 'accepted_success': observation['accepted_success']}, indent=2))
    return 0 if observation['accepted_success'] else 2 if terminal else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware-checkout', type=Path, default=os.environ.get('NEO_HARDWARE_CHECKOUT'))
    parser.add_argument('--backup-receipt', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--status', type=Path, help='Read the original local operation directory; never resubmit')
    parser.add_argument('--output', type=Path, help='Fresh local operation directory under this checkout .local')
    args = parser.parse_args()
    require(args.hardware_checkout is not None, 'Set --hardware-checkout or NEO_HARDWARE_CHECKOUT')
    require(not (args.status and (args.apply or args.backup_receipt or args.output)),
            'Status is separate from planning/submission')
    require(not args.apply or args.backup_receipt, '--apply requires --backup-receipt')
    hardware = args.hardware_checkout.absolute()
    backup = read_json(args.backup_receipt.absolute()) if args.backup_receipt else None
    status = args.status.absolute() if args.status else None
    token = uuid.uuid4().hex
    directory = (args.output.absolute() if args.output else ROOT / '.local/multiboot/growth' / token)
    from dev_store_transport import load_hardware
    remote, config = load_hardware(hardware)
    if status:
        return observe(remote, config, status)
    if not args.apply:
        print(json.dumps(plan(remote, config, backup), indent=2))
        return 0
    worker = load_worker()
    worker.validate_backup(backup)
    # Full raw hashes and runtime admission are checked again inside the owned worker.
    admission = plan(remote, config, backup)
    require(admission['growth_required'], 'No growth is required')
    require(directory.resolve().is_relative_to(ROOT / '.local') and directory.resolve() == directory,
            'Use a fresh real operation directory inside this checkout .local')
    directory.mkdir(mode=0o700, parents=True)
    sources = {}
    for name in DEPENDENCIES:
        raw = (ROOT / 'tools' / name).read_bytes()
        sources[name] = {'sha256': hashlib.sha256(raw).hexdigest(),
                         'base64': base64.b64encode(raw).decode()}
    submission = {'schema': 1, 'id': token, 'unit': 'gameshellneo-store-grow-' + token,
                  'remote_directory': '/var/lib/gameshellneo/development-store-growth-' + token,
                  'boot_id': backup['root']['boot_id'],
                  'source_sha256': {name: item['sha256'] for name, item in sources.items()}}
    save_new(directory / 'planned.json', submission)
    save_new(directory / 'backup-receipt.json', backup)
    save_new(directory / 'read-only-plan.json', admission)
    print('Original growth operation:', directory, flush=True)
    payload = dict(submission, backup=backup, sources=sources)
    source = submission_source(payload)
    with (directory / 'submission-source.py').open('x') as output:
        output.write(source)
        output.flush()
        os.fsync(output.fileno())
    try:
        with remote.device(config, 'usb') as client, (directory / 'submission-output.json').open('xb') as output:
            remote.run(client, **remote.python_command(source),
                       output=output, display=False, timeout=120)
    except BaseException as error:
        save_new(directory / 'submission-uncertain.json',
                 {'error': type(error).__name__ + ': ' + str(error),
                  'instruction': 'Inspect this original operation with --status; never resubmit.'})
        raise
    print('One unit submitted. Use --status', directory, 'to observe its original result.', flush=True)
    return 0


if __name__ == '__main__':
    os.umask(0o077)
    sys.exit(main())
