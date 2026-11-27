"""Run the local restoration adaptation comparison from a saved corpus."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..cluster_replay.settings import read_settings
from .suite import run


def main() -> None:
    """Resolve local defaults and execute only the simulation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--teaching-product-id', type=int)
    parser.add_argument('--with-model', action='store_true')
    parser.add_argument('--hermes-install', type=Path)
    args = parser.parse_args()
    settings = read_settings()
    corpus = args.corpus if args.corpus is not None else settings.corpus
    install = args.hermes_install if args.hermes_install is not None else settings.hermes_install
    teaching_product_id = (args.teaching_product_id if args.teaching_product_id is not None
                           else settings.teaching_product_id)
    if corpus is None:
        parser.error('provide --corpus')
    if args.with_model and install is None:
        parser.error('provide --hermes-install when enabling the model')
    run(args.output, corpus, args.with_model, install, teaching_product_id=teaching_product_id)


if __name__ == '__main__':
    main()
