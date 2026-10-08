"""Bounded Ethernet/IPv4 SSH metadata recorder; never persist packet bytes.

Linux uses an interface-bound, non-promiscuous AF_PACKET socket. Darwin uses
the system libpcap with an equivalent narrow filter. Neither changes the link.
Only TCP headers and a four-byte SSH-prefix Boolean leave the decoder.
"""
import argparse
import ctypes as C
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import time

SNAPLEN = 128
MAX_PACKETS = 8192
MAX_READS = 32768
MAX_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 300


def token(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid capture identity')
    return value


def directory(value):
    p = Path(value)
    if not re.fullmatch(r'/tmp/gameshellneo-tcp\.[A-Za-z0-9]+', str(p)) or p.is_symlink() or not p.is_dir():
        raise ValueError('Invalid private capture directory')
    return p


def exclusive(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb')


def save(path, value):
    with exclusive(path) as stream:
        stream.write((json.dumps(value, sort_keys=True)+'\n').encode())


def clock():
    a = time.monotonic_ns()
    wall = time.time_ns()
    boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME) if hasattr(time, 'CLOCK_BOOTTIME') else None
    return dict(monotonic_before_ns=a, realtime_ns=wall, boottime_ns=boot,
                monotonic_after_ns=time.monotonic_ns())


def decode(data, wire_length, address):
    """Accept untagged Ethernet IPv4 TCP; reject malformed relevant headers.

    Normal payload truncation is expected. A prefix split between packets is
    unknown, not negative. Sequence numbers permit matching without payloads.
    """
    if len(data) < 14 or data[12:14] != b'\x08\x00':
        return None
    if len(data) < 34 or data[14] >> 4 != 4:
        raise ValueError('Invalid IPv4 header')
    source, destination = socket.inet_ntoa(data[26:30]), socket.inet_ntoa(data[30:34])
    if address not in (source, destination) or data[23] != 6:
        return None
    ihl = (data[14] & 15) * 4
    total, ident, fragment = struct.unpack_from('!HHH', data, 16)
    if ihl < 20 or total < ihl+20 or total+14 > wire_length or fragment & 0x3fff:
        raise ValueError('Unsupported fragmented or malformed IPv4 TCP')
    offset = 14+ihl
    if len(data) < offset+20:
        raise ValueError('Truncated TCP header')
    sport, dport, seq, ack = struct.unpack_from('!HHII', data, offset)
    if 22 not in (sport, dport):
        return None
    thl = (data[offset+12] >> 4) * 4
    if thl < 20 or ihl+thl > total or offset+thl > len(data):
        raise ValueError('Invalid TCP header length')
    payload_length = total-ihl-thl
    prefix = data[offset+thl:offset+thl+4]
    return dict(source=source, destination=destination, source_port=sport, destination_port=dport,
                seq=seq, ack=ack, flags=data[offset+13], window=struct.unpack_from('!H', data, offset+14)[0],
                ip_id=ident, payload_length=payload_length,
                ssh_prefix=(prefix == b'SSH-') if payload_length >= 4 and len(prefix) == 4 else None)


class LinuxPackets:
    def __init__(self, interface, address):
        # Protocol 0 avoids receiving other interfaces before bind. No membership
        # request, promiscuity, filter replacement or link setting is performed.
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, 0)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
            # Fixed-width new timespec ABI works on ARM32 and x86_64 alike.
            self.sock.setsockopt(socket.SOL_SOCKET, 64, 1)  # SO_TIMESTAMPNS_NEW
            self.sock.bind((interface, 3))  # ETH_P_ALL, including local output
            self.sock.setblocking(False)
        except BaseException:
            self.sock.close()
            raise

    def fileno(self):
        return self.sock.fileno()

    def read(self):
        buffer = bytearray(SNAPLEN)
        try:
            length, ancillary, flags, _ = self.sock.recvmsg_into(
                [buffer], socket.CMSG_SPACE(16), socket.MSG_TRUNC)
        except BlockingIOError:
            return None
        stamps = [value for level, kind, value in ancillary if level == socket.SOL_SOCKET and kind == 64]
        if flags & socket.MSG_CTRUNC or len(stamps) != 1 or len(stamps[0]) != 16:
            raise ValueError('Missing kernel packet timestamp')
        sec, ns = struct.unpack('=qq', stamps[0])
        if sec < 0 or not 0 <= ns < 10**9:
            raise ValueError('Invalid kernel packet timestamp')
        return bytes(buffer[:min(length, SNAPLEN)]), length, sec*10**9+ns

    def stats(self):
        received, dropped = struct.unpack('=II', self.sock.getsockopt(263, 6, 8))  # SOL_PACKET, PACKET_STATISTICS
        return dict(received=received, dropped=dropped, interface_dropped=None)

    def close(self):
        self.sock.close()


