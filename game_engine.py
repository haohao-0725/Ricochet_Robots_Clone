import random
import json
import os
from ricochet_robots_board_data import build_board_matrix, TARGETS, GRID_SIZE
from momentum_rules import resolve_momentum_move

# Bump whenever the generated-board format or the certified map set changes in a
# way that makes previously saved boards stale (e.g. the old 32x32 Super Expert
# layout). Saved slots stamped with an older value are treated as incompatible
# and regenerated instead of being silently restored.
CURRENT_BOARD_SCHEMA_VERSION = 3


class GameEngine:
    def __init__(self):
        # Game State
        self.grid_size = 16
        self.board = build_board_matrix()
        self.targets = list(TARGETS.items()) # list of (name, (r, c))
        random.shuffle(self.targets)
        self.current_target_idx = 0
        self.completed_targets = set()
        self.skipped_targets = set()
        
        self.test_mode = False
        self.backup_state = None
        
        self.robots = {
            'Red': (0, 0),
            'Blue': (0, 15),
            'Green': (15, 0),
            'Yellow': (15, 15)
        }
        self.start_robots = {}
        self.move_history = []
        self.steps = 0
        self.win_count = 0
        self.difficulty_mode = 'easy'
        self.diagonal_walls = {}
        self.validated_target_order = []
        self.validation_rounds = []
        self.generated_quality = {}
        self.saved_slots = {}
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        
        self.reset_to_static_board(full_reset=True)

    def reset_game(self, full_reset=True):
        if self.difficulty_mode == 'easy':
            self.reset_to_static_board(full_reset)
        else:
            # Only reset targets and robots to start positions for the current generated map
            if full_reset:
                self.win_count = 0
                self.completed_targets.clear()
                self.skipped_targets.clear()
                if self.validated_target_order:
                    by_name = dict(self.targets)
                    self.targets = [
                        (name, by_name[name])
                        for name in self.validated_target_order
                        if name in by_name
                    ]
                else:
                    random.shuffle(self.targets)
                self.current_target_idx = 0
            self.test_mode = False
            self.backup_state = None
            self.steps = 0
            self.move_history = []
            self.robots = self.start_robots.copy()
            self.last_move_changed_colors = []
            self.last_move_animation_steps = []

    def reset_to_static_board(self, full_reset=True):
        from ricochet_robots_board_data import TARGETS, build_board_matrix
        self.grid_size = 16
        self.board = build_board_matrix()
        self.targets = list(TARGETS.items())
        if full_reset:
            self.win_count = 0
        self.current_target_idx = 0
        random.shuffle(self.targets)
        self.completed_targets.clear()
        self.skipped_targets.clear()
        self.test_mode = False
        self.backup_state = None
        self.steps = 0
        self.move_history = []
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        
        # 固定機器人的起始位置 (依照使用者要求)
        self.robots = {
            'Blue': (7, 6),
            'Yellow': (6, 8),
            'Green': (8, 9),
            'Red': (9, 7)
        }
        self.start_robots = self.robots.copy()
        self.difficulty_mode = 'easy'
        self.diagonal_walls = {}
        self.validated_target_order = []
        self.validation_rounds = []
        self.generated_quality = {}
        self.current_target_idx = self._pick_starting_target_idx()

    def reset_to_v3_momentum_board(self, full_reset=True):
        from ricochet_robots_board_data import TARGETS, build_board_matrix
        self.grid_size = 16
        self.board = build_board_matrix()
        self.diagonal_walls = {}
        self.validated_target_order = []
        self.validation_rounds = []
        self.generated_quality = {}
        self.targets = list(TARGETS.items())
        if full_reset:
            self.win_count = 0
        self.current_target_idx = 0
        random.shuffle(self.targets)
        self.completed_targets.clear()
        self.skipped_targets.clear()
        self.test_mode = False
        self.backup_state = None
        self.steps = 0
        self.move_history = []
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        self.robots = {
            'Blue': (7, 6),
            'Yellow': (6, 8),
            'Green': (8, 9),
            'Red': (9, 7)
        }
        self.start_robots = self.robots.copy()
        self.difficulty_mode = 'v3_momentum'
        self.current_target_idx = 0

    def load_generated_board(self, board_data):
        from ricochet_robots_board_data import build_board_matrix_from_walls
        self.grid_size = board_data.get('grid_size', 16)
        self.board = build_board_matrix_from_walls(
            board_data['h_walls'], board_data['v_walls'], grid_size=self.grid_size
        )
        self.diagonal_walls = board_data.get('diagonal_walls', {})

        target_items = list(board_data['targets'].items())
        self.validated_target_order = list(board_data.get('validated_target_order', []))
        self.validation_rounds = list(board_data.get('validation_rounds', []))
        self.generated_quality = dict(board_data.get('quality', {}))
        if self.validated_target_order:
            by_name = dict(target_items)
            ordered = [
                (name, by_name[name])
                for name in self.validated_target_order
                if name in by_name
            ]
            used_names = {name for name, _ in ordered}
            remaining = [item for item in target_items if item[0] not in used_names]
            random.shuffle(remaining)
            self.targets = ordered + remaining
        else:
            self.targets = target_items
            random.shuffle(self.targets)
        self.current_target_idx = 0
        self.completed_targets.clear()
        self.skipped_targets.clear()
        self.steps = 0
        self.move_history = []
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        self.robots = board_data['robot_positions'].copy()
        self.start_robots = self.robots.copy()
        self.difficulty_mode = board_data.get('difficulty', 'normal')
        self.current_target_idx = 0 if self.validated_target_order else self._pick_starting_target_idx()

    def get_current_target(self):
        return self.targets[self.current_target_idx]

    def is_target_retired(self, target_name):
        return target_name in self.completed_targets

    def _normalized_diagonal_walls(self):
        normalized = {}
        for key, value in self.diagonal_walls.items():
            if isinstance(key, list):
                normalized[tuple(key)] = value
            elif isinstance(key, str):
                try:
                    import ast
                    normalized[ast.literal_eval(key)] = value
                except Exception:
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized

    def _target_solve_steps(self, target_name, target_pos, max_depth=22, max_states=220000):
        steps, _ = self._target_solve_metrics(
            target_name,
            target_pos,
            max_depth=max_depth,
            max_states=max_states,
        )
        return steps

    def _target_solve_metrics(self, target_name, target_pos, max_depth=22, max_states=220000):
        try:
            from solver import RicochetSolver
            target_color = target_name.split('_')[0]
            solver = RicochetSolver(
                self.board,
                grid_size=self.grid_size,
                diagonal_walls=self._normalized_diagonal_walls(),
                movement_mode=self._solver_movement_mode(),
            )
            steps, path = solver.solve(
                self.robots.copy(),
                target_color,
                target_pos,
                max_depth=max_depth,
                max_states=max_states
            )
            moved_count = len({color for color, _ in path}) if steps >= 0 else 0
            return steps, moved_count
        except Exception:
            return -1, 0

    def _target_is_solvable(self, target_name, target_pos):
        return self._target_solve_steps(target_name, target_pos) >= 0

    def _pick_starting_target_idx(self):
        return self._pick_target_idx(exclude_current=False)

    def _pick_next_target_idx(self):
        preferred_idx = self._pick_validated_target_idx()
        if preferred_idx is not None:
            return preferred_idx
        return self._pick_target_idx(exclude_current=True)

    def _pick_validated_target_idx(self):
        best_fallback = None
        best_fallback_key = None
        required_steps = self.generated_quality.get('required_min_steps', 0)
        required_max_steps = self.generated_quality.get('required_max_steps')
        required_robots = self.generated_quality.get('required_min_moved_robots', 0)
        for order_index, target_name in enumerate(self.validated_target_order):
            if self.is_target_retired(target_name):
                continue
            for idx, (name, pos) in enumerate(self.targets):
                if name != target_name or idx == self.current_target_idx:
                    continue
                if order_index > 0 and order_index <= len(self.validation_rounds):
                    expected_previous_end = self.validation_rounds[
                        order_index - 1
                    ].get('end_robots', {})
                    normalized_previous_end = {
                        color: tuple(position)
                        for color, position in expected_previous_end.items()
                    }
                    if normalized_previous_end == self.robots:
                        return idx
                steps, moved_count = self._target_solve_metrics(name, pos)
                if steps < 0:
                    continue
                if (
                    steps >= required_steps
                    and (required_max_steps is None or steps <= required_max_steps)
                    and moved_count >= required_robots
                ):
                    return idx
                # Keep the hardest still-solvable target as a fallback so a player
                # who diverges from the certified route never collapses the
                # difficulty to a trivial 1-2 step target. Prefer meeting the
                # robot floor first, then maximise steps, then moved robots.
                fallback_key = (
                    moved_count >= required_robots,
                    steps,
                    moved_count,
                )
                if best_fallback_key is None or fallback_key > best_fallback_key:
                    best_fallback_key = fallback_key
                    best_fallback = idx
        return best_fallback

    def _ordered_uncompleted_target_indices(self, exclude_current=False):
        candidates = []
        offsets = range(1, len(self.targets)) if exclude_current else range(len(self.targets))
        for offset in offsets:
            idx = (self.current_target_idx + offset) % len(self.targets)
            name, _ = self.targets[idx]
            if not self.is_target_retired(name):
                candidates.append(idx)
        if exclude_current and not candidates:
            current_name, _ = self.get_current_target()
            if not self.is_target_retired(current_name):
                candidates.append(self.current_target_idx)
        return candidates

    def _pick_target_idx(self, exclude_current=False):
        candidates = self._ordered_uncompleted_target_indices(exclude_current=exclude_current)
        if not candidates:
            return self.current_target_idx

        if self.difficulty_mode == 'easy':
            return self._pick_easy_progression_target(candidates)

        needs_full_solve = []
        within_three_steps = []
        unknown = []

        for idx in candidates:
            name, pos = self.targets[idx]
            steps = self._target_solve_steps(name, pos, max_depth=3, max_states=50000)
            if 0 <= steps <= 3:
                within_three_steps.append(idx)
            else:
                needs_full_solve.append(idx)

        for idx in needs_full_solve:
            name, pos = self.targets[idx]
            steps = self._target_solve_steps(name, pos)
            if steps > 3:
                return idx
            if 0 <= steps <= 3:
                within_three_steps.append(idx)
            else:
                unknown.append(idx)

        for group in (within_three_steps, unknown):
            if group:
                return group[0]

        return self.current_target_idx

    def _pick_easy_progression_target(self, candidates):
        completed = len(self.completed_targets)
        if completed < 5:
            preferred_min, preferred_max = 2, 5
        elif completed < 11:
            preferred_min, preferred_max = 3, 7
        else:
            preferred_min, preferred_max = 4, 10

        scored = []
        fallback = []
        for idx in candidates:
            name, pos = self.targets[idx]
            steps = self._target_solve_steps(
                name,
                pos,
                max_depth=preferred_max,
                max_states=100000,
            )
            if preferred_min <= steps <= preferred_max:
                scored.append((abs(steps - preferred_max), steps, idx))
            elif steps >= 0:
                fallback.append((abs(steps - preferred_max), steps, idx))
        if scored:
            return min(scored)[2]
        if fallback:
            return min(fallback)[2]
        return candidates[0]

    def _solver_movement_mode(self):
        return 'momentum' if self.difficulty_mode == 'v3_momentum' else 'classic'

    def move_robot(self, color, direction):
        if color not in self.robots: return False

        if self.difficulty_mode == 'v3_momentum':
            result = resolve_momentum_move(self.board, self.robots, color, direction)
            if not result.moved:
                self.last_move_changed_colors = []
                self.last_move_animation_steps = []
                return False

            self.move_history.append({'robots': self.robots.copy()})
            self.robots = result.robots
            self.last_move_changed_colors = result.changed_colors
            self.last_move_animation_steps = result.animation_steps
            self.steps += 1
            return True
        
        start_r, start_c = self.robots[color]
        curr_r, curr_c = start_r, start_c
        curr_direction = direction
        
        # curr_direction: 'top', 'bottom', 'left', 'right'
        while True:
            cell = self.board[curr_r][curr_c]
            if cell[curr_direction]: # hit wall
                break
                
            next_r, next_c = curr_r, curr_c
            if curr_direction == 'top': next_r -= 1
            elif curr_direction == 'bottom': next_r += 1
            elif curr_direction == 'left': next_c -= 1
            elif curr_direction == 'right': next_c += 1
            
            # Check if next cell is occupied by another robot
            collision = False
            for c, pos in self.robots.items():
                if pos == (next_r, next_c):
                    collision = True
                    break
            
            if collision:
                break
                
            curr_r, curr_c = next_r, next_c
            
            # 檢查新格子是否有斜向牆壁
            # 斜向牆壁字典格式: (r, c): {'type': '/', 'color': 'Red'}
            if (curr_r, curr_c) in self.diagonal_walls:
                d_wall = self.diagonal_walls[(curr_r, curr_c)]
                # 如果顏色不符（或者是銀色機器人），則發生反射
                if d_wall['color'] != color or color == 'Silver':
                    w_type = d_wall['type']
                    if curr_direction == 'top':
                        curr_direction = 'right' if w_type == '/' else 'left'
                    elif curr_direction == 'bottom':
                        curr_direction = 'left' if w_type == '/' else 'right'
                    elif curr_direction == 'left':
                        curr_direction = 'bottom' if w_type == '/' else 'top'
                    elif curr_direction == 'right':
                        curr_direction = 'top' if w_type == '/' else 'bottom'

        if (curr_r, curr_c) != (start_r, start_c):
            # Valid move
            self.move_history.append((color, start_r, start_c))
            self.robots[color] = (curr_r, curr_c)
            self.last_move_changed_colors = [color]
            self.last_move_animation_steps = [{'color': color, 'to': (curr_r, curr_c)}]
            self.steps += 1
            return True
        
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        return False

    def undo(self):
        if not self.move_history: return False
        previous = self.move_history.pop()
        if isinstance(previous, dict) and 'robots' in previous:
            self.robots = {k: tuple(v) for k, v in previous['robots'].items()}
        else:
            color, old_r, old_c = previous
            self.robots[color] = (old_r, old_c)
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        self.steps -= 1
        return True

    def check_win(self):
        target_name, target_pos = self.get_current_target()
        color_name, shape_name = target_name.split('_')
        
        if color_name == 'Wild': # Vortex
            # Any robot can arrive
            for pos in self.robots.values():
                if pos == target_pos:
                    return True
        else:
            if self.robots[color_name] == target_pos:
                return True
        return False
        
    def next_target(self, mark_completed=True):
        # Only completed targets count toward clearing the board.
        current_target_name = self.get_current_target()[0]
        if mark_completed:
            self.completed_targets.add(current_target_name)
        
        if len(self.completed_targets) >= len(self.targets):
            self.win_count += 1
            return True # 代表所有目標完成，破關
        
        next_idx = self._pick_validated_target_idx()
        if next_idx is None:
            next_idx = (
                self._pick_next_target_idx()
                if not mark_completed
                else self._pick_target_idx(exclude_current=False)
            )
        if next_idx is None or len(self.completed_targets) >= len(self.targets):
            self.win_count += 1
            return True

        self.current_target_idx = next_idx
        self.steps = 0
        self.move_history = []
        self.start_robots = self.robots.copy()
        return False
        
    def toggle_test_mode(self, enabled):
        self.test_mode = enabled
        if self.test_mode:
            # 備份狀態
            self.backup_state = {
                'robots': self.robots.copy(),
                'steps': self.steps,
                'move_history': self.move_history.copy()
            }
        else:
            self.backup_state = None

    def revert_test_mode(self):
        self.robots = self.start_robots.copy()
        self.steps = 0
        self.move_history = []
        self.last_move_changed_colors = []
        self.last_move_animation_steps = []
        return True

    def _serialize_current_state(self):
        state = {
            'version': 2,
            'difficulty_mode': self.difficulty_mode,
            'targets': self.targets,
            'current_target_idx': self.current_target_idx,
            'completed_targets': list(self.completed_targets),
            'skipped_targets': [],
            'robots': self.robots,
            'start_robots': self.start_robots,
            'steps': self.steps,
            'move_history': self.move_history,
            'win_count': self.win_count
        }
        if self.difficulty_mode != 'easy':
            h_walls = []
            v_walls = []
            for r in range(self.grid_size):
                for c in range(self.grid_size):
                    if r < self.grid_size - 1 and self.board[r][c]['bottom']:
                        h_walls.append([r, c])
                    if c < self.grid_size - 1 and self.board[r][c]['right']:
                        v_walls.append([r, c])
            state['generated_board'] = {
                'board_schema_version': CURRENT_BOARD_SCHEMA_VERSION,
                'h_walls': h_walls,
                'v_walls': v_walls,
                'diagonal_walls': {str(k): v for k, v in self.diagonal_walls.items()},
                'targets': dict(self.targets),
                'robot_positions': self.start_robots,
                'grid_size': self.grid_size,
                'difficulty': self.difficulty_mode,
                'validated_target_order': self.validated_target_order,
                'validation_rounds': self.validation_rounds,
                'quality': self.generated_quality,
            }
        return state

    def _read_save_document(self, filepath):
        if not os.path.exists(filepath):
            return {'version': 3, 'active_difficulty': self.difficulty_mode, 'win_count': self.win_count, 'slots': {}}
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('version') == 3:
            data.setdefault('slots', {})
            data.setdefault('win_count', self.win_count)
            data.setdefault('active_difficulty', self.difficulty_mode)
            return data

        mode = data.get('difficulty_mode', 'easy')
        return {
            'version': 3,
            'active_difficulty': mode,
            'win_count': data.get('win_count', self.win_count),
            'slots': {mode: data},
        }

    def save_state(self, filepath):
        state = self._serialize_current_state()
        try:
            document = self._read_save_document(filepath)
            document['version'] = 3
            document['active_difficulty'] = self.difficulty_mode
            document['win_count'] = self.win_count
            document.setdefault('slots', {})
            document['slots'][self.difficulty_mode] = state
            folder = os.path.dirname(filepath)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(document, f)
            self.saved_slots = document['slots']
            return True
        except Exception:
            return False

    def read_settings(self, filepath):
        defaults = {'music_enabled': True, 'sound_enabled': True}
        try:
            document = self._read_save_document(filepath)
            settings = document.get('settings', {})
            return {**defaults, **settings}
        except Exception:
            return defaults

    def load_record_summary(self, filepath):
        try:
            if not os.path.exists(filepath):
                return False
            document = self._read_save_document(filepath)
            self.win_count = document.get('win_count', self.win_count)
            self.saved_slots = document.get('slots', {})
            return True
        except Exception:
            return False

    def save_settings(self, filepath, settings):
        try:
            document = self._read_save_document(filepath)
            document['version'] = 3
            document['active_difficulty'] = self.difficulty_mode
            document['win_count'] = self.win_count
            document.setdefault('slots', {})
            current_settings = document.get('settings', {})
            current_settings.update(settings)
            document['settings'] = current_settings
            folder = os.path.dirname(filepath)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(document, f)
            self.saved_slots = document.get('slots', {})
            return True
        except Exception:
            return False

    def has_saved_slot(self, filepath, mode):
        try:
            document = self._read_save_document(filepath)
            return mode in document.get('slots', {})
        except Exception:
            return False

    def active_saved_difficulty(self, filepath):
        try:
            document = self._read_save_document(filepath)
            return document.get('active_difficulty')
        except Exception:
            return None

    def is_saved_slot_compatible(self, filepath, mode):
        """Return True only if the saved slot can still be restored as-is.

        Easy always uses the static board, so its slot is always compatible.
        Generated modes must carry the current board schema version and a
        16x16 grid; older saves (e.g. the legacy 32x32 Super Expert board) are
        rejected so the caller regenerates a fresh, certified board instead of
        restoring stale content.
        """
        try:
            document = self._read_save_document(filepath)
            slot = document.get('slots', {}).get(mode)
            if slot is None:
                return False
            if mode == 'easy':
                return True
            generated = slot.get('generated_board')
            if not generated:
                return False
            if generated.get('grid_size', 16) != 16:
                return False
            return generated.get('board_schema_version', 0) >= CURRENT_BOARD_SCHEMA_VERSION
        except Exception:
            return False

    def load_state(self, filepath, mode=None):
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                state = json.load(f)

            version = state.get('version', 1)
            if version == 3:
                self.saved_slots = state.get('slots', {})
                target_mode = mode or state.get('active_difficulty') or self.difficulty_mode
                slot = self.saved_slots.get(target_mode)
                if slot is None:
                    return False
                self._apply_state(slot)
                self.win_count = state.get('win_count', self.win_count)
                self.difficulty_mode = target_mode
                return True

            self._apply_state(state)
            return True
        except Exception as e:
            return False

    def _apply_state(self, state):
            version = state.get('version', 1)
            self.difficulty_mode = state.get('difficulty_mode', 'easy')
            
            if version == 1 or self.difficulty_mode == 'easy':
                self.reset_to_static_board(full_reset=False)
            elif version == 2 and 'generated_board' in state:
                gb = state['generated_board']
                # restore tuples for walls
                gb['h_walls'] = [tuple(w) for w in gb['h_walls']]
                gb['v_walls'] = [tuple(w) for w in gb['v_walls']]
                if 'diagonal_walls' in gb:
                    import ast
                    gb['diagonal_walls'] = {
                        ast.literal_eval(k) if isinstance(k, str) else tuple(k): v
                        for k, v in gb['diagonal_walls'].items()
                    }
                # restore tuple for targets
                gb['targets'] = {k: tuple(v) for k, v in gb['targets'].items()}
                # restore tuple for robot_positions
                gb['robot_positions'] = {k: tuple(v) for k, v in gb['robot_positions'].items()}
                gb['difficulty'] = self.difficulty_mode
                self.load_generated_board(gb)
                
            self.targets = [(t[0], tuple(t[1])) for t in state['targets']]
            self.current_target_idx = state['current_target_idx']
            self.completed_targets = set(state['completed_targets'])
            self.skipped_targets = set(state.get('skipped_targets', []))
            self.robots = {k: tuple(v) for k, v in state['robots'].items()}
            self.start_robots = {k: tuple(v) for k, v in state.get('start_robots', self.robots).items()}
            self.steps = state.get('steps', 0)
            self.move_history = state.get('move_history', [])
            self.win_count = state.get('win_count', 0)
            return True

    def clear_all_records(self, filepath=None):
        self.saved_slots = {}
        self.win_count = 0
        self.difficulty_mode = 'easy'
        self.reset_to_static_board(full_reset=True)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                return False
        return True
