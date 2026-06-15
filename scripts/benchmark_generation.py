"""Benchmark structured map generation with reproducible random seeds."""

import argparse
import json
import os
import random
import statistics
import sys
import time


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from board_generator import BoardGenerator


def benchmark_mode(mode, runs, seed):
    records = []
    for offset in range(runs):
        run_seed = seed + offset
        random.seed(run_seed)
        started_at = time.perf_counter()
        result = BoardGenerator().generate(mode)
        elapsed = time.perf_counter() - started_at
        quality = result.get('quality', {}) if result else {}
        record = {
            'mode': mode,
            'seed': run_seed,
            'success': bool(result),
            'seconds': round(elapsed, 4),
            'validated_rounds': quality.get('validated_rounds', 0),
            'total_round_steps': quality.get('total_round_steps', 0),
            'round_min_steps': quality.get('round_min_steps', 0),
            'round_min_moved_robots': quality.get('round_min_moved_robots', 0),
            'round_step_range': quality.get('round_step_range', 0),
            'max_round_step_drop': quality.get('max_round_step_drop', 0),
            'wall_count': quality.get('wall_count', 0),
            'symmetry_score': quality.get('symmetry_score', 0),
            'max_wall_cluster': quality.get('max_wall_cluster', 0),
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False))
    return records


def summarize(records):
    successful = [record for record in records if record['success']]
    seconds = [record['seconds'] for record in successful]
    return {
        'runs': len(records),
        'successes': len(successful),
        'success_rate': round(len(successful) / len(records), 3) if records else 0,
        'mean_seconds': round(statistics.mean(seconds), 4) if seconds else None,
        'median_seconds': round(statistics.median(seconds), 4) if seconds else None,
        'max_seconds': max(seconds) if seconds else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--modes',
        nargs='+',
        default=['normal', 'hard', 'expert', 'v3_momentum', 'super_expert'],
    )
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()

    all_records = {}
    for mode in args.modes:
        records = benchmark_mode(mode, args.runs, args.seed)
        all_records[mode] = summarize(records)
    print(json.dumps({'summary': all_records}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
