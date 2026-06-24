"""Build or resume the versioned offline certified map catalog."""

import argparse
import os
import random
import sys
from copy import deepcopy


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from board_generator import BoardGenerator
from catalog_validation import topology_signature, validate_catalog_entry
from hard_board_catalog import HARD_BOARD_BASES
from session_planner import plan_hard_session, plan_normal_session
from map_catalog import (
    decode_map_entry,
    empty_catalog,
    encode_map_entry,
    load_catalog,
    save_catalog,
)
from ricochet_robots_board_data import (
    HORIZONTAL_WALLS,
    TARGETS,
    VERTICAL_WALLS,
    build_board_matrix_from_walls,
)
from solver import RicochetSolver


FAMILIES = (
    'balanced_rooms',
    'offset_pinwheel',
    'axial_gates',
    'central_locks',
)
NORMAL_TARGET_ORDER = (
    'Green_Star',
    'Red_Moon',
    'Red_Planet',
    'Yellow_Planet',
    'Blue_Star',
    'Blue_Moon',
    'Green_Gear',
    'Blue_Gear',
    'Yellow_Star',
    'Yellow_Moon',
    'Wild_Vortex',
    'Red_Gear',
    'Green_Planet',
    'Yellow_Gear',
    'Blue_Planet',
    'Red_Star',
    'Green_Moon',
)
DIAGONAL_REFLECTIONS = {
    '/': {
        'top': 'right',
        'bottom': 'left',
        'left': 'bottom',
        'right': 'top',
    },
    '\\': {
        'top': 'left',
        'bottom': 'right',
        'left': 'top',
        'right': 'bottom',
    },
}
ROBOT_COLORS = ('Red', 'Blue', 'Green', 'Yellow')
MOMENTUM_TARGET_ORDER = (
    'Red_Star',
    'Yellow_Star',
    'Green_Gear',
    'Blue_Gear',
    'Blue_Star',
    'Blue_Moon',
    'Red_Moon',
    'Red_Planet',
    'Green_Moon',
    'Wild_Vortex',
    'Green_Star',
    'Yellow_Planet',
    'Green_Planet',
    'Yellow_Moon',
    'Blue_Planet',
    'Red_Gear',
    'Yellow_Gear',
)


def legacy_hard_seed():
    base = HARD_BOARD_BASES[0]
    color_codes = {
        'R': 'Red',
        'B': 'Blue',
        'G': 'Green',
        'Y': 'Yellow',
        'S': 'Silver',
    }
    direction_codes = {
        't': 'top',
        'b': 'bottom',
        'l': 'left',
        'r': 'right',
    }
    rounds = []
    for target_name, encoded_path in zip(base['target_order'], base['paths']):
        rounds.append({
            'target': target_name,
            'path': [
                [color_codes[token[0]], direction_codes[token[1]]]
                for token in encoded_path.split()
            ],
        })
    return {
        'id': 'hard-certified-00',
        'mode': 'hard',
        'family': 'balanced_rooms',
        'grid_size': 16,
        'h_walls': set(base['h_walls']),
        'v_walls': set(base['v_walls']),
        'diagonal_walls': {},
        'targets': dict(base['targets']),
        'robot_positions': dict(base['robot_positions']),
        'target_order': list(base['target_order']),
        'rounds': rounds,
        'safe_transforms': list(base['safe_transforms']),
        'certification': {
            'method': 'exact_astar_or_bfs',
        },
    }


def exact_normal_seed():
    entry = {
        'id': 'normal-seed-static',
        'mode': 'normal',
        'family': 'normal_seed',
        'grid_size': 16,
        'h_walls': set(HORIZONTAL_WALLS),
        'v_walls': set(VERTICAL_WALLS),
        'diagonal_walls': {},
        'targets': dict(TARGETS),
        'robot_positions': {
            'Blue': (7, 6),
            'Yellow': (6, 8),
            'Green': (8, 9),
            'Red': (9, 7),
        },
        'target_order': list(NORMAL_TARGET_ORDER),
        'rounds': [],
        'safe_transforms': [
            (rotation, mirror)
            for rotation in range(4)
            for mirror in (False, True)
        ],
        'certification': {
            'method': 'exact_astar_or_bfs',
        },
    }
    board = build_board_matrix_from_walls(entry['h_walls'], entry['v_walls'])
    solver = RicochetSolver(board)
    robots = dict(entry['robot_positions'])
    for target_name in NORMAL_TARGET_ORDER:
        target_color = target_name.split('_')[0]
        steps, path = solver.solve(
            robots,
            target_color,
            entry['targets'][target_name],
            max_depth=9,
            max_states=160000,
        )
        if steps < 0:
            raise RuntimeError(f'Normal seed target failed: {target_name}')
        entry['rounds'].append({
            'target': target_name,
            'path': path,
        })
        robots = solver.apply_path(robots, path)
    return validate_catalog_entry(entry, exact=True)


