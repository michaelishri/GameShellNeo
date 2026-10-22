#!/usr/bin/env python3
"""Qualify candidate 0057 against a five-file projection of locked Linux."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import uuid

from brcmfmac_eapol_checks import admit_native, inputs, prepare, qualify, qualify_drivers
from kernel_sources import atomic_json, locked

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path,
                        default=ROOT / '.local/downloads/linux-6.18.54.tar.xz')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reference-only', action='store_true',
                        help='retain the declared nine failing/five passing baseline cases')
    mode.add_argument('--compile-drivers', action='store_true',
                      help='run managed ARM and board/debug objects using proved original native evidence')
    parser.add_argument('--native-evidence', type=Path,
                        help='original accepted native/sanitizer/control attempt; required with --compile-drivers')
    args = parser.parse_args()
    if bool(args.native_evidence) != args.compile_drivers:
        parser.error('--compile-drivers and --native-evidence must be supplied together')
    work = ROOT / '.local/tests/brcmfmac-eapol'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        attempt = work / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
        attempt.mkdir()
        initial = inputs(ROOT)
        atomic_json(attempt / 'started.json', dict(pid=os.getpid(), inputs=initial,
                    mode='drivers' if args.compile_drivers else 'reference' if args.reference_only else 'candidate',
                    archive=str(args.archive.resolve()), started_utc=datetime.now(timezone.utc).isoformat()))
        print('Original operation: ' + str(attempt), flush=True)
        try:
            baseline, candidate, source = prepare(ROOT, args.archive.resolve(), attempt)
            atomic_json(attempt / 'sources.json', source)
            if args.compile_drivers:
                results = dict(native_provenance=admit_native(ROOT, candidate, attempt, args.native_evidence))
                results['drivers'] = qualify_drivers(ROOT, args.archive.resolve(), candidate, attempt,
                                                    args.native_evidence.resolve())
            else:
                results = qualify(ROOT, baseline, candidate, attempt, reference_only=args.reference_only)
            if inputs(ROOT) != initial:
                raise RuntimeError('Maintained inputs changed during this operation')
            atomic_json(attempt / 'result.json', dict(status='passed', inputs=initial, results=results,
                        limits='Actual driver bodies and key structs; scripted wait/transport and scalar ownership, not Linux scheduling/SMP/firmware/board or original NEO-55 attribution.'))
        except BaseException as error:
            atomic_json(attempt / 'failure.json', dict(type=type(error).__name__, error=str(error)))
            raise
        print('Evidence: ' + str(attempt / 'result.json'), flush=True)


if __name__ == '__main__':
    main()
