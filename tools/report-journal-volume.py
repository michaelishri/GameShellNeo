#!/usr/bin/env python3
"""Summarize a private journalctl JSON-lines capture without printing messages."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

MAX_LINE = 4 * 1024 * 1024
MAX_CAPTURE = 128 * 1024 * 1024


def summarize(path):
    digest = hashlib.sha256()
    counts, sizes = Counter(), Counter()
    total = commands = inline = 0
    with path.open('rb') as source:
        while raw := source.readline(MAX_LINE + 1):
            total += len(raw)
            if len(raw) > MAX_LINE or total > MAX_CAPTURE:
                raise ValueError('Journal capture exceeds the bounded report size')
            digest.update(raw)
            try:
                record = json.loads(raw)
                identifier = record.get('SYSLOG_IDENTIFIER', record.get('_COMM', 'other'))
                message = record.get('MESSAGE', '')
                if isinstance(message, list):
                    if any(type(x) is not int or not 0 <= x <= 255 for x in message):
                        raise ValueError
                    payload = bytes(message)
                elif isinstance(message, str):
                    payload = message.encode('utf-8')
                else:
                    raise ValueError
                # Fixed categories: no arbitrary captured field or source text
                # is reproduced in the public summary or error message.
                group = identifier if identifier in ('sudo', 'kernel', 'wpa_supplicant') else 'other'
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Invalid journal JSON record; contents withheld') from None
            counts[group] += 1
            sizes[group] += len(payload)
            if group == 'sudo' and b'COMMAND=' in payload:
                commands += 1
                inline += b'python3 -B -c ' in payload or b'python3 -c ' in payload
    if not counts:
        raise ValueError('Empty journal capture')
    return dict(sha256=digest.hexdigest(), capture_bytes=total,
                entries=sum(counts.values()), message_bytes=sum(sizes.values()),
                groups={k: dict(entries=counts[k], message_bytes=sizes[k]) for k in sorted(counts)},
                sudo_command_records=commands, sudo_inline_python_commands=inline,
                limits='Retained entries only. Message bytes are uncompressed text, not disk allocation. '
                       'Command continuations are counted in sudo volume, not as additional commands. '
                       'This does not prove why any particular journal file disappeared.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args(sys.argv[1:] or shlex.split(os.environ.get('NEO_COMMAND', '')))
    print(json.dumps(summarize(args.capture), indent=2))


if __name__ == '__main__':
    main()
