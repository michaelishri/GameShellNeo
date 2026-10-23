"""Real completed-stage CLI/shell routes stop before a nonexecuting build boundary."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ('build-image.sh', 'kernel-artifacts.py', 'kernel-inputs.py', 'build_preflight.py',
         'image_provisioning.py', 'rootfs-cache.py', 'verify-rootfs.py', 'usb_poll_boot.py',
         'keypad_supply.py', 'cpi_idle.py')
FAMILIES = {
    'certificates': ('valid', 'cert-directory-missing', 'cert-directory-empty', 'cert-malformed', 'cert-stale-signer'),
    'existing': ('ledger-missing', 'zimage-changed', 'module-changed', 'patch-changed', 'fragment-changed'),
    'context': ('builder-changed', 'linux-identity-changed', 'compiler-record-missing',
                'builder-packages-missing', 'compiler-record-changed', 'builder-packages-changed'),
    'exact-set': ('certificate-added', 'certificate-removed-nonempty', 'legacy-ledger'),
    'rootfs': ('rootfs-only',),
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2); out.write('\n')


def hex_bytes(data):
    return (', '.join(f'0x{value:02x}' for value in data) + '\n').encode()


class KernelArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='neo-kernel-artifacts-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.shared = Path(cls.temporary.name)
        (cls.shared/'regulatory.db').write_bytes(b'NEO-233 representative signed database\n')
        for signer in ('a', 'b'):
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                '-days', '1', '-subj', '/CN=NEO-233 fixture ' + signer,
                '-keyout', str(cls.shared/(signer+'.key')), '-out', str(cls.shared/(signer+'.pem'))],
                capture_output=True, check=True)
            subprocess.run(['openssl', 'x509', '-in', str(cls.shared/(signer+'.pem')), '-outform', 'DER',
                            '-out', str(cls.shared/(signer+'.der'))], capture_output=True, check=True)
        subprocess.run(['openssl', 'cms', '-sign', '-binary', '-in', str(cls.shared/'regulatory.db'),
            '-signer', str(cls.shared/'a.pem'), '-inkey', str(cls.shared/'a.key'), '-outform', 'DER',
            '-out', str(cls.shared/'regulatory.db.p7s')], capture_output=True, check=True)

    def command(self, case, name, command, *, project, environment=None):
        child = subprocess.Popen(command, cwd=project, env=environment or dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = child.communicate()
        (case/(name+'.stdout')).write_bytes(stdout); (case/(name+'.stderr')).write_bytes(stderr)
        result = dict(command=command, pid=child.pid, exit_code=child.returncode,
                      stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                      original_job_terminal=True)
        save(case/(name+'.terminal.json'), result)
        return result

    def fixture(self, case):
        project = case/'project'; (project/'tools').mkdir(parents=True)
        for name in TOOLS:
            shutil.copyfile(ROOT/'tools'/name, project/'tools'/name)
        for name in ('patches', 'overlay', 'candidates/clock-provenance'):
            shutil.copytree(ROOT/'kernel'/name, project/'kernel'/name)
        shutil.copyfile(ROOT/'kernel/gameshellneo.config', project/'kernel/gameshellneo.config')
        lock = json.loads((ROOT/'build/sources.lock.json').read_text())
        lock['bootloader'] = dict(filename='fixture-bootloader.bin', size_bytes=18,
                                 sha256=hashlib.sha256(b'fixture bootloader').hexdigest())
        lock['radio'] = dict(nvram=dict(filename='fixture-nvram.txt', sha256=hashlib.sha256(b'fixture radio').hexdigest()))
        (project/'build').mkdir(); (project/'build/sources.lock.json').write_text(json.dumps(lock))
        release = lock['linux']['tag'][1:] + lock['linux']['localversion']
        kernel = project/'.local/build/kernel'
        for name in ('.config', 'System.map', 'vmlinux', 'arch/arm/boot/zImage',
                     'arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb'):
            path = kernel/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('NEO-233 representative '+name+'\n').encode())
        path = kernel/'include/config/kernel.release'; path.parent.mkdir(parents=True); path.write_text(release+'\n')
        module = project/'.local/kernel-install/lib/modules'/release/'fixture.ko'
        module.parent.mkdir(parents=True); module.write_bytes(b'fixture module\n')
        for name in ('compiler.txt', 'builder-packages.txt'):
            (project/'.local/build'/name).write_text('NEO-233 representative '+name+'\n')
        certs = project/'.local/sources'/('linux-'+lock['linux']['tag'][1:])/'net/wireless/certs'
        certs.mkdir(parents=True); (certs/'a.hex').write_bytes(hex_bytes((self.shared/'a.der').read_bytes()))
        provision = project/'.local/provisioning/device'; provision.mkdir(parents=True)
        for name in ('identity.json', 'authorized_keys', 'ssh_host_ed25519_key', 'ssh_host_ed25519_key.pub',
                     'machine-id', 'wpa_supplicant-wlan0.conf'):
            (provision/name).write_text('NEO-233 explicit private test fixture only\n')
        (project/'fixture-bootloader.bin').write_bytes(b'fixture bootloader')
        (project/'fixture-radio').mkdir(); (project/'fixture-radio/fixture-nvram.txt').write_bytes(b'fixture radio')
        return project, certs, module

    def run_case(self, name):
        parent = Path(os.environ['NEO_KERNEL_ARTIFACTS_RESULTS']) if os.environ.get('NEO_KERNEL_ARTIFACTS_RESULTS') else self.shared/'cases'
        case = parent/name; case.mkdir(parents=True, exist_ok=False)
        project, certs, module = self.fixture(case)
        if name == 'certificate-removed-nonempty':
            (certs/'b.hex').write_bytes(hex_bytes((self.shared/'b.der').read_bytes()))
        recorded = self.command(case, 'record', [sys.executable, '-B', str(project/'tools/kernel-artifacts.py'), 'record'], project=project)
        self.assertEqual(recorded['exit_code'], 0, (case/'record.stderr').read_text())
        ledger = project/'.local/build/kernel-completed.json'
        initial = ledger.read_bytes(); manifest = json.loads(initial)
        self.assertEqual(manifest['schema'], 2)
        lock_path = project/'build/sources.lock.json'
        self.assertEqual(manifest['linux'], json.loads(lock_path.read_text())['linux'])
        self.assertEqual(manifest['builder'], json.loads(lock_path.read_text())['builder'])
        if name == 'cert-directory-missing': shutil.rmtree(certs)
        elif name == 'cert-directory-empty': (certs/'a.hex').unlink()
        elif name == 'cert-malformed': (certs/'a.hex').write_bytes(b'0x00, 0x01\n')
        elif name == 'cert-stale-signer': (certs/'a.hex').write_bytes(hex_bytes((self.shared/'b.der').read_bytes()))
        elif name == 'certificate-added': (certs/'b.hex').write_bytes(hex_bytes((self.shared/'b.der').read_bytes()))
        elif name == 'certificate-removed-nonempty': (certs/'b.hex').unlink()
        elif name == 'ledger-missing': ledger.unlink()
        elif name == 'zimage-changed': (project/'.local/build/kernel/arch/arm/boot/zImage').write_bytes(b'changed kernel')
        elif name == 'module-changed': module.write_bytes(b'changed module')
        elif name == 'patch-changed': next((project/'kernel/patches').glob('*.patch')).write_bytes(b'changed patch')
        elif name == 'fragment-changed': (project/'kernel/gameshellneo.config').write_bytes(b'changed fragment')
        elif name in ('builder-changed', 'linux-identity-changed'):
            lock = json.loads(lock_path.read_text())
            if name == 'builder-changed': lock['builder']['image'] = 'ghcr.io/armbian/docker-armbian-build@sha256:'+'1'*64
            else: lock['linux'].update(commit='1'*40, tarball_sha256='2'*64)
            lock_path.write_text(json.dumps(lock))
        elif name in ('compiler-record-missing', 'builder-packages-missing'):
            (project/'.local/build'/('compiler.txt' if name == 'compiler-record-missing' else 'builder-packages.txt')).unlink()
        elif name in ('compiler-record-changed', 'builder-packages-changed'):
            (project/'.local/build'/('compiler.txt' if name == 'compiler-record-changed' else 'builder-packages.txt')).write_bytes(b'changed record')
        elif name == 'legacy-ledger':
            legacy = {key: manifest[key] for key in ('kernel_release', 'patches', 'fragment_sha256', 'files')}
            legacy['files'] = {p:h for p,h in legacy['files'].items() if p.startswith(('.local/build/kernel/', '.local/kernel-install/'))}
            ledger.write_text(json.dumps(legacy))
        elif name == 'rootfs-only':
            ledger.unlink(); shutil.rmtree(project/'.local/build/kernel'); shutil.rmtree(project/'.local/kernel-install'); shutil.rmtree(certs)
        def snapshot():
            return {str(p.relative_to(project)):(digest(p),p.stat().st_mtime_ns) for p in project.rglob('*') if p.is_file()}
        before = snapshot()
        record_refusal = None
        if name == 'cert-malformed':
            record_refusal = self.command(case, 'record-malformed', [sys.executable, '-B', str(project/'tools/kernel-artifacts.py'), 'record'], project=project)
        check = None if name == 'rootfs-only' else self.command(case, 'check',
            [sys.executable, '-B', str(project/'tools/kernel-artifacts.py'), 'check'], project=project)
        binary = case/'bin'; binary.mkdir()
        (binary/'python3').write_text('#!'+sys.executable+'''
import importlib.util,json,os,pathlib,sys
with open(os.environ['NEO_KERNEL_COMMANDS'],'a') as out:out.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:2]==['tools/build_preflight.py']:
    spec=importlib.util.spec_from_file_location('actual_preflight',pathlib.Path(sys.argv[1]))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.filesystem=lambda path:(1,20*m.GIB,str(pathlib.Path.cwd()))
    sys.argv=sys.argv[1:];m.main()
else:os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
'''); (binary/'python3').chmod(0o700)
        sentinel = case/'expensive-stage.json'
        (binary/'docker').write_text('#!'+sys.executable+'''
import json,os,sys
with open(os.environ['NEO_KERNEL_SENTINEL'],'x') as out:json.dump({'argv':sys.argv[1:],'expensive_stage_entry_only':True,'real_docker_executed':False},out)
raise SystemExit(97)
'''); (binary/'docker').chmod(0o700)
        environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1',
            NEO_IMAGE_PROVISIONING_DIRECTORY=str(project/'.local/provisioning/device'), NEO_BOOTLOADER=str(project/'fixture-bootloader.bin'),
            NEO_RADIO_DIR=str(project/'fixture-radio'), NEO_KERNEL_COMMANDS=str(case/'python-commands.jsonl'), NEO_KERNEL_SENTINEL=str(sentinel))
        arguments = ['bash', str(project/'tools/build-image.sh')] + (['rootfs'] if name == 'rootfs-only' else [])
        shell = self.command(case, 'build-entrypoint', arguments, project=project, environment=environment)
        after = snapshot()
        sources = {n:dict(staged_sha256=digest(project/'tools'/n), maintained_sha256=digest(ROOT/'tools'/n)) for n in TOOLS}
        observed = dict(schema=1, case=name, family=next(f for f,names in FAMILIES.items() if name in names),
            record=recorded, check=check, malformed_record_refusal=record_refusal, build_entrypoint=shell,
            expensive_stage_reached=sentinel.exists(), completed_image_build=False, real_docker_executed=False,
            source_inputs=sources, project_data_and_mtime_unchanged=before==after,
            unchanged_ledger=not ledger.exists() or ledger.read_bytes()==(json.dumps(legacy).encode() if name=='legacy-ledger' else initial),
            explicit_disk_headroom_API_seam=True, representative_kernel_and_private_inputs=True,
            no_original_cache_source_or_device_mutation=True)
        save(case/'observed.json', observed)
        self.assertEqual(before, after)
        self.assertTrue(observed['unchanged_ledger'])
        self.assertTrue(all(v['staged_sha256']==v['maintained_sha256'] for v in sources.values()))
        allowed = name in ('valid', 'rootfs-only')
        self.assertEqual(shell['exit_code'], 97 if allowed else 1, (case/'build-entrypoint.stderr').read_text())
        self.assertEqual(sentinel.exists(), allowed)
        if check is not None:
            self.assertEqual(check['exit_code'], 0 if name=='valid' else 1, (case/'check.stderr').read_text())
        if record_refusal is not None:
            self.assertEqual(record_refusal['exit_code'], 1)
        if name == 'valid':
            root = case/'representative-rootfs'; firmware = root/'usr/lib/firmware'; firmware.mkdir(parents=True)
            alternatives = root/'etc/alternatives'; alternatives.mkdir(parents=True)
            for suffix in ('', '.p7s'):
                filename = 'regulatory.db'+suffix
                shutil.copyfile(self.shared/filename, firmware/(filename+'-upstream'))
                (firmware/filename).symlink_to('/etc/alternatives/'+filename)
                (alternatives/filename).symlink_to('/lib/firmware/'+filename+'-upstream')
            probe = case/'actual-regulatory.py'
            probe.write_text('''import importlib.util,json,pathlib,sys
p=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(p/'tools'))
s=importlib.util.spec_from_file_location('actual_verifier',p/'tools/verify-rootfs.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.verify_regulatory(pathlib.Path(sys.argv[2]),p,json.loads((p/'build/sources.lock.json').read_text()))
''')
            verified = self.command(case, 'actual-regulatory', [sys.executable, '-B', str(probe), str(project), str(root)], project=project)
            self.assertEqual(verified['exit_code'], 0, (case/'actual-regulatory.stderr').read_text())

    def test_certificate_prerequisites(self):
        for name in FAMILIES['certificates']:
            with self.subTest(case=name): self.run_case(name)

    def test_existing_artifact_guards(self):
        for name in FAMILIES['existing']:
            with self.subTest(case=name): self.run_case(name)

    def test_source_builder_and_finalizer_metadata(self):
        for name in FAMILIES['context']:
            with self.subTest(case=name): self.run_case(name)

    def test_exact_certificate_sets_and_legacy_readonly_refusal(self):
        for name in FAMILIES['exact-set']:
            with self.subTest(case=name): self.run_case(name)

    def test_rootfs_only_does_not_require_a_completed_kernel(self):
        self.run_case('rootfs-only')


if __name__ == '__main__':
    unittest.main()
