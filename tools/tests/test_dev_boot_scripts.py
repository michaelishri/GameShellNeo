"""Generated boot flow under modeled commands, not vendor U-Boot qualification."""
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_boot_scripts as scripts


def legacy(payload, kind, *, arch=2, compression=0):
    header = struct.pack('>7I4B32s', 0x27051956, 0, 0, len(payload), 0, 0,
                         zlib.crc32(payload), 5, arch, kind, compression, b'test fixture')
    return header[:4] + struct.pack('>I', zlib.crc32(header)) + header[8:] + payload


def descriptor(text):
    return legacy(struct.pack('>2I', len(text), 0) + text, 6)


def valid_image(data):
    if len(data) < 64:
        return False
    fields = struct.unpack('>7I4B32s', data[:64])
    header = data[:4] + b'\0' * 4 + data[8:64]
    payload = data[64:64 + fields[3]]
    return (fields[0] == 0x27051956 and fields[1] == zlib.crc32(header) and
            len(payload) == fields[3] and fields[6] == zlib.crc32(payload))


# Bash supplies real if/&&/quoting/while behavior. These functions model the
# command primitives and byte-addressed RAM, including deliberately failed
# operations. iminfo's results are independently computed from fixture CRCs.
# This does not model the vendor parser, FAT durability, SD or kernel execution.
MODEL = r'''
declare -A fs ram valid calls sizes returning
number() { local text=${1#0x}; reply=$((16#${text:-0})); }
memory() {
  local address=$1 count=$2 base offset hex
  for base in "${!ram[@]}"; do
    hex=${ram[$base]}
    if ((address >= base && address + count <= base + ${#hex} / 2)); then
      offset=$(((address - base) * 2))
      bytes=${hex:$offset:$((count * 2))}
      return 0
    fi
  done
  return 1
}
value() {
  local raw=$1 width=$2 address count i
  if [[ $raw == \** ]]; then
    number "${raw:1}"; address=$reply
    memory "$address" "$width" || return 1
    reply=0
    for ((i=width-1; i>=0; i--)); do
      count=${bytes:$((i*2)):2}
      reply=$((reply * 256 + 16#$count))
    done
  else
    number "$raw"
  fi
}
setenv() { local variable=$1; shift; printf -v "$variable" '%s' "$*"; }
setexpr.b() { value "$2" 1 || return 1; printf -v "$1" '%x' "$reply"; }
setexpr() {
  local variable=$1 left right
  value "$2" 4 || return 1; left=$reply
  value "$4" 4 || return 1; right=$reply
  case $3 in
    +) reply=$((left + right));;
    -) reply=$((left - right));;
    '*') reply=$((left * right));;
    *) return 1;;
  esac
  printf -v "$variable" '%x' "$reply"
}
compare() {
  local width=$1 left right operator=$3
  value "$2" "$width" || return 1; left=$reply
  value "$4" "$width" || return 1; right=$reply
  case $operator in
    -eq) ((left == right));; -ge) ((left >= right));;
    -le) ((left <= right));; *) return 1;;
  esac
}
itest.l() { compare 4 "$@"; }
itest.b() { compare 1 "$@"; }
run() {
  local variable status
  for variable in "$@"; do
    eval "${!variable}"; status=$?
    if ((status)); then return "$status"; fi
  done
}
fatsize() {
  local name=$3 length
  printf 'SIZE:%s\n' "$name"
  [[ $fault != "fatsize:$name" && ${fs[$name]+set} ]] || return 1
  length=$((${#fs[$name]} / 2))
  [[ ! ${sizes[$name]+set} ]] || length=${sizes[$name]}
  printf -v filesize '%x' "$length"
}
fatload() {
  local name=$4 address count hex key
  key="load:$name"; calls[$key]=$((${calls[$key]:-0} + 1))
  printf 'LOAD:%s:%s\n' "$name" "${calls[$key]}"
  [[ $fault != "fatload:$name:${calls[$key]}" && ${fs[$name]+set} ]] || return 1
  number "$3"; address=$reply
  printf 'PLACE:%s:%s\n' "$name" "$3"
  number "$5"; count=$reply
  hex=${fs[$name]:0:$((count * 2))}
  if [[ $fault == "shortload:$name:${calls[$key]}" ]]; then hex=${hex:0:-2}; fi
  if [[ $fault == "corruptload:$name:${calls[$key]}" ]]; then hex=${hex:0:-2}ff; fi
  ram[$address]=$hex
  printf -v filesize '%x' "$((${#hex} / 2))"
}
iminfo() {
  local address
  number "$1"; address=$reply
  printf 'CRC:%s\n' "$1"
  [[ $fault != "iminfo:$1" && ${valid[${ram[$address]}]+set} ]]
}
cmp.b() {
  local left right count first
  number "$1"; left=$reply
  number "$2"; right=$reply
  number "$3"; count=$reply
  printf 'CMP:%s:%s\n' "$1" "$2"
  [[ $fault != "cmp:$1:$2" ]] || return 1
  memory "$left" "$count" || return 1; first=$bytes
  memory "$right" "$count" || return 1
  [[ $first == "$bytes" ]]
}
fatwrite() {
  local address count name=$4
  printf 'WRITE:%s\n' "$name"
  [[ $fault != "fatwrite:$name" ]] || return 1
  number "$3"; address=$reply
  number "$5"; count=$reply
  memory "$address" "$count" || return 1
  fs[$name]=$bytes
  [[ $fault != "wrongwrite:$name" ]] || fs[$name]=$trial
  printf 'WROTE:%s:%s\n' "$name" "${fs[$name]}"
}
source() {
  local address kind=trial
  number "$1"; address=$reply
  [[ ${ram[$address]} != "$good" ]] || kind=good
  [[ ${ram[$address]} != "$recovery" ]] || kind=recovery
  printf 'SOURCE:%s:verify=%s\n' "$kind" "$verify"
  [[ ${returning[$kind]+set} ]] || exit 0
  return 0
}
bootm() {
  printf 'BOOT:%s\nARGS:%s\n' "$*" "$bootargs"
  [[ $fault == bootm ]] || exit 0
  return 1
}
sleep() { echo HALT; exit 0; }
'''


