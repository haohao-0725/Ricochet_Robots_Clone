"""Versioned offline map catalog loading and serialization helpers."""

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone

from mode_contracts import MODE_CONTRACTS


CATALOG_SCHEMA_VERSION = 2
DEFAULT_CATALOG_RELATIVE_PATH = os.path.join('assets', 'map_catalog_v2.json')


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)


def empty_catalog():
    return {
        'schema_version': CATALOG_SCHEMA_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'generator_version': 'structured_qd_catalog_v2',
        'contracts': deepcopy(MODE_CONTRACTS),
        'maps': [],
        'search_state': {
            'next_seed': 0,
            'attempts': 0,
            'accepted': 0,
        },
    }


def load_catalog(path=None):
    catalog_path = path or resource_path(DEFAULT_CATALOG_RELATIVE_PATH)
    if not os.path.exists(catalog_path):
        return empty_catalog()
    with open(catalog_path, 'r', encoding='utf-8') as handle:
        catalog = json.load(handle)
    validate_catalog_shape(catalog)
    return catalog


def save_catalog(catalog, path):
    validate_catalog_shape(catalog)
    catalog['generated_at'] = datetime.now(timezone.utc).isoformat()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temporary_path = f'{path}.tmp'
    with open(temporary_path, 'w', encoding='utf-8') as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write('\n')
    os.replace(temporary_path, path)


def validate_catalog_shape(catalog):
    if catalog.get('schema_version') != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f'Unsupported map catalog schema: {catalog.get("schema_version")}'
        )
    if not isinstance(catalog.get('maps'), list):
        raise ValueError('Catalog maps must be a list.')
    seen_ids = set()
    for entry in catalog['maps']:
        map_id = entry.get('id')
        if not map_id or map_id in seen_ids:
            raise ValueError(f'Invalid or duplicate catalog map id: {map_id!r}')
        seen_ids.add(map_id)
        if entry.get('mode') not in MODE_CONTRACTS:
            raise ValueError(f'Unknown catalog mode: {entry.get("mode")!r}')
        for key in ('h_walls', 'v_walls', 'targets', 'robot_positions', 'rounds'):
            if key not in entry:
                raise ValueError(f'Catalog map {map_id} is missing {key}.')


def catalog_maps(mode, path=None):
    return [
        decode_map_entry(entry)
        for entry in load_catalog(path)['maps']
        if entry.get('mode') == mode and entry.get('certified', False)
    ]


def decode_map_entry(entry):
    decoded = deepcopy(entry)
    decoded['h_walls'] = [tuple(item) for item in decoded['h_walls']]
    decoded['v_walls'] = [tuple(item) for item in decoded['v_walls']]
    decoded['targets'] = {
        name: tuple(position)
        for name, position in decoded['targets'].items()
    }
    decoded['robot_positions'] = {
        color: tuple(position)
        for color, position in decoded['robot_positions'].items()
    }
    diagonal_walls = {}
    for item in decoded.get('diagonal_walls', []):
        diagonal_walls[tuple(item['cell'])] = {
            'type': item['type'],
            'color': item['color'],
        }
    decoded['diagonal_walls'] = diagonal_walls
    for round_data in decoded['rounds']:
        round_data['path'] = [tuple(move) for move in round_data['path']]
        round_data['end_robots'] = {
            color: tuple(position)
            for color, position in round_data.get('end_robots', {}).items()
        }
    decoded['target_order'] = list(decoded.get(
        'target_order',
        [item['target'] for item in decoded['rounds']],
    ))
    decoded['safe_transforms'] = [
        (int(item[0]), bool(item[1]))
        for item in decoded.get('safe_transforms', [[0, False]])
    ]
    return decoded


def encode_map_entry(entry):
    encoded = deepcopy(entry)
    encoded['h_walls'] = [list(item) for item in sorted(entry['h_walls'])]
    encoded['v_walls'] = [list(item) for item in sorted(entry['v_walls'])]
    encoded['targets'] = {
        name: list(position)
        for name, position in entry['targets'].items()
    }
    encoded['robot_positions'] = {
        color: list(position)
        for color, position in entry['robot_positions'].items()
    }
    encoded['diagonal_walls'] = [
        {
            'cell': list(cell),
            'type': value['type'],
            'color': value['color'],
        }
        for cell, value in sorted(entry.get('diagonal_walls', {}).items())
    ]
    encoded['safe_transforms'] = [
        [int(rotations), bool(mirror)]
        for rotations, mirror in entry.get('safe_transforms', [(0, False)])
    ]
    for round_data in encoded['rounds']:
        round_data['path'] = [list(move) for move in round_data['path']]
        round_data['end_robots'] = {
            color: list(position)
            for color, position in round_data.get('end_robots', {}).items()
        }
    return encoded