def symmetric_normal_seed():
    seed_entry = exact_normal_seed()
    h_walls = set(seed_entry['h_walls'])
    v_walls = set(seed_entry['v_walls'])
    missing_h = sorted({
        (14 - r, 15 - c)
        for r, c in h_walls
    } - h_walls)
    missing_v = sorted({
        (15 - r, 14 - c)
        for r, c in v_walls
    } - v_walls)

    for wall_type, walls in (('h_walls', missing_h), ('v_walls', missing_v)):
        for wall in walls:
            candidate = deepcopy(seed_entry)
            candidate['h_walls'] = set(h_walls)
            candidate['v_walls'] = set(v_walls)
            candidate[wall_type].add(wall)
            if replay_witness(candidate):
                if wall_type == 'h_walls':
                    h_walls.add(wall)
                else:
                    v_walls.add(wall)

    seed_entry['id'] = 'normal-seed-symmetric'
    seed_entry['family'] = 'symmetric_normal_seed'
    seed_entry['h_walls'] = h_walls
    seed_entry['v_walls'] = v_walls
    seed_entry['certification'] = {
        'method': 'monotonic_additive_exact_witness',
        'parent': 'normal-seed-static',
    }
    return validate_catalog_entry(seed_entry, exact=False)


def add_l_wall(h_walls, v_walls, position, orientation):
    r, c = position
    options = (
        ((r - 1, c), (r, c - 1)),
        ((r - 1, c), (r, c)),
        ((r, c), (r, c - 1)),
        ((r, c), (r, c)),
    )
    h_wall, v_wall = options[orientation]
    if not (0 <= h_wall[0] < 15 and 0 <= h_wall[1] < 16):
        return False
    if not (0 <= v_wall[0] < 16 and 0 <= v_wall[1] < 15):
        return False
    h_walls.add(h_wall)
    v_walls.add(v_wall)
    return True


def rotate_cell(position, rotations):
    r, c = position
    for _ in range(rotations):
        r, c = c, 15 - r
    return r, c


def rotate_orientation(orientation, rotations):
    for _ in range(rotations):
        orientation = (1, 3, 0, 2)[orientation]
    return orientation


def replay_witness(entry):
    board = build_board_matrix_from_walls(
        entry['h_walls'],
        entry['v_walls'],
        grid_size=entry['grid_size'],
    )
    solver = RicochetSolver(board, grid_size=entry['grid_size'])
    robots = dict(entry['robot_positions'])
    for round_data in entry['rounds']:
        try:
            robots = solver.apply_path(robots, round_data['path'])
        except (KeyError, ValueError):
            return False
        target_name = round_data['target']
        target_color = target_name.split('_')[0]
        target_position = entry['targets'][target_name]
        reached = (
            target_position in robots.values()
            if target_color == 'Wild'
            else robots.get(target_color) == target_position
        )
        if not reached:
            return False
        expected_end = round_data.get('end_robots')
        if expected_end and robots != {
            color: tuple(position)
            for color, position in expected_end.items()
        }:
            return False
    return True


def precompute_safe_structures(seed_entry):
    safe_motifs = []
    original_h = set(seed_entry['h_walls'])
    original_v = set(seed_entry['v_walls'])
    for r in range(1, 15):
        for c in range(1, 15):
            for orientation in range(4):
                candidate = deepcopy(seed_entry)
                candidate['h_walls'] = set(candidate['h_walls'])
                candidate['v_walls'] = set(candidate['v_walls'])
                add_l_wall(
                    candidate['h_walls'],
                    candidate['v_walls'],
                    (r, c),
                    orientation,
                )
                if (
                    candidate['h_walls'] == original_h
                    and candidate['v_walls'] == original_v
                ):
                    continue
                if replay_witness(candidate):
                    safe_motifs.append(((r, c), orientation))

    safe_set = set(safe_motifs)
    paired = set()
    for position, orientation in safe_motifs:
        mirrored = (15 - position[0], 15 - position[1])
        mirrored_orientation = 3 - orientation
        if (mirrored, mirrored_orientation) not in safe_set:
            continue
        pair = tuple(sorted((
            (position, orientation),
            (mirrored, mirrored_orientation),
        )))
        paired.add(pair)

    pinwheels = set()
    for position, orientation in safe_motifs:
        orbit = tuple(
            (rotate_cell(position, rotations), rotate_orientation(orientation, rotations))
            for rotations in range(4)
        )
        if all(item in safe_set for item in orbit):
            pinwheels.add(tuple(sorted(set(orbit))))

    def edge_distance(structure):
        return min(
            min(position[0], position[1], 15 - position[0], 15 - position[1])
            for position, _ in structure
        )

    def axis_distance(structure):
        return min(
            min(abs(position[0] - 7.5), abs(position[1] - 7.5))
            for position, _ in structure
        )

    pairs = sorted(paired)
    return {
        'balanced_rooms': [
            item for item in pairs
            if edge_distance(item) >= 3 and axis_distance(item) >= 2.5
        ],
        'offset_pinwheel': [
            item for item in pairs
            if edge_distance(item) >= 2
            and 1.5 < axis_distance(item) <= 3.5
        ],
        'axial_gates': [
            item for item in pairs
            if axis_distance(item) <= 1.5 and edge_distance(item) >= 2
        ],
        'edge_pockets': [
            item for item in pairs
            if edge_distance(item) <= 2
        ],
        'central_locks': [
            item for item in pairs
            if axis_distance(item) <= 0.75
        ],
    }


