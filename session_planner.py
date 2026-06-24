"""Endpoint-targeting inverse designer for diverse, chained difficulty maps.

On a fixed wall board with 4 robots that CHAIN between rounds (no reset), each
round's target is PLACED at an in-band optimal endpoint instead of being a fixed
input. One labeled BFS to depth `hi` per round yields the exact optimal-to-every
-cell for every colour at once; we pick an in-band ([lo,hi] step, >=min_robots)
endpoint, place a target there and advance. 17 rounds => a full session where
every round is a certified in-band chained optimal, by construction -- no wall
forcing, no reset.

The band is a parameter, so the SAME designer drives every classic mode:
  Normal -> band [5,9], >=2 robots;  Hard -> band [9,13], >=3 robots.
Difficulty is met with NO contract relaxation: far endpoints make the optimal
naturally bounce extra robots. Diversity comes from the base board, the robot
start and the search choices, giving distinct target layouts AND trajectories.
"""

import random
from collections import deque

from ricochet_robots_board_data import build_board_matrix_from_walls
from solver import RicochetSolver

GRID = 16
MAX_DROP = 3
MIN_SPACING = 2
BASE_COLORS = ('Red', 'Blue', 'Green', 'Yellow')
SYMBOLS = ('Moon', 'Star', 'Planet', 'Gear')
CENTER = {(7, 7), (7, 8), (8, 7), (8, 8)}
DIRECTIONS = ('top', 'bottom', 'left', 'right')

# (lo, hi, min_robots) bands, kept in sync with mode_contracts.MODE_CONTRACTS.
MODE_BANDS = {
    'normal': (5, 9, 2),
    'hard': (9, 13, 3),
}


def _popcount(x):
    return bin(x).count('1')


