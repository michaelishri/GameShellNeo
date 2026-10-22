#!/usr/bin/env python3
"""Inspect or select a system on an already prepared development card; never reboot."""
import argparse
import json
from pathlib import Path

from dev_systems import Card, slot_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot', type=Path, required=True,
                        help='Mounted shared development boot filesystem')
    parser.add_argument('--store', type=Path, required=True,
                        help='Mounted complete system store (not an individual root)')
    command = parser.add_subparsers(dest='command', required=True)
    command.add_parser('status')
    command.add_parser('recovery')
    for name in ('select', 'confirm', 'register'):
        command.add_parser(name).add_argument('system')
    importer = command.add_parser('import-bundle', help='Import a host-prepared version without selecting or rebooting')
    importer.add_argument('system')
    importer.add_argument('--bundle', type=Path, required=True)
    importer.add_argument('--sha256', required=True)
    args = parser.parse_args()
    card = Card(args.boot, args.store)
    if args.command == 'status':
        result = card.status()
    elif args.command == 'recovery':
        result = card.select_recovery()
    elif args.command == 'select':
        result = card.select(args.system)
    elif args.command == 'register':
        result = card.register(args.system)
    elif args.command == 'import-bundle':
        from dev_bundle import unpack_release
        slot_id(args.system)
        if args.system == 'recovery':
            raise ValueError('The fixed recovery identifier is reserved')
        with card.lock():
            if args.system in card.releases:
                raise ValueError('System identifiers are immutable; use a fresh name')
            unpacked = unpack_release(args.bundle, card.store / 'systems' / args.system,
                                      expected_hash=args.sha256,
                                      store_partuuid=card.record['store_partuuid'])
        result = dict(card.register(args.system), imported=unpacked)
    else:
        result = card.confirm(args.system)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
