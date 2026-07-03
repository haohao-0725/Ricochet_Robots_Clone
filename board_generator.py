import random
import time
from dataclasses import dataclass

from hard_board_catalog import HARD_BOARD_BASES
from map_catalog import catalog_maps
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
TARGET_SHAPES = ('Moon', 'Planet', 'Star', 'Gear')
TARGET_COLORS = ('Red', 'Blue', 'Green', 'Yellow')
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
CATALOG_ONLY_MODES = ('v3_momentum', 'super_expert', 'chaos')
QUADRANTS = ('tl', 'tr', 'bl', 'br')
QUADRANT_TEMPLATES = {
    'balanced': ((1, 2), (2, 5), (4, 1), (5, 4)),
    'diagonal': ((1, 1), (2, 4), (4, 2), (5, 5)),
    'pinwheel': ((1, 4), (2, 1), (4, 5), (5, 2)),
}
EXTRA_ANCHORS = ((1, 5), (3, 3), (3, 5), (5, 1), (5, 3))


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
    symmetry_score: float
    max_wall_cluster: int
    validated_rounds: int
    total_round_steps: int


class BoardGenerator:
    """
    Structured generator for playable Ricochet Robots boards.

    The layout is built from reusable L-wall motifs distributed across all four
    quadrants. Mirrored motif placement gives the board a visual rhythm, while
    controlled orientation mutations and one extra anchor prevent exact,
    repetitive symmetry. Exact solving is delayed until cheap structural checks
    pass. Normal verifies five successive rounds; Hard jointly assigns all 17
    targets and plans a smooth full-session difficulty curve.
    """

    CONFIGS = {
        'normal': {
            'num_robots': 4,
            'max_attempts': 12,
            'rounds': 17,
            'strict_rounds': 17,
            'round_min_steps': 5,
            'round_max_steps': 9,
            'round_min_robots': 2,
            'session_min_steps': 5,
            'session_min_robots': 2,
            'round_max_depth': 14,
            'round_target_steps': 7,
            'min_total_steps': 85,
            'max_states': 160000,
            'candidate_pool': 17,
            'orientation_mutation_rate': 0.28,
            'min_symmetry_score': 0.42,
            'max_wall_cluster': 8,
            'edge_notch_sets': 1,
            'support_wall_pairs': 1,
            'full_session_planner': True,
            'tail_search_rounds': 4,
            'max_round_step_drop': 3,
            'max_session_step_range': 4,
            'min_session_average_steps': 5.8,
            'candidate_time_limit_seconds': 20.0,
            'session_beam_width': 8,
            'target_assignment': 'easier',
        },
        'hard': {
            'num_robots': 5,
            'max_attempts': 8,
            'rounds': 17,
            'strict_rounds': 17,
            'round_min_steps': 9,
            'round_max_steps': 13,
            'round_min_robots': 3,
            'session_min_steps': 9,
            'session_min_robots': 3,
            'round_max_depth': 17,
            'round_target_steps': 10,
            'min_total_steps': 153,
            'max_states': 250000,
            'tail_search_rounds': 4,
            'max_round_step_drop': 3,
            'max_session_step_range': 4,
            'min_session_average_steps': 9.5,
            'orientation_mutation_rate': 0.38,
            'min_symmetry_score': 0.34,
            'max_wall_cluster': 10,
            'edge_notch_sets': 2,
            'support_wall_pairs': 3,
            'full_session_planner': True,
            'candidate_time_limit_seconds': 25.0,
        },
        'expert': {
            'num_robots': 4,
            'rounds': 17,
            'round_min_steps': 6,
            'round_max_steps': 12,
            'round_min_robots': 2,
            'round_max_depth': 12,
            'max_states': 220000,
            'max_round_step_drop': 3,
        },
        'v3_momentum': {
            'num_robots': 4,
            'rounds': 17,
            'round_min_steps': 2,
            'round_max_steps': 14,
            'round_min_robots': 1,
            'round_max_depth': 14,
            'max_states': 220000,
            'max_round_step_drop': 4,
        },
        'super_expert': {
            'num_robots': 5,
            'rounds': 17,
            'round_min_steps': 9,
            'round_max_steps': 14,
            'round_min_robots': 3,
            'round_max_depth': 14,
            'max_states': 250000,
            'max_round_step_drop': 3,
        },
        'chaos': {
            'num_robots': 4,
            'rounds': 17,
            'round_min_steps': 5,
            'round_max_steps': 11,
            'round_min_robots': 1,
            'round_max_depth': 11,
            'max_states': 400000,
            'max_round_step_drop': 3,
        },
    }

    def generate(
        self,
        mode,
        max_attempts=None,
        progress_callback=None,
        cancel_callback=None,
        use_catalog=True,
    ):
        if mode != 'easy' and use_catalog and catalog_maps(mode):
            return self._generate_catalog_variant(
                mode,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

        # v3_momentum and super_expert can only be produced from the certified
        # catalog (they rely on momentum / dense-topology proofs the structured
        # generator cannot reproduce). If the bundled catalog is missing or
        # corrupt we fail cleanly instead of crashing on a missing config key.
        if mode in CATALOG_ONLY_MODES:
            if progress_callback:
                progress_callback(
                    f'{mode.replace("_", " ").title()} 地圖資料缺失或損壞，'
                    '無法生成；請重新安裝或還原 assets/map_catalog_v2.json。'
                )
            return None

        config = self.CONFIGS[mode]
        attempts = max_attempts or config['max_attempts']
        best_candidate = None
        best_score = float('-inf')

        for attempt in range(1, attempts + 1):
            if self._cancelled(cancel_callback):
                return None
            if progress_callback:
                progress_callback(f'{mode.capitalize()} 地圖生成中... 結構候選 {attempt}/{attempts}')

            h_walls, v_walls, targets, layout_name = self._build_structured_layout(config)
            board_matrix = build_board_matrix_from_walls(h_walls, v_walls)
            structural = self._structural_metrics(board_matrix, h_walls, v_walls, targets)

            if structural.symmetry_score < config['min_symmetry_score']:
                continue
            if structural.max_wall_cluster > config['max_wall_cluster']:
                continue
            if structural.min_target_spacing < 2:
                continue

            robots = self._distributed_robot_positions(config['num_robots'], targets)
            min_reachable = self._precheck_reachability(board_matrix, robots, targets)
            if min_reachable <= 0:
                continue

            if progress_callback:
                validation_label = (
                    '完整 17 回合難度曲線'
                    if config.get('full_session_planner')
                    else f'連續 {config["rounds"]} 回合'
                )
                progress_callback(
                    f'{mode.capitalize()} 地圖生成中... 驗證{validation_label}'
                    f'（前 {config.get("strict_rounds", config["rounds"])} 題至少 '
                    f'{config["round_min_steps"]} 步 / '
                    f'{config["round_min_robots"]} 台機器人）'
                )
            candidate_deadline = None
            if config.get('candidate_time_limit_seconds'):
                candidate_deadline = (
                    time.perf_counter()
                    + config['candidate_time_limit_seconds']
                )
            validation = self._validate_round_chain(
                board_matrix,
                robots,
                targets,
                config,
                cancel_callback=cancel_callback,
                deadline=candidate_deadline,
            )
            if validation is None:
                continue
            if validation == '__cancelled__':
                return None
            rounds = validation['rounds']
            targets = validation['targets']

            steps = [item['steps'] for item in rounds]
            metrics = BoardQualityMetrics(
                wall_count=structural.wall_count,
                target_quadrant_balance=structural.target_quadrant_balance,
                wall_quadrant_balance=structural.wall_quadrant_balance,
                min_target_spacing=structural.min_target_spacing,
                min_reachable_cells=min_reachable,
                solved_targets=len(rounds),
                average_steps=sum(steps) / len(steps),
                max_steps=max(steps),
                symmetry_score=structural.symmetry_score,
                max_wall_cluster=structural.max_wall_cluster,
                validated_rounds=len(rounds),
                total_round_steps=sum(steps),
            )
            candidate = self._make_result(
                mode,
                h_walls,
                v_walls,
                targets,
                robots,
                metrics,
                rounds,
                layout_name,
            )
            score = metrics.total_round_steps + metrics.symmetry_score * 4

            if metrics.total_round_steps >= config['min_total_steps']:
                return candidate
            if score > best_score:
                best_candidate = candidate
                best_score = score

        if best_candidate and best_candidate['quality']['validated_rounds'] >= config['rounds']:
            if progress_callback:
                progress_callback(
                    f'使用已通過 {config["rounds"]} 回合驗證的最佳候選地圖。'
                )
            return best_candidate

        if progress_callback:
            progress_callback(
                f'生成失敗：找不到可連續遊玩 {config["rounds"]} 回合的候選地圖，'
                '請再試一次。'
            )
        return None

    def generate_hard_candidate(
        self,
        max_attempts=None,
        progress_callback=None,
        cancel_callback=None,
    ):
        """Run the expensive planner used to expand the offline Hard catalog."""
        return self.generate(
            'hard',
            max_attempts=max_attempts,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
            use_catalog=False,
        )

    def _generate_hard_catalog_variant(self, progress_callback=None, cancel_callback=None):
        return self._generate_catalog_variant(
            'hard',
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    def _generate_catalog_variant(self, mode, progress_callback=None, cancel_callback=None):
        config = self.CONFIGS[mode]
        if progress_callback:
            progress_callback(f'{mode.capitalize()} 地圖載入中... 建立認證盤面的等價變體')

        bases = catalog_maps(mode)
        if not bases and mode == 'hard':
            bases = list(HARD_BOARD_BASES)
        if not bases:
            return None
        base_index = random.randrange(len(bases))
        base = bases[base_index]
        grid_size = base.get('grid_size', GRID_SIZE)
        rotations, mirror = random.choice(base['safe_transforms'])
        if grid_size != GRID_SIZE:
            # geometric transforms are 16x16-tuned; larger boards (chaos 25x25)
            # ship identity-only safe_transforms, variety comes from remapping
            rotations, mirror = 0, False
        h_walls, v_walls = self._transform_board_walls(
            base['h_walls'],
            base['v_walls'],
            rotations,
            mirror,
        )

        color_values = list(TARGET_COLORS)
        shape_values = list(TARGET_SHAPES)
        random.shuffle(color_values)
        random.shuffle(shape_values)
        color_map = dict(zip(TARGET_COLORS, color_values))
        shape_map = dict(zip(TARGET_SHAPES, shape_values))

        targets = {
            self._remap_target_name(name, color_map, shape_map):
                self._transform_cell(position, rotations, mirror)
            for name, position in base['targets'].items()
        }
        robots = {
            (color_map[color] if color in color_map else color):
                self._transform_cell(position, rotations, mirror)
            for color, position in base['robot_positions'].items()
        }
        target_order = [
            self._remap_target_name(name, color_map, shape_map)
            for name in base['target_order']
        ]
        diagonal_walls = {
            self._transform_cell(position, rotations, mirror): {
                'type': self._transform_diagonal_type(
                    value['type'],
                    rotations,
                    mirror,
                ),
                'color': color_map.get(value['color'], value['color']),
            }
            for position, value in base.get('diagonal_walls', {}).items()
        }
        # chaos extras (identity geometry, colour remap only; White is universal)
        portals = {
            tuple(cell): {
                'color': color_map.get(value['color'], value['color']),
                'exit': tuple(value['exit']),
            }
            for cell, value in base.get('portals', {}).items()
        }
        sand_cells = [tuple(cell) for cell in base.get('sand_cells', [])]

        board_matrix = build_board_matrix_from_walls(h_walls, v_walls, grid_size=grid_size)
        if mode == 'v3_momentum':
            variant_movement_mode = 'momentum'
        elif mode == 'chaos':
            variant_movement_mode = 'chaos'
        else:
            variant_movement_mode = 'classic'
        solver = RicochetSolver(
            board_matrix,
            grid_size=grid_size,
            diagonal_walls=diagonal_walls,
            movement_mode=variant_movement_mode,
            portals=portals,
            sand_cells=sand_cells,
        )
        current_robots = robots.copy()
        rounds = []
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
        base_paths = (
            [item['path'] for item in base['rounds']]
            if 'rounds' in base
            else base['paths']
        )
        for index, (target_name, encoded_path) in enumerate(
            zip(target_order, base_paths),
            start=1,
        ):
            if self._cancelled(cancel_callback):
                return None
            if progress_callback:
                progress_callback(
                    f'Hard 地圖生成中... 重放難度證明 {index}/{len(target_order)}'
                )
            path = []
            encoded_moves = (
                [
                    (color_codes[token[0]], direction_codes[token[1]])
                    for token in encoded_path.split()
                ]
                if isinstance(encoded_path, str)
                else encoded_path
            )
            for old_color, old_direction in encoded_moves:
                color = color_map.get(old_color, old_color)
                direction = self._transform_direction(
                    old_direction,
                    rotations,
                    mirror,
                )
                path.append((color, direction))
            steps = len(path)
            path_features = solver.analyze_path(
                current_robots,
                path,
                target_color=target_name.split('_')[0],
            )
            moved_robots = path_features['moved_robots']
            current_robots = path_features['end_robots']
            target_color = target_name.split('_')[0]
            target_position = targets[target_name]
            reached = (
                target_position in current_robots.values()
                if target_color == 'Wild'
                else current_robots[target_color] == target_position
            )
            if (
                not reached
                or steps < config.get('session_min_steps', config['round_min_steps'])
                or steps > config.get('round_max_steps', steps)
                or len(moved_robots) < config.get(
                    'session_min_robots',
                    config['round_min_robots'],
                )
            ):
                return None
            rounds.append({
                'target': target_name,
                'steps': steps,
                'path': path,
                'moved_robots': moved_robots,
                'moved_robot_count': len(moved_robots),
                'end_robots': current_robots.copy(),
                'states_expanded': 0,
                'features': {
                    key: value
                    for key, value in path_features.items()
                    if key not in ('end_robots', 'moved_robots', 'moved_robot_count')
                },
            })

        steps = [item['steps'] for item in rounds]
        if mode == 'chaos':
            # structural metrics / reachability precheck are 16x16-tuned; the
            # chaos entry is already exact-certified offline, so use pass-through
            # values instead of running them on the 25x25 board
            metrics = BoardQualityMetrics(
                wall_count=len(h_walls) + len(v_walls),
                target_quadrant_balance=0,
                wall_quadrant_balance=0,
                min_target_spacing=2,
                min_reachable_cells=1,
                solved_targets=len(rounds),
                average_steps=sum(steps) / len(steps),
                max_steps=max(steps),
                symmetry_score=1.0,
                max_wall_cluster=0,
                validated_rounds=len(rounds),
                total_round_steps=sum(steps),
            )
        else:
            structural = self._structural_metrics(
                board_matrix,
                set(h_walls),
                set(v_walls),
                targets,
            )
            metrics = BoardQualityMetrics(
                wall_count=structural.wall_count,
                target_quadrant_balance=structural.target_quadrant_balance,
                wall_quadrant_balance=structural.wall_quadrant_balance,
                min_target_spacing=structural.min_target_spacing,
                min_reachable_cells=self._precheck_reachability(
                    board_matrix,
                    robots,
                    targets,
                ),
                solved_targets=len(rounds),
                average_steps=sum(steps) / len(steps),
                max_steps=max(steps),
                symmetry_score=structural.symmetry_score,
                max_wall_cluster=structural.max_wall_cluster,
                validated_rounds=len(rounds),
                total_round_steps=sum(steps),
            )
        result = self._make_result(
            mode,
            h_walls,
            v_walls,
            targets,
            robots,
            metrics,
            rounds,
            base.get('family', base.get('layout_template', 'catalog')),
        )
        result['difficulty'] = mode
        result['diagonal_walls'] = diagonal_walls
        result['grid_size'] = grid_size
        result['portals'] = portals
        result['sand_cells'] = sand_cells
        result['quality'].update({
            'generator': 'validated_catalog_v2',
            'catalog_base': base_index,
            'catalog_map_id': base.get('id', f'legacy-hard-{base_index:02d}'),
            'topology_family': base.get('family', base.get('layout_template', 'legacy')),
            'geometry_rotation': rotations * 90,
            'geometry_mirrored': mirror,
        })
        return result

    def _transform_diagonal_type(self, wall_type, rotations, mirror):
        if (rotations + int(mirror)) % 2:
            return '\\' if wall_type == '/' else '/'
        return wall_type

    def _transform_cell(self, position, rotations, mirror):
        r, c = position
        for _ in range(rotations):
            r, c = c, GRID_SIZE - 1 - r
        if mirror:
            c = GRID_SIZE - 1 - c
        return r, c

    def _transform_board_walls(self, h_walls, v_walls, rotations, mirror):
        transformed_h = set(h_walls)
        transformed_v = set(v_walls)
        for _ in range(rotations):
            next_h = {
                (c, GRID_SIZE - 1 - r)
                for r, c in transformed_v
            }
            next_v = {
                (c, GRID_SIZE - 2 - r)
                for r, c in transformed_h
            }
            transformed_h, transformed_v = next_h, next_v
        if mirror:
            transformed_h = {
                (r, GRID_SIZE - 1 - c)
                for r, c in transformed_h
            }
            transformed_v = {
                (r, GRID_SIZE - 2 - c)
                for r, c in transformed_v
            }
        return sorted(transformed_h), sorted(transformed_v)

    def _transform_direction(self, direction, rotations, mirror):
        clockwise = {
            'top': 'right',
            'right': 'bottom',
            'bottom': 'left',
            'left': 'top',
        }
        for _ in range(rotations):
            direction = clockwise[direction]
        if mirror:
            direction = {
                'left': 'right',
                'right': 'left',
            }.get(direction, direction)
        return direction

    def _remap_target_name(self, name, color_map, shape_map):
        color, shape = name.split('_')
        if color == 'Wild':
            return name
        return f'{color_map[color]}_{shape_map[shape]}'

    def generate_expert(self, max_attempts=240, progress_callback=None, cancel_callback=None):
        if catalog_maps('expert'):
            return self._generate_catalog_variant(
                'expert',
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )
        board = build_board_matrix()
        target_items = list(TARGETS.items())
        best_candidate = None

        for attempt in range(1, max_attempts + 1):
            if self._cancelled(cancel_callback):
                return None
            if progress_callback:
                progress_callback(f'Expert 地圖生成中... 已嘗試 {attempt} 次')

            diagonal_walls = self._random_diagonal_walls(board)
            robots = self._distributed_robot_positions(5, TARGETS, forbidden=set(diagonal_walls))
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

    def _build_structured_layout(self, config):
        template_name = random.choice(tuple(QUADRANT_TEMPLATES))
        template = QUADRANT_TEMPLATES[template_name]
        h_walls = set()
        v_walls = set()
        anchors = {quadrant: [] for quadrant in QUADRANTS}

        self._add_center_block_walls(h_walls, v_walls)
        self._add_balanced_edge_notches(
            h_walls,
            v_walls,
            config.get('edge_notch_sets', 1),
        )

        for local_pos in template:
            base_orientation = random.randrange(4)
            for quadrant in QUADRANTS:
                position = self._transform_local_anchor(local_pos, quadrant)
                orientation = self._transform_orientation(base_orientation, quadrant)
                if random.random() < config['orientation_mutation_rate']:
                    orientation = random.randrange(4)
                self._add_l_wall(position, orientation, h_walls, v_walls)
                anchors[quadrant].append(position)

        extra_quadrant = random.choice(QUADRANTS)
        used_local = set(template)
        extra_candidates = [position for position in EXTRA_ANCHORS if position not in used_local]
        random.shuffle(extra_candidates)
        for local_pos in extra_candidates:
            position = self._transform_local_anchor(local_pos, extra_quadrant)
            if self._too_close_to_used(position, set(sum(anchors.values(), [])), min_distance=2):
                continue
            self._add_l_wall(position, random.randrange(4), h_walls, v_walls)
            anchors[extra_quadrant].append(position)
            break

        self._add_support_wall_pairs(
            h_walls,
            v_walls,
            set(sum(anchors.values(), [])),
            config.get('support_wall_pairs', 0),
        )
        targets = self._assign_targets(anchors)
        return h_walls, v_walls, targets, template_name

    def _add_center_block_walls(self, h_walls, v_walls):
        h_walls.update({(6, 7), (6, 8), (8, 7), (8, 8)})
        v_walls.update({(7, 6), (8, 6), (7, 8), (8, 8)})

    def _add_balanced_edge_notches(self, h_walls, v_walls, notch_sets):
        offsets = [3, 4, 5]
        random.shuffle(offsets)
        for offset in offsets[:notch_sets]:
            opposite = GRID_SIZE - 2 - offset
            v_walls.update({
                (0, offset),
                (GRID_SIZE - 1, opposite),
            })
            h_walls.update({
                (opposite, 0),
                (offset, GRID_SIZE - 1),
            })

    def _add_support_wall_pairs(self, h_walls, v_walls, used_cells, pair_count):
        candidates = [
            (r, c)
            for r in range(2, 7)
            for c in range(2, 7)
            if (r, c) not in used_cells
            and not self._too_close_to_used((r, c), used_cells, min_distance=2)
        ]
        random.shuffle(candidates)
        placed = 0
        for position in candidates:
            if placed >= pair_count:
                break
            mirrored = (GRID_SIZE - 1 - position[0], GRID_SIZE - 1 - position[1])
            if mirrored in used_cells:
                continue
            orientation = random.randrange(4)
            self._add_l_wall(position, orientation, h_walls, v_walls)
            self._add_l_wall(
                mirrored,
                self._transform_orientation(orientation, 'br'),
                h_walls,
                v_walls,
            )
            used_cells.update((position, mirrored))
            placed += 1

    def _transform_local_anchor(self, local_pos, quadrant):
        r, c = local_pos
        if quadrant == 'tl':
            return r, c
        if quadrant == 'tr':
            return r, GRID_SIZE - 1 - c
        if quadrant == 'bl':
            return GRID_SIZE - 1 - r, c
        return GRID_SIZE - 1 - r, GRID_SIZE - 1 - c

    def _transform_orientation(self, orientation, quadrant):
        if quadrant == 'tl':
            return orientation
        if quadrant == 'tr':
            return (1, 0, 3, 2)[orientation]
        if quadrant == 'bl':
            return (2, 3, 0, 1)[orientation]
        return (3, 2, 1, 0)[orientation]

    def _add_l_wall(self, position, orientation, h_walls, v_walls):
        r, c = position
        options = (
            ((r - 1, c), (r, c - 1)),
            ((r - 1, c), (r, c)),
            ((r, c), (r, c - 1)),
            ((r, c), (r, c)),
        )
        h_wall, v_wall = options[orientation]
        h_walls.add(h_wall)
        v_walls.add(v_wall)

    def _assign_targets(self, anchors):
        available = {quadrant: positions[:] for quadrant, positions in anchors.items()}
        for positions in available.values():
            random.shuffle(positions)

        targets = {}
        for color in TARGET_COLORS:
            shapes = list(TARGET_SHAPES)
            quadrants = list(QUADRANTS)
            random.shuffle(shapes)
            random.shuffle(quadrants)
            for shape, quadrant in zip(shapes, quadrants):
                targets[f'{color}_{shape}'] = available[quadrant].pop()

        extra_quadrant = next(quadrant for quadrant, positions in available.items() if positions)
        targets['Wild_Vortex'] = available[extra_quadrant].pop()
        return targets

    def _distributed_robot_positions(self, num_robots, targets=None, forbidden=None):
        forbidden_cells = set(CENTER_CELLS)
        if targets:
            forbidden_cells.update(targets.values())
        if forbidden:
            forbidden_cells.update(forbidden)

        ranges = {
            'Blue': (range(0, 7), range(0, 7)),
            'Yellow': (range(0, 7), range(9, 16)),
            'Green': (range(9, 16), range(0, 7)),
            'Red': (range(9, 16), range(9, 16)),
        }
        robots = {}
        for color, (rows, cols) in ranges.items():
            candidates = [
                (r, c)
                for r in rows
                for c in cols
                if (r, c) not in forbidden_cells and (r, c) not in robots.values()
            ]
            robots[color] = random.choice(candidates)

        if num_robots >= 5:
            candidates = [
                (r, c)
                for r in range(GRID_SIZE)
                for c in range(GRID_SIZE)
                if (r, c) not in forbidden_cells and (r, c) not in robots.values()
            ]
            robots['Silver'] = random.choice(candidates)
        return robots

    def _precheck_reachability(self, board_matrix, robots, targets):
        solver = RicochetSolver(board_matrix)
        reachable_counts = []
        for target_name, target_pos in targets.items():
            target_cell = solver._encode(*target_pos)
            distances = solver._get_relaxed_distances(target_cell)
            target_color = target_name.split('_')[0]
            if target_color == 'Wild':
                starts = [solver._encode(*position) for position in robots.values()]
            else:
                starts = [solver._encode(*robots[target_color])]
            if not any(distances[start] >= 0 for start in starts):
                return 0
            reachable_counts.append(sum(1 for distance in distances if distance >= 0))
        return min(reachable_counts)

    def _validate_round_chain(
        self,
        board_matrix,
        robots,
        targets,
        config,
        cancel_callback=None,
        deadline=None,
    ):
        if config.get('full_session_planner'):
            return self._validate_full_session_round_chain(
                board_matrix,
                robots,
                targets,
                config,
                cancel_callback=cancel_callback,
                deadline=deadline,
            )
        if config.get('adaptive_target_assignment'):
            return self._validate_adaptive_round_chain(
                board_matrix,
                robots,
                targets,
                config,
                cancel_callback=cancel_callback,
                deadline=deadline,
            )

        def validation_cancelled():
            return (
                self._cancelled(cancel_callback)
                or (deadline is not None and time.perf_counter() >= deadline)
            )

        solver = RicochetSolver(board_matrix)
        current_robots = robots.copy()
        remaining = list(targets.items())
        rounds = []
        blocked_targets = set()

        for round_index in range(config['rounds']):
            if validation_cancelled():
                return '__cancelled__' if self._cancelled(cancel_callback) else None

            candidates = [
                item for item in remaining
                if item[0] not in blocked_targets
            ]
            random.shuffle(candidates)
            target_steps = config['round_target_steps']
            candidates.sort(
                key=lambda item: abs(
                    self._relaxed_target_distance(solver, current_robots, item) - min(2, target_steps)
                )
            )
            accepted = []

            for target_name, target_pos in candidates[:config['candidate_pool']]:
                if validation_cancelled():
                    return '__cancelled__' if self._cancelled(cancel_callback) else None
                target_color = target_name.split('_')[0]
                steps, path = solver.solve(
                    current_robots,
                    target_color,
                    target_pos,
                    max_depth=config['round_max_depth'],
                    max_states=config['max_states'],
                    cancel_callback=validation_cancelled,
                )
                if steps == -2:
                    return '__cancelled__' if self._cancelled(cancel_callback) else None
                if (
                    steps < 0
                    and solver.last_stats.get('states_expanded', 0) >= config['max_states']
                ):
                    blocked_targets.add(target_name)
                moved_robots = sorted({color for color, _ in path})
                if (
                    steps < config['round_min_steps']
                    or len(moved_robots) < config['round_min_robots']
                ):
                    continue
                accepted.append((
                    abs(steps - target_steps),
                    -len(moved_robots),
                    -steps,
                    target_name,
                    target_pos,
                    path,
                    moved_robots,
                ))
                if accepted:
                    break

            if not accepted:
                return None

            (
                _,
                _,
                negative_steps,
                target_name,
                target_pos,
                path,
                moved_robots,
            ) = min(accepted)
            steps = -negative_steps
            current_robots = solver.apply_path(current_robots, path)
            rounds.append({
                'target': target_name,
                'steps': steps,
                'path': path,
                'moved_robots': moved_robots,
                'moved_robot_count': len(moved_robots),
                'end_robots': current_robots.copy(),
                'states_expanded': solver.last_stats.get('states_expanded', 0),
            })
            remaining = [item for item in remaining if item[0] != target_name]

        return {'rounds': rounds, 'targets': targets}

    def _validate_adaptive_round_chain(
        self,
        board_matrix,
        robots,
        targets,
        config,
        cancel_callback=None,
        deadline=None,
    ):
        def validation_cancelled():
            return (
                self._cancelled(cancel_callback)
                or (deadline is not None and time.perf_counter() >= deadline)
            )

        solver = RicochetSolver(board_matrix)
        current_robots = robots.copy()
        available_names = {quadrant: [] for quadrant in QUADRANTS}
        available_positions = {quadrant: [] for quadrant in QUADRANTS}
        for target_name, position in targets.items():
            quadrant = self._cell_quadrant(position)
            available_names[quadrant].append(target_name)
            available_positions[quadrant].append(position)

        final_targets = {}
        rounds = []
        blocked_candidates = set()

        for round_index in range(config['rounds']):
            if validation_cancelled():
                return '__cancelled__' if self._cancelled(cancel_callback) else None

            candidates = []
            for quadrant in QUADRANTS:
                for target_name in available_names[quadrant]:
                    target_color = target_name.split('_')[0]
                    for target_pos in available_positions[quadrant]:
                        candidate_key = (target_color, target_pos)
                        if candidate_key in blocked_candidates:
                            continue
                        relaxed = self._relaxed_target_distance(
                            solver,
                            current_robots,
                            (target_name, target_pos),
                        )
                        if target_color == 'Wild':
                            manhattan = min(
                                abs(r - target_pos[0]) + abs(c - target_pos[1])
                                for r, c in current_robots.values()
                            )
                        else:
                            r, c = current_robots[target_color]
                            manhattan = abs(r - target_pos[0]) + abs(c - target_pos[1])
                        candidates.append((
                            -relaxed,
                            -manhattan,
                            random.random(),
                            target_name,
                            target_pos,
                        ))

            candidates.sort()
            accepted = None
            checked_keys = set()
            for _, _, _, target_name, target_pos in candidates:
                if validation_cancelled():
                    return '__cancelled__' if self._cancelled(cancel_callback) else None
                target_color = target_name.split('_')[0]
                candidate_key = (target_color, target_pos)
                if candidate_key in checked_keys:
                    continue
                checked_keys.add(candidate_key)
                if len(checked_keys) > config['candidate_pool']:
                    break

                steps, path = solver.solve(
                    current_robots,
                    target_color,
                    target_pos,
                    max_depth=config['round_max_depth'],
                    max_states=config['max_states'],
                    cancel_callback=validation_cancelled,
                )
                if steps == -2:
                    return '__cancelled__' if self._cancelled(cancel_callback) else None
                if (
                    steps < 0
                    and solver.last_stats.get('states_expanded', 0) >= config['max_states']
                ):
                    blocked_candidates.add(candidate_key)
                moved_robots = sorted({color for color, _ in path})
                if (
                    steps < config['round_min_steps']
                    or len(moved_robots) < config['round_min_robots']
                ):
                    continue
                accepted = (
                    target_name,
                    target_pos,
                    steps,
                    path,
                    moved_robots,
                )
                break

            if accepted is None:
                return None

            target_name, target_pos, steps, path, moved_robots = accepted
            quadrant = self._cell_quadrant(target_pos)
            final_targets[target_name] = target_pos
            available_names[quadrant].remove(target_name)
            available_positions[quadrant].remove(target_pos)
            current_robots = solver.apply_path(current_robots, path)
            rounds.append({
                'target': target_name,
                'steps': steps,
                'path': path,
                'moved_robots': moved_robots,
                'moved_robot_count': len(moved_robots),
                'end_robots': current_robots.copy(),
                'states_expanded': solver.last_stats.get('states_expanded', 0),
            })

        for quadrant in QUADRANTS:
            random.shuffle(available_names[quadrant])
            random.shuffle(available_positions[quadrant])
            final_targets.update(zip(
                available_names[quadrant],
                available_positions[quadrant],
            ))

        return {'rounds': rounds, 'targets': final_targets}

    def _validate_full_session_round_chain(
        self,
        board_matrix,
        robots,
        targets,
        config,
        cancel_callback=None,
        deadline=None,
    ):
        """
        Assign all target colors globally, then plan a smooth 17-round session.

        The assignment uses dynamic programming over the required color counts,
        based on relaxed slide distance and geometric separation. The order is
        selected from exact shortest paths at every round, with a small
        exhaustive search reserved for the final rounds where greedy scheduling
        is most likely to collapse.
        """
        def validation_cancelled():
            return (
                self._cancelled(cancel_callback)
                or (deadline is not None and time.perf_counter() >= deadline)
            )

        solver = RicochetSolver(board_matrix)
        assigned_targets = self._assign_targets_by_structural_difficulty(
            solver,
            robots,
            targets,
            config,
            validation_cancelled,
        )
        if assigned_targets == '__cancelled__':
            return '__cancelled__' if self._cancelled(cancel_callback) else None
        if not assigned_targets:
            return None
        if config.get('session_beam_width'):
            return self._plan_full_session_beam(
                solver,
                robots,
                assigned_targets,
                config,
                validation_cancelled,
            )

        current_robots = robots.copy()
        remaining = list(assigned_targets)
        rounds = []
        greedy_rounds = config['rounds'] - config['tail_search_rounds']

        while len(rounds) < greedy_rounds:
            if validation_cancelled():
                return '__cancelled__' if self._cancelled(cancel_callback) else None

            candidates = []
            previous_steps = rounds[-1]['steps'] if rounds else config['round_target_steps']
            for target_name in remaining:
                target_pos = assigned_targets[target_name]
                target_color = target_name.split('_')[0]
                steps, path = solver.solve(
                    current_robots,
                    target_color,
                    target_pos,
                    max_depth=config['round_max_depth'],
                    max_states=config['max_states'],
                    cancel_callback=validation_cancelled,
                )
                if steps == -2:
                    return '__cancelled__' if self._cancelled(cancel_callback) else None
                moved_robots = sorted({color for color, _ in path})
                if not self._round_meets_session_floor(
                    steps,
                    len(moved_robots),
                    previous_steps,
                    config,
                ):
                    continue
                candidates.append((
                    self._session_round_score(
                        steps,
                        len(moved_robots),
                        previous_steps,
                        config,
                    ),
                    target_name,
                    steps,
                    path,
                    moved_robots,
                    solver.last_stats.get('states_expanded', 0),
                ))

            if not candidates:
                return None

            (
                _,
                target_name,
                steps,
                path,
                moved_robots,
                states_expanded,
            ) = min(candidates)
            current_robots = solver.apply_path(current_robots, path)
            rounds.append({
                'target': target_name,
                'steps': steps,
                'path': path,
                'moved_robots': moved_robots,
                'moved_robot_count': len(moved_robots),
                'end_robots': current_robots.copy(),
                'states_expanded': states_expanded,
            })
            remaining.remove(target_name)

        tail = self._search_session_tail(
            solver,
            current_robots,
            remaining,
            assigned_targets,
            rounds[-1]['steps'],
            config,
            validation_cancelled,
        )
        if tail == '__cancelled__':
            return '__cancelled__' if self._cancelled(cancel_callback) else None
        if tail is None:
            return None
        rounds.extend(tail)

        steps = [item['steps'] for item in rounds]
        if max(steps) - min(steps) > config['max_session_step_range']:
            return None
        if sum(steps) / len(steps) < config['min_session_average_steps']:
            return None
        return {'rounds': rounds, 'targets': assigned_targets}

    def _plan_full_session_beam(
        self,
        solver,
        robots,
        targets,
        config,
        cancel_callback,
    ):
        beam = [{
            'robots': robots.copy(),
            'remaining': tuple(targets),
            'rounds': [],
            'score': 0.0,
        }]
        solve_cache = {}

        for _ in range(config['rounds']):
            next_beam = []
            for node in beam:
                if cancel_callback():
                    return '__cancelled__'
                previous_steps = (
                    node['rounds'][-1]['steps']
                    if node['rounds']
                    else config['round_target_steps']
                )
                robot_key = tuple(sorted(node['robots'].items()))
                for target_name in node['remaining']:
                    cache_key = (robot_key, target_name)
                    cached = solve_cache.get(cache_key)
                    if cached is None:
                        target_color = target_name.split('_')[0]
                        steps, path = solver.solve(
                            node['robots'],
                            target_color,
                            targets[target_name],
                            max_depth=config['round_max_depth'],
                            max_states=config['max_states'],
                            cancel_callback=cancel_callback,
                        )
                        if steps == -2:
                            return '__cancelled__'
                        cached = (
                            steps,
                            path,
                            solver.last_stats.get('states_expanded', 0),
                        )
                        solve_cache[cache_key] = cached
                    steps, path, states_expanded = cached
                    moved_robots = sorted({color for color, _ in path})
                    if not self._round_meets_session_floor(
                        steps,
                        len(moved_robots),
                        previous_steps,
                        config,
                    ):
                        continue
                    end_robots = solver.apply_path(node['robots'], path)
                    round_score = self._session_round_score(
                        steps,
                        len(moved_robots),
                        previous_steps,
                        config,
                    )
                    round_data = {
                        'target': target_name,
                        'steps': steps,
                        'path': path,
                        'moved_robots': moved_robots,
                        'moved_robot_count': len(moved_robots),
                        'end_robots': end_robots.copy(),
                        'states_expanded': states_expanded,
                    }
                    next_beam.append({
                        'robots': end_robots,
                        'remaining': tuple(
                            name for name in node['remaining']
                            if name != target_name
                        ),
                        'rounds': node['rounds'] + [round_data],
                        'score': node['score'] + round_score,
                    })

            if not next_beam:
                return None

            deduplicated = {}
            for node in sorted(next_beam, key=lambda item: item['score']):
                key = (
                    tuple(sorted(node['robots'].items())),
                    node['remaining'],
                )
                if key not in deduplicated:
                    deduplicated[key] = node
            beam = list(deduplicated.values())[:config['session_beam_width']]

        valid = []
        for node in beam:
            steps = [item['steps'] for item in node['rounds']]
            if max(steps) - min(steps) > config['max_session_step_range']:
                continue
            if sum(steps) / len(steps) < config['min_session_average_steps']:
                continue
            valid.append(node)
        if not valid:
            return None
        best = min(valid, key=lambda item: item['score'])
        return {'rounds': best['rounds'], 'targets': targets}

    def _assign_targets_by_structural_difficulty(
        self,
        solver,
        robots,
        targets,
        config,
        cancel_callback,
    ):
        colors = ('Red', 'Blue', 'Green', 'Yellow', 'Wild')
        names_by_color = {
            color: [
                name for name in targets
                if name.split('_')[0] == color
            ]
            for color in colors
        }
        positions = tuple(targets.values())
        scores = {}
        for color in colors:
            for position in positions:
                if cancel_callback():
                    return '__cancelled__'
                target_name = names_by_color[color][0]
                relaxed = self._relaxed_target_distance(
                    solver,
                    robots,
                    (target_name, position),
                )
                if color == 'Wild':
                    manhattan = min(
                        abs(r - position[0]) + abs(c - position[1])
                        for r, c in robots.values()
                    )
                else:
                    r, c = robots[color]
                    manhattan = abs(r - position[0]) + abs(c - position[1])
                scores[(color, position)] = relaxed * 8 + manhattan

        quotas = tuple(len(names_by_color[color]) for color in colors)
        states = {(0, 0, 0, 0, 0): (0, [])}
        for position in positions:
            next_states = {}
            for counts, (total_score, assignments) in states.items():
                for color_index, color in enumerate(colors):
                    if counts[color_index] >= quotas[color_index]:
                        continue
                    next_counts = list(counts)
                    next_counts[color_index] += 1
                    next_counts = tuple(next_counts)
                    candidate = (
                        total_score + scores[(color, position)],
                        assignments + [(color, position)],
                    )
                    keep_candidate = next_counts not in next_states
                    if not keep_candidate:
                        if config.get('target_assignment') == 'easier':
                            keep_candidate = candidate[0] < next_states[next_counts][0]
                        else:
                            keep_candidate = candidate[0] > next_states[next_counts][0]
                    if keep_candidate:
                        next_states[next_counts] = candidate
            states = next_states

        if quotas not in states:
            return None
        assigned = {}
        available_names = {
            color: list(names)
            for color, names in names_by_color.items()
        }
        for color, position in states[quotas][1]:
            assigned[available_names[color].pop()] = position
        return assigned

    def _round_meets_session_floor(
        self,
        steps,
        moved_count,
        previous_steps,
        config,
    ):
        return (
            steps >= config['session_min_steps']
            and steps <= config.get('round_max_steps', steps)
            and moved_count >= config['session_min_robots']
            and previous_steps - steps <= config['max_round_step_drop']
        )

    def _session_round_score(
        self,
        steps,
        moved_count,
        previous_steps,
        config,
    ):
        score = abs(steps - config['round_target_steps'])
        score += abs(moved_count - 3) * 2.5
        score += max(0, abs(steps - previous_steps) - 1) * 3
        return score

    def _search_session_tail(
        self,
        solver,
        robots,
        remaining,
        targets,
        previous_steps,
        config,
        cancel_callback,
    ):
        best = None

        def search(current_robots, names, prior_steps, path_rounds, score):
            nonlocal best
            if cancel_callback():
                return
            if not names:
                candidate = (score, path_rounds)
                if best is None or candidate[0] < best[0]:
                    best = candidate
                return

            for target_name in names:
                target_color = target_name.split('_')[0]
                steps, path = solver.solve(
                    current_robots,
                    target_color,
                    targets[target_name],
                    max_depth=config['round_max_depth'],
                    max_states=config['max_states'],
                    cancel_callback=cancel_callback,
                )
                if steps < 0:
                    continue
                moved_robots = sorted({color for color, _ in path})
                if not self._round_meets_session_floor(
                    steps,
                    len(moved_robots),
                    prior_steps,
                    config,
                ):
                    continue
                round_score = self._session_round_score(
                    steps,
                    len(moved_robots),
                    prior_steps,
                    config,
                )
                if best is not None and score + round_score >= best[0]:
                    continue
                end_robots = solver.apply_path(current_robots, path)
                round_data = {
                    'target': target_name,
                    'steps': steps,
                    'path': path,
                    'moved_robots': moved_robots,
                    'moved_robot_count': len(moved_robots),
                    'end_robots': end_robots.copy(),
                    'states_expanded': solver.last_stats.get('states_expanded', 0),
                }
                search(
                    end_robots,
                    [name for name in names if name != target_name],
                    steps,
                    path_rounds + [round_data],
                    score + round_score,
                )

        search(robots, remaining, previous_steps, [], 0.0)
        if cancel_callback():
            return '__cancelled__'
        return best[1] if best else None

    def _relaxed_target_distance(self, solver, robots, target_item):
        target_name, target_pos = target_item
        distances = solver._get_relaxed_distances(solver._encode(*target_pos))
        target_color = target_name.split('_')[0]
        if target_color == 'Wild':
            values = [distances[solver._encode(*position)] for position in robots.values()]
            valid = [value for value in values if value >= 0]
            return min(valid) if valid else 0
        value = distances[solver._encode(*robots[target_color])]
        return value if value >= 0 else 0

    def _structural_metrics(self, board_matrix, h_walls, v_walls, targets):
        quadrant_counts = {quadrant: 0 for quadrant in QUADRANTS}
        for position in targets.values():
            quadrant_counts[self._cell_quadrant(position)] += 1

        wall_quadrants = {quadrant: 0 for quadrant in QUADRANTS}
        for r, c in h_walls:
            wall_quadrants[self._cell_quadrant((r, c))] += 1
        for r, c in v_walls:
            wall_quadrants[self._cell_quadrant((r, c))] += 1

        positions = list(targets.values())
        min_spacing = min(
            abs(a[0] - b[0]) + abs(a[1] - b[1])
            for index, a in enumerate(positions)
            for b in positions[index + 1:]
        )
        symmetry_score = self._rotational_symmetry_score(h_walls, v_walls)
        max_cluster = self._max_wall_cluster(h_walls, v_walls)

        return BoardQualityMetrics(
            wall_count=len(h_walls) + len(v_walls),
            target_quadrant_balance=max(quadrant_counts.values()) - min(quadrant_counts.values()),
            wall_quadrant_balance=max(wall_quadrants.values()) - min(wall_quadrants.values()),
            min_target_spacing=min_spacing,
            min_reachable_cells=0,
            solved_targets=0,
            average_steps=0.0,
            max_steps=0,
            symmetry_score=symmetry_score,
            max_wall_cluster=max_cluster,
            validated_rounds=0,
            total_round_steps=0,
        )

    def _rotational_symmetry_score(self, h_walls, v_walls):
        transformed_h = {
            (GRID_SIZE - 2 - r, GRID_SIZE - 1 - c)
            for r, c in h_walls
        }
        transformed_v = {
            (GRID_SIZE - 1 - r, GRID_SIZE - 2 - c)
            for r, c in v_walls
        }
        original = {('h', *wall) for wall in h_walls} | {('v', *wall) for wall in v_walls}
        transformed = (
            {('h', *wall) for wall in transformed_h}
            | {('v', *wall) for wall in transformed_v}
        )
        union = original | transformed
        return len(original & transformed) / len(union) if union else 1.0

    def _max_wall_cluster(self, h_walls, v_walls):
        segments = []
        for r, c in h_walls:
            segments.append(((r + 1, c), (r + 1, c + 1)))
        for r, c in v_walls:
            segments.append(((r, c + 1), (r + 1, c + 1)))

        by_endpoint = {}
        for index, segment in enumerate(segments):
            for endpoint in segment:
                by_endpoint.setdefault(endpoint, []).append(index)

        visited = set()
        largest = 0
        for start in range(len(segments)):
            if start in visited:
                continue
            stack = [start]
            visited.add(start)
            size = 0
            while stack:
                current = stack.pop()
                size += 1
                for endpoint in segments[current]:
                    for neighbor in by_endpoint[endpoint]:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            stack.append(neighbor)
            largest = max(largest, size)
        return largest

    def _cell_quadrant(self, position):
        r, c = position
        if r < 8 and c < 8:
            return 'tl'
        if r < 8 and c >= 8:
            return 'tr'
        if r >= 8 and c < 8:
            return 'bl'
        return 'br'

    def _too_close_to_used(self, position, used_cells, min_distance=2):
        r, c = position
        return any(abs(r - ur) + abs(c - uc) < min_distance for ur, uc in used_cells)

    def _make_result(self, mode, h_walls, v_walls, targets, robots, metrics, rounds, layout_name):
        round_steps = [item['steps'] for item in rounds]
        max_step_drop = max(
            (
                previous - current
                for previous, current in zip(round_steps, round_steps[1:])
            ),
            default=0,
        )
        return {
            'h_walls': sorted(h_walls),
            'v_walls': sorted(v_walls),
            'targets': targets,
            'robot_positions': robots,
            'solved_steps': metrics.max_steps,
            'difficulty': mode,
            'grid_size': GRID_SIZE,
            'validated_target_order': [item['target'] for item in rounds],
            'validation_rounds': [
                {
                    'target': item['target'],
                    'steps': item['steps'],
                    'path': item['path'],
                    'moved_robots': item['moved_robots'],
                    'moved_robot_count': item['moved_robot_count'],
                    'end_robots': item['end_robots'],
                    'states_expanded': item['states_expanded'],
                    'features': item.get('features', {}),
                }
                for item in rounds
            ],
            'quality': {
                'generator': (
                    'structured_motif_v2_session_beam'
                    if self.CONFIGS[mode].get('full_session_planner')
                    else 'structured_motif_v1'
                ),
                'layout_template': layout_name,
                'wall_count': metrics.wall_count,
                'average_steps': round(metrics.average_steps, 2),
                'max_steps': metrics.max_steps,
                'round_step_range': max(round_steps) - min(round_steps),
                'max_round_step_drop': max_step_drop,
                'total_round_steps': metrics.total_round_steps,
                'validated_rounds': metrics.validated_rounds,
                'round_min_steps': min(item['steps'] for item in rounds),
                'round_min_moved_robots': min(item['moved_robot_count'] for item in rounds),
                'required_min_steps': self.CONFIGS[mode]['round_min_steps'],
                'required_max_steps': self.CONFIGS[mode].get('round_max_steps'),
                'required_min_moved_robots': self.CONFIGS[mode]['round_min_robots'],
                'target_quadrant_balance': metrics.target_quadrant_balance,
                'wall_quadrant_balance': metrics.wall_quadrant_balance,
                'min_target_spacing': metrics.min_target_spacing,
                'min_reachable_cells': metrics.min_reachable_cells,
                'symmetry_score': round(metrics.symmetry_score, 3),
                'max_wall_cluster': metrics.max_wall_cluster,
            },
        }

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
        for wall_type, reflections in DIAGONAL_REFLECTIONS.items():
            safe = True
            for in_direction, out_direction in reflections.items():
                if self._can_enter_diagonal_cell(board, cell, in_direction) and board[r][c][out_direction]:
                    safe = False
                    break
            if safe:
                safe_types.append(wall_type)
        return safe_types

    def _random_diagonal_walls(self, board=None):
        board = board or build_board_matrix()
        colors = ['Red', 'Blue', 'Green', 'Yellow']
        cells = [
            (r, c)
            for r in range(2, 14)
            for c in range(2, 14)
            if (r, c) not in CENTER_CELLS
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
