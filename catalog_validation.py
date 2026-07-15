"""Shared exact and witness-based validation for offline catalog maps."""

import hashlib
import json
import statistics

from board_generator import BoardGenerator
from mode_contracts import get_mode_contract, session_meets_contract
from ricochet_robots_board_data import build_board_matrix_from_walls
from solver import RicochetSolver
from wall_layout import wall_layout_summary


def validate_catalog_entry(entry, exact=False):
    mode = entry['mode']
    if mode == 'chaos':
        layout_summary = wall_layout_summary(entry['h_walls'], entry['v_walls'])
        if layout_summary['complex_wall_component_count']:
            raise ValueError(
                f'{entry["id"]}: Chaos wall layout contains '
                f'{layout_summary["complex_wall_component_count"]} '
                'complex components.'
            )
    contract = get_mode_contract(mode)
    board = build_board_matrix_from_walls(
        entry['h_walls'],
        entry['v_walls'],
        grid_size=entry.get('grid_size', 16),
    )
    if mode == 'v3_momentum':
        movement_mode = 'momentum'
    elif mode == 'chaos':
        movement_mode = 'chaos'
    else:
        movement_mode = 'classic'
    solver = RicochetSolver(
        board,
        grid_size=entry.get('grid_size', 16),
        diagonal_walls=entry.get('diagonal_walls', {}),
        movement_mode=movement_mode,
        portals=entry.get('portals', {}),
        sand_cells=entry.get('sand_cells', ()),
    )
    current_robots = {
        color: tuple(position)
        for color, position in entry['robot_positions'].items()
    }
    validated_rounds = []

    for round_data in entry['rounds']:
        target_name = round_data['target']
        target_color = target_name.split('_')[0]
        target_position = tuple(entry['targets'][target_name])
        path = [tuple(move) for move in round_data['path']]
        path_features = solver.analyze_path(
            current_robots,
            path,
            target_color=target_color,
        )
        end_robots = path_features.pop('end_robots')
        moved_robots = path_features.pop('moved_robots')
        moved_robot_count = path_features.pop('moved_robot_count')
        reached = (
            target_position in end_robots.values()
            if target_color == 'Wild'
            else end_robots.get(target_color) == target_position
        )
        if not reached:
            raise ValueError(
                f'{entry["id"]}: witness path misses target {target_name}.'
            )

        states_expanded = round_data.get('states_expanded', 0)
        if exact:
            exact_steps, _ = solver.solve(
                current_robots,
                target_color,
                target_position,
                max_depth=contract.get('max_steps'),
                max_states=entry.get('certification_max_states', 500000),
            )
            states_expanded = solver.last_stats.get('states_expanded', 0)
            if exact_steps != len(path):
                raise ValueError(
                    f'{entry["id"]}: {target_name} witness has {len(path)} steps, '
                    f'exact solver returned {exact_steps}.'
                )

        validated_rounds.append({
            'target': target_name,
            'steps': len(path),
            'path': path,
            'moved_robots': moved_robots,
            'moved_robot_count': moved_robot_count,
            'end_robots': end_robots,
            'states_expanded': states_expanded,
            'features': path_features,
        })
        current_robots = end_robots

    if not session_meets_contract(validated_rounds, contract):
        raise ValueError(f'{entry["id"]}: round chain violates the {mode} contract.')

    entry['rounds'] = validated_rounds
    entry['target_order'] = [item['target'] for item in validated_rounds]
    entry['features'] = describe_entry(entry)
    entry['certified'] = True
    entry['certification'] = {
        'method': 'exact_astar_or_bfs' if exact else entry.get(
            'certification',
            {},
        ).get('method', 'replayed_exact_witness'),
        'rounds': len(validated_rounds),
        'contract': mode,
    }
    return entry


def describe_entry(entry):
    generator = BoardGenerator()
    board = build_board_matrix_from_walls(
        entry['h_walls'],
        entry['v_walls'],
        grid_size=entry.get('grid_size', 16),
    )
    structural = generator._structural_metrics(
        board,
        set(entry['h_walls']),
        set(entry['v_walls']),
        entry['targets'],
    )
    steps = [item['steps'] for item in entry['rounds']]
    expanded = [item.get('states_expanded', 0) for item in entry['rounds']]
    robot_switches = [
        item.get('features', {}).get('robot_switches', 0)
        for item in entry['rounds']
    ]
    support_moves = [
        item.get('features', {}).get('support_moves', 0)
        for item in entry['rounds']
    ]
    max_drop = max(
        (
            previous - current
            for previous, current in zip(steps, steps[1:])
        ),
        default=0,
    )
    features = {
        'wall_count': len(entry['h_walls']) + len(entry['v_walls']),
        'wall_density': round(
            (len(entry['h_walls']) + len(entry['v_walls']))
            / (2 * entry.get('grid_size', 16) * (entry.get('grid_size', 16) - 1)),
            4,
        ),
        'symmetry_score': round(structural.symmetry_score, 3),
        'max_wall_cluster': structural.max_wall_cluster,
        'wall_quadrant_balance': structural.wall_quadrant_balance,
        'target_quadrant_balance': structural.target_quadrant_balance,
        'min_target_spacing': structural.min_target_spacing,
        'round_min_steps': min(steps),
        'round_max_steps': max(steps),
        'round_average_steps': round(statistics.mean(steps), 3),
        'round_step_range': max(steps) - min(steps),
        'max_round_step_drop': max_drop,
        'round_min_moved_robots': min(
            item['moved_robot_count']
            for item in entry['rounds']
        ),
        'average_robot_switches': round(statistics.mean(robot_switches), 3),
        'average_support_moves': round(statistics.mean(support_moves), 3),
        'average_states_expanded': round(statistics.mean(expanded), 3),
        'trajectory_signature': trajectory_signature(entry['rounds']),
        'topology_signature': topology_signature(entry),
    }
    features.update(wall_layout_summary(entry['h_walls'], entry['v_walls']))
    return features


def topology_signature(entry):
    payload = {
        'grid_size': entry.get('grid_size', 16),
        'h': sorted(tuple(item) for item in entry['h_walls']),
        'v': sorted(tuple(item) for item in entry['v_walls']),
        'd': sorted(
            (tuple(cell), value['type'], value['color'])
            for cell, value in entry.get('diagonal_walls', {}).items()
        ),
    }
    # chaos-only extras; omitted when empty so legacy signatures stay stable
    if entry.get('portals'):
        payload['p'] = sorted(
            (tuple(cell), value['color'], tuple(value['exit']))
            for cell, value in entry['portals'].items()
        )
    if entry.get('sand_cells'):
        payload['s'] = sorted(tuple(cell) for cell in entry['sand_cells'])
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]


def trajectory_signature(rounds):
    payload = [
        [
            f'{color[0]}{direction[0]}'
            for color, direction in round_data['path']
        ]
        for round_data in rounds
    ]
    encoded = json.dumps(payload, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]
