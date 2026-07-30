#!/usr/bin/env python3
"""Build the reusable gazetteer index — `data/artifacts/gazetteer.json`.

Two readers share this artifact: `extract/aho.py` (P1, recall floor) and
`linking/retrieve.py` (P5, candidate generation) — build once, read twice. See
`src/smart_medic/linking/README.md` §"extract/aho.py dùng lại chỉ mục gazetteer".

    python3 scripts/build_gazetteer.py --out data/artifacts/gazetteer.json

## THE MATCH KEY RECIPE — reproduce this EXACTLY on the document side

`extract/aho.py` must build its scan key with the identical recipe, or recall
silently drops to whatever the two normalisations happen to agree on. Given a
raw string `s`:

    1. unicodedata.normalize("NFC", s)
    2. lowercase CHARACTER BY CHARACTER: for each character `ch`, keep `ch`
       unchanged if `len(ch.lower()) != 1` (a handful of Unicode characters
       lowercase to 2+ codepoints — e.g. "İ") and use `ch.lower()` otherwise.
       This keeps `k` a faithful, length-stable 1:1 view of the surface form
       instead of a blob that could silently grow or shrink — cheap insurance
       even though the reader that exists today (below) does not walk `k`
       character-by-character.
    3. collapse every run of whitespace (`re.sub(r"\\s+", " ", ...)`) to one
       U+0020.
    4. `.strip()`.

`normalize_key()` below is that recipe, verbatim — import it rather than
re-deriving it if you write a sibling script.

As actually consumed by `extract/aho.py` (read, not written, by this
script): the reader re-tokenises `k` with `extract.spans.tokenize_key()` —
the SAME token regex + per-token `.lower()` the document side uses on
`doc.normalized` — and matches token SEQUENCES, not character offsets, so
`k` never needs a literal position-preserving walk on the reader's side. It
still needs the NFC-normalise + whitespace-collapse from steps 1 and 3,
because the reader's tokenizer runs on `Document.normalized` (also NFC), and
a `k` that skipped that step could tokenise differently than the same phrase
found inside a document.

## WHAT GOES IN (see resources/gazetteer_vi.yaml for every threshold/prior)

1. ICD-10 Vietnamese (`kb_sources.ICD10_VI` / `ICD10.csv`) — 13,189 codes /
   ~36.7k name rows. The organisers' own list; irreplaceable, never the
   English `icd10cm-codes-2027.txt` (that file only ENRICHES by code, in P5).
2. RxNorm ingredients (`kb_sources.iter_rxnconso()`), filtered to
   `sab == "RXNORM"`, `tty in {IN, PIN, MIN}`, `suppress in ("", "N")` — the
   11x-smaller ingredient family, not the full 656k-row concept table.
3. Silver-mined surface forms, from
   `data/generated_medical_records/{synthetic,translated}/annotations/*.json`
   ONLY.

   `restyled/annotations` is EXCLUDED ON PURPOSE: `restyled/annotations` labels
   the exact same texts that `restyled/annotations_gold/` re-annotates by
   hand. Gold is this project's only measuring stick (`io/corpus.load_gold`).
   Mining `restyled/annotations` into a gazetteer that then gets *evaluated*
   against `restyled/annotations_gold` would mean part of the "recall" number
   is the gazetteer having memorised the answer key — every gold number
   downstream of that would be inflated and not reproducible on the private
   test set, which has no such shortcut available. `synthetic/` and
   `translated/` texts are disjoint from the gold-annotated documents, so
   mining them is ordinary training-signal use, not leakage.

## DETERMINISM

Two builds of the same inputs must produce byte-identical `entries` (required
for the P1 acceptance gate). The one intentionally time-varying field is
`built_utc`: pass `--built-utc` explicitly (e.g. from CI) to get a fully
byte-identical file across two runs; the default is wall-clock time, so a
`cmp` of two *default* builds run seconds apart will differ in exactly that
one field and nothing else — verify determinism with a pinned `--built-utc`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from kb_sources import ICD10_VI, RXNCONSO, iter_rxnconso  # noqa: E402

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("thiếu PyYAML: pip install pyyaml") from exc

DEFAULT_CONFIG = REPO / "resources" / "gazetteer_vi.yaml"
DEFAULT_OUT = REPO / "data" / "artifacts" / "gazetteer.json"
SILVER_ROOT = REPO / "data" / "generated_medical_records"

# The competition's own label vocabulary (src/smart_medic/io/labels.py). Not
# reimported from src/ — src/ may never be imported by scripts/, and this
# script is build-time only (see linking/README.md, extract/README.md).
CODEABLE_TYPES = frozenset({"CHẨN_ĐOÁN", "THUỐC"})

_WS_RE = re.compile(r"\s+")


def normalize_key(s: str) -> str:
    """The match key recipe — see module docstring. `extract/aho.py` mirrors this."""
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch if len(ch.lower()) != 1 else ch.lower() for ch in s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def round_dist(dist: dict) -> dict:
    """Round a type distribution to 4dp so it still sums to exactly 1.0000.

    Plain per-key rounding can leave the sum at 0.9999/1.0001 after four
    values are each rounded independently; the residual is folded into
    whichever label already carries the largest share, since that is the
    entry least likely to be pushed into a different argmax by a 0.0001 move.
    """
    if not dist:
        return {}
    total = sum(dist.values())
    norm = {k: v / total for k, v in dist.items()}
    rounded = {k: round(v, 4) for k, v in norm.items()}
    residual = round(1.0 - sum(rounded.values()), 4)
    if residual:
        top = max(rounded, key=rounded.get)
        rounded[top] = round(rounded[top] + residual, 4)
    return {k: v for k, v in rounded.items() if v > 0}


class Filter:
    """The stoplist / min_key_chars gate from resources/gazetteer_vi.yaml."""

    def __init__(self, cfg: dict):
        self.min_chars = cfg["min_key_chars"]
        sl = cfg["stoplist"]
        self.literal = set(sl["literal"])
        self.patterns = [re.compile(p) for p in sl["patterns"]]
        self.dropped: Counter = Counter()
        self.examples: dict[str, list[str]] = {"short": [], "literal": [], "pattern": []}

    def keep(self, key: str) -> bool:
        if not key:
            self.dropped["short"] += 1
            return False
        if len(key) < self.min_chars:
            self.dropped["short"] += 1
            if len(self.examples["short"]) < 15:
                self.examples["short"].append(key)
            return False
        if key in self.literal:
            self.dropped["literal"] += 1
            if len(self.examples["literal"]) < 15:
                self.examples["literal"].append(key)
            return False
        for pat in self.patterns:
            if pat.fullmatch(key):
                self.dropped["pattern"] += 1
                if len(self.examples["pattern"]) < 15:
                    self.examples["pattern"].append(key)
                return False
        return True


# ─────────────────────────────── ICD-10 Vietnamese ───────────────────────────
def build_icd_entries(cfg: dict, flt: Filter) -> tuple[dict, dict]:
    """Returns (entries, source_stats). entries[key] = {"codes": set, "type_dist": dict}."""
    import csv

    icfg = cfg["icd10_vi"]
    prior = cfg["icd_chapter_type_prior"]
    r_block = prior["r_block"]
    default = prior["default"]

    with ICD10_VI.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = [h.strip() for h in rows[icfg["header_row"] - 1]]
    code_col = header.index(icfg["code_column"])
    name_col = header.index(icfg["name_column"])

    entries: dict[str, dict] = {}
    n_names = 0
    for row in rows[icfg["header_row"] :]:
        if len(row) <= max(code_col, name_col):
            continue
        code = row[code_col].strip()
        name = row[name_col].strip()
        if not code or not name:
            continue
        n_names += 1
        key = normalize_key(name)
        if not flt.keep(key):
            continue
        dist = r_block if code.startswith("R") else default
        e = entries.setdefault(key, {"codes": set(), "type_dist": Counter()})
        e["codes"].add(code)
        for t, p in dist.items():
            e["type_dist"][t] += p

    for e in entries.values():
        total = sum(e["type_dist"].values())
        e["type_dist"] = {t: v / total for t, v in e["type_dist"].items()}

    stats = {
        "sha256": sha256_file(ICD10_VI),
        "names": n_names,
        "kept": len(entries),
    }
    return entries, stats


# ─────────────────────────────────── RxNorm ──────────────────────────────────
def build_rxnorm_entries(cfg: dict, flt: Filter) -> tuple[dict, dict]:
    rcfg = cfg["rxnorm"]
    sab = rcfg["sab"]
    ttys = set(rcfg["tty"])
    suppress_ok = set(rcfg["suppress"])

    entries: dict[str, dict] = {}
    rows_scanned = 0
    for row in iter_rxnconso(sabs=frozenset({sab})):
        if row["tty"] not in ttys or row["suppress"] not in suppress_ok:
            continue
        rows_scanned += 1
        key = normalize_key(row["str"])
        if not flt.keep(key):
            continue
        e = entries.setdefault(key, {"codes": set(), "type_dist": {"THUỐC": 1.0}})
        e["codes"].add(row["rxcui"])

    stats = {
        "sha256": sha256_file(RXNCONSO),
        "rows_scanned": rows_scanned,
        "kept": len(entries),
    }
    return entries, stats


# ─────────────────────────── silver-mined surface forms ──────────────────────
def build_silver_entries(cfg: dict, flt: Filter) -> tuple[dict, dict]:
    scfg = cfg["silver"]
    ann_subdir = scfg["annotations_subdir"]

    entries: dict[str, dict] = {}
    n_files = 0
    n_entities = 0
    for kind in scfg["kinds"]:
        ann_dir = SILVER_ROOT / kind / ann_subdir
        if not ann_dir.is_dir():
            raise SystemExit(f"thiếu thư mục silver: {ann_dir}")
        for path in sorted(ann_dir.glob("*.json")):
            n_files += 1
            with path.open(encoding="utf-8") as fh:
                doc_entities = json.load(fh)
            if not isinstance(doc_entities, list):
                continue
            for ent in doc_entities:
                if not isinstance(ent, dict):
                    continue
                text = ent.get("text")
                etype = ent.get("type")
                if not text or not etype:
                    continue
                n_entities += 1
                key = normalize_key(text)
                if not flt.keep(key):
                    continue
                e = entries.setdefault(
                    key, {"codes": set(), "type_dist": Counter()}
                )
                e["type_dist"][etype] += 1
                if etype in CODEABLE_TYPES:
                    for c in ent.get("candidates") or []:
                        if c:
                            e["codes"].add(str(c))

    for e in entries.values():
        total = sum(e["type_dist"].values())
        e["type_dist"] = {t: v / total for t, v in e["type_dist"].items()}

    stats = {
        "kinds": list(scfg["kinds"]),
        "files": n_files,
        "entities_scanned": n_entities,
        "kept": len(entries),
    }
    return entries, stats


# ────────────────────────────────── merge ────────────────────────────────────
def argmax_type(dist: dict) -> str:
    """Same tie-break as `extract.spans.Span.argmax_type`: (value, key)."""
    return max(dist.items(), key=lambda kv: (kv[1], kv[0]))[0]


def merge(
    icd: dict, rxnorm: dict, silver: dict, cfg: dict
) -> tuple[list[dict], Counter, Counter]:
    """Returns (entries, winning_source_counts, dropped_dominant_type_counts).

    `winning_source_counts["_usage_overrides_vocabulary"]` counts the keys where
    `usage_overrides_vocabulary` suppressed the vocabulary source's type vote.

    `dropped_dominant_type_counts` is keyed by the type that got an entry
    dropped, e.g. `{"KẾT_QUẢ_XÉT_NGHIỆM": 181}` — see `drop_dominant_types`
    in resources/gazetteer_vi.yaml. Computed on the BLENDED distribution
    (after merging sources), because a key's dominant type can only be known
    once every source that contributed to it has been combined.
    """
    weights = cfg["source_weight"]
    priority = cfg["source_priority"]
    drop_types = set(cfg.get("drop_dominant_types", ()))
    by_source = {"icd_vi": icd, "rxnorm": rxnorm, "silver": silver}

    # `usage_overrides_vocabulary`: see resources/gazetteer_vi.yaml for the
    # measurement. A drug vocabulary listing `creatinine` is not evidence that
    # `creatinine` is a drug in a clinical note; an annotated corpus saying it is
    # a lab name IS. Suppresses the vocabulary source's TYPE vote only — its
    # codes still merge.
    uov = cfg.get("usage_overrides_vocabulary") or {}
    uov_vocab = uov.get("vocabulary_source")
    uov_usage = uov.get("usage_source")
    uov_types = set(uov.get("usage_dominant_in", ()))

    all_keys = set(icd) | set(rxnorm) | set(silver)
    entries = []
    winning_source_counts: Counter = Counter()
    dropped_dominant_type: Counter = Counter()
    usage_overrides = 0

    for key in sorted(all_keys):
        blended: Counter = Counter()
        codes: set = set()
        contributing = []

        usage_wins = False
        if uov_vocab and uov_usage:
            vocab_e = by_source[uov_vocab].get(key)
            usage_e = by_source[uov_usage].get(key)
            if vocab_e is not None and usage_e is not None and usage_e["type_dist"]:
                usage_wins = argmax_type(usage_e["type_dist"]) in uov_types
                usage_overrides += usage_wins

        for src in ("icd_vi", "rxnorm", "silver"):
            e = by_source[src].get(key)
            if e is None:
                continue
            contributing.append(src)
            codes |= e["codes"]          # codes merge regardless of the override
            if usage_wins and src == uov_vocab:
                continue                 # TYPE vote suppressed, nothing else
            w = weights[src]
            for t, p in e["type_dist"].items():
                blended[t] += w * p

        dist = round_dist(dict(blended))
        if dist and argmax_type(dist) in drop_types:
            dropped_dominant_type[argmax_type(dist)] += 1
            continue

        winner = next(s for s in priority if s in contributing)
        winning_source_counts[winner] += 1

        entries.append(
            {
                "k": key,
                "t": dist,
                "c": sorted(codes),
                "s": winner,
            }
        )

    entries.sort(key=lambda e: e["k"])
    winning_source_counts["_usage_overrides_vocabulary"] = usage_overrides
    return entries, winning_source_counts, dropped_dominant_type


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--built-utc",
        default=None,
        help="ISO8601 UTC timestamp to embed. Default: now(). Pass an explicit "
        "value to get byte-identical output across repeated builds.",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    flt = Filter(cfg)

    icd_entries, icd_stats = build_icd_entries(cfg, flt)
    rx_entries, rx_stats = build_rxnorm_entries(cfg, flt)
    silver_entries, silver_stats = build_silver_entries(cfg, flt)

    entries, winning, dropped_dominant = merge(icd_entries, rx_entries, silver_entries, cfg)

    built_utc = args.built_utc or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    doc = {
        "version": 1,
        "built_utc": built_utc,
        "sources": {
            "ICD10.csv": icd_stats,
            "RXNCONSO.RRF": rx_stats,
            "silver": silver_stats,
        },
        "counts": {
            "icd_vi": winning["icd_vi"],
            "rxnorm": winning["rxnorm"],
            "silver": winning["silver"],
            "entries": len(entries),
        },
        "entries": entries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=None, separators=(",", ":"))
        fh.write("\n")

    print(f"wrote {args.out}")
    print()
    print(f"{'source':<12}{'raw seen':>12}{'kept (pre-merge)':>18}{'won key':>10}")
    print(
        f"{'icd_vi':<12}{icd_stats['names']:>12}{icd_stats['kept']:>18}"
        f"{winning['icd_vi']:>10}"
    )
    print(
        f"{'rxnorm':<12}{rx_stats['rows_scanned']:>12}{rx_stats['kept']:>18}"
        f"{winning['rxnorm']:>10}"
    )
    print(
        f"{'silver':<12}{silver_stats['entities_scanned']:>12}"
        f"{silver_stats['kept']:>18}{winning['silver']:>10}"
    )
    print(f"{'TOTAL':<12}{'':>12}{'':>18}{len(entries):>10}")
    print()
    print(
        "usage_overrides_vocabulary: type vote of "
        f"{cfg['usage_overrides_vocabulary']['vocabulary_source']} suppressed on "
        f"{winning['_usage_overrides_vocabulary']} key(s) where "
        f"{cfg['usage_overrides_vocabulary']['usage_source']} says lab"
    )
    print("stoplist drops (key-level, pre-merge):", dict(flt.dropped))
    for reason, examples in flt.examples.items():
        if examples:
            print(f"  {reason}: {examples}")
    print("dropped by dominant type (entry-level, post-merge):", dict(dropped_dominant))


if __name__ == "__main__":
    main()
