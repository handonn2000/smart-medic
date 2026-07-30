"""L1 · `io/` — the survival gate.

Generates no points, blocks all 70.00. The contract:

    Document(doc_id, raw)      `raw` read with newline="", never normalised
      .slice(s, e)             raw[s:e]
      .normalized/.char_map    NFC — FOR MATCHING ONLY
      .to_raw(i)               map back before anything leaves the pipeline

    load_test()   -> list[Document]            100 files, immutable
    load_gold()   -> list[AnnotatedDocument]   162 files, the yardstick
    load_silver() -> list[AnnotatedDocument]   543 files, 165 violations filtered

Also the reader for L0 `configs/*.yaml` (`io.config`) and the competition's label
vocabulary (`io.labels`), both of which every layer above needs.
"""
from __future__ import annotations

from .config import (
    ConfigError,
    ModelsConfig,
    ModelSpec,
    kb_paths,
    load_metric,
    load_models,
    load_pipeline,
    load_yaml,
    repo_root,
    require,
)
from .corpus import (
    LoadReport,
    gold_dir,
    load_documents,
    load_gold,
    load_silver,
    load_test,
    output_dir,
    test_dir,
)
from .document import (
    AnnotatedDocument,
    Document,
    OffsetError,
    normalise_with_map,
    read_raw,
)
from .labels import (
    ASSERTABLE_TYPES,
    ASSERTIONS,
    CODEABLE_TYPES,
    LAB_TYPES,
    REQUIRED_FIELDS,
    TYPES,
)

__all__ = [
    # document
    "Document",
    "AnnotatedDocument",
    "OffsetError",
    "read_raw",
    "normalise_with_map",
    # corpus
    "load_test",
    "load_gold",
    "load_silver",
    "load_documents",
    "LoadReport",
    "test_dir",
    "gold_dir",
    "output_dir",
    # config
    "ConfigError",
    "repo_root",
    "load_yaml",
    "load_pipeline",
    "load_metric",
    "load_models",
    "ModelsConfig",
    "ModelSpec",
    "kb_paths",
    "require",
    # labels
    "TYPES",
    "ASSERTIONS",
    "ASSERTABLE_TYPES",
    "CODEABLE_TYPES",
    "LAB_TYPES",
    "REQUIRED_FIELDS",
]