def curated_hard_specs(safe_structures):
    balanced = safe_structures['balanced_rooms']
    axial = safe_structures['axial_gates']
    return [
        ('balanced_rooms', balanced[1]),
        ('balanced_rooms', balanced[3]),
        ('offset_pinwheel', axial[1]),
        ('offset_pinwheel', axial[4]),
        ('offset_pinwheel', axial[10]),
        ('axial_gates', axial[11]),
        ('axial_gates', axial[12]),
        ('axial_gates', axial[13]),
        ('central_locks', axial[15]),
        ('central_locks', axial[16]),
        ('central_locks', axial[14]),
    ]


def mutate_from_safe_structures(
    seed_entry,
    family,
    rng,
    variant_index,
    safe_structures,
):
    entry = deepcopy(seed_entry)
    entry['family'] = family
    h_walls = set(entry['h_walls'])
    v_walls = set(entry['v_walls'])
    structures = safe_structures[family]
    if not structures:
        return None
    structure_count = rng.randint(1, min(len(structures), max(1, variant_index + 1)))
    for structure in rng.sample(structures, structure_count):
        for position, orientation in structure:
            add_l_wall(h_walls, v_walls, position, orientation)

    entry['h_walls'] = h_walls
    entry['v_walls'] = v_walls
    entry['safe_transforms'] = [
        (rotation, mirror)
        for rotation in range(4)
        for mirror in (False, True)
    ]
    entry['certification'] = {
        'method': 'monotonic_additive_exact_witness',
        'parent': seed_entry['id'],
    }
    if (
        len(h_walls - set(seed_entry['h_walls']))
        + len(v_walls - set(seed_entry['v_walls']))
        < 3
    ):
        return None
    return entry


def structurally_acceptable(entry):
    generator = BoardGenerator()
    board = build_board_matrix_from_walls(
        entry['h_walls'],
        entry['v_walls'],
        grid_size=entry['grid_size'],
    )
    metrics = generator._structural_metrics(
        board,
        set(entry['h_walls']),
        set(entry['v_walls']),
        entry['targets'],
    )
    if entry['mode'] == 'normal':
        return (
            metrics.symmetry_score >= 0.40
            and metrics.max_wall_cluster <= 8
            and len(entry['h_walls']) + len(entry['v_walls']) <= 76
        )
    return (
        metrics.symmetry_score >= 0.30
        and metrics.max_wall_cluster <= 10
        and len(entry['h_walls']) + len(entry['v_walls']) <= 76
    )


def ensure_normal_catalog(catalog, target_normal, seed, path):
    existing_normal = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'normal'
    ]
    if len(existing_normal) >= target_normal:
        return

    normal_seed = symmetric_normal_seed()
    safe_structures = precompute_safe_structures(normal_seed)
    seen_signatures = {
        item.get('features', {}).get('topology_signature')
        or topology_signature(item)
        for item in existing_normal
    }
    seen_trajectories = {
        item.get('features', {}).get('trajectory_signature')
        for item in existing_normal
    }
    # Endpoint-targeting inverse design (same concept as Hard): each Normal map
    # gets a freshly designed in-band chained session => distinct topology AND
    # trajectory, no shared replayed solution.
    boards = endpoint_boards(normal_seed, safe_structures, target_normal, seed, 'normal')
    for idx, (family, h_walls, v_walls) in enumerate(boards):
        if len(existing_normal) >= target_normal:
            break
        map_id = f'normal-certified-{len(existing_normal):02d}'
        try:
            candidate = endpoint_entry(h_walls, v_walls, family, map_id,
                                       seed + idx, 'normal', plan_normal_session)
        except ValueError as error:
            print(f'rejected normal board {idx} ({family}): {error}', flush=True)
            continue
        if candidate is None:
            print(f'no strict session for normal board {idx} ({family})', flush=True)
            continue
        signature = candidate['features']['topology_signature']
        trajectory = candidate['features']['trajectory_signature']
        if signature in seen_signatures or trajectory in seen_trajectories:
            continue
        existing_normal.append(candidate)
        seen_signatures.add(signature)
        seen_trajectories.add(trajectory)
        catalog['maps'].append(encode_map_entry(candidate))
        save_catalog(catalog, path)
        print(
            f'accepted {candidate["id"]}: {family}, '
            f'walls={candidate["features"]["wall_count"]}, '
            f'steps {candidate["features"]["round_min_steps"]}-'
            f'{candidate["features"]["round_max_steps"]}, '
            f'avg {candidate["features"]["round_average_steps"]}, '
            f'traj={trajectory[:8]}',
            flush=True,
        )

    if len(existing_normal) < target_normal:
        raise RuntimeError(
            f'Accepted {len(existing_normal)}/{target_normal} Normal maps.'
        )


