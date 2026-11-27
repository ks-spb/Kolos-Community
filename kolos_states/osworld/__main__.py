"""Run preflight, teaching or the paired OSWorld benchmark."""

from __future__ import annotations

import argparse
import logging
import subprocess
from importlib.metadata import PackageNotFoundError
from pathlib import Path

from ..ipc import atomic_json
from .gui import SCREEN_SIZE
from .manifest import REVISION, load_calibration, load_tasks
from .runner import (
    GNOME_START_TIMEOUT, RELEASE, VM_CPUS, VM_RAM, benchmark, desktop_session, guest_digest, image_digest,
    preflight, teach_curriculum,
)


def main() -> int:
    """Run the selected local benchmark operation and emit its artifact location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "teach", "run", "all"))
    parser.add_argument("--osworld", type=Path, required=True, help="clean pinned OSWorld source checkout")
    parser.add_argument("--vm-image", type=Path, required=True, help="official Ubuntu.qcow2 guest")
    parser.add_argument("--output", type=Path, default=Path("tests/desktop-output/osworld"))
    parser.add_argument("--fast-reset", action="store_true", help="verify and reuse a clean snapshot inside QEMU")
    parser.add_argument("--video-adapter", choices=("virtio", "std"), default="virtio")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        return run(args)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, PackageNotFoundError) as exc:
        parser.exit(2, f"OSWorld {args.mode}: {exc}\n")


def run(args: argparse.Namespace) -> int:
    """Verify the pinned inputs before opening a fresh environment."""
    tasks = load_tasks(args.osworld.resolve())
    vm_image = args.vm_image.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provenance = {"revision": REVISION, "desktop_env": RELEASE, "docker": image_digest(),
                  "guest_sha256": guest_digest(vm_image, output), "screen_size": list(SCREEN_SIZE),
                  "guest_ram": VM_RAM, "guest_cpus": int(VM_CPUS),
                  "guest_video_adapter": args.video_adapter,
                  "guest_gnome_start_timeout": None if Path("/dev/kvm").exists() else GNOME_START_TIMEOUT,
                  "reset_strategy": "qemu-with-docker-fallback" if args.fast_reset else "docker-restart"}
    modes = ("preflight", "teach", "run") if args.mode == "all" else (args.mode,)
    success = True
    with desktop_session(vm_image, output / "cache", fast_reset=args.fast_reset, video_adapter=args.video_adapter) as desktop:
        for mode in modes:
            print(f"Starting OSWorld {mode}", flush=True)
            if mode == "preflight":
                artifact = output / "preflight.json"
                atomic_json(artifact, {"provenance": provenance, **preflight(desktop, tasks, load_calibration(args.osworld), output)})
            elif mode == "teach":
                artifact = output / "teaching.json"
                success &= teach_curriculum(desktop, output, provenance)["qualified"]
            else:
                artifact = output / "results.json"
                success &= benchmark(desktop, tasks, output, provenance)["scored"] == 20
            print(artifact, flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
