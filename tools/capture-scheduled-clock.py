#!/usr/bin/env python3
"""Run one explicit finite scheduled capture from the proven directory root."""
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
from clock_deployment import bounded, digest, save, validate_files
from clock_scheduled import FILES, NativePause, execute, validate_contract
from development_clock import ADAPTERS, deployment_snapshot


def main():
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location('scheduled_original_runner', DIRECTORY / 'capture-clock-boundary.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    signal.signal(signal.SIGTERM, original.interrupted)
    signal.signal(signal.SIGINT, original.interrupted)
    try:
        contract = json.loads(bounded(DIRECTORY / 'contract.json'))
        validate_contract(contract)

        def verify_sources():
            validate_files(DIRECTORY, contract)
            hashes = contract['development']['adapter_files'] | contract['scheduled']['files']
            for name in (*ADAPTERS, *FILES):
                path = DIRECTORY / name
                if path.is_symlink() or digest(bounded(path)) != hashes[name]:
                    raise ValueError('Executed scheduled source changed: ' + name)

        verify_sources()
        reader = NativeReader(DIRECTORY / 'clock-boundary.so')
        pause = NativePause(DIRECTORY / 'clock-pause.so')

        def observe():
            verify_sources()
            deployment = deployment_snapshot(contract)
            return original.snapshot(reader, contract) | {'development': deployment, 'scheduled': contract['scheduled']}

        public = {1: time.monotonic_ns, 4: lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
                  7: lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
        result = execute(DIRECTORY, contract, observe, reader, public, pause, original.open_control)
    except BaseException as error:
        save(DIRECTORY, 'runner-error.json', dict(type=type(error).__name__, message=str(error)))
        return 1
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
