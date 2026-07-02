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
    def __init__(self, h_walls, v_walls, lo, hi, min_robots, grid_size=GRID, spread=False):
        self.lo = lo
        self.hi = hi
        self.min_robots = min_robots
        self.spread = spread   # bias target placement toward under-populated 4x4 regions
        self.grid_size = grid_size
        self.board = build_board_matrix_from_walls(h_walls, v_walls, grid_size)
        self.solver = RicochetSolver(self.board, grid_size=grid_size)
        self.all_cells = [(r, c) for r in range(grid_size) for c in range(grid_size)
                          if (r, c) not in CENTER]
        self._cache = {}
        self._build_slide_tables()

    def _build_slide_tables(self):
        """Per (cell, direction): bitmask of the ray to the wall, the no-blocker
        endpoint, and the per-step stride (+-1 / +-grid_size). Lets the BFS
        resolve a slide in O(1) int ops (mask intersect + lowest/highest set
        bit for the first blocker) instead of walking the ray cell by cell."""
        n = self.grid_size * self.grid_size
        rays = self.solver._rays
        self._ray_mask = [[0] * 4 for _ in range(n)]
        self._ray_far = [[0] * 4 for _ in range(n)]
        self._ray_stride = [[0] * 4 for _ in range(n)]  # +-1 / +-grid_size
        for cell in range(n):
            for di in range(4):
                ray = rays[cell][di]
                if not ray:
                    self._ray_far[cell][di] = cell
                    continue
                m = 0
                for c in ray:
                    m |= 1 << c
                self._ray_mask[cell][di] = m
                self._ray_far[cell][di] = ray[-1]
                self._ray_stride[cell][di] = ray[0] - cell

    def _pack(self, config):
        """Pack a {colour: (r, c)} config into one int key (a byte per robot)."""
        gs = self.grid_size
        key = 0
        for i, c in enumerate(BASE_COLORS):
            r, col = config[c]
            key |= (r * gs + col) << (8 * i)
        return key

    def _unpack(self, key):
        gs = self.grid_size
        return tuple(divmod((key >> (8 * i)) & 255, gs)
                     for i in range(len(BASE_COLORS)))

    def _endpoints(self, config, cap=160000):
        """ONE labeled BFS to depth `hi` computing optimal-to-every-cell for every
        colour at once. Returns (per_colour, parent, start_key) where
        per_colour[colour][cell] = (opt_depth, movers, end_state_key).

        Records the TRUE minimum depth a colour first reaches each cell (any
        depth, BFS depth-ordered), so a cheap (<lo) cell keeps its small optimal
        and is later filtered out -- never mistaken for an in-band endpoint via a
        leave-and-return detour. Callers filter to [lo,hi]; an exact re-solve
        (verify pass) guards the state cap.

        States are packed ints (one cell byte per robot) and slides use the
        solver's precomputed rays with a bitboard occupancy mask -- this is the
        planner's hot loop (~90% of session design time)."""
        start_key = self._pack(config)
        cached = self._cache.get(start_key)
        if cached is not None:
            return cached
        gs = self.grid_size
        hi = self.hi
        ray_mask = self._ray_mask
        ray_far = self._ray_far
        ray_stride = self._ray_stride
        n_robots = len(BASE_COLORS)
        center_cells = {r * gs + c for r, c in CENTER}
        per_colour = {c: {} for c in BASE_COLORS}
        per_colour_by_i = [per_colour[c] for c in BASE_COLORS]
        parent = {}
        # plain FIFO BFS visits states in non-decreasing depth, so the first
        # visit is minimal -- a membership set is enough
        visited = {start_key}
        q = deque([(start_key, 0, 0)])
        expanded = 0
        while q and expanded <= cap:
            key, depth, movers = q.popleft()
            if depth >= hi:
                continue
            expanded += 1
            cells = [(key >> (8 * i)) & 255 for i in range(n_robots)]
            mask = 0
            for ci in cells:
                mask |= 1 << ci
            for i in range(n_robots):
                ci = cells[i]
                shift = 8 * i
                masks_ci = ray_mask[ci]
                for di in range(4):
                    m = mask & masks_ci[di]
                    if m == 0:
                        end = ray_far[ci][di]
                    else:
                        s = ray_stride[ci][di]
                        if s > 0:
                            end = (m & -m).bit_length() - 1 - s
                        else:
                            end = m.bit_length() - 1 - s
                    if end == ci:
                        continue
                    nk = key + ((end - ci) << shift)
                    nd = depth + 1
                    if nk in visited:
                        continue
                    visited.add(nk)
                    parent[nk] = (key, (BASE_COLORS[i], DIRECTIONS[di]))
                    nmov = movers | (1 << i)
                    if end not in center_cells:
                        pc = per_colour_by_i[i]
                        cell = (end // gs, end % gs)
                        if cell not in pc:
                            pc[cell] = (nd, _popcount(nmov), nk)
                    if nd < hi:
                        q.append((nk, nd, nmov))
        result = (per_colour, parent, start_key)
        self._cache[start_key] = result
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
    def _reconstruct(parent, start_key, end_key):
        moves = []
        s = end_key
        while s != start_key:
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
            if self.spread:
                # spread targets across the board: prefer cells in the least
                # populated 4x4 region, then more robots, then mid-band steps.
                def region_pop(cell):
                    rr, cc = cell[0] // 4, cell[1] // 4
                    return sum(1 for u in used_cells if u[0] // 4 == rr and u[1] // 4 == cc)
                options.sort(key=lambda o: (region_pop(o[2]), -o[4], abs(o[3] - want), rng.random()))
            else:
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
                end_config = dict(zip(BASE_COLORS, self._unpack(ns)))
                if dfs(end_config, used_cells | {cell}, colored2, wild2, steps, acc):
                    return True
                acc.pop()
            return False

        ok = dfs(dict(robot_start), set(), {c: 0 for c in BASE_COLORS}, False, None, [])
        return result[0] if ok else None


def plan_session(h_walls, v_walls, lo, hi, min_robots, grid_size=GRID, seed=0,
                 start_attempts=24, desired_steps=None, spread=False):
    """Try several random robot starts; return the first full 17-round session as
    an entry-ready dict (robot_positions, targets, target_order, rounds) or None."""
    planner = SessionPlanner(h_walls, v_walls, lo, hi, min_robots, grid_size, spread=spread)
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
                      desired_steps=None, spread=False):
    lo, hi, mr = MODE_BANDS['hard']
    return plan_session(h_walls, v_walls, lo, hi, mr, grid_size, seed,
                        start_attempts, desired_steps, spread=spread)


def plan_normal_session(h_walls, v_walls, grid_size=GRID, seed=0, start_attempts=30,
                        desired_steps=None, spread=False):
    lo, hi, mr = MODE_BANDS['normal']
    return plan_session(h_walls, v_walls, lo, hi, mr, grid_size, seed,
                        start_attempts, desired_steps, spread=spread)


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
