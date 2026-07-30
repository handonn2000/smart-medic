"""L1 · the reader for L0 `configs/*.yaml`.

Configs are data; this is the code that loads them. It lives in `io/` — the lowest
code layer — because every layer above needs it, and because reading files off
disk is exactly what `io/` is for.

Two rules this module enforces rather than documents:

* **No threshold is defined here.** Every number comes out of `configs/*.yaml`.
  A missing key raises; it never falls back to a hard-coded default, because a
  silent default is a magic number with extra steps.
* **The 9B parameter cap is a startup error.** `load_models()` sums the `params`
  field and fails the build if the enabled set overruns `param_budget`.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ConfigError",
    "repo_root",
    "config_dir",
    "load_yaml",
    "load_pipeline",
    "load_metric",
    "load_models",
    "ModelsConfig",
    "ModelSpec",
    "kb_paths",
    "require",
    "require_probability",
]


class ConfigError(RuntimeError):
    """A config file is missing, malformed, or violates a regulation."""


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from this file to the directory holding `configs/`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "configs").is_dir() and (parent / "src").is_dir():
            return parent
    raise ConfigError(f"cannot locate the repo root above {here}")


def config_dir() -> Path:
    return repo_root() / "configs"


def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = config_dir() / p
    if not p.exists():
        raise ConfigError(f"missing config file: {p}")
    with p.open(encoding="utf-8") as fh:
        obj = yaml.safe_load(fh)
    if not isinstance(obj, dict):
        raise ConfigError(f"{p}: top level must be a mapping, got {type(obj).__name__}")
    return obj


def require(cfg: dict, dotted: str) -> Any:
    """Fetch `cfg["a"]["b"]` from `"a.b"`, raising instead of defaulting.

    A threshold that silently falls back to a value baked into Python is the
    magic number this project bans. Missing key ⇒ loud.
    """
    node: Any = cfg
    walked: list[str] = []
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(
                f"missing config key {dotted!r}"
                + (f" (resolved as far as {'.'.join(walked)!r})" if walked else "")
            )
        node = node[part]
        walked.append(part)
    return node


def require_probability(cfg: dict, dotted: str) -> float:
    """`require`, plus the check that the value is a usable probability.

    Lives here rather than in the caller because `decision/` is forbidden float
    literals in executable code (tests/test_decision.py enforces it): a bound
    written into Python is a bound nobody reviews, and the config's sha256 is
    what goes into the run manifest. The unit interval is not a threshold, so it
    belongs in the loader that validates shapes.
    """
    value = require(cfg, dotted)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{dotted} must be a number, got {value!r}") from exc
    if not 0 <= out <= 1:
        raise ConfigError(
            f"{dotted} must be a probability in [0, 1], got {out}. A score gate "
            f"outside that range either passes everything or nothing."
        )
    return out


@lru_cache(maxsize=1)
def load_pipeline() -> dict:
    """`configs/pipeline.yaml` — thresholds, stage flags, layout rules."""
    return load_yaml("pipeline.yaml")


@lru_cache(maxsize=1)
def load_metric() -> dict:
    """`configs/metric.yaml` — the identity of the measurement.

    Asserts that both required alignments are declared. `greedy_iou` alone can
    never reward a type fix, and `overlap_type` alone is not the official number.
    """
    cfg = load_yaml("metric.yaml")
    alignment = require(cfg, "alignment")
    for needed in ("greedy_iou", "overlap_type"):
        if needed not in alignment:
            raise ConfigError(
                f"configs/metric.yaml: alignment must contain BOTH greedy_iou and "
                f"overlap_type; {needed!r} is missing (got {alignment!r})"
            )
    return cfg


# ────────────────────────────── model budget ──────────────────────────────
@dataclass(frozen=True)
class ModelSpec:
    name: str
    hf_id: str
    params: int
    revision_sha: str | None
    enabled: bool
    role: str = ""


@dataclass(frozen=True)
class ModelsConfig:
    budget: int
    specs: tuple[ModelSpec, ...]

    @property
    def enabled(self) -> tuple[ModelSpec, ...]:
        return tuple(s for s in self.specs if s.enabled)

    @property
    def params_enabled(self) -> int:
        return sum(s.params for s in self.enabled)

    @property
    def params_declared(self) -> int:
        return sum(s.params for s in self.specs)

    def manifest_entries(self) -> list[dict]:
        """`models[]` for `runs/<ts>/manifest.json` — id, revision SHA, params."""
        return [
            {
                "id": s.hf_id,
                "name": s.name,
                "revision_sha": s.revision_sha,
                "params": s.params,
                "enabled": s.enabled,
            }
            for s in self.specs
        ]


@lru_cache(maxsize=1)
def load_models() -> ModelsConfig:
    """`configs/models.yaml`, with the regulation checked at load time.

    Fails the build when the enabled models overrun `param_budget`, and when an
    enabled model has no pinned `revision_sha` — a moving tag means a moving
    tokenizer, and a moving tokenizer means moving offsets.
    """
    cfg = load_yaml("models.yaml")
    budget = int(require(cfg, "param_budget"))

    specs: list[ModelSpec] = []
    for i, entry in enumerate(require(cfg, "models")):
        for key in ("name", "hf_id", "params"):
            if key not in entry:
                raise ConfigError(f"configs/models.yaml: models[{i}] has no {key!r}")
        specs.append(
            ModelSpec(
                name=entry["name"],
                hf_id=entry["hf_id"],
                params=int(entry["params"]),
                revision_sha=entry.get("revision_sha"),
                enabled=bool(entry.get("enabled", False)),
                role=entry.get("role", ""),
            )
        )

    conf = ModelsConfig(budget=budget, specs=tuple(specs))

    if conf.params_enabled >= budget:
        detail = ", ".join(f"{s.name}={s.params:,}" for s in conf.enabled)
        raise ConfigError(
            f"PARAMETER BUDGET EXCEEDED: enabled models total "
            f"{conf.params_enabled:,} >= {budget:,} (9e9). Disable a model or "
            f"pick a smaller one. Enabled: {detail or 'none'}"
        )

    unpinned = [s.name for s in conf.enabled if not s.revision_sha]
    if unpinned:
        raise ConfigError(
            f"configs/models.yaml: enabled model(s) {unpinned} have no "
            f"revision_sha. Pin the revision SHA, not a tag — a tag moves, and a "
            f"moved tokenizer moves every offset."
        )
    return conf


# ─────────────────────────── knowledge-base paths ───────────────────────────
def kb_paths() -> dict[str, Path]:
    """Runtime KB paths, resolved from `configs/pipeline.yaml`.

    `scripts/kb_sources.py` is the build-time equivalent. `src/` may not import
    `scripts/` — the dependency runs one way only — so L0 declares the paths and
    both sides read them from there.
    """
    kb = require(load_pipeline(), "knowledge_base")
    root = repo_root() / kb["root"]
    out = {"root": root}
    for key in ("icd10_vi", "rxnconso"):
        out[key] = root / require(kb, key)
    out["cache"] = repo_root() / require(kb, "cache")
    return out
