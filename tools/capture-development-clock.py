#!/usr/bin/env python3
"""One explicit, bounded awake capture from a proven development directory."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY))
from clock_boundary import NativeReader
from clock_deployment import bounded, digest, execute, save, validate_files
from development_clock import ADAPTERS, deployment_snapshot, validate_development_contract


def main():
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location('original_clock_runner', DIRECTORY / 'capture-clock-boundary.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    signal.signal(signal.SIGTERM, original.interrupted)
    signal.signal(signal.SIGINT, original.interrupted)
    try:
        contract = json.loads(bounded(DIRECTORY / 'contract.json'))
        validate_development_contract(contract)
        validate_files(DIRECTORY, contract)

        def adapter_files():
            for name in ADAPTERS:
                path = DIRECTORY / name
                if path.is_symlink() or digest(bounded(path)) != contract['development']['adapter_files'][name]:
                    raise ValueError('Executed adapter changed: ' + name)

        adapter_files()
        reader = NativeReader(DIRECTORY / 'clock-boundary.so')

        def observe():
            adapter_files()
            deployment = deployment_snapshot(contract)
            return original.snapshot(reader, contract) | {'development': deployment}

        public = {1: time.monotonic_ns, 4: lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
                  7: lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
        result = execute(DIRECTORY, contract, observe, reader, public, original.open_control)
    except BaseException as error:
        save(DIRECTORY, 'runner-error.json', dict(type=type(error).__name__, message=str(error)))
        return 1
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
