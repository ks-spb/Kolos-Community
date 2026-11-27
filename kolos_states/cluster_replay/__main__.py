"""Run a local operation replay from an explicit input or private installation settings."""
from __future__ import annotations

import argparse
from pathlib import Path

from .settings import read_settings
from .suite import run


def main() -> None:
    """Resolve local defaults, then run the requested offline comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frozen-corpus', type=Path)
    parser.add_argument('--teaching-product-id', type=int)
    parser.add_argument('--with-model', action='store_true')
    parser.add_argument('--hermes-install', type=Path)
    args = parser.parse_args()
    settings = read_settings()
    source = args.source if args.source is not None else settings.source
    install = args.hermes_install if args.hermes_install is not None else settings.hermes_install
    teaching_product_id = (args.teaching_product_id if args.teaching_product_id is not None
                           else settings.teaching_product_id)
    if source is None and args.frozen_corpus is None:
        parser.error('provide --source or --frozen-corpus')
    if args.with_model and install is None:
        parser.error('provide --hermes-install when enabling the model')
    run(args.output, source, args.with_model, install, args.frozen_corpus,
        teaching_product_id=teaching_product_id)


if __name__ == '__main__':
    main()
