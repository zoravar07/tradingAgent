"""Config loading — minimal slice needed by the portfolio module (§9 in SPEC.md).

This is NOT the full config system described in build-order step 1 / §8.1
(hot-reload, Pydantic validation of every section, version snapshots on write).
It only models what portfolio.py reads today. Extend as later build-order
steps (screener, scoring, risk, research) land — add a section model and
wire it into `Config` rather than reaching into the raw yaml dict.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class PortfolioConfig(BaseModel):
    import_reminder_days: int = 7
    allow_fractional: bool = False


class Config(BaseModel):
    # extra="allow" so unmodeled sections (screener, risk, sources, ...) round-trip
    # instead of being rejected — they just aren't validated or typed yet.
    model_config = ConfigDict(extra="allow")

    version: int = 1
    portfolio: PortfolioConfig = PortfolioConfig()


def load_config(path: str | Path) -> Config:
    """Read and validate config.yaml. Raises if the file is missing or malformed."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(raw)