def add_endpoint_diagonals(source_entry, target_id, target_mode):
    entry = deepcopy(source_entry)
    entry['id'] = target_id
    entry['mode'] = target_mode
    entry['family'] = f'diagonal_{source_entry["family"]}'
    entry['certification'] = {
        'method': 'exact_bfs_with_required_reflections',
        'parent': source_entry['id'],
    }
    board = build_board_matrix_from_walls(
        entry['h_walls'],
        entry['v_walls'],
        grid_size=entry['grid_size'],
    )
    solver = RicochetSolver(board, grid_size=entry['grid_size'])
    robots = dict(entry['robot_positions'])
    candidates = {}

    for round_index, round_data in enumerate(entry['rounds']):
        for color, direction in round_data['path']:
            start = robots[color]
            occupied = set(robots.values()) - {start}
            end = solver.get_slide_endpoint(
                start[0],
                start[1],
                direction,
                occupied,
                color=color,
            )
            robots[color] = end
            if end in {(7, 7), (7, 8), (8, 7), (8, 8)}:
                continue
            for wall_type, reflections in DIAGONAL_REFLECTIONS.items():
                outgoing = reflections[direction]
                if not board[end[0]][end[1]][outgoing]:
                    continue
                for wall_color in ROBOT_COLORS:
                    if wall_color == color:
                        continue
                    key = (end, wall_type, wall_color)
                    candidates.setdefault(key, set()).add(round_index)

    chosen = []
    covered = set()
    for _ in range(4):
        available = [
            (
                len(rounds - covered),
                key,
                rounds,
            )
            for key, rounds in candidates.items()
            if key[0] not in {item[0][0] for item in chosen}
        ]
        if not available:
            break
        _, key, rounds = max(available, key=lambda item: (item[0], item[1]))
        chosen.append((key, rounds))
        covered.update(rounds)

    entry['diagonal_walls'] = {
        cell: {
            'type': wall_type,
            'color': wall_color,
        }
        for (cell, wall_type, wall_color), _ in chosen
    }
    if len(covered) < 8:
        raise RuntimeError(
            f'{source_entry["id"]} only covers {len(covered)} reflection rounds.'
        )
    return validate_catalog_entry(entry, exact=True)


def ensure_expert_catalog(catalog, target_expert, path):
    existing_expert = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'expert'
    ]
    if len(existing_expert) >= target_expert:
        return
    normal_entries = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'normal'
    ]
    for normal_entry in normal_entries:
        if len(existing_expert) >= target_expert:
            break
        try:
            candidate = add_endpoint_diagonals(
                normal_entry,
                f'expert-certified-{len(existing_expert):02d}',
                'expert',
            )
        except (RuntimeError, ValueError) as error:
            print(f'rejected Expert candidate from {normal_entry["id"]}: {error}')
            continue
        existing_expert.append(candidate)
        catalog['maps'].append(encode_map_entry(candidate))
        save_catalog(catalog, path)
        print(
            f'accepted {candidate["id"]}: '
            f'{sum(item["features"]["diagonal_reflections"] > 0 for item in candidate["rounds"])} '
            'reflection rounds',
            flush=True,
        )
    if len(existing_expert) < target_expert:
        raise RuntimeError(
            f'Accepted {len(existing_expert)}/{target_expert} Expert maps.'
        )


MOMENTUM_MIN_STEPS = 5
MOMENTUM_MAX_STEPS = 13
MOMENTUM_MIN_ROBOTS = 2
MOMENTUM_MAX_DROP = 3
MOMENTUM_TARGET_STEPS = 9
MOMENTUM_TAIL = 5
MOMENTUM_TOPK = 6


