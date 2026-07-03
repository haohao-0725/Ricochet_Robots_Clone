"""Chaos mode movement rules: momentum + diagonal walls + portals + sand.

One move resolver combining every mechanic on a (typically 25x25) board:

- Momentum base (from momentum_rules): the active robot slides; hitting a
  robot after travelling >=1 cell transfers its momentum, shunting the hit
  robot (and possibly a chain) in the same direction.
- Diagonal walls ({(r, c): {'type': '/', 'color': 'Red'}}): a robot entering
  the cell is reflected 90 degrees unless the wall is its own colour
  (Silver always reflects). Applies to pushed robots too.
- Portals ({(r, c): {'color': 'White', 'exit': (r2, c2)}}): a robot entering
  a portal it can use (White = anyone, coloured = matching robot only)
  teleports to the paired exit and keeps sliding in the same direction.
  A portal is inert when its exit cell is occupied. Teleporting costs no
  momentum. A robot never re-teleports from the exit cell it arrives on.
- Sand cells (set of (r, c)): any robot entering sand stops there
  immediately; for pushed robots the sand absorbs all remaining momentum.

Tile effects trigger on ENTERING a cell, in the order sand -> portal ->
diagonal. Board generation never stacks two specials on one cell.
"""

from dataclasses import dataclass, field


DIRECTION_DELTAS = {
    'top': (-1, 0),
    'bottom': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}

REFLECT = {
    '/': {'top': 'right', 'bottom': 'left', 'left': 'bottom', 'right': 'top'},
    '\\': {'top': 'left', 'bottom': 'right', 'left': 'top', 'right': 'bottom'},
}

# hard safety guard against pathological reflect/portal cycles
MAX_TRAVEL_STEPS = 2500


@dataclass
class ChaosMoveResult:
    moved: bool
    robots: dict
    changed_colors: list = field(default_factory=list)
    events: list = field(default_factory=list)
    animation_steps: list = field(default_factory=list)


def _next_pos(pos, direction):
    dr, dc = DIRECTION_DELTAS[direction]
    return pos[0] + dr, pos[1] + dc


def _occupant_at(robots, pos, ignore_color=None):
    for color, robot_pos in robots.items():
        if color != ignore_color and robot_pos == pos:
            return color
    return None


def _tile_effects(board_ctx, robots, color, pos, direction, events,
                  animation_steps, arrived_by_teleport):
    """Apply on-enter tile effects at `pos`. Returns (pos, direction, stop)."""
    diagonal_walls, portals, sand_cells = board_ctx
    if pos in sand_cells:
        events.append({'type': 'sand_stop', 'color': color, 'cell': pos})
        return pos, direction, True
    portal = None if arrived_by_teleport else portals.get(pos)
    if portal is not None and portal['color'] in ('White', color):
        exit_cell = tuple(portal['exit'])
        if exit_cell != pos and _occupant_at(robots, exit_cell, ignore_color=color) is None:
            events.append({
                'type': 'teleport',
                'color': color,
                'from': pos,
                'to': exit_cell,
            })
            animation_steps.append({'color': color, 'to': pos})
            # the exit cell may itself carry sand/diagonal effects (never a
            # second usable portal hop: arrived_by_teleport suppresses it)
            return _tile_effects(board_ctx, robots, color, exit_cell, direction,
                                 events, animation_steps, True)
    diagonal = diagonal_walls.get(pos)
    if diagonal is not None and (diagonal['color'] != color or color == 'Silver'):
        new_direction = REFLECT[diagonal['type']][direction]
        events.append({'type': 'reflect', 'color': color, 'cell': pos})
        animation_steps.append({'color': color, 'to': pos})
        return pos, new_direction, False
    return pos, direction, False


def resolve_chaos_move(board, diagonal_walls, portals, sand_cells,
                       robots, color, direction):
    """Resolve one chaos move. Same contract as resolve_momentum_move."""
    if color not in robots or direction not in DIRECTION_DELTAS:
        return ChaosMoveResult(False, dict(robots))

    board_ctx = (diagonal_walls or {}, portals or {}, set(sand_cells or ()))
    start_robots = {name: tuple(pos) for name, pos in robots.items()}
    next_robots = dict(start_robots)
    curr = next_robots[color]
    curr_direction = direction
    travelled = 0
    steps_guard = 0
    events = []
    animation_steps = []

    ended_by_collision = False
    while True:
        steps_guard += 1
        if steps_guard > MAX_TRAVEL_STEPS:
            break
        r, c = curr
        if board[r][c][curr_direction]:
            break
        nxt = _next_pos(curr, curr_direction)
        hit_color = _occupant_at(next_robots, nxt, ignore_color=color)
        if hit_color:
            if travelled == 0:
                return ChaosMoveResult(False, start_robots)
            animation_steps.append({'color': color, 'to': curr})
            events.append({
                'type': 'robot_collision',
                'source': color,
                'target': hit_color,
                'momentum': travelled,
            })
            _propagate_chaos_momentum(
                board, board_ctx, next_robots, hit_color, curr_direction,
                travelled, events, animation_steps,
            )
            ended_by_collision = True
            break
        curr = nxt
        travelled += 1
        next_robots[color] = curr
        curr, curr_direction, stop = _tile_effects(
            board_ctx, next_robots, color, curr, curr_direction,
            events, animation_steps, False,
        )
        next_robots[color] = curr
        if stop:
            break

    if travelled > 0 and not ended_by_collision:
        animation_steps.append({'color': color, 'to': curr})

    changed = [
        name for name in next_robots
        if next_robots[name] != start_robots.get(name)
    ]
    if not changed:
        return ChaosMoveResult(False, start_robots)
    return ChaosMoveResult(True, next_robots, changed, events, animation_steps)


def _propagate_chaos_momentum(board, board_ctx, robots, color, direction,
                              momentum, events, animation_steps):
    current_color = color
    current_direction = direction
    energy = momentum
    steps_guard = 0

    while energy > 0:
        steps_guard += 1
        if steps_guard > MAX_TRAVEL_STEPS:
            return
        curr = robots[current_color]
        r, c = curr
        if board[r][c][current_direction]:
            events.append({
                'type': 'wall_absorb',
                'source': current_color,
                'remaining_momentum': energy,
            })
            animation_steps.append({'color': current_color, 'to': curr})
            return
        nxt = _next_pos(curr, current_direction)
        hit_color = _occupant_at(robots, nxt, ignore_color=current_color)
        if hit_color:
            events.append({
                'type': 'robot_collision',
                'source': current_color,
                'target': hit_color,
                'momentum': energy,
            })
            animation_steps.append({'color': current_color, 'to': curr})
            current_color = hit_color
            continue
        robots[current_color] = nxt
        energy -= 1
        new_pos, new_direction, stop = _tile_effects(
            board_ctx, robots, current_color, nxt, current_direction,
            events, animation_steps, False,
        )
        robots[current_color] = new_pos
        current_direction = new_direction
        if stop:
            animation_steps.append({'color': current_color, 'to': new_pos})
            return

    animation_steps.append({'color': current_color, 'to': robots[current_color]})
