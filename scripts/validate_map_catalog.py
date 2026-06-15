"""Validate every certified map in map_catalog_v2.json."""

import argparse
import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from catalog_validation import validate_catalog_entry
from map_catalog import decode_map_entry, load_catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--catalog',
        default=os.path.join(ROOT_DIR, 'assets', 'map_catalog_v2.json'),
    )
    parser.add_argument('--exact', action='store_true')
    parser.add_argument('--mode', choices=(
        'normal',
        'hard',
        'expert',
        'v3_momentum',
        'super_expert',
    ))
    args = parser.parse_args()

    catalog = load_catalog(os.path.abspath(args.catalog))
    entries = [
        decode_map_entry(item)
        for item in catalog['maps']
        if args.mode is None or item['mode'] == args.mode
    ]
    for index, entry in enumerate(entries, start=1):
        validate_catalog_entry(entry, exact=args.exact)
        print(
            f'[{index}/{len(entries)}] {entry["id"]}: '
            f'{len(entry["rounds"])} rounds, {entry["family"]}'
        )
    print(f'validated {len(entries)} catalog maps')


if __name__ == '__main__':
    main()
