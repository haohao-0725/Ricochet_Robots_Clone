"""Graph-based wall-layout metrics shared by generators and validators."""

from collections import Counter, defaultdict
from dataclasses import dataclass


Wall = tuple[str, int, int]
Point = tuple[int, int]


@dataclass(frozen=True)
class WallComponentMetrics:
    """Shape metrics for one endpoint-connected wall component."""

    walls: frozenset[Wall]
    edge_count: int
    vertex_count: int
    cycle_rank: int
    branch_excess: int
    max_degree: int
    max_straight_run: int
    bbox_height: int
    bbox_width: int

    def complexity_score(
        self,
        max_edges=4,
        max_cycle_rank=0,
        max_branch_excess=1,
        max_degree=3,
        max_straight_run=2,
    ):
        """Zero means L/T-like; larger values indicate visual complexity."""
        return (
            max(0, self.edge_count - max_edges)
            + 2 * max(0, self.cycle_rank - max_cycle_rank)
            + 2 * max(0, self.branch_excess - max_branch_excess)
            + max(0, self.max_degree - max_degree)
            + max(0, self.max_straight_run - max_straight_run)
        )


def wall_endpoints(wall):
    orientation, r, c = wall
    if orientation == 'h':
        return (r + 1, c), (r + 1, c + 1)
    if orientation == 'v':
        return (r, c + 1), (r + 1, c + 1)
    raise ValueError(f'Unknown wall orientation: {orientation!r}')


def wall_component_metrics(h_walls, v_walls):
    """Return deterministic metrics for endpoint-connected wall segments."""
    walls = (
        [('h', int(r), int(c)) for r, c in h_walls]
        + [('v', int(r), int(c)) for r, c in v_walls]
    )
    endpoints = [wall_endpoints(wall) for wall in walls]
    by_endpoint = defaultdict(list)
    for index, segment_endpoints in enumerate(endpoints):
        for endpoint in segment_endpoints:
            by_endpoint[endpoint].append(index)

    visited = set()
    components = []
    for start in range(len(walls)):
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        indices = []
        while stack:
            current = stack.pop()
            indices.append(current)
            for endpoint in endpoints[current]:
                for neighbor in by_endpoint[endpoint]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)

        component_walls = frozenset(walls[index] for index in indices)
        vertices = {
            endpoint
            for index in indices
            for endpoint in endpoints[index]
        }
        degrees = Counter(
            endpoint
            for index in indices
            for endpoint in endpoints[index]
        )
        rows = [point[0] for point in vertices]
        columns = [point[1] for point in vertices]
        edge_count = len(indices)
        components.append(WallComponentMetrics(
            walls=component_walls,
            edge_count=edge_count,
            vertex_count=len(vertices),
            cycle_rank=edge_count - len(vertices) + 1,
            branch_excess=sum(max(0, degree - 2) for degree in degrees.values()),
            max_degree=max(degrees.values(), default=0),
            max_straight_run=_max_straight_run(component_walls),
            bbox_height=max(rows) - min(rows) if rows else 0,
            bbox_width=max(columns) - min(columns) if columns else 0,
        ))

    return sorted(
        components,
        key=lambda item: (
            -item.edge_count,
            -item.cycle_rank,
            -item.branch_excess,
            sorted(item.walls),
        ),
    )


def _max_straight_run(walls):
    horizontal = defaultdict(set)
    vertical = defaultdict(set)
    for orientation, r, c in walls:
        if orientation == 'h':
            horizontal[r + 1].add(c)
        else:
            vertical[c + 1].add(r)

    longest = 0
    for groups in (horizontal, vertical):
        for starts in groups.values():
            previous = None
            current = 0
            for start in sorted(starts):
                current = current + 1 if previous is not None and start == previous + 1 else 1
                longest = max(longest, current)
                previous = start
    return longest


def is_clean_wall_layout(
    h_walls,
    v_walls,
    max_component_edges=4,
    max_cycle_rank=0,
    max_branch_excess=1,
    max_degree=3,
    max_straight_run=2,
):
    """Whether every connected wall group remains a simple L/T-like motif."""
    return all(
        component.edge_count <= max_component_edges
        and component.cycle_rank <= max_cycle_rank
        and component.branch_excess <= max_branch_excess
        and component.max_degree <= max_degree
        and component.max_straight_run <= max_straight_run
        for component in wall_component_metrics(h_walls, v_walls)
    )


def wall_layout_summary(h_walls, v_walls):
    components = wall_component_metrics(h_walls, v_walls)
    return {
        'wall_component_count': len(components),
        'max_wall_cluster': max((item.edge_count for item in components), default=0),
        'max_wall_cycle_rank': max((item.cycle_rank for item in components), default=0),
        'max_wall_branch_excess': max((item.branch_excess for item in components), default=0),
        'max_wall_degree': max((item.max_degree for item in components), default=0),
        'max_wall_straight_run': max((item.max_straight_run for item in components), default=0),
        'complex_wall_component_count': sum(
            item.complexity_score() > 0 for item in components
        ),
        'wall_layout_complexity': sum(
            item.complexity_score() for item in components
        ),
    }