def _momentum_round_penalty(steps, moved, coll, prev):
    """Soft cost for a tail round so the planner avoids step craters and keeps
    momentum collisions / multi-robot rounds where the board still allows it."""
    penalty = 0.0
    if prev - steps > MOMENTUM_MAX_DROP:
        penalty += (prev - steps - MOMENTUM_MAX_DROP) * 4
    if steps < MOMENTUM_MIN_STEPS:
        penalty += (MOMENTUM_MIN_STEPS - steps) * 3
    if moved < MOMENTUM_MIN_ROBOTS:
        penalty += 5
    if coll < 1:
        penalty += 4
    penalty += abs(steps - MOMENTUM_TARGET_STEPS) * 0.3
    return penalty


def plan_momentum_session(board, robots, targets, grid_size, seed):
    """Plan a smooth 17-round momentum session.

    A greedy phase keeps every early round inside the strict floor (>= 5 steps,
    >= 2 robots, a momentum collision, no drop beyond 3). The final rounds are
    completed by a penalised backtracking search that maximises the minimum
    step count instead of cratering to trivial 2-3 step targets, because a
    fully strict 17-round momentum session does not exist for a fixed 4-robot
    board.
    """
    solver = RicochetSolver(board, grid_size=grid_size, movement_mode='momentum')
    cache = {}

    def solve_round(state, target_name):
        key = (tuple(sorted(state.items())), target_name)
        if key in cache:
            return cache[key]
        color = target_name.split('_')[0]
        steps, path = solver.solve(
            state,
            color,
            targets[target_name],
            max_depth=MOMENTUM_MAX_STEPS,
            max_states=220000,
        )
        if steps < 0:
            cache[key] = None
            return None
        feat = solver.analyze_path(state, path, target_color=color)
        result = (
            steps,
            path,
            feat['moved_robot_count'],
            feat['momentum_collisions'],
            feat['end_robots'],
        )
        cache[key] = result
        return result

    def relaxed_rank(state, target_name):
        distances = solver._get_relaxed_distances(solver._encode(*targets[target_name]))
        color = target_name.split('_')[0]
        if color == 'Wild':
            values = [
                value for value in (
                    distances[solver._encode(*position)]
                    for position in state.values()
                )
                if value >= 0
            ]
            return min(values) if values else 99
        value = distances[solver._encode(*state[color])]
        return value if value >= 0 else 99

    def tail_search(state, remaining, prev):
        best = [None]

        def recurse(current, names, prior, acc, score):
            if best[0] is not None and score >= best[0][0]:
                return
            if not names:
                best[0] = (score, acc)
                return
            options = []
            for target_name in names:
                result = solve_round(current, target_name)
                if result is None:
                    continue
                steps, path, moved, coll, end = result
                options.append((
                    _momentum_round_penalty(steps, moved, coll, prior),
                    target_name,
                    steps,
                    path,
                    end,
                ))
            options.sort(key=lambda item: item[0])
            for penalty, target_name, steps, path, end in options:
                recurse(
                    end,
                    [name for name in names if name != target_name],
                    steps,
                    acc + [(target_name, path)],
                    score + penalty,
                )

        recurse(state, remaining, prev, [], 0.0)
        return best[0][1] if best[0] else None

    rng = random.Random(seed)
    state = dict(robots)
    remaining = list(targets)
    rounds = []
    prev = MOMENTUM_TARGET_STEPS
    while len(remaining) > MOMENTUM_TAIL:
        ranked = sorted(
            remaining,
            key=lambda name: abs(relaxed_rank(state, name) - MOMENTUM_TARGET_STEPS) + rng.random(),
        )
        best = None
        for target_name in ranked[:MOMENTUM_TOPK]:
            result = solve_round(state, target_name)
            if result is None:
                continue
            steps, path, moved, coll, end = result
            if not (
                MOMENTUM_MIN_STEPS <= steps <= MOMENTUM_MAX_STEPS
                and moved >= MOMENTUM_MIN_ROBOTS
                and coll >= 1
                and prev - steps <= MOMENTUM_MAX_DROP
            ):
                continue
            score = (
                abs(steps - MOMENTUM_TARGET_STEPS)
                + abs(moved - 3) * 2
                + max(0, abs(steps - prev) - 1) * 2
            )
            candidate = (score, target_name, steps, path, end)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            break
        _, target_name, steps, path, end = best
        rounds.append({'target': target_name, 'path': path})
        state = end
        remaining.remove(target_name)
        prev = steps

    tail = tail_search(state, remaining, prev)
    if tail is None:
        return None
    for target_name, path in tail:
        rounds.append({'target': target_name, 'path': path})
    return rounds


