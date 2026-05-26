from collections import deque


class RicochetSolver:
    def __init__(self, board, grid_size=16, diagonal_walls=None):
        self.board = board
        self.grid_size = grid_size
        self.diagonal_walls = diagonal_walls or {}
        self._color_empty_adj = {}
        self._color_rev_adj = {}
        self.empty_adj = {}
        self.rev_adj = {}
        self._build_empty_adj('__default__')
        self.empty_adj = self._color_empty_adj['__default__']
        self.rev_adj = self._color_rev_adj['__default__']

    def _build_empty_adj(self, color='__default__'):
        if color in self._color_empty_adj:
            return

        adj = {}
        for r in range(self.grid_size):
            for c in range(self.grid_size):
                adj[(r, c)] = []
                for direction in ['top', 'bottom', 'left', 'right']:
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
        Exact breadth-first solver. If it returns a non-negative step count, that
        count is the minimum number of moves for the provided board state.

        Return codes:
        - steps >= 0: solved
        - -1: no solution found within optional limits
        - -2: cancelled by cancel_callback
        """
        colors = tuple(sorted(robots_dict.keys()))
        start_state = tuple(robots_dict[color] for color in colors)
        target_pos = tuple(target_pos)

        def is_goal(state):
            if target_color == 'Wild':
                return target_pos in state
            try:
                return state[colors.index(target_color)] == target_pos
            except ValueError:
                return False

        if is_goal(start_state):
            return 0, []

        q = deque([start_state])
        visited = {start_state}
        parent = {}
        depth = {start_state: 0}
        states_expanded = 0

        while q:
            if cancel_callback and cancel_callback():
                return -2, []

            state = q.popleft()
            curr_depth = depth[state]
            states_expanded += 1

            if progress_callback and states_expanded % progress_interval == 0:
                progress_callback(states_expanded, curr_depth)

            if max_states is not None and states_expanded > max_states:
                return -1, []
            if max_depth is not None and curr_depth >= max_depth:
                continue

            occupied_all = set(state)
            state_by_color = dict(zip(colors, state))

            for color in colors:
                r, c = state_by_color[color]
                robot_index = colors.index(color)
                occupied = occupied_all - {(r, c)}

                for direction in ['top', 'bottom', 'left', 'right']:
                    nr, nc = self.get_slide_endpoint(r, c, direction, occupied, color=color)
                    if (nr, nc) == (r, c):
                        continue

                    next_state = list(state)
                    next_state[robot_index] = (nr, nc)
                    next_state = tuple(next_state)

                    if next_state in visited:
                        continue

                    visited.add(next_state)
                    parent[next_state] = (state, (color, direction))
                    depth[next_state] = curr_depth + 1

                    if is_goal(next_state):
                        return curr_depth + 1, self._reconstruct_path(parent, next_state)

                    q.append(next_state)

        return -1, []

    def _reconstruct_path(self, parent, end_state):
        path = []
        state = end_state
        while state in parent:
            state, move = parent[state]
            path.append(move)
        path.reverse()
        return path