class SessionPlanner:
    def __init__(self, h_walls, v_walls, lo, hi, min_robots, grid_size=GRID):
        self.lo = lo
        self.hi = hi
        self.min_robots = min_robots
        self.grid_size = grid_size
        self.board = build_board_matrix_from_walls(h_walls, v_walls, grid_size)
        self.solver = RicochetSolver(self.board, grid_size=grid_size)
        self.all_cells = [(r, c) for r in range(grid_size) for c in range(grid_size)
                          if (r, c) not in CENTER]
        self._cache = {}

    def _endpoints(self, config, cap=160000):
        """ONE labeled BFS to depth `hi` computing optimal-to-every-cell for every
        colour at once. Returns (per_colour, parent, start) where
        per_colour[colour][cell] = (opt_depth, movers, end_state_tuple).

        Records the TRUE minimum depth a colour first reaches each cell (any
        depth, BFS depth-ordered), so a cheap (<lo) cell keeps its small optimal
        and is later filtered out -- never mistaken for an in-band endpoint via a
        leave-and-return detour. Callers filter to [lo,hi]; an exact re-solve
        (verify pass) guards the state cap."""
        start = tuple(config[c] for c in BASE_COLORS)
        cached = self._cache.get(start)
        if cached is not None:
            return cached
        bit = {c: 1 << i for i, c in enumerate(BASE_COLORS)}
        per_colour = {c: {} for c in BASE_COLORS}
        parent = {}
        visited = {start: 0}
        q = deque([(start, 0, 0)])
        expanded = 0
        while q and expanded <= cap:
            state, depth, movers = q.popleft()
            if depth >= self.hi:
                continue
            expanded += 1
            occ = set(state)
            for i, col in enumerate(BASE_COLORS):
                r, c = state[i]
                for d in DIRECTIONS:
                    nr, nc = self.solver.get_slide_endpoint(r, c, d, occ - {(r, c)}, color=col)
                    if (nr, nc) == (r, c):
                        continue
                    ns = list(state)
                    ns[i] = (nr, nc)
                    ns = tuple(ns)
                    nd = depth + 1
                    if visited.get(ns, 99) <= nd:
                        continue
                    visited[ns] = nd
                    parent[ns] = (state, (col, d))
                    nmov = movers | bit[col]
                    cell = (nr, nc)
                    if cell not in per_colour[col] and cell not in CENTER:
                        per_colour[col][cell] = (nd, _popcount(nmov), ns)
                    if nd < self.hi:
                        q.append((ns, nd, nmov))
        result = (per_colour, parent, start)
        self._cache[start] = result
        return result

    def verify(self, robot_start, rounds):
        """Exact re-solve guard against the BFS state cap: confirm every round's
        true optimal == planned steps with >=min_robots, chaining the witnesses."""
        cfg = {c: tuple(p) for c, p in robot_start.items()}
        for rd in rounds:
            name = rd['target']
            tcolor = 'Wild' if name.startswith('Wild') else name.split('_')[0]
            steps, _ = self.solver.solve(cfg, tcolor, rd['cell'],
                                         max_depth=self.hi, max_states=400000)
            if steps != rd['steps'] or not (self.lo <= steps <= self.hi):
                return False
            feat = self.solver.analyze_path(cfg, [tuple(m) for m in rd['path']],
                                            target_color=tcolor)
            if feat['moved_robot_count'] < self.min_robots:
                return False
            if tcolor != 'Wild' and feat['end_robots'].get(rd['color']) != rd['cell']:
                return False
            cfg = feat['end_robots']
        return True

    @staticmethod
    def _reconstruct(parent, start, end_state):
        moves = []
        s = end_state
        while s != start:
            prev, (col, d) = parent[s]
            moves.append([col, d])
            s = prev
        moves.reverse()
        return moves

    def plan(self, robot_start, rng, desired_steps=None):
        """Depth-first design with backtracking. Returns list of round dicts
        {target, path, color, cell, steps, movers} or None."""
        result = [None]
        lo, hi, min_robots = self.lo, self.hi, self.min_robots

        def far_enough(cell, used_cells):
            return all(abs(cell[0] - u[0]) + abs(cell[1] - u[1]) >= MIN_SPACING
                       for u in used_cells)

        def dfs(config, used_cells, colored_used, wild_used, prev, acc):
            if len(acc) == 17:
                result[0] = list(acc)
                return True
            per_colour, parent, start = self._endpoints(config)
            options = []  # (is_wild, color, cell, steps, movers, ns)
            for color in BASE_COLORS:
                if colored_used[color] >= 4:
                    continue
                for cell, (steps, movers, ns) in per_colour[color].items():
                    if not (lo <= steps <= hi) or movers < min_robots:
                        continue
                    if cell in used_cells or not far_enough(cell, used_cells):
                        continue
                    if prev is not None and prev - steps > MAX_DROP:
                        continue
                    options.append((False, color, cell, steps, movers, ns))
            if not wild_used:
                wild_cells = set()
                for color in BASE_COLORS:
                    wild_cells.update(per_colour[color].keys())
                for cell in wild_cells:
                    best = min(((per_colour[c][cell][0], c) for c in BASE_COLORS
                                if cell in per_colour[c]), default=(99, None))
                    steps, bcolor = best
                    if bcolor is None or not (lo <= steps <= hi):
                        continue
                    _, movers, ns = per_colour[bcolor][cell]
                    if movers < min_robots or cell in used_cells:
                        continue
                    if not far_enough(cell, used_cells):
                        continue
                    if prev is not None and prev - steps > MAX_DROP:
                        continue
                    options.append((True, bcolor, cell, steps, movers, ns))
            if not options:
                return False
            want = desired_steps[len(acc)] if desired_steps else (lo + hi) // 2
            options.sort(key=lambda o: (-o[4], abs(o[3] - want), rng.random()))
            for is_wild, color, cell, steps, movers, ns in options[:16]:
                name = 'Wild_Vortex' if is_wild else f'{color}_{SYMBOLS[colored_used[color]]}'
                colored2 = dict(colored_used)
                wild2 = wild_used
                if is_wild:
                    wild2 = True
                else:
                    colored2[color] += 1
                path = self._reconstruct(parent, start, ns)
                acc.append({'target': name, 'path': path, 'color': color,
                            'cell': cell, 'steps': steps, 'movers': movers})
                end_config = dict(zip(BASE_COLORS, ns))
                if dfs(end_config, used_cells | {cell}, colored2, wild2, steps, acc):
                    return True
                acc.pop()
            return False

        ok = dfs(dict(robot_start), set(), {c: 0 for c in BASE_COLORS}, False, None, [])
        return result[0] if ok else None


