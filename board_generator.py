import random
from dataclasses import dataclass

from ricochet_robots_board_data import (
    GRID_SIZE,
    HORIZONTAL_WALLS,
    TARGETS,
    VERTICAL_WALLS,
    build_board_matrix,
    build_board_matrix_from_walls,
)
from solver import RicochetSolver


CENTER_CELLS = {(7, 7), (7, 8), (8, 7), (8, 8)}
FIXED_ROBOTS = {
    'Blue': (7, 6),
    'Yellow': (6, 8),
    'Green': (8, 9),
    'Red': (9, 7),
}
DIRECTION_DELTAS = {
    'top': (-1, 0),
    'bottom': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}
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


@dataclass
class BoardQualityMetrics:
    wall_count: int
    target_quadrant_balance: int
    wall_quadrant_balance: int
    min_target_spacing: int
    min_reachable_cells: int
    solved_targets: int
    average_steps: float
    max_steps: int


class BoardGenerator:
    CONFIGS = {
        'normal': {
            'min_steps': 8,
            'target_min_steps': 6,
            'all_target_max_depth': 18,
            'required_hard_targets': 3,
            'num_robots': 4,
            'extra_l_walls': (1, 3),
            'extra_quadrants': ('tl', 'bl'),
            'min_reachable_cells': 4,
            'max_attempts': 36,
            'max_states': 120000,
            'sample_targets': 5,
            'verified_solvable_targets': 8,
        },
        'hard': {
            'min_steps': 9,
            'target_min_steps': 7,
            'all_target_max_depth': 20,
            'required_hard_targets': 2,
            'num_robots': 5,
            'extra_l_walls': (3, 6),
            'extra_quadrants': ('tl', 'bl'),
            'min_reachable_cells': 4,
            'max_attempts': 48,
            'max_states': 180000,
            'sample_targets': 4,
            'verified_solvable_targets': 8,
        },
    }

    def generate(self, mode, max_attempts=None, progress_callback=None, cancel_callback=None):
        config = self.CONFIGS[mode]
        attempts = max_attempts or config['max_attempts']
        best_candidate = None

        for attempt in range(1, attempts + 1):
            if self._cancelled(cancel_callback):
                return None
            if progress_callback:
                progress_callback(f'{mode.capitalize()} 地圖生成中... 已嘗試 {attempt} 次')

            h_walls, v_walls, targets = self._build_variant_layout(config)
            robots = self._random_robot_positions(config['num_robots'], targets)
            board_matrix = build_board_matrix_from_walls(h_walls, v_walls)

            if not self._precheck_reachability(board_matrix, targets, config['min_reachable_cells']):
                continue

            validation = self._validate_sample_targets(
                board_matrix, robots, targets, config, cancel_callback=cancel_callback
            )
            if validation is None:
                continue
            _, solved_paths = validation

            verified_paths = self._collect_solvable_targets(
                board_matrix, robots, targets, config, cancel_callback=cancel_callback
            )
            if verified_paths is None:
                continue

            solved_paths.update({name: path for name, path in verified_paths.items() if name not in solved_paths})
            metrics = self._quality_metrics(
                board_matrix,
                targets,
                {name: len(path) for name, path in solved_paths.items()},
            )
            candidate = self._make_result(mode, h_walls, v_walls, targets, robots, metrics, solved_paths)

            if self._meets_difficulty(metrics, solved_paths, config):
                return candidate
            if best_candidate is None or metrics.average_steps > best_candidate['quality']['average_steps']:
                best_candidate = candidate

        if best_candidate:
            if progress_callback:
                progress_callback('使用已驗證可解的最佳候選地圖。')
            return best_candidate

        if progress_callback:
            progress_callback('生成失敗：找不到足夠可解的候選地圖，請再試一次。')
        return None

    def generate_expert(self, max_attempts=240, progress_callback=None, cancel_callback=None):
        board = build_board_matrix()
        target_items = list(TARGETS.items())
        best_candidate = None

        for attempt in range(1, max_attempts + 1):
            if self._cancelled(cancel_callback):
                return None
            if progress_callback:
                progress_callback(f'Expert 地圖生成中... 已嘗試 {attempt} 次')

            diagonal_walls = self._random_diagonal_walls(board)
            robots = self._random_robot_positions(5, TARGETS, forbidden=set(diagonal_walls))
            solver = RicochetSolver(board, diagonal_walls=diagonal_walls)

            shuffled_targets = target_items[:]
            random.shuffle(shuffled_targets)
            solved_paths = {}
            hard_count = 0

            for target_name, target_pos in shuffled_targets:
                if self._cancelled(cancel_callback):
                    return None
                target_color = target_name.split('_')[0]
                steps, path = solver.solve(
                    robots.copy(),
                    target_color,
                    target_pos,
                    max_depth=22,
                    max_states=220000,
                    cancel_callback=cancel_callback,
                )
                if steps == -2:
                    return None
                if steps < 0:
                    continue
                solved_paths[target_name] = path
                if steps >= 8:
                    hard_count += 1
                if len(solved_paths) >= 8:
                    break

            if len(solved_paths) < 8:
                continue

            candidate = {
                'h_walls': list(HORIZONTAL_WALLS),
                'v_walls': list(VERTICAL_WALLS),
                'diagonal_walls': diagonal_walls,
                'targets': dict(TARGETS.items()),
                'robot_positions': robots,
                'solved_steps': max(len(path) for path in solved_paths.values()),
                'difficulty': 'expert',
                'grid_size': 16,
                'quality': {
                    'solved_targets': len(solved_paths),
                    'hard_targets': hard_count,
                },
            }
            if hard_count >= 2:
                return candidate
            best_candidate = candidate

        if best_candidate:
            if progress_callback:
                progress_callback('使用已驗證可解的 Expert 候選地圖。')
            return best_candidate

        if progress_callback:
            progress_callback('生成失敗：找不到符合可解性要求的 Expert 地圖，請再試一次。')
        return None

    def _cancelled(self, cancel_callback):
        return bool(cancel_callback and cancel_callback())

    def _build_variant_layout(self, config):
        h_walls = set(HORIZONTAL_WALLS)
        v_walls = set(VERTICAL_WALLS)
        wall_counts = self._wall_counts_from_walls(h_walls, v_walls)
        targets = dict(TARGETS.items())
        used_cells = set(CENTER_CELLS) | set(FIXED_ROBOTS.values()) | set(targets.values())
        extra_count = random.randint(*config['extra_l_walls'])
        self._add_extra_l_walls(
            extra_count,
            used_cells,
            h_walls,
            v_walls,
            wall_counts,
            allowed_quadrants=config.get('extra_quadrants'),
        )
        return h_walls, v_walls, targets

    def _wall_counts_from_walls(self, h_walls, v_walls):
        wall_counts = [[0 for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]

        for i in range(GRID_SIZE):
            wall_counts[0][i] += 1
            wall_counts[GRID_SIZE - 1][i] += 1
            wall_counts[i][0] += 1
            wall_counts[i][GRID_SIZE - 1] += 1

        for r, c in h_walls:
            if 0 <= r < GRID_SIZE - 1 and 0 <= c < GRID_SIZE:
                wall_counts[r][c] += 1
                wall_counts[r + 1][c] += 1
        for r, c in v_walls:
            if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE - 1:
                wall_counts[r][c] += 1
                wall_counts[r][c + 1] += 1

        return wall_counts

    def _add_extra_l_walls(self, count, used_cells, h_walls, v_walls, wall_counts, allowed_quadrants=None):
        candidates = [
            (r, c)
            for r in range(1, 15)
            for c in range(1, 15)
            if (r, c) not in used_cells and (r, c) not in CENTER_CELLS
        ]
        if allowed_quadrants:
            candidates = [cell for cell in candidates if self._cell_quadrant(cell) in allowed_quadrants]
        random.shuffle(candidates)

        placed = 0
        for pos in candidates:
            if placed >= count:
                break
            if self._too_close_to_used(pos, used_cells, min_distance=2):
                continue
            if self._try_add_l_wall(pos, h_walls, v_walls, wall_counts):
                used_cells.add(pos)
                placed += 1

    def _too_close_to_used(self, pos, used_cells, min_distance=2):
        r, c = pos
        return any(abs(r - ur) + abs(c - uc) < min_distance for ur, uc in used_cells)

    def _try_add_l_wall(self, pos, h_walls, v_walls, wall_counts):
        r, c = pos
        orientations = [
            ((r - 1, c), (r, c - 1)),
            ((r - 1, c), (r, c)),
            ((r, c), (r, c - 1)),
            ((r, c), (r, c)),
        ]
        random.shuffle(orientations)

        for h_wall, v_wall in orientations:
            if self._can_add_h(h_wall, h_walls, wall_counts) and self._can_add_v(v_wall, v_walls, wall_counts):
                self._add_h_wall(h_wall, h_walls, wall_counts)
                self._add_v_wall(v_wall, v_walls, wall_counts)
                return True
        return False

    def _can_add_h(self, wall, h_walls, wall_counts):
        r, c = wall
        if (r, c) in h_walls:
            return True
        if r < 0 or r >= GRID_SIZE - 1 or c < 0 or c >= GRID_SIZE:
            return False
        return wall_counts[r][c] < 2 and wall_counts[r + 1][c] < 2

    def _can_add_v(self, wall, v_walls, wall_counts):
        r, c = wall
        if (r, c) in v_walls:
            return True
        if r < 0 or r >= GRID_SIZE or c < 0 or c >= GRID_SIZE - 1:
            return False
        return wall_counts[r][c] < 2 and wall_counts[r][c + 1] < 2

    def _add_h_wall(self, wall, h_walls, wall_counts):
        if wall in h_walls:
            return
        h_walls.add(wall)
        r, c = wall
        wall_counts[r][c] += 1
        wall_counts[r + 1][c] += 1

    def _add_v_wall(self, wall, v_walls, wall_counts):
        if wall in v_walls:
            return
        v_walls.add(wall)
        r, c = wall
        wall_counts[r][c] += 1
        wall_counts[r][c + 1] += 1

    def _precheck_reachability(self, board_matrix, targets, min_reachable_cells):
        solver = RicochetSolver(board_matrix)
        min_reachable = GRID_SIZE * GRID_SIZE
        for target_name, target_pos in targets.items():
            target_color = target_name.split('_')[0]
            h_table = solver._get_h_table(*target_pos, color=target_color)
            min_reachable = min(min_reachable, len(h_table))
            if len(h_table) < min_reachable_cells:
                return None
        return min_reachable

    def _validate_sample_targets(self, board_matrix, robots, targets, config, cancel_callback=None):
        solver = RicochetSolver(board_matrix)
        target_items = list(targets.items())
        random.shuffle(target_items)

        anchor_names = ['Red_Gear', 'Green_Moon', 'Yellow_Planet', 'Wild_Vortex']
        anchors = [(name, targets[name]) for name in anchor_names if name in targets]
        sample_limit = config.get('sample_targets', 7)
        sample = anchors + [item for item in target_items if item[0] not in anchor_names]
        sample = sample[:sample_limit]

        solved_steps = {}
        solved_paths = {}
        for target_name, target_pos in sample:
            if self._cancelled(cancel_callback):
                return None
            target_color = target_name.split('_')[0]
            steps, path = solver.solve(
                robots.copy(),
                target_color,
                target_pos,
                max_depth=config['all_target_max_depth'],
                max_states=config['max_states'],
                cancel_callback=cancel_callback,
            )
            if steps < 0:
                return None
            solved_steps[target_name] = steps
            solved_paths[target_name] = path

        metrics = self._quality_metrics(board_matrix, targets, solved_steps)
        return metrics, solved_paths

    def _collect_solvable_targets(self, board_matrix, robots, targets, config, cancel_callback=None):
        solver = RicochetSolver(board_matrix)
        target_items = list(targets.items())
        random.shuffle(target_items)
        required_count = config.get('verified_solvable_targets', 8)
        solved_paths = {}

        for target_name, target_pos in target_items:
            if self._cancelled(cancel_callback):
                return None
            target_color = target_name.split('_')[0]
            steps, path = solver.solve(
                robots.copy(),
                target_color,
                target_pos,
                max_depth=max(20, config['all_target_max_depth']),
                max_states=max(200000, config['max_states']),
                cancel_callback=cancel_callback,
            )
            if steps >= 0:
                solved_paths[target_name] = path
                if len(solved_paths) >= required_count:
                    return solved_paths
        return None

    def _quality_metrics(self, board_matrix, targets, solved_steps):
        wall_count = sum(
            1
            for r in range(GRID_SIZE)
            for c in range(GRID_SIZE)
            if board_matrix[r][c]['right'] or board_matrix[r][c]['bottom']
        )

        quadrant_counts = {'tl': 0, 'tr': 0, 'bl': 0, 'br': 0}
        for pos in targets.values():
            quadrant_counts[self._cell_quadrant(pos)] += 1
        target_balance = max(quadrant_counts.values()) - min(quadrant_counts.values())

        wall_quadrants = {'tl': 0, 'tr': 0, 'bl': 0, 'br': 0}
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                if board_matrix[r][c]['right'] or board_matrix[r][c]['bottom']:
                    wall_quadrants[self._cell_quadrant((r, c))] += 1
        wall_balance = max(wall_quadrants.values()) - min(wall_quadrants.values())

        positions = list(targets.values())
        min_spacing = min(
            abs(a[0] - b[0]) + abs(a[1] - b[1])
            for i, a in enumerate(positions)
            for b in positions[i + 1:]
        )

        steps_values = list(solved_steps.values())
        return BoardQualityMetrics(
            wall_count=wall_count,
            target_quadrant_balance=target_balance,
            wall_quadrant_balance=wall_balance,
            min_target_spacing=min_spacing,
            min_reachable_cells=0,
            solved_targets=len(solved_steps),
            average_steps=sum(steps_values) / len(steps_values),
            max_steps=max(steps_values),
        )

    def _cell_quadrant(self, pos):
        r, c = pos
        if r < 8 and c < 8:
            return 'tl'
        if r < 8 and c >= 8:
            return 'tr'
        if r >= 8 and c < 8:
            return 'bl'
        return 'br'

    def _meets_difficulty(self, metrics, solved_paths, config):
        if metrics.target_quadrant_balance > 1:
            return False
        if metrics.min_target_spacing < 2:
            return False
        hard_targets = sum(1 for path in solved_paths.values() if len(path) >= config['target_min_steps'])
        if hard_targets < config['required_hard_targets']:
            return False
        return metrics.max_steps >= config['min_steps']

    def _make_result(self, mode, h_walls, v_walls, targets, robots, metrics, solved_paths):
        representative_target, representative_path = max(solved_paths.items(), key=lambda item: len(item[1]))
        return {
            'h_walls': sorted(h_walls),
            'v_walls': sorted(v_walls),
            'targets': targets,
            'robot_positions': robots,
            'solved_steps': len(representative_path),
            'difficulty': mode,
            'grid_size': 16,
            'quality': {
                'average_steps': round(metrics.average_steps, 2),
                'max_steps': metrics.max_steps,
                'representative_target': representative_target,
                'solved_targets': metrics.solved_targets,
                'target_quadrant_balance': metrics.target_quadrant_balance,
                'wall_quadrant_balance': metrics.wall_quadrant_balance,
            },
        }

    def _random_robot_positions(self, num_robots, targets=None, forbidden=None):
        robots = dict(FIXED_ROBOTS)
        occupied = set(robots.values()) | set(CENTER_CELLS)
        if targets:
            occupied |= set(targets.values())
        if forbidden:
            occupied |= set(forbidden)

        if num_robots >= 5:
            candidates = [
                (r, c)
                for r in range(GRID_SIZE)
                for c in range(GRID_SIZE)
                if (r, c) not in occupied
            ]
            robots['Silver'] = random.choice(candidates)

        return robots

    def _can_enter_diagonal_cell(self, board, cell, direction):
        r, c = cell
        dr, dc = DIRECTION_DELTAS[direction]
        prev_r, prev_c = r - dr, c - dc
        if prev_r < 0 or prev_r >= GRID_SIZE or prev_c < 0 or prev_c >= GRID_SIZE:
            return False
        return not board[prev_r][prev_c][direction]

    def _safe_diagonal_types(self, board, cell):
        r, c = cell
        safe_types = []
        for w_type, reflections in DIAGONAL_REFLECTIONS.items():
            safe = True
            for in_direction, out_direction in reflections.items():
                if self._can_enter_diagonal_cell(board, cell, in_direction) and board[r][c][out_direction]:
                    safe = False
                    break
            if safe:
                safe_types.append(w_type)
        return safe_types

    def _random_diagonal_walls(self, board=None):
        board = board or build_board_matrix()
        colors = ['Red', 'Blue', 'Green', 'Yellow']
        cells = [
            (r, c)
            for r in range(2, 14)
            for c in range(2, 14)
            if (r, c) not in CENTER_CELLS and (r, c) not in FIXED_ROBOTS.values()
        ]
        random.shuffle(cells)
        diagonal_walls = {}
        for cell in cells:
            if len(diagonal_walls) >= len(colors):
                break
            safe_types = self._safe_diagonal_types(board, cell)
            if not safe_types:
                continue
            color = colors[len(diagonal_walls)]
            diagonal_walls[cell] = {'type': random.choice(safe_types), 'color': color}
        return diagonal_walls
