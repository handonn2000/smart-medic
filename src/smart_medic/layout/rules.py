"""L2 · the compiled form of the `layout:` block in `configs/pipeline.yaml`.

Every pattern and every width in this layer comes from L0. Nothing here holds a
literal — a regex baked into Python is a rule nobody but a Python reader can
review, and the whole point of this layer is that a clinician can audit it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..io.config import load_pipeline, require

__all__ = ["LayoutRules", "default_rules"]


@dataclass(frozen=True)
class LayoutRules:
    indent_levels: tuple[int, ...]
    tab_width: int

    marker_numeric: re.Pattern
    marker_bullet: re.Pattern

    kv_label: re.Pattern
    kv_label_max_chars: int
    kv_time_like: re.Pattern
    kv_clock_window: int

    semicolon: str
    comma: str
    comma_requires_lab_name: bool
    lab_name: re.Pattern
    inline_kv: re.Pattern
    inline_kv_min_gap: int

    open_on: frozenset[str]
    prose_header_max_chars: int
    prose_header_requires_following_bullet: bool
    prose_header_forbidden_tail: re.Pattern
    outline_lookahead_lines: int

    token: re.Pattern
    token_prefix: re.Pattern
    token_suffix: re.Pattern

    def level_of(self, indent: int) -> int:
        """Largest i with `indent >= indent_levels[i]`. Three tiers, then capped."""
        level = 0
        for i, threshold in enumerate(self.indent_levels):
            if indent >= threshold:
                level = i
        return level

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "LayoutRules":
        layout = require(cfg or load_pipeline(), "layout")
        marker = require(layout, "marker")
        kv = require(layout, "kv")
        split = require(layout, "split")
        outline = require(layout, "outline")
        return cls(
            indent_levels=tuple(require(layout, "indent_levels")),
            tab_width=int(require(layout, "tab_width")),
            marker_numeric=re.compile(require(marker, "numeric")),
            marker_bullet=re.compile(require(marker, "bullet")),
            kv_label=re.compile(require(kv, "label")),
            kv_label_max_chars=int(require(kv, "label_max_chars")),
            kv_time_like=re.compile(require(kv, "time_like")),
            kv_clock_window=int(require(kv, "clock_window")),
            semicolon=require(split, "semicolon"),
            comma=require(split, "comma"),
            comma_requires_lab_name=bool(require(split, "comma_requires_lab_name")),
            lab_name=re.compile(require(split, "lab_name")),
            inline_kv=re.compile(require(split, "inline_kv")),
            inline_kv_min_gap=int(require(split, "inline_kv_min_gap")),
            open_on=frozenset(require(outline, "open_on")),
            prose_header_max_chars=int(require(outline, "prose_header_max_chars")),
            prose_header_requires_following_bullet=bool(
                require(outline, "prose_header_requires_following_bullet")
            ),
            prose_header_forbidden_tail=re.compile(
                require(outline, "prose_header_forbidden_tail")
            ),
            outline_lookahead_lines=int(require(outline, "lookahead_lines")),
            token=re.compile(require(layout, "token")),
            token_prefix=re.compile(require(layout, "token_prefix")),
            token_suffix=re.compile(require(layout, "token_suffix")),
        )


@lru_cache(maxsize=1)
def default_rules() -> LayoutRules:
    return LayoutRules.from_config()
