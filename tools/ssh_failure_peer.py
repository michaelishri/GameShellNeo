"""One bounded, unprivileged loopback peer for reproducible SSH setup failures."""
import json
import signal
import socket
import sys
import time

GREETING = b'SSH-2.0-GameShellNeo_awake_fixture\r\n'


def serve(mode):
    if mode not in ('silent','greeting-only'):
        raise ValueError('Unknown fixture mode')
    signal.alarm(60)  # Also bounds a lost controller/session; no persistent daemon.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as server:
        server.bind(('127.0.0.1',0))
        server.listen(1)
        server.settimeout(25)
        print(json.dumps(dict(event='ready',target=list(server.getsockname()),mode=mode)),flush=True)
        with server.accept()[0] as peer:
            connection = dict(client=list(peer.getpeername()),server=list(peer.getsockname()))
            sent, received = 0, 0
            if mode == 'greeting-only':
                peer.sendall(GREETING)
                sent = len(GREETING)
            deadline = time.monotonic()+40
            while True:
                peer.settimeout(max(0.01,deadline-time.monotonic()))
                data = peer.recv(4096)
                if not data:
                    break
                received += len(data)
                if received > 65536 or time.monotonic() >= deadline:
                    raise ValueError('Fixture byte/time bound')
            # Count/discard input; no banner, key, authentication or payload logs.
            print(json.dumps(dict(event='closed',mode=mode,connection=connection,
                                  sent_bytes=sent,received_bytes=received)),flush=True)
    signal.alarm(0)


if __name__ == '__main__':
    serve(sys.argv[1])
