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
MAX_FLOWS = 128
FLOW_PREFIX_PACKETS = 16
RECEIVE_BUFFER = 4*1024*1024


class CaptureError(RuntimeError):
    """Fixed labels only; libpcap strings may contain private interface details."""
    def __init__(self, phase, category, status=None, error_number=None):
        self.phase, self.category = phase, category
        self.status, self.error_number = status, error_number
        super().__init__('Capture backend failure')

    def record(self):
        return dict(phase=self.phase, category=self.category, status=self.status, errno=self.error_number)


class FlowSelection:
    """Retain beginnings/control/first payload; count omitted bulk explicitly."""
    def __init__(self, server):
        self.server, self.flows = server, {}

    def keep(self, packet):
        outgoing = packet['source'] == self.server and packet['source_port'] == 22
        key = (packet['destination'], packet['destination_port']) if outgoing else (packet['source'], packet['source_port'])
        if key not in self.flows:
            if len(self.flows) >= MAX_FLOWS:
                raise ValueError('Flow observation limit reached')
            self.flows[key] = dict(count=0, server_isn=None)
        flow = self.flows[key]
        flow['count'] += 1
        if outgoing and packet['flags'] & 0x12 == 0x12:
            flow['server_isn'] = packet['seq']
        # Initial sequence identity, retries, closure/reset and zero-window
        # controls always survive selection. Tuple reuse remains ambiguous to
        # the report even if more than the prefix budget was already observed.
        return (flow['count'] <= FLOW_PREFIX_PACKETS or packet['flags'] & 7 != 0 or
                packet['window'] == 0 or packet['ssh_prefix'] is True or
                (outgoing and packet['payload_length'] > 0 and flow['server_isn'] is not None and
                 packet['seq'] == (flow['server_isn']+1) % 2**32))


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
            self.sock.setsockopt(socket.SOL_SOCKET, 33, RECEIVE_BUFFER)  # SO_RCVBUFFORCE, this socket only
            self.configuration = dict(receive_buffer_requested=RECEIVE_BUFFER,
                                      receive_buffer_effective=self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF))
            # Fixed-width new timespec ABI works on ARM32 and x86_64 alike.
            self.sock.setsockopt(socket.SOL_SOCKET, 64, 1)  # SO_TIMESTAMPNS_NEW
            self.sock.bind((interface, 3))  # ETH_P_ALL, including local output
            self.sock.setblocking(False)
            self.buffer = bytearray(SNAPLEN)
        except BaseException:
            self.sock.close()
            raise

    def fileno(self):
        return self.sock.fileno()

    def read(self):
        buffer = self.buffer
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
        self.lib = lib = C.CDLL('/usr/lib/libpcap.dylib', use_errno=True)
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
            'pcap_geterr': ([C.c_void_p], C.c_char_p),
            'pcap_close': ([C.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(lib, name)
            function.argtypes, function.restype = arguments, result
        error = C.create_string_buffer(256)
        self.handle = lib.pcap_open_live(interface.encode(), SNAPLEN, 0, 100, error)
        if not self.handle:
            raise CaptureError('open', 'unavailable', error_number=C.get_errno())
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
        C.set_errno(0)
        status = self.lib.pcap_next_ex(self.handle, C.byref(header), C.byref(data))
        if status == 0:
            return None
        if status != 1:
            number = C.get_errno()
            message = self.lib.pcap_geterr(self.handle) or b''
            category = 'interface-disappeared' if message == b'The interface disappeared' else 'read-failed'
            raise CaptureError('read', category, status, number)
        h = header.contents
        if h.caplen > SNAPLEN or h.caplen > h.length or not 0 <= h.stamp.microseconds < 10**6:
            raise ValueError('Invalid pcap header')
        return C.string_at(data, h.caplen), h.length, h.stamp.seconds*10**9+h.stamp.microseconds*1000

    def stats(self):
        buffer = C.create_string_buffer(256)  # Includes platform-specific tail fields.
        if self.lib.pcap_stats(self.handle, buffer) != 0:
            raise CaptureError('stats', 'unavailable', error_number=C.get_errno())
        received, dropped, interface_dropped = struct.unpack_from('=III', buffer.raw)
        return dict(received=received, dropped=dropped, interface_dropped=interface_dropped)

    def close(self):
        if self.handle:
            self.lib.pcap_close(self.handle)
            self.handle = None


class ReopeningPcap:
    """Bounded capture-handle recovery, never network configuration/recovery.

    Every disappearance closes one segment. Packets after reopening belong to a
    new segment, and a gapped capture can never claim continuous coverage.
    """
    def __init__(self, interface, address, test_gap_after=0, factory=None):
        self.factory = factory or PcapPackets
        self.interface, self.address = interface, address
        opened = clock()
        self.current = self.factory(interface, address)
        self.segments, self.gaps = [], []
        self.segment, self.attempts, self.reads = 0, 0, 0
        self.next_attempt = 0
        self.test_gap_after, self.injected = test_gap_after, False
        self._opened(opened)

    def _opened(self, opened):
        try:
            index = socket.if_nametoindex(self.interface)
        except BaseException:
            self.current.close(); self.current = None
            raise
        self.segment = len(self.segments)
        self.segments.append(dict(id=self.segment, interface_index=index, opened=opened,
                                  closed=None, stats=None, error=None))

    def _end(self, error=None):
        segment = self.segments[-1]
        if segment['closed'] is not None:
            return
        segment['error'] = error.record() if error is not None else None
        try:
            segment['stats'] = self.current.stats()
        except Exception:
            segment['stats'] = None  # Unknown counters never qualify a segment.
            if segment['error'] is None:
                segment['error'] = CaptureError('stats', 'unavailable').record()
        finally:
            try:
                self.current.close()
            finally:
                self.current = None
                segment['closed'] = clock()

    def fileno(self):
        return self.current.fileno() if self.current is not None else None

    def read(self):
        if self.current is None:
            if time.monotonic() < self.next_attempt:
                return None
            if self.attempts >= 60:
                raise CaptureError('reopen', 'attempt-limit')
            self.attempts += 1
            self.next_attempt = time.monotonic()+1
            try:
                opened = clock()
                self.current = self.factory(self.interface, self.address)
                self._opened(opened)
            except (CaptureError, OSError) as error:
                if isinstance(error, CaptureError) and error.phase != 'open':
                    raise
                self.gaps[-1]['reopen_attempts'] += 1
                return None
            self.gaps[-1]['reopen_attempts'] += 1
            self.gaps[-1]['ended'] = clock()
        try:
            if self.test_gap_after and self.reads >= self.test_gap_after and not self.injected:
                self.injected = True
                raise CaptureError('read', 'injected-interface-gap')
            value = self.current.read()
            if value is not None:
                self.reads += 1
            return value
        except CaptureError as error:
            if error.phase != 'read' or error.category not in ('interface-disappeared', 'injected-interface-gap'):
                raise
            self._end(error)
            if len(self.gaps) >= 3:
                raise CaptureError('reopen', 'gap-limit')
            self.gaps.append(dict(after_segment=self.segment, started=clock(), ended=None,
                                 error=error.record(), reopen_attempts=0))
            self.next_attempt = time.monotonic()+1
            return None

    def stats(self):
        if self.current is not None:
            self._end()
        known = [s['stats'] for s in self.segments if s['stats'] is not None]
        return dict(received=sum(s['received'] for s in known), dropped=sum(s['dropped'] for s in known),
                    interface_dropped=None if len(known) != len(self.segments) or
                        any(s['interface_dropped'] is None for s in known) else
                        sum(s['interface_dropped'] for s in known))

    def close(self):
        if self.current is not None:
            self._end()


def capture(path, identity, interface, address, seconds, backend=None,
            lock_path='/var/run/gameshellneo-tcp-metadata.lock', test_gap_after=0):
    if not re.fullmatch(r'(usb0|en[0-9]+)', interface) or not 10 <= seconds <= MAX_SECONDS:
        raise ValueError('Invalid capture interface or duration')
    address = str(ipaddress.IPv4Address(address))
    identity = token(identity)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if test_gap_after not in (0, 32) or (test_gap_after and sys.platform != 'darwin'):
        raise ValueError('Synthetic gap is a fixed Mac-only awake test')
    result = dict(schema=3, run_id=identity, source_sha256=source, interface=interface, address=address,
                  platform=sys.platform, passed=False, reason='incomplete', packets=0, reads=0, rejected=0,
                  selection='flow-prefix16-control-first-payload', selected_out=0, matched=0,
                  gaps=[], segments=[], test_gap_after=test_gap_after,
                  stats=None, started=clock(), finished=None, seconds_limit=seconds)
    cpu_start = time.process_time()
    selection = FlowSelection(address)
    selected_segment = 0
    error_phase = 'open'
    receiver = None
    metadata_digest = hashlib.sha256()
    output_created = False
    try:
        if os.fstat(descriptor).st_uid != os.geteuid():
            raise ValueError('Recorder lock has another owner')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if backend is not None:
            receiver = backend(interface, address)
        elif sys.platform == 'linux':
            receiver = LinuxPackets(interface, address)
        else:
            receiver = ReopeningPcap(interface, address, test_gap_after)
        if hasattr(receiver, 'segments'):
            result['segments'], result['gaps'] = receiver.segments, receiver.gaps
        result['backend_configuration'] = getattr(receiver, 'configuration', {})
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
                error_phase = 'read'
                value = receiver.read()
                if value is None:
                    error_phase = 'wait'
                    fd = receiver.fileno()
                    if fd is None:
                        time.sleep(0.1)
                    else:
                        select.select([fd], [], [], 0.1)
                else:
                    result['reads'] += 1
                    raw, wire_length, stamp = value
                    try:
                        record = decode(raw, wire_length, address)
                    except ValueError:
                        result['rejected'] += 1
                        record = None
                    if record is not None:
                        result['matched'] += 1
                        if getattr(receiver, 'segment', 0) != selected_segment:
                            selected_segment = receiver.segment
                            selection = FlowSelection(address)
                        if selection.keep(record):
                            error_phase = 'write'
                            emit(dict(event='packet', segment=getattr(receiver, 'segment', 0),
                                      realtime_ns=stamp, observed_monotonic_ns=time.monotonic_ns(), **record))
                            result['packets'] += 1
                        else:
                            result['selected_out'] += 1
                if time.monotonic() >= next_clock:
                    emit(dict(event='clock', **clock()))
                    output.flush()
                    next_clock = time.monotonic()+1
            emit(dict(event='clock', **clock()))
            output.flush()
            error_phase = 'stats'
            result.update(reason=reason, bytes=size, stats=receiver.stats())
            error_phase = 'interface'
            result['final_interface_index'] = socket.if_nametoindex(interface)
            if not result['segments']:
                result['segments'] = [dict(id=0, interface_index=result['interface_index'],
                    opened=result['started'], closed=clock(), stats=result['stats'], error=None)]
            # A deadline/cap is useful retained evidence, never an admitted full window.
            result['passed'] = (reason == 'stopped' and result['rejected'] == 0 and
                                not result['gaps'] and not test_gap_after and
                                all(s['stats'] is not None and s['error'] is None for s in result['segments']) and
                                result['interface_index'] == result['final_interface_index'] and
                                result['stats']['dropped'] == 0 and result['stats']['interface_dropped'] in (0, None))
    except BaseException as error:
        result['reason'] = 'error'
        result['error_type'] = type(error).__name__
        result['error_phase'] = error_phase
        if isinstance(error, CaptureError):
            result['backend_error'] = error.record()
        raise
    finally:
        if receiver is not None:
            receiver.close()
        os.close(descriptor)
        result['finished'] = clock()
        result['process_cpu_seconds'] = time.process_time()-cpu_start
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
    parser.add_argument('--test-gap-after', type=int, choices=(0, 32), default=0)
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
                     '--seconds', str(args.seconds), '--test-gap-after', str(args.test_gap_after)]
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
    capture(path, identity, args.interface, args.address, args.seconds, test_gap_after=args.test_gap_after)


if __name__ == '__main__':
    main()
