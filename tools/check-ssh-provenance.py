#!/usr/bin/env python3
"""Read SSH implementation/version provenance while awake; no policy changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

POLICY_FIELDS = frozenset(('logingracetime','maxstartups','persourcemaxstartups',
    'persourcenetblocksize','persourcepenalties','persourcepenaltyexemptlist',
    'loglevel','usedns','versionaddendum','rekeylimit','channeltimeout',
    'unusedconnectiontimeout','tcpkeepalive','clientaliveinterval','clientalivecountmax'))


def command(arguments):
    result = subprocess.run(arguments,capture_output=True,timeout=15)
    if len(result.stdout)+len(result.stderr)>65536:
        raise ValueError('Version command output exceeds limit')
    return dict(returncode=result.returncode,stdout=result.stdout.decode(errors='replace').strip(),
                stderr=result.stderr.decode(errors='replace').strip())


def health():
    read=lambda p:Path(p).read_text().strip()
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id'),
                pm={k:read('/sys/power/suspend_stats/'+k) for k in ('success','fail')},
                brightness=read('/sys/class/backlight/ocp8178/brightness'),
                bl_power=read('/sys/class/backlight/ocp8178/bl_power'))


def access_rules():
    """Record whether wrapper rules exist without exporting their contents."""
    result = {}
    for name in ('/etc/hosts.allow', '/etc/hosts.deny'):
        path = Path(name)
        if not path.exists():
            result[name] = dict(present=False)
            continue
        data = path.read_bytes()
        if len(data) > 65536:
            raise ValueError('Access-control file exceeds inspection limit')
        lines = data.decode(errors='replace').splitlines()
        result[name] = dict(present=True, sha256=hashlib.sha256(data).hexdigest(),
                           bytes=len(data), active_lines=sum(
                               bool(line.strip()) and not line.lstrip().startswith('#')
                               for line in lines))
    return result


def inspect(role):
    if (role=='mac') != (sys.platform=='darwin'):
        raise ValueError('Unexpected provenance host platform')
    value=dict(schema=1,role=role,binaries={})
    if role=='device':value['before']=health()
    for name in ('/usr/bin/ssh','/usr/sbin/sshd','/usr/libexec/sshd-session',
                 '/usr/lib/openssh/sshd-session','/usr/libexec/sshd-auth',
                 '/usr/lib/openssh/sshd-auth','/usr/libexec/sshd-keygen-wrapper'):
        path=Path(name)
        if path.is_file():
            digest=hashlib.sha256()
            with path.open('rb') as source:
                for part in iter(lambda:source.read(65536),b''):digest.update(part)
            value['binaries'][name]=dict(sha256=digest.hexdigest(),bytes=path.stat().st_size)
    value['client_version']=command(['/usr/bin/ssh','-V'])
    value['server_version']=command(['/usr/sbin/sshd','-V'])
    # -G exits after parsing/dumping config, before private host-key loading.
    # This permits the same read-only inspection as the ordinary Mac account.
    raw=command(['/usr/sbin/sshd','-G'])
    value['global_policy']=dict(mode='dump-config-G',returncode=raw['returncode'],stderr=raw['stderr'],
        selected={key:val for line in raw['stdout'].splitlines() if ' ' in line
                  for key,val in [line.split(' ',1)] if key in POLICY_FIELDS},
        scope='On-disk global config dump; no per-connection Match evaluation or proof of historical settings.')
    if role=='mac':
        value['os_version']=command(['/usr/bin/sw_vers'])
        value['server_signature']=command(['/usr/bin/codesign','-d','--verbose=4','/usr/sbin/sshd'])
    else:
        value['packages']=command(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\n',
                                   'openssh-server','openssh-client'])
        value['worker_libraries']=command(['/usr/bin/ldd','/usr/lib/openssh/sshd-session'])
        value['access_rules']=access_rules()
        value['after']=health()
        if value['before']!=value['after']:
            raise ValueError('Boot, PM or display changed during provenance inspection')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--on-host',choices=('mac','device'))
    args=parser.parse_args()
    if args.on_host:
        print(json.dumps(inspect(args.on_host),indent=2))
        return
    import importlib.metadata
    import paramiko
    from private_config import load_env
    from remote import connect_mac,device,evidence_directory,python_command,run
    os.umask(0o077)
    path=evidence_directory()
    source=Path(__file__).read_bytes()
    (path/'check-ssh-provenance.py').write_bytes(source)
    result=dict(schema=1,source_sha256=hashlib.sha256(source).hexdigest(),host={})
    print('Private SSH provenance:',path,flush=True)
    for name in ('paramiko','cryptography'):
        result['host'][name]=importlib.metadata.version(name)
    for name in ('client','transport','channel','packet'):
        module=__import__('paramiko.'+name,fromlist=[name])
        data=Path(module.__file__).read_bytes()
        (path/('paramiko-'+name+'.py')).write_bytes(data)
        result['host'][name+'_sha256']=hashlib.sha256(data).hexdigest()
    config=load_env()
    with connect_mac(config) as mac:
        value=json.loads(run(mac,'/usr/bin/python3 -B - --on-host mac',input_data=source,
                             display=False,timeout=90))
        value['authenticated_server_banner']=mac.get_transport().remote_version
        result['mac']=value
    with device(config,'usb') as board:
        value=json.loads(run(board,**python_command(source.decode(),'--on-host','device'),
                             display=False,timeout=90))
        value['authenticated_server_banner']=board.get_transport().remote_version
        result['device']=value
    (path/'ssh-provenance.json').write_text(json.dumps(result,indent=2)+'\n')
    for role in ('mac','device'):
        print(role+':',result[role]['authenticated_server_banner'])
    print('Same device boot, PM counters and display state; no policy writes.')


if __name__=='__main__':main()
