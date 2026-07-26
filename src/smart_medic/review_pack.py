"""Build deterministic Bronze/Silver/Gold medication review artifacts.

The generator is intentionally independent from inference.  It consumes a
frozen ``explain.json`` plus the original text files, validates every raw
offset, and produces CSV files suitable for human adjudication.  Silver files
may be regenerated; an existing Gold template is never overwritten with
different bytes.

Example::

    PYTHONPATH=src python3 -m smart_medic.review_pack \
      --input data/test --explain data/output/explain.json --kb data/kb \
      --root data/curation --scope all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from . import V4_VERSION
from .kb.store import KBError, KnowledgeBase, load_kb
from .normalize import norm_drug
from .schema import ConceptType
from .stages.medication_v4 import MedicationAttributeParser


SCHEMA_VERSION = 1
GENERATOR_VERSION = V4_VERSION
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MASK_RE = re.compile(r"\*{3,}")

MENTION_FIELDS = (
    "review_id", "group_id", "group_size", "is_representative",
    "review_priority", "review_reason", "document_id", "source_file",
    "document_sha256", "span_start", "span_end", "surface_text",
    "normalized_text", "line_number", "display_context", "is_masked",
    "predicted_rxcuis_json", "candidate_details_json", "confidence",
    "assertions_json", "extractor", "locate_method", "link_path",
    "anchor", "best_alias", "parsed_attributes_json", "kb_rows_json",
    "evidence_json",
)

GROUP_FIELDS = (
    "group_id", "normalized_surface", "representative_surface",
    "occurrence_count", "review_priority", "review_reason",
    "member_review_ids_json", "source_files_json", "representative_context",
    "candidate_details_json",
)

REVIEW_FIELDS = (
    "decision", "gold_rxcui", "gold_ingredient", "gold_strength",
    "gold_unit", "gold_dose_form", "gold_span_start", "gold_span_end",
    "reviewer_id", "notes",
)


class ReviewPackError(ValueError):
    pass


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: str, prefix: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return f"{prefix}_{digest.hexdigest()[:20]}"


def _json_cell(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _csv_bytes(rows: Iterable[dict], fields: tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return stream.getvalue().encode("utf-8")


def _json_bytes(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _write(path: Path, payload: bytes) -> None:
    if path.is_symlink():
        raise ReviewPackError(f"refusing to write through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_gold_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ReviewPackError(f"Gold target is not a regular file: {path}")
        if path.read_bytes() != payload:
            raise ReviewPackError(
                f"Gold already exists and differs; refusing to overwrite: {path}"
            )
        return
    _write(path, payload)


def _sort_key(path: Path) -> tuple[int, str]:
    return (int(path.stem), "") if path.stem.isdigit() else (10**9, path.name)


def _candidate_details(record: dict, kb: KnowledgeBase) -> list[dict]:
    provenance = record.get("_provenance", {})
    scores = provenance.get("scores", {})
    codes = set(str(code) for code in record.get("candidates", []))
    codes.update(
        key.removeprefix("code:")
        for key in scores
        if isinstance(key, str) and key.startswith("code:")
    )
    reverse: dict[str, list[str]] = defaultdict(list)
    for old, new in kb.rx_remap.items():
        reverse[new].append(old)

    details = []
    for code in sorted(codes, key=lambda value: (not value.isdigit(), value)):
        concept = kb.rx_concepts.get(code)
        details.append({
            "rxcui": code,
            "score": scores.get(f"code:{code}"),
            "emitted": code in record.get("candidates", []),
            "is_current": concept is not None,
            "tty": "" if concept is None else concept.get("tty", ""),
            "canonical_name": "" if concept is None else concept.get("str", ""),
            "remap_to": kb.rx_remap.get(code, ""),
            "legacy_from": sorted(reverse.get(code, [])),
        })
    return details


def _context(raw: str, start: int, end: int, chars: int) -> tuple[int, str]:
    left = max(0, start - chars)
    right = min(len(raw), end + chars)
    before = raw[left:start].replace("\r", "⏎").replace("\n", "⏎")
    focus = raw[start:end].replace("\r", "⏎").replace("\n", "⏎")
    after = raw[end:right].replace("\r", "⏎").replace("\n", "⏎")
    return raw.count("\n", 0, start) + 1, f"{before}⟦{focus}⟧{after}"


def _priority(record: dict) -> tuple[int, str]:
    masked = bool(_MASK_RE.search(record.get("text", "")))
    candidates = record.get("candidates", [])
    confidence = float(record.get("_provenance", {}).get("scores", {}).get(
        "confidence", 0.0
    ) or 0.0)
    if not masked and not candidates:
        return 1, "plaintext_unlinked"
    if len(candidates) > 1:
        return 2, "multiple_candidates"
    if candidates and confidence < 0.92:
        return 3, "low_confidence_linked"
    if masked and candidates:
        return 4, "resolved_mask"
    if masked:
        return 5, "unresolved_mask"
    return 6, "high_confidence_linked"


def _in_scope(record: dict, scope: str) -> bool:
    priority, _ = _priority(record)
    if scope == "all":
        return True
    if scope == "unlinked":
        return not record.get("candidates", [])
    return priority <= 4


def _load_explain(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPackError(f"cannot read explain file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewPackError("explain.json must be an object keyed by source filename")
    return value


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise ReviewPackError(f"unsafe {label}: {value!r}")
    return value


def build_review_pack(
    *,
    input_dir: Path,
    explain_path: Path,
    kb: KnowledgeBase,
    root: Path,
    snapshot_id: str = "competition_test_v1",
    run_id: str = "v3_3_medications",
    gold_version: str = "medications_v0",
    scope: str = "actionable",
    context_chars: int = 160,
) -> dict:
    """Validate inputs and create deterministic curation artifacts."""
    snapshot_id = _safe_id(snapshot_id, "snapshot_id")
    run_id = _safe_id(run_id, "run_id")
    gold_version = _safe_id(gold_version, "gold_version")
    if scope not in {"actionable", "unlinked", "all"}:
        raise ReviewPackError(f"unsupported scope: {scope}")
    if not 0 <= context_chars <= 2000:
        raise ReviewPackError("context_chars must be between 0 and 2000")
    if "gold" in {part.casefold() for part in root.parts[-2:]}:
        raise ReviewPackError("curation root must not itself be a Gold directory")

    files = sorted(input_dir.glob("*.txt"), key=_sort_key)
    if not files:
        raise ReviewPackError(f"no .txt files found in {input_dir}")
    explain = _load_explain(explain_path)
    expected_names = {path.name for path in files}
    if set(explain) != expected_names:
        missing = sorted(expected_names - set(explain))
        extra = sorted(set(explain) - expected_names)
        raise ReviewPackError(
            f"explain/input file mismatch; missing={missing[:5]}, extra={extra[:5]}"
        )

    parser = MedicationAttributeParser()
    documents: list[dict] = []
    rows: list[dict] = []
    for path in files:
        payload = path.read_bytes()
        try:
            raw = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewPackError(f"source must be UTF-8: {path}") from exc
        document_sha = _sha256_bytes(payload)
        documents.append({
            "source_file": path.name,
            "sha256": document_sha,
            "bytes": len(payload),
        })
        records = explain[path.name]
        if not isinstance(records, list):
            raise ReviewPackError(f"{path.name}: explain value must be a list")
        for record in records:
            if not isinstance(record, dict) or record.get("type") != ConceptType.THUOC.value:
                continue
            position = record.get("position")
            if not (
                isinstance(position, list) and len(position) == 2
                and all(isinstance(value, int) for value in position)
            ):
                raise ReviewPackError(f"{path.name}: invalid medication position")
            start, end = position
            surface = record.get("text", "")
            if not (0 <= start < end <= len(raw)) or raw[start:end] != surface:
                raise ReviewPackError(
                    f"{path.name}:{start}-{end}: stale explain/raw offset mismatch"
                )
            if not _in_scope(record, scope):
                continue
            provenance = record.get("_provenance", {})
            if not isinstance(provenance, dict):
                raise ReviewPackError(f"{path.name}:{start}: malformed provenance")
            evidence = provenance.get("evidence", {})
            scores = provenance.get("scores", {})
            anchor = evidence.get("anchor", "") if isinstance(evidence, dict) else ""
            parsed = parser.parse(surface, anchor=anchor)
            line_number, display_context = _context(raw, start, end, context_chars)
            review_id = _stable_id(
                document_sha, str(start), str(end), surface, prefix="med"
            )
            normalized = norm_drug(surface)
            candidate_signature = _json_cell(sorted(record.get("candidates", [])))
            group_material = (
                review_id if parsed.masked else normalized,
                candidate_signature,
            )
            group_id = _stable_id(*group_material, prefix="grp")
            priority, reason = _priority(record)
            candidate_details = _candidate_details(record, kb)
            rows.append({
                "review_id": review_id,
                "group_id": group_id,
                "review_priority": priority,
                "review_reason": reason,
                "document_id": path.stem,
                "source_file": path.name,
                "document_sha256": document_sha,
                "span_start": start,
                "span_end": end,
                "surface_text": surface,
                "normalized_text": normalized,
                "line_number": line_number,
                "display_context": display_context,
                "is_masked": int(parsed.masked),
                "predicted_rxcuis_json": _json_cell(record.get("candidates", [])),
                "candidate_details_json": _json_cell(candidate_details),
                "confidence": scores.get("confidence", "") if isinstance(scores, dict) else "",
                "assertions_json": _json_cell(record.get("assertions", [])),
                "extractor": provenance.get("extractor", ""),
                "locate_method": provenance.get("locate_method", ""),
                "link_path": provenance.get("link_path", ""),
                "anchor": anchor,
                "best_alias": evidence.get("best_alias", "") if isinstance(evidence, dict) else "",
                "parsed_attributes_json": _json_cell(parsed.to_dict()),
                "kb_rows_json": _json_cell(provenance.get("kb_rows", [])),
                "evidence_json": _json_cell(evidence),
            })

    rows.sort(key=lambda row: (
        row["review_priority"],
        int(row["document_id"]) if str(row["document_id"]).isdigit() else 10**9,
        str(row["document_id"]),
        row["span_start"],
        row["review_id"],
    ))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["group_id"]].append(row)
    for members in grouped.values():
        representative = min(members, key=lambda row: (
            row["review_priority"], row["source_file"], row["span_start"]
        ))
        for row in members:
            row["group_size"] = len(members)
            row["is_representative"] = int(row is representative)

    group_rows = []
    for group_id, members in sorted(
        grouped.items(),
        key=lambda item: (
            min(row["review_priority"] for row in item[1]),
            -len(item[1]),
            item[0],
        ),
    ):
        representative = next(row for row in members if row["is_representative"])
        group_rows.append({
            "group_id": group_id,
            "normalized_surface": representative["normalized_text"],
            "representative_surface": representative["surface_text"],
            "occurrence_count": len(members),
            "review_priority": min(row["review_priority"] for row in members),
            "review_reason": representative["review_reason"],
            "member_review_ids_json": _json_cell(sorted(
                row["review_id"] for row in members
            )),
            "source_files_json": _json_cell(sorted({
                row["source_file"] for row in members
            }, key=lambda name: _sort_key(Path(name)))),
            "representative_context": representative["display_context"],
            "candidate_details_json": representative["candidate_details_json"],
        })

    bronze_dir = root / "bronze" / snapshot_id
    silver_dir = root / "silver" / run_id
    gold_dir = root / "gold" / gold_version

    bronze_manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "source": "competition_input",
        "documents": documents,
        "document_count": len(documents),
    }
    _write(bronze_dir / "MANIFEST.json", _json_bytes(bronze_manifest))

    mention_payload = _csv_bytes(rows, MENTION_FIELDS)
    group_payload = _csv_bytes(group_rows, GROUP_FIELDS)
    _write(silver_dir / "medication_mentions.csv", mention_payload)
    _write(silver_dir / "medication_groups.csv", group_payload)

    gold_rows = []
    for row in rows:
        gold_rows.append({
            **{field: row.get(field, "") for field in MENTION_FIELDS},
            **{field: "" for field in REVIEW_FIELDS},
        })
    gold_payload = _csv_bytes(gold_rows, MENTION_FIELDS + REVIEW_FIELDS)
    _write_gold_once(gold_dir / "medication_annotations.csv", gold_payload)

    reason_counts = dict(sorted(Counter(
        row["review_reason"] for row in rows
    ).items()))
    silver_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "scope": scope,
        "context_chars": context_chars,
        "input_manifest_sha256": _sha256_file(bronze_dir / "MANIFEST.json"),
        "explain_sha256": _sha256_file(explain_path),
        "kb_artifacts": kb.manifest.get("artifacts", {}),
        "mention_count": len(rows),
        "group_count": len(group_rows),
        "review_reason_counts": reason_counts,
        "artifacts": {
            "medication_mentions.csv": {
                "bytes": len(mention_payload),
                "sha256": _sha256_bytes(mention_payload),
            },
            "medication_groups.csv": {
                "bytes": len(group_payload),
                "sha256": _sha256_bytes(group_payload),
            },
        },
    }
    _write(silver_dir / "MANIFEST.json", _json_bytes(silver_manifest))

    gold_manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": gold_version,
        "source_run_id": run_id,
        "allowed_decisions": [
            "accept", "replace", "not_drug", "insufficient_evidence", "span_error",
        ],
        "annotation_rows": len(gold_rows),
        "template": {
            "bytes": len(gold_payload),
            "sha256": _sha256_bytes(gold_payload),
        },
    }
    _write_gold_once(gold_dir / "MANIFEST.json", _json_bytes(gold_manifest))
    return {
        "bronze": bronze_dir,
        "silver": silver_dir,
        "gold": gold_dir,
        "mentions": len(rows),
        "groups": len(group_rows),
        "reasons": reason_counts,
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build a medication review pack")
    parser.add_argument("--input", type=Path, default=root / "data/test")
    parser.add_argument(
        "--explain", type=Path, default=root / "data/output/explain.json"
    )
    parser.add_argument("--kb", type=Path, default=root / "data/kb")
    parser.add_argument("--root", type=Path, default=root / "data/curation")
    parser.add_argument("--snapshot-id", default="competition_test_v1")
    parser.add_argument("--run-id", default="v3_3_medications")
    parser.add_argument("--gold-version", default="medications_v0")
    parser.add_argument(
        "--scope", default="actionable", choices=["actionable", "unlinked", "all"]
    )
    parser.add_argument("--context-chars", type=int, default=160)
    args = parser.parse_args(argv)

    try:
        kb = load_kb(args.kb)
        result = build_review_pack(
            input_dir=args.input,
            explain_path=args.explain,
            kb=kb,
            root=args.root,
            snapshot_id=args.snapshot_id,
            run_id=args.run_id,
            gold_version=args.gold_version,
            scope=args.scope,
            context_chars=args.context_chars,
        )
    except (KBError, ReviewPackError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"{result['mentions']} medication mentions · {result['groups']} groups"
    )
    print(f"  Bronze: {result['bronze']}")
    print(f"  Silver: {result['silver']}")
    print(f"  Gold template: {result['gold']}")
    print(f"  Reasons: {result['reasons']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