def modeled(source, files, *, fault='', size_overrides=None, returns=()):
    setup = [MODEL, 'fault=' + shlex.quote(fault), 'setenv verify no']
    for name, data in files.items():
        setup.append(f'fs[{shlex.quote(name)}]={shlex.quote(data.hex())}')
        if valid_image(data):
            setup.append(f'valid[{shlex.quote(data.hex())}]=1')
    for name, size in (size_overrides or {}).items():
        setup.append(f'sizes[{shlex.quote(name)}]={size}')
    for kind in returns:
        setup.append(f'returning[{kind}]=1')
    setup.extend(('good=' + shlex.quote(files.get('good.scr', b'').hex()),
                  'trial=' + shlex.quote(files.get('next.scr', b'').hex()),
                  'recovery=' + shlex.quote(files.get('recover.scr', b'').hex())))
    setup.append(source.decode())
    setup.append('echo OUTER_SCAN')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'model.sh'
        path.write_text('\n'.join(setup) + '\n')
        result = subprocess.run(['bash', str(path)], capture_output=True, text=True,
                                timeout=10, cwd=directory)
    if result.returncode or result.stderr:
        raise AssertionError(f'Model failed: {result.returncode}\n{result.stderr}\n{result.stdout}')
    return result.stdout.splitlines()