def ensure_momentum_catalog(catalog, target_momentum, path):
    existing = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'v3_momentum'
    ]
    if len(existing) >= target_momentum:
        return
    # Momentum keeps its own fixed-target Normal base (the layout its planner was
    # tuned for). It is intentionally decoupled from the endpoint-designed Normal
    # catalog -- the momentum mechanic needs collisions on a known layout, and
    # planning momentum on arbitrary designed target cells is unstable.
    base_seed = symmetric_normal_seed()
    board = build_board_matrix_from_walls(
        base_seed['h_walls'],
        base_seed['v_walls'],
        grid_size=base_seed['grid_size'],
    )
    accepted_entry = None
    # A single greedy session can still craft a weak tail, so scan seeds and
    # accept the first planned session that passes the full contract (>= 4 steps
    # every round, smooth <= 3-step drops, >= 15 collision rounds) instead of the
    # first session that merely reaches 17 rounds.
    for seed in range(8):
        rounds = plan_momentum_session(
            board,
            dict(base_seed['robot_positions']),
            base_seed['targets'],
            base_seed['grid_size'],
            seed,
        )
        if not rounds or len(rounds) != 17:
            continue
        entry = deepcopy(base_seed)
        entry['id'] = f'momentum-certified-{len(existing):02d}'
        entry['mode'] = 'v3_momentum'
        entry['family'] = f'momentum_{base_seed["family"]}'
        entry['target_order'] = [item['target'] for item in rounds]
        entry['rounds'] = rounds
        entry['certification'] = {
            'method': 'exact_momentum_bfs_planned_tail',
            'parent': base_seed['id'],
        }
        try:
            entry = validate_catalog_entry(entry, exact=True)
        except ValueError as error:
            print(f'rejected Momentum seed {seed}: {error}', flush=True)
            continue
        accepted_entry = entry
        break

    if accepted_entry is None:
        raise RuntimeError(
            f'Accepted 0/{target_momentum} Momentum maps.'
        )
    existing.append(accepted_entry)
    catalog['maps'].append(encode_map_entry(accepted_entry))
    save_catalog(catalog, path)
    steps = [item['steps'] for item in accepted_entry['rounds']]
    mechanic_rounds = sum(
        item['features']['momentum_collisions'] > 0
        for item in accepted_entry['rounds']
    )
    print(
        f'accepted {accepted_entry["id"]}: {mechanic_rounds}/17 collision rounds, '
        f'min {min(steps)} avg {round(sum(steps) / 17, 1)} steps {steps}',
        flush=True,
    )


def transform_entry_geometry(entry, rotations, mirror):
    """Apply a fixed rotation/mirror to a decoded catalog entry.

    Produces a geometrically distinct entry (different wall, target and
    trajectory signatures) that is still backed by the same proven exact
    witness, so it re-certifies without an expensive fresh search. This is how
    Super Expert is derived as an independent entry from a dense Hard base
    instead of being a byte-identical clone.
    """
    generator = BoardGenerator()
    moved = deepcopy(entry)
    h_walls, v_walls = generator._transform_board_walls(
        set(entry['h_walls']),
        set(entry['v_walls']),
        rotations,
        mirror,
    )
    moved['h_walls'] = set(h_walls)
    moved['v_walls'] = set(v_walls)
    moved['targets'] = {
        name: generator._transform_cell(position, rotations, mirror)
        for name, position in entry['targets'].items()
    }
    moved['robot_positions'] = {
        color: generator._transform_cell(position, rotations, mirror)
        for color, position in entry['robot_positions'].items()
    }
    moved['diagonal_walls'] = {
        generator._transform_cell(cell, rotations, mirror): {
            'type': generator._transform_diagonal_type(value['type'], rotations, mirror),
            'color': value['color'],
        }
        for cell, value in entry.get('diagonal_walls', {}).items()
    }
    moved['rounds'] = []
    for round_data in entry['rounds']:
        moved['rounds'].append({
            'target': round_data['target'],
            'path': [
                [color, generator._transform_direction(direction, rotations, mirror)]
                for color, direction in round_data['path']
            ],
        })
    return moved


