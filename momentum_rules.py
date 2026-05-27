from dataclasses import dataclass, field


DIRECTION_DELTAS = {
    'top': (-1, 0),
    'bottom': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}


@dataclass
class MomentumMoveResult:
    moved: bool
    robots: dict
    changed_colors: list = field(default_factory=list)
    events: list = field(default_factory=list)
    animation_steps: list = field(default_factory=list)


def _next_pos(pos, direction):
    dr, dc = DIRECTION_DELTAS[direction]
    return pos[0] + dr, pos[1] + dc


def _wall_blocks(board, pos, direction):
    r, c = pos
    return board[r][c][direction]


def _occupant_at(robots, pos, ignore_color=None):
    for color, robot_pos in robots.items():
        if color != ignore_color and robot_pos == pos:
            return color
    return None


def resolve_momentum_move(board, robots, color, direction):
    """
    Resolve one v3 momentum move.

    Rules:
    - The active robot must move at least one cell before it can push another robot.
    - Momentum equals the active robot's travelled distance before first robot collision.
    - Passive robots move in the same direction, spending one momentum per cell.
    - Hitting a wall absorbs all remaining momentum.
    - Hitting another robot transfers the remaining momentum to that robot.
    """
    if color not in robots or direction not in DIRECTION_DELTAS:
        return MomentumMoveResult(False, dict(robots))

    start_robots = {name: tuple(pos) for name, pos in robots.items()}
    next_robots = dict(start_robots)
    curr = next_robots[color]
    travelled = 0
    events = []
    animation_steps = []

    while True:
        if _wall_blocks(board, curr, direction):
            break

        nxt = _next_pos(curr, direction)
        hit_color = _occupant_at(next_robots, nxt, ignore_color=color)
        if hit_color:
            if travelled == 0:
                return MomentumMoveResult(False, start_robots)
            next_robots[color] = curr
            animation_steps.append({'color': color, 'to': curr})
            events.append({
                'type': 'robot_collision',
                'source': color,
                'target': hit_color,
                'momentum': travelled,
            })
            _propagate_momentum(
                board,
                next_robots,
                hit_color,
                direction,
                travelled,
                events,
                animation_steps,
            )
            break

        curr = nxt
        travelled += 1

    if travelled > 0 and next_robots[color] == start_robots[color]:
        next_robots[color] = curr
        animation_steps.append({'color': color, 'to': curr})

    changed = [
        name for name in next_robots
        if next_robots[name] != start_robots.get(name)
    ]
    return MomentumMoveResult(bool(changed), next_robots, changed, events, animation_steps)


def _append_animation_step(animation_steps, color, start_pos, end_pos):
    if start_pos != end_pos:
        animation_steps.append({'color': color, 'to': end_pos})


def _propagate_momentum(board, robots, color, direction, momentum, events, animation_steps):
    current_color = color
    energy = momentum
    segment_start = robots[current_color]

    while energy > 0:
        curr = robots[current_color]

        if _wall_blocks(board, curr, direction):
            _append_animation_step(animation_steps, current_color, segment_start, curr)
            events.append({
                'type': 'wall_absorb',
                'source': current_color,
                'remaining_momentum': energy,
            })
            return

        nxt = _next_pos(curr, direction)
        hit_color = _occupant_at(robots, nxt, ignore_color=current_color)
        if hit_color:
            _append_animation_step(animation_steps, current_color, segment_start, curr)
            events.append({
                'type': 'robot_collision',
                'source': current_color,
                'target': hit_color,
                'momentum': energy,
            })
            current_color = hit_color
            segment_start = robots[current_color]
            continue

        robots[current_color] = nxt
        energy -= 1

    _append_animation_step(animation_steps, current_color, segment_start, robots[current_color])
