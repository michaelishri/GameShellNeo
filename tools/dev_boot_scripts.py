"""Generate opt-in development boot scripts; no card access or persistence claims."""
import re
import struct
import zlib

SCRIPT_LIMIT = 0x10000
KERNEL_LIMIT = 0x1000000
DTB_LIMIT = 0x100000
INITRD_LIMIT = 0x1000000


def script_image(source: bytes) -> bytes:
    """Wrap trusted script text in a deterministic legacy ARM image."""
    if not isinstance(source, bytes) or not source or b'\0' in source:
        raise ValueError('Expected nonempty script bytes without NUL')
    if len(source) > SCRIPT_LIMIT - 72:
        raise ValueError('Development script exceeds its load buffer')
    payload = struct.pack('>2I', len(source), 0) + source
    header = struct.pack('>7I4B32s', 0x27051956, 0, 0, len(payload), 0, 0,
                         zlib.crc32(payload), 5, 2, 6, 0, b'GameShellNeo development')
    return header[:4] + struct.pack('>I', zlib.crc32(header)) + header[8:] + payload


def _definition(name, commands):
    return "setenv " + name + " '" + ' &&\n  '.join(commands) + "'\n"


def _image_helpers():
    # Read header words bytewise: the legacy header is big endian on this
    # little-endian ARM machine. Check its declared length before iminfo can
    # read the payload. All callers already bound the load to their buffer.
    reader = ['setenv neo_value 0']
    for _ in range(4):
        reader.extend((
            'setexpr.b neo_byte *${neo_read}',
            'setexpr neo_value ${neo_value} \\* 0x100',
            'setexpr neo_value ${neo_value} + ${neo_byte}',
            'setexpr neo_read ${neo_read} + 1',
        ))
    image = [
        'itest.l ${neo_len} -ge 0x40',
        'setenv neo_read ${neo_addr}',
        'run neo_be32',
        'itest.l ${neo_value} -eq 0x27051956',
        'setexpr neo_read ${neo_addr} + 0xc',
        'run neo_be32',
        'setexpr neo_expected ${neo_len} - 0x40',
        'itest.l ${neo_value} -eq ${neo_expected}',
    ]
    for offset, value in ((0x1c, '0x5'), (0x1d, '0x2'), (0x1e, '${neo_type}')):
        image.extend((f'setexpr neo_at ${{neo_addr}} + 0x{offset:x}',
                      'itest.b *${neo_at} -eq ' + value))
    image.append('iminfo ${neo_addr}')
    return _definition('neo_be32', reader) + _definition('neo_image', image)


def dispatcher() -> bytes:
    """Consume a requested trial before handoff; recovery never returns outward.

    The verified FAT rewrite is best effort. It does not promise power-cut
    persistence, SD survival or recovery from a kernel hang without a reset.
    """
    validate = [
        'setenv neo_type 0x6',
        'run neo_image',
        'setexpr neo_at ${neo_addr} + 0x1f',
        'itest.b *${neo_at} -eq 0',
        'setexpr neo_read ${neo_addr} + 0x40',
        'run neo_be32',
        'setexpr neo_expected ${neo_len} - 0x48',
        'itest.l ${neo_value} -eq ${neo_expected}',
        'setexpr neo_at ${neo_addr} + 0x44',
        'itest.l *${neo_at} -eq 0',
    ]
    load = [
        'fatsize mmc 0:1 ${neo_file}',
        'setenv neo_len ${filesize}',
        'itest.l ${neo_len} -ge 0x49',
        'itest.l ${neo_len} -le 0x10000',
        'fatload mmc 0:1 ${neo_addr} ${neo_file} ${neo_len}',
        'itest.l ${filesize} -eq ${neo_len}',
        'run neo_script',
    ]
    text = ('# Development only; no saveenv or raw-sector writes.\n'
            'setenv verify yes\n' + _image_helpers() +
            _definition('neo_script', validate) + _definition('neo_load', load))
    text += '''setenv neo_file NEXT.SCR
setenv neo_addr 0x43000000
if run neo_load; then
  setenv neo_next_len ${neo_len}
  setenv neo_file GOOD.SCR
  setenv neo_addr 0x43300000
  if run neo_load; then
    setenv neo_good_len ${neo_len}
    if itest.l ${neo_next_len} -eq ${neo_good_len} && cmp.b 0x43000000 0x43300000 ${neo_next_len}; then
      source 0x43000000
    else
      if fatwrite mmc 0:1 0x43300000 NEXT.SCR ${neo_good_len}; then
        setenv neo_file NEXT.SCR
        setenv neo_addr 0x43200000
        if run neo_load && itest.l ${neo_len} -eq ${neo_good_len} && cmp.b 0x43300000 0x43200000 ${neo_good_len}; then
          source 0x43000000
        fi
      fi
    fi
  fi
fi
# A kernel handoff never returns, including when the final command returned 0.
setenv verify yes
setenv neo_file RECOVER.SCR
setenv neo_addr 0x43400000
if run neo_load; then
  source 0x43400000
fi
echo "GameShellNeo development recovery failed; halted"
while true; do
  sleep 1
done
'''
    return text.encode()