def ensure_super_expert_catalog(catalog, target_super_expert, path):
    existing = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'super_expert'
    ]
    if len(existing) >= target_super_expert:
        return
    hard_entries = [
        decode_map_entry(item)
        for item in catalog['maps']
        if item['mode'] == 'hard'
    ]
    hard_entries.sort(
        key=lambda item: item.get('features', {}).get('wall_count', 0),
        reverse=True,
    )
    hard_signatures = {
        item.get('features', {}).get('topology_signature') or topology_signature(item)
        for item in hard_entries
    }
    hard_trajectories = {
        item.get('features', {}).get('trajectory_signature')
        for item in hard_entries
    }
    # Rotations/mirrors applied to the dense base so the stored Super Expert
    # never shares a topology or trajectory signature with any Hard map.
    transforms = [(1, False), (1, True), (2, True), (3, False), (3, True), (2, False)]
    for hard_entry in hard_entries:
        if len(existing) >= target_super_expert:
            break
        for rotations, mirror in transforms:
            if len(existing) >= target_super_expert:
                break
            moved = transform_entry_geometry(hard_entry, rotations, mirror)
            moved['id'] = f'super-expert-certified-{len(existing):02d}'
            moved['mode'] = 'super_expert'
            moved['family'] = f'dense_{hard_entry["family"]}'
            moved['certification'] = {
                'method': 'transformed_exact_witness_dense_topology',
                'parent': hard_entry['id'],
                'geometry_rotation': rotations * 90,
                'geometry_mirrored': mirror,
            }
            try:
                candidate = validate_catalog_entry(moved, exact=False)
            except ValueError as error:
                print(f'rejected Super Expert transform: {error}', flush=True)
                continue
            signature = candidate['features']['topology_signature']
            trajectory = candidate['features']['trajectory_signature']
            if signature in hard_signatures or trajectory in hard_trajectories:
                continue
            existing.append(candidate)
            hard_signatures.add(signature)
            hard_trajectories.add(trajectory)
            catalog['maps'].append(encode_map_entry(candidate))
            save_catalog(catalog, path)
            print(
                f'accepted {candidate["id"]}: '
                f'{candidate["features"]["wall_count"]} walls, '
                f'{candidate["features"]["round_average_steps"]} average steps, '
                f'rot{rotations * 90}{"+mirror" if mirror else ""}',
                flush=True,
            )
    if len(existing) < target_super_expert:
        raise RuntimeError(
            f'Accepted {len(existing)}/{target_super_expert} Super Expert maps.'
        )


def endpoint_boards(seed_entry, safe_structures, count, seed, mode):
    """Yield (family, h_walls, v_walls) distinct wall boards for endpoint design.

    Endpoint design does not replay a seed solution, so walls need only be
    distinct and structurally acceptable for `mode` (the old "safe vs the seed
    solve" constraint no longer applies). Curated structures first, then
    mutations."""
    boards = []
    seen = set()

    def consider(family, h_walls, v_walls):
        key = (frozenset(h_walls), frozenset(v_walls))
        if key in seen:
            return
        probe = {
            'mode': mode,
            'grid_size': 16,
            'h_walls': set(h_walls),
            'v_walls': set(v_walls),
            'targets': seed_entry['targets'],
        }
        if not structurally_acceptable(probe):
            return
        seen.add(key)
        boards.append((family, set(h_walls), set(v_walls)))

    # bare seed board is a valid baseline for endpoint design
    consider(seed_entry.get('family', 'seed'),
             set(seed_entry['h_walls']), set(seed_entry['v_walls']))

    # curated structures are tuned for the Hard seed's safe_structures only
    if mode == 'hard':
        try:
            curated = curated_hard_specs(safe_structures)
        except IndexError:
            curated = []
        for family, structure in curated:
            h_walls = set(seed_entry['h_walls'])
            v_walls = set(seed_entry['v_walls'])
            for position, orientation in structure:
                add_l_wall(h_walls, v_walls, position, orientation)
            consider(family, h_walls, v_walls)

    attempts = 0
    families = [family for family in FAMILIES if safe_structures.get(family)]
    while len(boards) < count * 3 and attempts < 4000 and families:
        family = families[attempts % len(families)]
        candidate = mutate_from_safe_structures(
            seed_entry, family, random.Random(seed + attempts),
            attempts % 6, safe_structures,
        )
        attempts += 1
        if candidate is not None:
            consider(family, candidate['h_walls'], candidate['v_walls'])
    return boards


def endpoint_entry(h_walls, v_walls, family, map_id, seed, mode, planner_fn):
    """Endpoint-design a strict 17-round chained session on a fixed board for
    `mode` and return the exactly-certified catalog entry (or None)."""
    plan = planner_fn(set(h_walls), set(v_walls), grid_size=16,
                      seed=seed, start_attempts=30)
    if plan is None:
        return None
    entry = {
        'id': map_id,
        'mode': mode,
        'family': family,
        'grid_size': 16,
        'h_walls': set(h_walls),
        'v_walls': set(v_walls),
        'diagonal_walls': {},
        'targets': {name: tuple(cell) for name, cell in plan['targets'].items()},
        'robot_positions': {color: tuple(pos)
                            for color, pos in plan['robot_positions'].items()},
        'target_order': list(plan['target_order']),
        'rounds': plan['rounds'],
        'safe_transforms': [(0, False), (0, True)],
        'certification': {'method': 'endpoint_design_exact_astar'},
    }
    return validate_catalog_entry(entry, exact=True)


