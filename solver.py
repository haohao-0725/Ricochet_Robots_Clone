import heapq
import time
from collections import deque

from momentum_rules import resolve_momentum_move


DIRECTIONS = ('top', 'bottom', 'left', 'right')


class RicochetSolver:
    def __init__(self, board, grid_size=16, diagonal_walls=None, movement_mode='classic'):
        self.board = board
        self.grid_size = grid_size
        self.diagonal_walls = diagonal_walls or {}
        self.movement_mode = movement_mode
        self._color_empty_adj = {}
        self._color_rev_adj = {}
        self._relaxed_distance_cache = {}
        self._rays = self._build_rays()
        self._relaxed_reverse = self._build_relaxed_reverse()
        self.empty_adj = {}
        self.rev_adj = {}
        self.last_stats = {}
        self._build_empty_adj('__default__')
        self.empty_adj = self._color_empty_adj['__default__']
        self.rev_adj = self._color_rev_adj['__default__']

    def _build_rays(self):
        rays = [[None] * len(DIRECTIONS) for _ in range(self.grid_size * self.grid_size)]
        deltas = ((-1, 0), (1, 0), (0, -1), (0, 1))
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                start = self._encode(r, c)
                for direction_idx, direction in enumerate(DIRECTIONS):
                    dr, dc = deltas[direction_idx]
                    curr_r, curr_c = r, c
                    cells = []
                    while not self.board[curr_r][curr_c][direction]:
                        curr_r += dr
                        curr_c += dc
                        cells.append(self._encode(curr_r, curr_c))
                    rays[start][direction_idx] = tuple(cells)
        return tuple(tuple(row) for row in rays)

    def _encode(self, r, c):
        return r * self.grid_size + c

    def _build_relaxed_reverse(self):
        reverse = [[] for _ in range(self.grid_size * self.grid_size)]
        for start, rays in enumerate(self._rays):
            for ray in rays:
                for end in ray:
                    reverse[end].append(start)
        return tuple(tuple(predecessors) for predecessors in reverse)

    def _decode(self, cell):
        return divmod(cell, self.grid_size)

    def _build_empty_adj(self, color='__default__'):
        if color in self._color_empty_adj:
            return

        adj = {}
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                adj[(r, c)] = []
                for direction in DIRECTIONS:
                    nr, nc = self.get_slide_endpoint(r, c, direction, set(), color=color)
                    if (nr, nc) != (r, c):
                        adj[(r, c)].append((nr, nc))

        rev = {(r, c): [] for r in range(self.grid_size) for c in range(self.grid_size)}
        for start, endpoints in adj.items():
            for end in endpoints:
                rev[end].append(start)

        self._color_empty_adj[color] = adj
        self._color_rev_adj[color] = rev

    def get_slide_endpoint(self, r, c, direction, occupied, color='__default__'):
        curr_r, curr_c = r, c
        curr_direction = direction

        while True:
            cell = self.board[curr_r][curr_c]
            if cell[curr_direction]:
                break

            next_r, next_c = curr_r, curr_c
            if curr_direction == 'top':
                next_r -= 1
            elif curr_direction == 'bottom':
                next_r += 1
            elif curr_direction == 'left':
                next_c -= 1
            elif curr_direction == 'right':
                next_c += 1

            if (next_r, next_c) in occupied:
                break

            curr_r, curr_c = next_r, next_c

            if self.diagonal_walls and (curr_r, curr_c) in self.diagonal_walls:
                d_wall = self.diagonal_walls[(curr_r, curr_c)]
                if color == 'Silver' or d_wall['color'] != color:
                    w_type = d_wall['type']
                    if curr_direction == 'top':
                        curr_direction = 'right' if w_type == '/' else 'left'
                    elif curr_direction == 'bottom':
                        curr_direction = 'left' if w_type == '/' else 'right'
                    elif curr_direction == 'left':
                        curr_direction = 'bottom' if w_type == '/' else 'top'
                    elif curr_direction == 'right':
                        curr_direction = 'top' if w_type == '/' else 'bottom'

        return curr_r, curr_c

    def _get_h_table(self, target_r, target_c, color='__default__'):
        self._build_empty_adj(color)
        rev = self._color_rev_adj[color]
        h_table = {}
        q = deque([((target_r, target_c), 0)])
        h_table[(target_r, target_c)] = 0

        while q:
            curr, dist = q.popleft()
            for neighbor in rev[curr]:
                if neighbor not in h_table:
                    h_table[neighbor] = dist + 1
                    q.append((neighbor, dist + 1))
        return h_table

    def _get_relaxed_distances(self, target_cell):
        cached = self._relaxed_distance_cache.get(target_cell)
        if cached is not None:
            return cached

        cell_count = self.grid_size * self.grid_size
        distances = [-1] * cell_count
        distances[target_cell] = 0
        queue = deque([target_cell])
        while queue:
            cell = queue.popleft()
            next_distance = distances[cell] + 1
            for predecessor in self._relaxed_reverse[cell]:
                if distances[predecessor] == -1:
                    distances[predecessor] = next_distance
                    queue.append(predecessor)

        result = tuple(distances)
        self._relaxed_distance_cache[target_cell] = result
        return result

    def _slide_endpoint_fast(self, start, direction_idx, occupied_mask):
        endpoint = start
        for cell in self._rays[start][direction_idx]:
            if occupied_mask & (1 << cell):
                break
            endpoint = cell
        return endpoint

    def solve(
        self,
        robots_dict,
        target_color,
        target_pos,
        max_depth=None,
        max_states=None,
        cancel_callback=None,
        progress_callback=None,
        progress_interval=5000,
    ):
        """
        Return an exact shortest solution when steps >= 0.

        Classic boards without diagonal walls use an admissible A* search with
        canonical helper-robot states. Color-sensitive diagonal and momentum
        modes retain a labeled breadth-first search.

        Return codes:
        - steps >= 0: solved
        - -1: no solution found within optional limits
        - -2: cancelled by cancel_callback
        """
        started_at = time.perf_counter()
        if self.movement_mode == 'classic' and not self.diagonal_walls:
            result = self._solve_classic_astar(
                robots_dict,
                target_color,
                target_pos,
                max_depth=max_depth,
                max_states=max_states,
                cancel_callback=cancel_callback,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
        else:
            result = self._solve_labeled_bfs(
                robots_dict,
                target_color,
                target_pos,
                max_depth=max_depth,
                max_states=max_states,
                cancel_callback=cancel_callback,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
        self.last_stats['elapsed_seconds'] = time.perf_counter() - started_at
        return result

    def _solve_classic_astar(
        self,
        robots_dict,
        target_color,
        target_pos,
        max_depth,
        max_states,
        cancel_callback,
        progress_callback,
        progress_interval,
    ):
        target_cell = self._encode(*target_pos)
        labeled_start = {
            color: self._encode(*position)
            for color, position in robots_dict.items()
        }

        if target_color == 'Wild':
            start_state = tuple(sorted(labeled_start.values()))

            def is_goal(state):
                return target_cell in state

            def heuristic(state, distances):
                values = [distances[cell] for cell in state if distances[cell] >= 0]
                return min(values) if values else 0

            target_slot = None
        else:
            if target_color not in labeled_start:
                self.last_stats = {'algorithm': 'astar-canonical', 'states_expanded': 0, 'visited_states': 0}
                return -1, []
            helper_cells = sorted(
                cell for color, cell in labeled_start.items() if color != target_color
            )
            start_state = (labeled_start[target_color], *helper_cells)

            def is_goal(state):
                return state[0] == target_cell

            def heuristic(state, distances):
                distance = distances[state[0]]
                return distance if distance >= 0 else 0

            target_slot = 0

        if is_goal(start_state):
            self.last_stats = {'algorithm': 'astar-canonical', 'states_expanded': 0, 'visited_states': 1}
            return 0, []

        distances = self._get_relaxed_distances(target_cell)
        start_h = heuristic(start_state, distances)
        frontier = [(start_h, 0, start_state)]
        best_depth = {start_state: 0}
        parent = {}
        states_expanded = 0

        while frontier:
            if cancel_callback and cancel_callback():
                self.last_stats = {
                    'algorithm': 'astar-canonical',
                    'states_expanded': states_expanded,
                    'visited_states': len(best_depth),
                }
                return -2, []

            _, curr_depth, state = heapq.heappop(frontier)
            if best_depth.get(state) != curr_depth:
                continue
            if is_goal(state):
                abstract_path = self._reconstruct_abstract_path(parent, state)
                path = self._label_abstract_path(labeled_start, abstract_path)
                self.last_stats = {
                    'algorithm': 'astar-canonical',
                    'states_expanded': states_expanded,
                    'visited_states': len(best_depth),
                    'solution_depth': curr_depth,
                }
                return curr_depth, path

            states_expanded += 1
            if progress_callback and states_expanded % progress_interval == 0:
                progress_callback(states_expanded, curr_depth)
            if max_states is not None and states_expanded > max_states:
                break
            if max_depth is not None and curr_depth >= max_depth:
                continue

            occupied_mask = 0
            for cell in state:
                occupied_mask |= 1 << cell

            for slot, start in enumerate(state):
                blockers = occupied_mask & ~(1 << start)
                for direction_idx in range(len(DIRECTIONS)):
                    endpoint = self._slide_endpoint_fast(start, direction_idx, blockers)
                    if endpoint == start:
                        continue

                    if target_slot is not None and slot == target_slot:
                        next_state = (endpoint, *state[1:])
                    else:
                        helper_start = 0 if target_slot is None else 1
                        helpers = list(state[helper_start:])
                        helper_idx = slot - helper_start
                        helpers[helper_idx] = endpoint
                        helpers.sort()
                        next_state = tuple(helpers) if target_slot is None else (state[0], *helpers)

                    next_depth = curr_depth + 1
                    if next_depth >= best_depth.get(next_state, 1 << 30):
                        continue

                    best_depth[next_state] = next_depth
                    parent[next_state] = (state, start, direction_idx)
                    next_h = heuristic(next_state, distances)
                    heapq.heappush(frontier, (next_depth + next_h, next_depth, next_state))

        self.last_stats = {
            'algorithm': 'astar-canonical',
            'states_expanded': states_expanded,
            'visited_states': len(best_depth),
        }
        return -1, []

    def _reconstruct_abstract_path(self, parent, end_state):
        path = []
        state = end_state
        while state in parent:
            previous, start, direction_idx = parent[state]
            path.append((start, direction_idx))
            state = previous
        path.reverse()
        return path

    def _label_abstract_path(self, labeled_start, abstract_path):
        positions = dict(labeled_start)
        path = []
        for start, direction_idx in abstract_path:
            color = next(color for color, cell in positions.items() if cell == start)
            occupied_mask = 0
            for other_color, cell in positions.items():
                if other_color != color:
                    occupied_mask |= 1 << cell
            endpoint = self._slide_endpoint_fast(start, direction_idx, occupied_mask)
            positions[color] = endpoint
            path.append((color, DIRECTIONS[direction_idx]))
        return path

    def _solve_labeled_bfs(
        self,
        robots_dict,
        target_color,
        target_pos,
        max_depth,
        max_states,
        cancel_callback,
        progress_callback,
        progress_interval,
    ):
        colors = tuple(sorted(robots_dict.keys()))
        color_indices = {color: index for index, color in enumerate(colors)}
        start_state = tuple(robots_dict[color] for color in colors)
        target_pos = tuple(target_pos)

        def is_goal(state):
            if target_color == 'Wild':
                return target_pos in state
            target_index = color_indices.get(target_color)
            return target_index is not None and state[target_index] == target_pos

        if is_goal(start_state):
            self.last_stats = {'algorithm': 'bfs-labeled', 'states_expanded': 0, 'visited_states': 1}
            return 0, []

        queue = deque([(start_state, 0)])
        visited = {start_state}
        parent = {}
        states_expanded = 0

        while queue:
            if cancel_callback and cancel_callback():
                self.last_stats = {
                    'algorithm': 'bfs-labeled',
                    'states_expanded': states_expanded,
                    'visited_states': len(visited),
                }
                return -2, []

            state, curr_depth = queue.popleft()
            states_expanded += 1

            if progress_callback and states_expanded % progress_interval == 0:
                progress_callback(states_expanded, curr_depth)
            if max_states is not None and states_expanded > max_states:
                break
            if max_depth is not None and curr_depth >= max_depth:
                continue

            occupied_all = set(state)
            state_by_color = dict(zip(colors, state))

            for robot_index, color in enumerate(colors):
                r, c = state[robot_index]
                for direction in DIRECTIONS:
                    if self.movement_mode == 'momentum':
                        result = resolve_momentum_move(self.board, state_by_color, color, direction)
                        if not result.moved:
                            continue
                        next_state = tuple(result.robots[item_color] for item_color in colors)
                    else:
                        occupied = occupied_all - {(r, c)}
                        nr, nc = self.get_slide_endpoint(r, c, direction, occupied, color=color)
                        if (nr, nc) == (r, c):
                            continue
                        next_state_list = list(state)
                        next_state_list[robot_index] = (nr, nc)
                        next_state = tuple(next_state_list)

                    if next_state in visited:
                        continue

                    visited.add(next_state)
                    parent[next_state] = (state, (color, direction))
                    if is_goal(next_state):
                        path = self._reconstruct_path(parent, next_state)
                        self.last_stats = {
                            'algorithm': 'bfs-labeled',
                            'states_expanded': states_expanded,
                            'visited_states': len(visited),
                            'solution_depth': curr_depth + 1,
                        }
                        return curr_depth + 1, path
                    queue.append((next_state, curr_depth + 1))

        self.last_stats = {
            'algorithm': 'bfs-labeled',
            'states_expanded': states_expanded,
            'visited_states': len(visited),
        }
        return -1, []

    def apply_path(self, robots_dict, path):
        robots = {color: tuple(position) for color, position in robots_dict.items()}
        for color, direction in path:
            if self.movement_mode == 'momentum':
                result = resolve_momentum_move(self.board, robots, color, direction)
                if not result.moved:
                    raise ValueError(f'Invalid momentum path move: {color} {direction}')
                robots = result.robots
                continue
            r, c = robots[color]
            occupied = set(robots.values()) - {(r, c)}
            robots[color] = self.get_slide_endpoint(r, c, direction, occupied, color=color)
        return robots

    def analyze_path(self, robots_dict, path, target_color=None):
        """Replay a path and return difficulty and mechanic-use features."""
        robots = {color: tuple(position) for color, position in robots_dict.items()}
        moved_colors = []
        diagonal_reflections = 0
        momentum_collisions = 0
        momentum_chain_collisions = 0
        changed_robot_total = 0
        quadrant_transitions = 0

        for color, direction in path:
            start_positions = dict(robots)
            start = robots[color]
            if self.movement_mode == 'momentum':
                result = resolve_momentum_move(self.board, robots, color, direction)
                if not result.moved:
                    raise ValueError(f'Invalid momentum path move: {color} {direction}')
                collisions = [
                    event for event in result.events
                    if event.get('type') == 'robot_collision'
                ]
                momentum_collisions += len(collisions)
                momentum_chain_collisions += max(0, len(collisions) - 1)
                changed_robot_total += len(result.changed_colors)
                robots = result.robots
            else:
                occupied = set(robots.values()) - {start}
                end, reflections = self._trace_classic_move(
                    start,
                    direction,
                    occupied,
                    color,
                )
                robots[color] = end
                diagonal_reflections += reflections
                changed_robot_total += int(end != start)

            moved_colors.append(color)
            for changed_color, end in robots.items():
                before = start_positions.get(changed_color)
                if before is not None and self._quadrant(before) != self._quadrant(end):
                    quadrant_transitions += 1

        support_moves = sum(
            1 for color in moved_colors
            if target_color not in (None, 'Wild') and color != target_color
        )
        robot_switches = sum(
            previous != current
            for previous, current in zip(moved_colors, moved_colors[1:])
        )
        return {
            'end_robots': robots,
            'moved_robots': sorted(set(moved_colors)),
            'moved_robot_count': len(set(moved_colors)),
            'robot_switches': robot_switches,
            'support_moves': support_moves,
            'target_robot_moves': len(moved_colors) - support_moves,
            'diagonal_reflections': diagonal_reflections,
            'momentum_collisions': momentum_collisions,
            'momentum_chain_collisions': momentum_chain_collisions,
            'changed_robot_total': changed_robot_total,
            'quadrant_transitions': quadrant_transitions,
        }

    def _trace_classic_move(self, start, direction, occupied, color):
        curr_r, curr_c = start
        curr_direction = direction
        reflections = 0
        while True:
            if self.board[curr_r][curr_c][curr_direction]:
                break
            if curr_direction == 'top':
                next_r, next_c = curr_r - 1, curr_c
            elif curr_direction == 'bottom':
                next_r, next_c = curr_r + 1, curr_c
            elif curr_direction == 'left':
                next_r, next_c = curr_r, curr_c - 1
            else:
                next_r, next_c = curr_r, curr_c + 1
            if (next_r, next_c) in occupied:
                break
            curr_r, curr_c = next_r, next_c
            diagonal = self.diagonal_walls.get((curr_r, curr_c))
            if diagonal and (color == 'Silver' or diagonal['color'] != color):
                wall_type = diagonal['type']
                if curr_direction == 'top':
                    curr_direction = 'right' if wall_type == '/' else 'left'
                elif curr_direction == 'bottom':
                    curr_direction = 'left' if wall_type == '/' else 'right'
                elif curr_direction == 'left':
                    curr_direction = 'bottom' if wall_type == '/' else 'top'
                else:
                    curr_direction = 'top' if wall_type == '/' else 'bottom'
                reflections += 1
        return (curr_r, curr_c), reflections

    def _quadrant(self, position):
        half = self.grid_size // 2
        return position[0] >= half, position[1] >= half

    def _reconstruct_path(self, parent, end_state):
        path = []
        state = end_state
        while state in parent:
            state, move = parent[state]
            path.append(move)
        path.reverse()
        return path