def _asset(path, address, limit, kind=None):
    commands = [
        'fatsize mmc 0:1 ' + path,
        'setenv neo_len ${filesize}',
        'itest.l ${neo_len} -ge ' + ('0x41' if kind else '1'),
        f'itest.l ${{neo_len}} -le 0x{limit:x}',
        f'fatload mmc 0:1 0x{address:x} {path} ${{neo_len}}',
        'itest.l ${filesize} -eq ${neo_len}',
    ]
    if kind:
        commands.extend((f'setenv neo_addr 0x{address:x}',
                         f'setenv neo_type 0x{kind:x}', 'run neo_image'))
    return commands


def release_script(slot_id, root_partuuid, *, directory: bool,
                   suspend_diagnostics: bool = False) -> bytes:
    """Boot a matched development release or the fixed direct-root recovery."""
    if (not isinstance(slot_id, str) or
            not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', slot_id)):
        raise ValueError('Expected a lowercase development slot identifier')
    if type(directory) is not bool or type(suspend_diagnostics) is not bool:
        raise ValueError('Development boot options must be booleans')
    suffix = '03' if directory else '02'
    if (not isinstance(root_partuuid, str) or
            not re.fullmatch(r'[0-9a-f]{8}-' + suffix, root_partuuid)):
        raise ValueError('Root PARTUUID does not match the development root mode')
    args = ('console=tty0 console=ttyS0,115200n8 '
            f'root=PARTUUID={root_partuuid} rootfstype=ext4 rootwait rw panic=10')
    if directory:
        args += f' neo.dev=1 neo.slot={slot_id} neo.store=PARTUUID={root_partuuid}'
    if suspend_diagnostics:
        args += ' mem_sleep_default=s2idle'
    prefix = f'systems/{slot_id}/'
    commands = _asset(prefix + 'uImage', 0x48000000, KERNEL_LIMIT, 2)
    commands += _asset(prefix + 'sun8i-r16-clockworkpi-cpi3.dtb', 0x49000000, DTB_LIMIT)
    if directory:
        commands += _asset(prefix + 'uInitrd', 0x4a000000, INITRD_LIMIT, 3)
    text = '# Development release descriptor; a returning boot falls back.\n'
    text += 'setenv verify yes\n' + _image_helpers()
    text += 'setenv bootargs ' + args + '\n'
    text += 'if ' + ' &&\n  '.join(commands) + '; then\n'
    ramdisk = '0x4a000000' if directory else '-'
    text += f'  bootm 0x48000000 {ramdisk} 0x49000000\nfi\n'
    text += 'echo "GameShellNeo development release returned"\nfalse\n'
    return text.encode()
