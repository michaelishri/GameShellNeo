#!/usr/bin/env python3
"""Qualify the opt-in brcmfmac F2 reset-owner guard without device access."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import shutil
import sys
import uuid

from brcmfmac_reset_checks import file_hash, inputs, locked, prepare, qualify, qualify_drivers, save

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path,
                        help='Existing locked Linux archive; never downloaded or copied')
    parser.add_argument('--reference-only', action='store_true',
                        help='Retain original-source 13-pass/three-failure reproduction only')
    parser.add_argument('--compile-drivers', action='store_true',
                        help='Managed-only ARM/full-object phase from unchanged original native evidence')
    parser.add_argument('--native-evidence', type=Path)
    parser.add_argument('--native-revision', help='Full Git commit identifying the original native helper')
    parser.add_argument('--reuse-source-receipt', type=Path,
                        help='Original report314 full-source receipt; its exact retained profile is verified')
    args = parser.parse_args()
    if args.compile_drivers:
        if (args.reference_only or args.archive is not None or not args.native_evidence or
                not args.reuse_source_receipt or not re.fullmatch(r'[0-9a-f]{40}', args.native_revision or '')):
            parser.error('Managed phase needs --native-evidence, full --native-revision and --reuse-source-receipt only')
    elif not args.archive or args.native_evidence or args.native_revision or args.reuse_source_receipt:
        parser.error('Native qualification requires --archive; managed-only arguments need --compile-drivers')
    work = ROOT / '.local/tests/brcmfmac-reset'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.suite-lock'):
        if shutil.disk_usage(work).free < 3 * 1024 ** 3:
            raise RuntimeError('Require at least 3 GiB free before source projection')
        attempt = work / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
        attempt.mkdir()
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        before = inputs(ROOT)
        archive = args.archive.absolute() if args.archive else None
        save(attempt / 'inputs.json', dict(maintained=before, archive=str(archive) if archive else None,
             mode='managed-only' if args.compile_drivers else 'native',
             reference_only=args.reference_only, started_utc=datetime.now(timezone.utc).isoformat()))
        print('Original reset qualification: ' + str(attempt), flush=True)
        try:
            if args.compile_drivers:
                result = qualify_drivers(ROOT, args.native_evidence.absolute(), args.native_revision,
                                         args.reuse_source_receipt.absolute(), attempt)
            else:
                baseline, candidate, source = prepare(ROOT, archive, attempt)
                save(attempt / 'sources.json', source)
                result = qualify(ROOT, baseline, candidate, attempt,
                                 reference_only=args.reference_only)
            if inputs(ROOT) != before:
                raise RuntimeError('Maintained inputs changed during original operation')
            used = sum(path.stat().st_size for path in attempt.rglob('*') if path.is_file())
            if used > 128 * 1024 ** 2:
                raise RuntimeError('Original qualification exceeded its 128 MiB disk budget')
            artifacts = {str(path.relative_to(attempt)): file_hash(path)
                         for path in sorted(attempt.rglob('*')) if path.is_file()}
            save(attempt / 'result.json', dict(
                status=('qualified-managed-drivers' if args.compile_drivers else
                        'qualified-original-source' if args.reference_only else 'qualified-offline-candidate'),
                finished_utc=datetime.now(timezone.utc).isoformat(),
                baseline_passes=0 if args.compile_drivers else 13,
                baseline_expected_failures=0 if args.compile_drivers else 3,
                candidate_cases=0 if args.reference_only or args.compile_drivers else 16,
                sanitizer_cases=0 if args.reference_only or args.compile_drivers else 16,
                results=result, artifact_bytes=used, artifacts=artifacts))
        except BaseException as error:
            save(attempt / 'failure.json', dict(type=type(error).__name__, error=str(error),
                 finished_utc=datetime.now(timezone.utc).isoformat(),
                 action='Inspect this original operation and evidence; no automatic retry.'))
            raise
        if args.compile_drivers:
            print('New managed ARM: 16 PASS; complete normal/debug objects qualified; old source/evidence retained.')
            return
        print('Original source: 13 PASS / 3 expected FAIL; ' +
              ('candidate not executed.' if args.reference_only else
               'candidate native/sanitizer: 16 PASS each; eight compiling controls rejected.'))


if __name__ == '__main__':
    main()