def build_catalog(
    path,
    target_hard,
    target_normal,
    target_expert,
    target_momentum,
    target_super_expert,
    seed,
    exact,
    max_attempts,
):
    catalog = load_catalog(path) if os.path.exists(path) else empty_catalog()
    existing = [decode_map_entry(item) for item in catalog['maps']]
    hard_entries = [item for item in existing if item['mode'] == 'hard']
    seen_signatures = {
        item.get('features', {}).get('topology_signature')
        or topology_signature(item)
        for item in hard_entries
    }

    seed_entry = validate_catalog_entry(legacy_hard_seed(), exact=True)
    safe_structures = precompute_safe_structures(seed_entry)
    for family, structures in safe_structures.items():
        print(f'{family}: {len(structures)} safe structures', flush=True)

    seen_trajectories = {
        item.get('features', {}).get('trajectory_signature')
        for item in hard_entries
    }
    if len(hard_entries) < target_hard:
        boards = endpoint_boards(seed_entry, safe_structures, target_hard, seed, 'hard')
        for idx, (family, h_walls, v_walls) in enumerate(boards):
            if len(hard_entries) >= target_hard:
                break
            map_id = f'hard-certified-{len(hard_entries):02d}'
            try:
                entry = endpoint_entry(h_walls, v_walls, family, map_id,
                                       seed + idx, 'hard', plan_hard_session)
            except ValueError as error:
                print(f'rejected board {idx} ({family}): {error}', flush=True)
                continue
            if entry is None:
                print(f'no strict session for board {idx} ({family})', flush=True)
                continue
            signature = entry['features']['topology_signature']
            trajectory = entry['features']['trajectory_signature']
            if signature in seen_signatures or trajectory in seen_trajectories:
                continue
            hard_entries.append(entry)
            seen_signatures.add(signature)
            seen_trajectories.add(trajectory)
            catalog['maps'].append(encode_map_entry(entry))
            catalog['search_state']['accepted'] = len(hard_entries)
            save_catalog(catalog, path)
            print(
                f'accepted {map_id}: {family}, '
                f'walls={entry["features"]["wall_count"]}, '
                f'steps {entry["features"]["round_min_steps"]}-'
                f'{entry["features"]["round_max_steps"]}, '
                f'avg {entry["features"]["round_average_steps"]}, '
                f'traj={trajectory[:8]}',
                flush=True,
            )

    if len(hard_entries) < target_hard:
        raise RuntimeError(
            f'Accepted {len(hard_entries)}/{target_hard} Hard maps. Re-run to resume.'
        )
    ensure_normal_catalog(catalog, target_normal, seed + 1000000, path)
    ensure_expert_catalog(catalog, target_expert, path)
    ensure_momentum_catalog(catalog, target_momentum, path)
    ensure_super_expert_catalog(catalog, target_super_expert, path)
    for encoded_entry in catalog['maps']:
        if encoded_entry['mode'] in ('hard', 'super_expert'):
            encoded_entry['safe_transforms'] = [[0, False], [0, True]]
    save_catalog(catalog, path)
    return catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--output',
        default=os.path.join(ROOT_DIR, 'assets', 'map_catalog_v2.json'),
    )
    parser.add_argument('--target-hard', type=int, default=12)
    parser.add_argument('--target-normal', type=int, default=3)
    parser.add_argument('--target-expert', type=int, default=1)
    parser.add_argument('--target-momentum', type=int, default=1)
    parser.add_argument('--target-super-expert', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20260614)
    parser.add_argument('--max-attempts', type=int, default=5000)
    parser.add_argument(
        '--exact',
        action='store_true',
        help='Re-run exact A*/BFS for every derived map instead of using the additive proof.',
    )
    args = parser.parse_args()
    catalog = build_catalog(
        os.path.abspath(args.output),
        max(1, args.target_hard),
        max(1, args.target_normal),
        max(1, args.target_expert),
        max(1, args.target_momentum),
        max(1, args.target_super_expert),
        args.seed,
        args.exact,
        max(1, args.max_attempts),
    )
    hard_count = sum(item['mode'] == 'hard' for item in catalog['maps'])
    normal_count = sum(item['mode'] == 'normal' for item in catalog['maps'])
    expert_count = sum(item['mode'] == 'expert' for item in catalog['maps'])
    momentum_count = sum(item['mode'] == 'v3_momentum' for item in catalog['maps'])
    super_count = sum(item['mode'] == 'super_expert' for item in catalog['maps'])
    print(
        f'catalog ready: {normal_count} Normal / {hard_count} Hard / '
        f'{expert_count} Expert / {momentum_count} Momentum / '
        f'{super_count} Super Expert maps '
        f'-> {args.output}'
    )


if __name__ == '__main__':
    main()