class ScriptImageTests(unittest.TestCase):
    def test_deterministic_header_and_both_checksums(self):
        source = b'echo development\n'
        image = scripts.script_image(source)
        self.assertEqual(image, scripts.script_image(source))
        fields = struct.unpack('>7I4B32s', image[:64])
        self.assertEqual(fields[:7:2], (0x27051956, 0, 0, zlib.crc32(image[64:])))
        self.assertEqual(fields[3], len(source) + 8)
        self.assertEqual(fields[7:11], (5, 2, 6, 0))
        self.assertTrue(valid_image(image))
        self.assertEqual(image[64:72], struct.pack('>2I', len(source), 0))
        self.assertEqual(image[72:], source)

    def test_image_bounds_and_hidden_terminators_reject(self):
        maximum = b'#' * (scripts.SCRIPT_LIMIT - 72)
        self.assertEqual(len(scripts.script_image(maximum)), scripts.SCRIPT_LIMIT)
        for bad in ('echo text', bytearray(b'echo text'), b'', b'echo\0hidden', maximum + b'#'):
            with self.subTest(value=type(bad).__name__), self.assertRaises(ValueError):
                scripts.script_image(bad)


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.good = descriptor(b'echo good\n')
        self.trial = descriptor(b'echo trial with a different length\n')
        self.files = {'next.scr': self.trial, 'good.scr': self.good,
                      'recover.scr': descriptor(b'echo recovery\n')}

    def model(self, **kwargs):
        return modeled(scripts.dispatcher(), self.files, **kwargs)

    def assert_recovery(self, lines):
        self.assertIn('SOURCE:recovery:verify=yes', lines)
        self.assertNotIn('SOURCE:trial:verify=yes', lines)
        self.assertNotIn('OUTER_SCAN', lines)

    def test_normal_identical_descriptor_has_no_writes(self):
        self.files['next.scr'] = self.good
        lines = self.model()
        self.assertIn('SOURCE:good:verify=yes', lines)
        self.assertFalse(any(line.startswith('WRITE:') for line in lines))
        self.assertNotIn('OUTER_SCAN', lines)

    def test_trial_consumes_and_compares_before_preserved_handoff(self):
        lines = self.model()
        self.assertEqual([line for line in lines if line.startswith('WRITE:')], ['WRITE:next.scr'])
        self.assertLess(lines.index('WRITE:next.scr'), lines.index('LOAD:next.scr:2'))
        self.assertLess(lines.index('CMP:0x43300000:0x43200000'),
                        lines.index('SOURCE:trial:verify=yes'))
        self.assertNotIn('SOURCE:recovery:verify=yes', lines)
        self.assertNotIn('OUTER_SCAN', lines)
        written = next(line.split(':', 2)[2] for line in lines if line.startswith('WROTE:next.scr:'))
        self.assertEqual(bytes.fromhex(written), self.good)
        self.files['next.scr'] = bytes.fromhex(written)
        successor = self.model()
        self.assertIn('SOURCE:good:verify=yes', successor)
        self.assertFalse(any(line.startswith('WRITE:') for line in successor))

    def test_same_length_trial_is_distinct_and_crc_valid_wrong_readback_rejects(self):
        self.files['next.scr'] = descriptor(b'echo new!\n')
        self.assertEqual(len(self.files['next.scr']), len(self.good))
        lines = self.model()
        self.assertIn('CMP:0x43000000:0x43300000', lines)
        self.assertIn('SOURCE:trial:verify=yes', lines)
        lines = self.model(fault='wrongwrite:next.scr')
        self.assertIn('CMP:0x43300000:0x43200000', lines)
        self.assert_recovery(lines)

    def test_load_crc_write_and_readback_faults_never_enter_trial(self):
        faults = ('fatsize:next.scr', 'fatsize:good.scr',
                  'fatload:next.scr:1', 'fatload:good.scr:1',
                  'shortload:next.scr:1', 'shortload:good.scr:1',
                  'iminfo:0x43000000', 'iminfo:0x43300000',
                  'fatwrite:next.scr', 'fatload:next.scr:2',
                  'shortload:next.scr:2', 'corruptload:next.scr:2',
                  'iminfo:0x43200000', 'cmp:0x43300000:0x43200000')
        for fault in faults:
            with self.subTest(fault=fault):
                lines = self.model(fault=fault)
                self.assert_recovery(lines)

    def test_missing_bad_crc_and_oversized_descriptors_never_write(self):
        for name in ('next.scr', 'good.scr'):
            original = self.files[name]
            for bad in (None, original[:-1], original[:-1] + b'X'):
                with self.subTest(name=name, bad=bad):
                    if bad is None:
                        del self.files[name]
                    else:
                        self.files[name] = bad
                    lines = self.model()
                    self.assert_recovery(lines)
                    self.assertFalse(any(line.startswith('WRITE:') for line in lines))
            self.files[name] = original
            lines = self.model(size_overrides={name: scripts.SCRIPT_LIMIT + 1})
            self.assert_recovery(lines)
            self.assertFalse(any(line.startswith('LOAD:' + name) for line in lines))

    def test_crc_valid_wrong_type_arch_compression_and_component_table_reject(self):
        payload = struct.pack('>2I', 8, 0) + b'echo hi\n'
        invalid = (legacy(payload, 2), legacy(payload, 6, arch=22),
                   legacy(payload, 6, compression=1),
                   legacy(struct.pack('>2I', 0, 0), 6),
                   legacy(struct.pack('>2I', 7, 0) + b'echo hi\n', 6),
                   legacy(struct.pack('>2I', 8, 1) + b'echo hi\n', 6),
                   descriptor(b'echo hi\n') + b'trailing')
        for image in invalid:
            with self.subTest(image=image.hex()[:40]):
                self.files['next.scr'] = image
                lines = self.model()
                self.assert_recovery(lines)
                self.assertFalse(any(line.startswith('WRITE:') for line in lines))

    def test_unbounded_header_claim_never_reaches_crc_reader(self):
        image = bytearray(self.trial)
        struct.pack_into('>I', image, 12, 0xffffff00)
        image[4:8] = b'\0' * 4
        struct.pack_into('>I', image, 4, zlib.crc32(image[:64]))
        self.files['next.scr'] = bytes(image)
        lines = self.model()
        self.assert_recovery(lines)
        self.assertNotIn('CRC:0x43000000', lines)

    def test_other_image_magic_never_reaches_image_format_dispatch(self):
        image = bytearray(self.trial)
        struct.pack_into('>I', image, 0, 0xd00dfeed)
        image[4:8] = b'\0' * 4
        struct.pack_into('>I', image, 4, zlib.crc32(image[:64]))
        self.files['next.scr'] = bytes(image)
        lines = self.model()
        self.assert_recovery(lines)
        self.assertNotIn('CRC:0x43000000', lines)

    def test_returning_trial_enters_recovery_even_after_status_zero(self):
        lines = self.model(returns=('trial',))
        self.assertIn('SOURCE:trial:verify=yes', lines)
        self.assertIn('SOURCE:recovery:verify=yes', lines)
        self.assertNotIn('OUTER_SCAN', lines)

    def test_load_buffers_preserve_dispatcher_and_returning_descriptor(self):
        lines = self.model(returns=('trial',))
        for event in ('PLACE:next.scr:0x43000000', 'PLACE:good.scr:0x43300000',
                      'PLACE:next.scr:0x43200000', 'PLACE:recover.scr:0x43400000'):
            self.assertIn(event, lines)
        self.assertFalse(any(line.startswith('PLACE:') and line.endswith(':0x43100000')
                             for line in lines))
        self.assertNotIn('PLACE:recover.scr:0x43000000', lines)

    def test_returning_good_enters_recovery_without_writing(self):
        self.files['next.scr'] = self.good
        lines = self.model(returns=('good',))
        self.assertIn('SOURCE:recovery:verify=yes', lines)
        self.assertFalse(any(line.startswith('WRITE:') for line in lines))

    def test_failed_or_returning_recovery_halts_instead_of_outer_scan(self):
        del self.files['next.scr']
        for kwargs in ({'returns': ('recovery',)}, {'fault': 'fatload:recover.scr:1'}):
            with self.subTest(kwargs=kwargs):
                lines = self.model(**kwargs)
                self.assertIn('HALT', lines)
                self.assertNotIn('OUTER_SCAN', lines)

    def test_compiled_dispatcher_fits_its_own_bounded_load(self):
        self.assertLessEqual(len(scripts.script_image(scripts.dispatcher())), scripts.SCRIPT_LIMIT)


