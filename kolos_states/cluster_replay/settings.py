"""Read optional per-checkout replay bindings without exposing their values."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / '.local-data' / 'cluster-replay.json'


@dataclass(frozen=True)
class ReplaySettings:
    """Installation defaults shared by the replay and adaptation commands."""

    source: Path | None = None
    corpus: Path | None = None
    hermes_install: Path | None = None
    teaching_product_id: int | None = None


def _setting_path(data: dict, key: str, directory: Path) -> Path | None:
    """Resolve a relative path against the configuration directory."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Invalid replay path field: {key}')
    return directory / value


def read_settings(path: Path = SETTINGS) -> ReplaySettings:
    """A portable checkout without private bindings can run from CLI arguments."""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return ReplaySettings()
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid local replay configuration') from error
    if not isinstance(data, dict):
        raise ValueError('Local replay configuration must be a JSON object')
    product = data.get('teaching_product_id')
    if product is not None and (type(product) is not int or product <= 0):
        raise ValueError('teaching_product_id must be a positive integer')
    return ReplaySettings(
        source=_setting_path(data, 'source', path.parent),
        corpus=_setting_path(data, 'corpus', path.parent),
        hermes_install=_setting_path(data, 'hermes_install', path.parent),
        teaching_product_id=product,
    )
