#!/usr/bin/env python3
"""Save read-only keypad identity, power policy and tracing capability over USB."""
import json
import os
import shlex
from private_config import load_env
from remote import ROOT, device, evidence_directory, run


def main():
    os.umask(0o077)
    capture = evidence_directory()
    with device(load_env(), 'usb') as client:
        data = run(client, shlex.join(['sudo', '-n', 'python3', '-B', '-c',
                   (ROOT / 'tools/keypad_pm.py').read_text()]), display=False, timeout=40)
    (capture / 'keypad.json').write_bytes(data)
    value = json.loads(data)
    print('Private keypad evidence:', capture)
    print(json.dumps({key: value[key] for key in ('usb', 'inputs', 'regulators', 'port_quirks',
                     'tracing_available', 'dynamic_debug_available')}, indent=2))


if __name__ == '__main__':
    main()