def plan_session(h_walls, v_walls, lo, hi, min_robots, grid_size=GRID, seed=0,
                 start_attempts=24, desired_steps=None):
    """Try several random robot starts; return the first full 17-round session as
    an entry-ready dict (robot_positions, targets, target_order, rounds) or None."""
    planner = SessionPlanner(h_walls, v_walls, lo, hi, min_robots, grid_size)
    cells = [(r, c) for r in range(grid_size) for c in range(grid_size)
             if (r, c) not in CENTER]
    for attempt in range(start_attempts):
        rng = random.Random(seed * 1000 + attempt)
        start = dict(zip(BASE_COLORS, rng.sample(cells, 4)))
        planner._cache.clear()
        rounds = planner.plan(start, rng, desired_steps=desired_steps)
        if not rounds or not planner.verify(start, rounds):
            continue
        targets = {r['target']: r['cell'] for r in rounds}
        return {
            'robot_positions': dict(start),
            'targets': targets,
            'target_order': [r['target'] for r in rounds],
            'rounds': [{'target': r['target'], 'path': r['path']} for r in rounds],
            'session_stats': {
                'avg_robots': round(sum(r['movers'] for r in rounds) / 17, 3),
                'steps': [r['steps'] for r in rounds],
            },
        }
    return None


def plan_hard_session(h_walls, v_walls, grid_size=GRID, seed=0, start_attempts=30,
                      desired_steps=None):
    lo, hi, mr = MODE_BANDS['hard']
    return plan_session(h_walls, v_walls, lo, hi, mr, grid_size, seed,
                        start_attempts, desired_steps)


def plan_normal_session(h_walls, v_walls, grid_size=GRID, seed=0, start_attempts=30,
                        desired_steps=None):
    lo, hi, mr = MODE_BANDS['normal']
    return plan_session(h_walls, v_walls, lo, hi, mr, grid_size, seed,
                        start_attempts, desired_steps)


if __name__ == '__main__':
    # Self-test: both modes must pass the REAL validator.
    import copy
    from hard_board_catalog import HARD_BOARD_BASES
    from catalog_validation import validate_catalog_entry

    base = HARD_BOARD_BASES[0]
    h_walls, v_walls = set(base['h_walls']), set(base['v_walls'])
    for mode, planner_fn in (('normal', plan_normal_session), ('hard', plan_hard_session)):
        plan = planner_fn(h_walls, v_walls, seed=1)
        if not plan:
            print(f'{mode}: PLAN FAILED'); continue
        entry = {
            'id': f'{mode}-endpoint-test', 'mode': mode, 'family': 'endpoint_design',
            'grid_size': 16, 'h_walls': h_walls, 'v_walls': v_walls, 'diagonal_walls': {},
            'targets': plan['targets'], 'robot_positions': plan['robot_positions'],
            'target_order': plan['target_order'], 'rounds': plan['rounds'],
            'safe_transforms': [(0, False), (0, True)],
            'certification': {'method': 'endpoint_design_exact'},
        }
        val = validate_catalog_entry(copy.deepcopy(entry), exact=True)
        f = val['features']
        print(f"{mode}: OK steps {f['round_min_steps']}-{f['round_max_steps']} "
              f"minRobots={f['round_min_moved_robots']} avg={f['round_average_steps']}")