class PcapPackets:
    class Timeval(C.Structure):
        # Darwin LP64 timeval has a 64-bit time_t and 32-bit suseconds_t.
        # The final four bytes are padding, not part of tv_usec.
        _fields_ = [('seconds', C.c_long), ('microseconds', C.c_int32)]

    class Program(C.Structure):
        _fields_ = [('length', C.c_uint), ('instructions', C.c_void_p)]

    def __init__(self, interface, address):
        class Header(C.Structure):
            _fields_ = [('stamp', PcapPackets.Timeval), ('caplen', C.c_uint), ('length', C.c_uint)]
        self.Header = Header
        self.lib = lib = C.CDLL('/usr/lib/libpcap.dylib')
        signatures = {
            'pcap_open_live': ([C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_char_p], C.c_void_p),
            'pcap_datalink': ([C.c_void_p], C.c_int),
            'pcap_compile': ([C.c_void_p, C.POINTER(self.Program), C.c_char_p, C.c_int, C.c_uint], C.c_int),
            'pcap_setfilter': ([C.c_void_p, C.POINTER(self.Program)], C.c_int),
            'pcap_freecode': ([C.POINTER(self.Program)], None),
            'pcap_setnonblock': ([C.c_void_p, C.c_int, C.c_char_p], C.c_int),
            'pcap_get_selectable_fd': ([C.c_void_p], C.c_int),
            'pcap_next_ex': ([C.c_void_p, C.POINTER(C.POINTER(Header)), C.POINTER(C.c_void_p)], C.c_int),
            'pcap_stats': ([C.c_void_p, C.c_void_p], C.c_int),
            'pcap_close': ([C.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(lib, name)
            function.argtypes, function.restype = arguments, result
        error = C.create_string_buffer(256)
        self.handle = lib.pcap_open_live(interface.encode(), SNAPLEN, 0, 100, error)
        if not self.handle:
            raise RuntimeError('Cannot open non-promiscuous pcap capture')
        try:
            if lib.pcap_datalink(self.handle) != 1:
                raise ValueError('Require Ethernet DLT_EN10MB')
            program = self.Program()
            if lib.pcap_compile(self.handle, C.byref(program),
                                ('ip and tcp port 22 and host '+address).encode(), 1, 0xffffffff) != 0:
                raise RuntimeError('Cannot compile capture filter')
            try:
                if lib.pcap_setfilter(self.handle, C.byref(program)) != 0:
                    raise RuntimeError('Cannot install capture filter')
            finally:
                lib.pcap_freecode(C.byref(program))
            if lib.pcap_setnonblock(self.handle, 1, error) != 0:
                raise RuntimeError('Cannot make capture nonblocking')
            self.fd = lib.pcap_get_selectable_fd(self.handle)
            if self.fd < 0:
                raise RuntimeError('Capture has no selectable descriptor')
        except BaseException:
            self.close()
            raise

    def fileno(self):
        return self.fd

    def read(self):
        header, data = C.POINTER(self.Header)(), C.c_void_p()
        status = self.lib.pcap_next_ex(self.handle, C.byref(header), C.byref(data))
        if status == 0:
            return None
        if status != 1:
            raise RuntimeError('pcap read failed')
        h = header.contents
        if h.caplen > SNAPLEN or h.caplen > h.length or not 0 <= h.stamp.microseconds < 10**6:
            raise ValueError('Invalid pcap header')
        return C.string_at(data, h.caplen), h.length, h.stamp.seconds*10**9+h.stamp.microseconds*1000

    def stats(self):
        buffer = C.create_string_buffer(256)  # Includes platform-specific tail fields.
        if self.lib.pcap_stats(self.handle, buffer) != 0:
            raise RuntimeError('pcap statistics unavailable')
        received, dropped, interface_dropped = struct.unpack_from('=III', buffer.raw)
        return dict(received=received, dropped=dropped, interface_dropped=interface_dropped)

    def close(self):
        if self.handle:
            self.lib.pcap_close(self.handle)
            self.handle = None


def capture(path, identity, interface, address, seconds, backend=None,
            lock_path='/var/run/gameshellneo-tcp-metadata.lock'):
    if not re.fullmatch(r'(usb0|en[0-9]+)', interface) or not 10 <= seconds <= MAX_SECONDS:
        raise ValueError('Invalid capture interface or duration')
    address = str(ipaddress.IPv4Address(address))
    identity = token(identity)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(schema=1, run_id=identity, source_sha256=source, interface=interface, address=address,
                  platform=sys.platform, passed=False, reason='incomplete', packets=0, reads=0, rejected=0,
                  stats=None, started=clock(), finished=None, seconds_limit=seconds)
    receiver = None
    metadata_digest = hashlib.sha256()
    output_created = False
    try:
        if os.fstat(descriptor).st_uid != os.geteuid():
            raise ValueError('Recorder lock has another owner')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receiver = (backend or (LinuxPackets if sys.platform == 'linux' else PcapPackets))(interface, address)
        result['interface_index'] = socket.if_nametoindex(interface)
        with exclusive(path/'packets.jsonl') as output:
            output_created = True
            size = 0

            def emit(value):
                nonlocal size
                payload = (json.dumps(value, sort_keys=True)+'\n').encode()
                if size+len(payload) > MAX_BYTES:
                    raise ValueError('Metadata byte cap reached')
                if output.write(payload) != len(payload):
                    raise OSError('Short metadata write')
                metadata_digest.update(payload)
                size += len(payload)

            emit(dict(event='clock', **clock()))
            output.flush()
            save(path/'ready.json', result | dict(pid=os.getpid(), ready=True))
            deadline = time.monotonic()+seconds
            wall_deadline = time.time()+seconds
            next_clock = time.monotonic()+1
            reason = 'deadline'
            while time.monotonic() < deadline and time.time() < wall_deadline:
                if (path/'stop.json').exists():
                    stop = json.loads((path/'stop.json').read_text())
                    if stop != {'run_id': identity}:
                        raise ValueError('Stop identity mismatch')
                    reason = 'stopped'
                    break
                if result['reads'] >= MAX_READS or result['packets'] >= MAX_PACKETS:
                    reason = 'packet-cap'
                    break
                value = receiver.read()
                if value is None:
                    select.select([receiver.fileno()], [], [], 0.1)
                else:
                    result['reads'] += 1
                    raw, wire_length, stamp = value
                    try:
                        record = decode(raw, wire_length, address)
                    except ValueError:
                        result['rejected'] += 1
                        record = None
                    if record is not None:
                        emit(dict(event='packet', realtime_ns=stamp, observed_monotonic_ns=time.monotonic_ns(), **record))
                        result['packets'] += 1
                if time.monotonic() >= next_clock:
                    emit(dict(event='clock', **clock()))
                    output.flush()
                    next_clock = time.monotonic()+1
            emit(dict(event='clock', **clock()))
            output.flush()
            result.update(reason=reason, bytes=size, stats=receiver.stats())
            result['final_interface_index'] = socket.if_nametoindex(interface)
            # A deadline/cap is useful retained evidence, never an admitted full window.
            result['passed'] = (reason == 'stopped' and result['rejected'] == 0 and
                                result['interface_index'] == result['final_interface_index'] and
                                result['stats']['dropped'] == 0 and result['stats']['interface_dropped'] in (0, None))
    except BaseException as error:
        result['reason'] = 'error'
        result['error_type'] = type(error).__name__
        raise
    finally:
        if receiver is not None:
            receiver.close()
        os.close(descriptor)
        result['finished'] = clock()
        if output_created:
            result['metadata_sha256'] = metadata_digest.hexdigest()
        save(path/'result.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('capture', 'launch', 'stop', 'clock', 'export'))
    parser.add_argument('--directory')
    parser.add_argument('--run-id')
    parser.add_argument('--interface')
    parser.add_argument('--address')
    parser.add_argument('--seconds', type=int, default=MAX_SECONDS)
    parser.add_argument('--file', choices=('ready.json', 'result.json', 'packets.jsonl', 'supervisor.json', 'smoke.json'))
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == 'clock':
        print(json.dumps(clock()))
        return
    path, identity = directory(args.directory), token(args.run_id)
    if args.mode == 'export':
        if not args.file:
            raise ValueError('Export requires a known artifact name')
        fd = os.open(path/args.file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            data = stream.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError('Remote artifact exceeds limit')
        if args.file != 'packets.jsonl' and json.loads(data)['run_id'] != identity:
            raise ValueError('Export identity mismatch')
        sys.stdout.buffer.write(data)
        return
    if args.mode == 'stop':
        ready = json.loads((path/'ready.json').read_text())
        if ready['run_id'] != identity:
            raise ValueError('Recorder identity mismatch')
        if not (path/'stop.json').exists():
            save(path/'stop.json', dict(run_id=identity))
        return
    if args.mode == 'launch':
        if sys.platform != 'darwin':
            raise ValueError('Detached launch is only for the Mac; use systemd on Linux')
        arguments = [sys.executable, '-B', str(Path(__file__).resolve()), 'capture', '--directory', str(path),
                     '--run-id', identity, '--interface', args.interface, '--address', args.address,
                     '--seconds', str(args.seconds)]
        child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        print(json.dumps(dict(pid=child.pid, run_id=identity)))
        return
    # SIGTERM still closes the capture and writes an incomplete result. Kernel
    # resources also disappear if an external supervisor kills this worker.
    def interrupted(signum, frame):
        raise InterruptedError('Recorder interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    capture(path, identity, args.interface, args.address, args.seconds)


if __name__ == '__main__':
    main()
