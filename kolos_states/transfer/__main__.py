"""CLI: python -m kolos_states.transfer --seed-start 2000 --worlds 20."""
from __future__ import annotations

import argparse
from pathlib import Path

from .suite import run_suite


def main() -> None:
    """Use fresh seeds 2000..2019, disjoint from development and the pre-fix experiment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('tests/desktop-output/transfer-selection-v2'))
    parser.add_argument('--worlds', type=int, default=20)
    parser.add_argument('--seed-start', type=int, default=2000)
    args = parser.parse_args()
    if not 1 <= args.worlds <= 100:
        parser.error('--worlds must be 1..100')
    run_suite(args.output, list(range(args.seed_start, args.seed_start + args.worlds)))


if __name__ == '__main__':
    main()
