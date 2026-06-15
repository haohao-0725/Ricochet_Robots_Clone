"""Shared playability contracts for every game mode."""

from copy import deepcopy


MODE_CONTRACTS = {
    'easy': {
        'map_policy': 'static',
        'rounds': 17,
        'min_steps': 0,
        'max_steps': None,
        'min_moved_robots': 1,
        'max_round_step_drop': None,
        'target_progression': 'guided',
    },
    'normal': {
        'map_policy': 'certified_catalog',
        'rounds': 17,
        'min_steps': 5,
        'max_steps': 9,
        'target_steps': 7,
        'min_moved_robots': 2,
        'max_round_step_drop': 3,
        'max_session_step_range': 4,
    },
    'hard': {
        'map_policy': 'certified_catalog',
        'rounds': 17,
        'min_steps': 9,
        'max_steps': 13,
        'target_steps': 10,
        'min_moved_robots': 3,
        'max_round_step_drop': 3,
        'max_session_step_range': 4,
    },
    'expert': {
        'map_policy': 'certified_catalog',
        'rounds': 17,
        'min_steps': 6,
        'max_steps': 12,
        'target_steps': 8,
        'min_moved_robots': 2,
        'max_round_step_drop': 3,
        'min_diagonal_reflections': 1,
        'min_mechanic_rounds': 8,
    },
    'v3_momentum': {
        'map_policy': 'certified_catalog',
        'rounds': 17,
        'min_steps': 4,
        'max_steps': 13,
        'target_steps': 9,
        'min_moved_robots': 1,
        'max_round_step_drop': 3,
        'min_momentum_collisions': 1,
        'min_mechanic_rounds': 15,
    },
    'super_expert': {
        'map_policy': 'certified_catalog',
        'rounds': 17,
        'min_steps': 9,
        'max_steps': 14,
        'target_steps': 11,
        'min_moved_robots': 3,
        'max_round_step_drop': 3,
        'max_session_step_range': 4,
        'min_average_steps': 9.5,
        'min_average_robot_switches': 4.0,
        'min_average_support_moves': 3.5,
    },
}


def get_mode_contract(mode):
    if mode not in MODE_CONTRACTS:
        raise KeyError(f'Unknown difficulty mode: {mode}')
    return deepcopy(MODE_CONTRACTS[mode])


def round_meets_contract(round_data, contract):
    steps = round_data.get('steps', -1)
    if steps < contract.get('min_steps', 0):
        return False
    max_steps = contract.get('max_steps')
    if max_steps is not None and steps > max_steps:
        return False
    if round_data.get('moved_robot_count', 0) < contract.get('min_moved_robots', 1):
        return False
    return True


def session_meets_contract(rounds, contract):
    if len(rounds) != contract.get('rounds', len(rounds)):
        return False
    if not all(round_meets_contract(item, contract) for item in rounds):
        return False

    steps = [item['steps'] for item in rounds]
    max_drop = contract.get('max_round_step_drop')
    if max_drop is not None and any(
        previous - current > max_drop
        for previous, current in zip(steps, steps[1:])
    ):
        return False

    max_range = contract.get('max_session_step_range')
    if max_range is not None and max(steps) - min(steps) > max_range:
        return False

    if (
        sum(steps) / len(steps)
        < contract.get('min_average_steps', 0)
    ):
        return False
    average_switches = sum(
        item.get('features', {}).get('robot_switches', 0)
        for item in rounds
    ) / len(rounds)
    if average_switches < contract.get('min_average_robot_switches', 0):
        return False
    average_support = sum(
        item.get('features', {}).get('support_moves', 0)
        for item in rounds
    ) / len(rounds)
    if average_support < contract.get('min_average_support_moves', 0):
        return False

    required_mechanic_rounds = contract.get('min_mechanic_rounds', 0)
    if required_mechanic_rounds:
        mechanic_rounds = 0
        for item in rounds:
            features = item.get('features', {})
            if (
                features.get('diagonal_reflections', 0)
                >= contract.get('min_diagonal_reflections', 0)
                and features.get('momentum_collisions', 0)
                >= contract.get('min_momentum_collisions', 0)
            ):
                mechanic_rounds += 1
        if mechanic_rounds < required_mechanic_rounds:
            return False
    return True