class ReleaseScriptTests(unittest.TestCase):
    def setUp(self):
        self.prefix = 'systems/dev-26/'
        self.files = {self.prefix + 'uImage': legacy(b'kernel fixture', 2),
                      self.prefix + 'sun8i-r16-clockworkpi-cpi3.dtb': b'raw DTB fixture',
                      self.prefix + 'uInitrd': legacy(b'ramdisk fixture', 3)}

    def source(self, directory=True, **kwargs):
        return scripts.release_script('dev-26', '1234abcd-03' if directory else '1234abcd-02',
                                      directory=directory, **kwargs)

    def test_directory_kernel_dtb_initrd_handoff_and_matched_identity(self):
        lines = modeled(self.source(), self.files)
        self.assertIn('BOOT:0x48000000 0x4a000000 0x49000000', lines)
        args = next(line for line in lines if line.startswith('ARGS:'))
        for option in ('root=PARTUUID=1234abcd-03', 'neo.dev=1', 'neo.slot=dev-26',
                       'neo.store=PARTUUID=1234abcd-03', 'panic=10', 'rootwait'):
            self.assertIn(option, args.split())
        self.assertNotIn('mem_sleep_default=s2idle', args)

    def test_recovery_uses_direct_root_and_never_loads_initrd(self):
        lines = modeled(self.source(directory=False), self.files)
        self.assertIn('BOOT:0x48000000 - 0x49000000', lines)
        self.assertFalse(any('uInitrd' in line for line in lines))
        args = next(line for line in lines if line.startswith('ARGS:'))
        self.assertIn('root=PARTUUID=1234abcd-02', args)
        self.assertNotIn('neo.dev=', args)
        self.assertNotIn('neo.store=', args)

    def test_suspend_diagnostic_is_explicit(self):
        self.assertIn(b' mem_sleep_default=s2idle', self.source(suspend_diagnostics=True))
        self.assertNotIn(b'mem_sleep_default=', self.source())

    def test_missing_short_crc_and_oversized_assets_do_not_boot(self):
        for name, limit in ((self.prefix + 'uImage', scripts.KERNEL_LIMIT),
                            (self.prefix + 'sun8i-r16-clockworkpi-cpi3.dtb', scripts.DTB_LIMIT),
                            (self.prefix + 'uInitrd', scripts.INITRD_LIMIT)):
            for fault in ('fatsize:' + name, 'fatload:' + name + ':1',
                          'shortload:' + name + ':1'):
                with self.subTest(name=name, fault=fault):
                    lines = modeled(self.source(), self.files, fault=fault)
                    self.assertFalse(any(line.startswith('BOOT:') for line in lines))
            lines = modeled(self.source(), self.files, size_overrides={name: limit + 1})
            self.assertFalse(any(line.startswith('LOAD:' + name) for line in lines))
            self.assertFalse(any(line.startswith('BOOT:') for line in lines))
        for address in ('0x48000000', '0x4a000000'):
            lines = modeled(self.source(), self.files, fault='iminfo:' + address)
            self.assertFalse(any(line.startswith('BOOT:') for line in lines))

    def test_boot_return_is_a_failure_for_the_dispatcher(self):
        lines = modeled(self.source(), self.files, fault='bootm')
        self.assertIn('GameShellNeo development release returned', lines)

    def test_slot_partuuid_injection_mode_and_boolean_validation(self):
        invalid_slots = ('', '../dev', '1dev', 'Dev', 'a/b', 'a;reset', 'a\nreset',
                         '${bootcmd}', 'a' * 49, None)
        for slot in invalid_slots:
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                scripts.release_script(slot, '1234abcd-03', directory=True)
        for uuid in ('1234ABCD-03', '1234abcd-02', '1234abcd-03;reset',
                     '1234abcd-03\nreset', '1234abcd-03/other', None):
            with self.subTest(uuid=uuid), self.assertRaises(ValueError):
                scripts.release_script('dev', uuid, directory=True)
        with self.assertRaises(ValueError):
            scripts.release_script('recovery', '1234abcd-03', directory=False)
        for value in (0, 1, 'true', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scripts.release_script('dev', '1234abcd-03', directory=value)
            with self.subTest(diagnostic=value), self.assertRaises(ValueError):
                self.source(suspend_diagnostics=value)
        scripts.release_script('a' * 48, '1234abcd-03', directory=True)


if __name__ == '__main__':
    unittest.main()
