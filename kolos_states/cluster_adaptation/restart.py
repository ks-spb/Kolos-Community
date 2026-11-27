"""A fresh interpreter reads only the stored revised memory and frozen task cases."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from ..cluster_replay.corpus import digest, save
from ..cluster_replay.isolation import offline_host
from .controllers import trial


def main() -> None:
    """No model, runtime profile or business state is accessed by this worker."""
    directory = Path(sys.argv[1])
    learned = json.loads((directory / 'learned-v2.json').read_text(encoding='utf-8'))
    cases = json.loads((directory / 'heldout.json').read_text(encoding='utf-8'))
    before = digest(learned)
    with offline_host():
        rows = [trial(case, 'clean', 'kolos', learned, True, layout=100 + i)
                for i, case in enumerate(cases)]
    save(directory / 'restart.json', dict(pid=os.getpid(), learned_hash=before,
        graph_unchanged=digest(learned) == before, rows=rows))


if __name__ == '__main__':
    main()
