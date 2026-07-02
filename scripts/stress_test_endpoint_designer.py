"""Generality stress test for the endpoint-targeting inverse designer.

Runs the session planner across multiple boards (including random mutated
boards it was never tuned on) and multiple difficulty bands (including bands
no shipped mode uses), then the momentum endpoint planner across boards other
than the shipped one. Every OK line is a full 17-round chained session that
passed the planner's built-in exact re-solve verification.

Usage:  python scripts/stress_test_endpoint_designer.py [--quick]
"""

import argparse
import os
import random
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from hard_board_catalog import HARD_BOARD_BASES
from ricochet_robots_board_data import build_board_matrix_from_walls
from session_planner import plan_session
from build_map_catalog import (
    add_l_wall,
    plan_momentum_endpoint_session,
    structurally_acceptable,
    symmetric_normal_seed,
)

CENTER = {(7, 7), (7, 8), (8, 7), (8, 8)}

BANDS = (
    ('normal(5-9,r2)', 5, 9, 2),
    ('hard(9-13,r3)', 9, 13, 3),
    ('custom(4-7,r2)', 4, 7, 2),
    ('custom(7-11,r3)', 7, 11, 3),
    ('custom(10-14,r3)', 10, 14, 3),
    ('extreme(8-12,r4)', 8, 12, 4),
)


def random_board(rng, base_h, base_v, probe_targets, drop=6, add=6):
    """Perturb a base board into an out-of-distribution but structurally
    acceptable wall layout."""
    for _ in range(60):
        h = set(base_h)
        v = set(base_v)
        for wall in rng.sample(sorted(h), min(drop, len(h))):
            h.discard(wall)
        for wall in rng.sample(sorted(v), min(drop, len(v))):
            v.discard(wall)
        for _ in range(add):
            position = (rng.randrange(2, 14), rng.randrange(2, 14))
            if position in CENTER:
                continue
            add_l_wall(h, v, position, rng.randrange(4))
        probe = {
            'mode': 'hard',
            'grid_size': 16,
            'h_walls': set(h),
            'v_walls': set(v),
            'targets': dict(probe_targets),
        }
        if structurally_acceptable(probe):
            return h, v
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true',
                        help='2 boards x 3 bands, skip momentum')
    args = parser.parse_args()

    base = HARD_BOARD_BASES[0]
    boards = [('hard-base', set(base['h_walls']), set(base['v_walls']))]
    seed_entry = symmetric_normal_seed()
    boards.append((
        'normal-seed-sym',
        set(seed_entry['h_walls']),
        set(seed_entry['v_walls']),
    ))
    rng = random.Random(99)
    for index in range(2):
        h, v = random_board(rng, base['h_walls'], base['v_walls'], base['targets'])
        if h:
            boards.append((f'random-mutant-{index}', h, v))

    bands = BANDS[:3] if args.quick else BANDS
    if args.quick:
        boards = boards[:2]

    ok = total = 0
    for board_name, h, v in boards:
        for label, lo, hi, min_robots in bands:
            started = time.perf_counter()
            plan = plan_session(h, v, lo, hi, min_robots,
                                seed=7, start_attempts=30, spread=True)
            elapsed = time.perf_counter() - started
            total += 1
            if plan:
                ok += 1
                steps = plan['session_stats']['steps']
                print(f'{board_name} {label}: OK {elapsed:.0f}s '
                      f'steps {min(steps)}-{max(steps)} '
                      f'avg_robots {plan["session_stats"]["avg_robots"]}',
                      flush=True)
            else:
                print(f'{board_name} {label}: FAIL {elapsed:.0f}s', flush=True)
    print(f'CLASSIC GENERALITY: {ok}/{total}', flush=True)

    if args.quick:
        return

    momentum_ok = momentum_total = 0
    cells = [(r, c) for r in range(16) for c in range(16)
             if (r, c) not in CENTER]
    for board_name, h, v in boards[:3]:
        board = build_board_matrix_from_walls(h, v)
        for seed in (1, 2):
            start_rng = random.Random(seed)
            start = dict(zip(('Red', 'Blue', 'Green', 'Yellow'),
                             start_rng.sample(cells, 4)))
            started = time.perf_counter()
            plan = plan_momentum_endpoint_session(board, start, start_rng,
                                                  spread=True)
            elapsed = time.perf_counter() - started
            momentum_total += 1
            if plan:
                momentum_ok += 1
            status = 'OK' if plan else 'FAIL'
            print(f'momentum {board_name} start{seed}: {status} {elapsed:.0f}s',
                  flush=True)
    print(f'MOMENTUM GENERALITY: {momentum_ok}/{momentum_total}', flush=True)


if __name__ == '__main__':
    main()
