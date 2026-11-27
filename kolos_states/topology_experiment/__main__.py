"""Run new topologies: python -B -m kolos_states.topology_experiment."""
from __future__ import annotations

import argparse
from pathlib import Path

from .suite import run_suite


def main() -> None:
    """Default to ten unseen graphs per family, disjoint from previous experiments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('tests/desktop-output/topology-20261110'))
    parser.add_argument('--seed-start', type=int, default=3000)
    parser.add_argument('--worlds', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.worlds <= 100:
        parser.error('--worlds must be 1..100 per family')
    run_suite(args.output, list(range(args.seed_start, args.seed_start + args.worlds)))


if __name__ == '__main__':
    main()
