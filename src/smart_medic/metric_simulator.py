"""Threshold simulator for Smart Medic's uncertain competition metric.

With a labelled gold directory this module reports the real local score.  When
gold is unavailable it switches to an explicitly labelled expectation model;
it never presents a self-score as accuracy.  The proxy uses rerank confidence
as the probability that a retained code is correct and exposes every
assumption on the command line.

Examples::

    PYTHONPATH=src python -m smart_medic.metric_simulator \
        --explain data/output/explain.json

    PYTHONPATH=src python -m smart_medic.metric_simulator \
        --explain data/output/explain.json --gold data/dev_gold
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .pipeline import PipelineConfig, select_candidate_set
from .schema import MAPPABLE
from .score import W_ASSERT, W_CAND, W_TEXT, score_file

_MAPPABLE_VALUES = {value.value for value in MAPPABLE}


@dataclass(frozen=True)
class ThresholdPoint:
    threshold: float
    assigned_mentions: int
    assigned_codes: int
    candidate_score: float
    final_score: float
    mode: str


def threshold_grid(start: float, stop: float, step: float) -> list[float]:
    if step <= 0 or stop < start:
        raise ValueError("threshold grid không hợp lệ")
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def _candidate_scores(record: dict) -> list[tuple[str, float]]:
    provenance = record.get("_provenance", {})
    scores = provenance.get("scores", {})
    pairs = [
        (key[5:], float(value))
        for key, value in scores.items()
        if key.startswith("code:")
    ]
    return sorted(pairs, key=lambda item: (-item[1], item[0]))


def candidates_at_threshold(
    record: dict,
    threshold: float,
    *,
    max_candidates: int = 2,
    ambiguity_margin: float = 0.0,
) -> list[str]:
    """Áp ĐÚNG chính sách của pipeline lên một bản ghi explain.

    Trước đây hàm này chép lại luật lọc bằng tay và đã lệch (nó chỉ biết
    ``gazetteer_exact``, không biết ``rxnorm_anchor_exact`` thêm ở phase 1).
    Giờ nó gọi thẳng :func:`smart_medic.pipeline.select_candidate_set`, nên mô
    phỏng không thể lệch khỏi thứ đang chạy.

    Lưu ý: ``threshold`` không còn quét được đường bỏ trống nữa — bỏ trống bây
    giờ do ``p_t`` quyết định, không do điểm rerank. Sweep vì thế chỉ còn ảnh
    hưởng tới mã thứ hai.
    """
    provenance = record.get("_provenance", {})
    scores = {
        key: float(value)
        for key, value in provenance.get("scores", {}).items()
    }
    codes = [code for code, _ in _candidate_scores(record)]
    if not codes:
        codes = list(record.get("candidates", ()))
    decision = select_candidate_set(
        codes,
        scores=scores,
        link_path=provenance.get("link_path", ""),
        type_confidence=float(provenance.get("type_confidence", 1.0)),
        min_type_confidence=PipelineConfig().min_type_confidence,
        max_candidates=max_candidates,
        candidate_threshold=threshold,
        ambiguity_margin=ambiguity_margin,
    )
    return list(decision.codes)


def predictions_at_threshold(
    explain: dict[str, list[dict]],
    threshold: float,
    *,
    max_candidates: int = 2,
    ambiguity_margin: float = 0.0,
) -> dict[str, list[dict]]:
    predictions: dict[str, list[dict]] = {}
    for filename, records in explain.items():
        stem = Path(filename).stem
        clean: list[dict] = []
        for record in records:
            item = {key: value for key, value in record.items() if key != "_provenance"}
            item["candidates"] = candidates_at_threshold(
                record,
                threshold,
                max_candidates=max_candidates,
                ambiguity_margin=ambiguity_margin,
            )
            clean.append(item)
        predictions[stem] = clean
    return predictions


def _actual_point(
    predictions: dict[str, list[dict]], gold: dict[str, list[dict]], threshold: float
) -> ThresholdPoint:
    keys = sorted(set(predictions) & set(gold))
    if not keys:
        raise ValueError("không có file chung giữa explain và gold")
    rows = [score_file(gold[key], predictions[key]) for key in keys]
    mean = lambda name: sum(row[name] for row in rows) / len(rows)  # noqa: E731
    text_score = mean("text")
    assertion_score = mean("assertions")
    candidate_score = mean("candidates")
    assigned_mentions = sum(
        bool(record.get("candidates")) for records in predictions.values() for record in records
    )
    assigned_codes = sum(
        len(record.get("candidates", ())) for records in predictions.values() for record in records
    )
    final = W_TEXT * text_score + W_ASSERT * assertion_score + W_CAND * candidate_score
    return ThresholdPoint(
        threshold, assigned_mentions, assigned_codes,
        round(candidate_score, 6), round(final, 6), "gold",
    )


def _expected_point(
    explain: dict[str, list[dict]],
    predictions: dict[str, list[dict]],
    threshold: float,
    *,
    exact_accuracy: float,
    empty_gold_rate: float,
    text_score: float,
    assertion_score: float,
) -> ThresholdPoint:
    expected: list[float] = []
    assigned_mentions = assigned_codes = 0
    for filename, source_records in explain.items():
        predicted_records = predictions[Path(filename).stem]
        for source, predicted in zip(source_records, predicted_records):
            if source["type"] not in _MAPPABLE_VALUES:
                expected.append(1.0)  # schema guarantees both candidate sets are empty
                continue
            codes = predicted.get("candidates", [])
            if codes:
                assigned_mentions += 1
                assigned_codes += len(codes)
            path = source.get("_provenance", {}).get("link_path", "")
            if "gazetteer_exact" in path:
                expected.append(exact_accuracy if codes else empty_gold_rate)
                continue
            if not codes:
                expected.append(empty_gold_rate)
                continue
            probabilities = dict(_candidate_scores(source))
            # Approximation for a singleton gold set: extra candidates dilute
            # Jaccard even when one of them is correct.
            expected.append(
                (1.0 - empty_gold_rate)
                * min(1.0, sum(probabilities.get(code, 0.0) for code in codes))
                / len(codes)
            )

    candidate_score = sum(expected) / len(expected) if expected else 1.0
    final = W_TEXT * text_score + W_ASSERT * assertion_score + W_CAND * candidate_score
    return ThresholdPoint(
        threshold, assigned_mentions, assigned_codes,
        round(candidate_score, 6), round(final, 6), "expected",
    )


def sweep(
    explain: dict[str, list[dict]],
    thresholds: Iterable[float],
    *,
    gold: dict[str, list[dict]] | None = None,
    max_candidates: int = 2,
    ambiguity_margin: float = 0.0,
    exact_accuracy: float = 0.92,
    empty_gold_rate: float = 0.20,
    text_score: float = 0.85,
    assertion_score: float = 0.90,
) -> list[ThresholdPoint]:
    points: list[ThresholdPoint] = []
    for threshold in thresholds:
        predictions = predictions_at_threshold(
            explain,
            threshold,
            max_candidates=max_candidates,
            ambiguity_margin=ambiguity_margin,
        )
        if gold is not None:
            point = _actual_point(predictions, gold, threshold)
        else:
            point = _expected_point(
                explain,
                predictions,
                threshold,
                exact_accuracy=exact_accuracy,
                empty_gold_rate=empty_gold_rate,
                text_score=text_score,
                assertion_score=assertion_score,
            )
        points.append(point)
    return points


def _load_gold(directory: Path) -> dict[str, list[dict]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
        if path.name not in {"run_manifest.json", "explain.json"}
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smart Medic metric threshold simulator")
    parser.add_argument("--explain", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--start", type=float, default=0.50)
    parser.add_argument("--stop", type=float, default=0.95)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--ambiguity-margin", type=float, default=0.0)
    parser.add_argument("--exact-accuracy", type=float, default=0.92)
    parser.add_argument("--empty-gold-rate", type=float, default=0.20)
    parser.add_argument("--text-score", type=float, default=0.85)
    parser.add_argument("--assertion-score", type=float, default=0.90)
    parser.add_argument("--output", type=Path, default=None, help="ghi kết quả JSON")
    args = parser.parse_args(argv)

    explain = json.loads(args.explain.read_text(encoding="utf-8"))
    gold = _load_gold(args.gold) if args.gold else None
    points = sweep(
        explain,
        threshold_grid(args.start, args.stop, args.step),
        gold=gold,
        max_candidates=args.max_candidates,
        ambiguity_margin=args.ambiguity_margin,
        exact_accuracy=args.exact_accuracy,
        empty_gold_rate=args.empty_gold_rate,
        text_score=args.text_score,
        assertion_score=args.assertion_score,
    )
    best = max(points, key=lambda point: (point.final_score, point.threshold))

    label = "GOLD" if gold is not None else "EXPECTED (không có gold)"
    print(f"mode: {label}")
    print("threshold  assigned  codes  candidate  final")
    for point in points:
        marker = " *" if point == best else ""
        print(
            f"{point.threshold:>9.2f}  {point.assigned_mentions:>8}  "
            f"{point.assigned_codes:>5}  {point.candidate_score:>9.4f}  "
            f"{point.final_score:>6.4f}{marker}"
        )
    print(f"recommended_threshold: {best.threshold:.2f}")
    if gold is None:
        print(
            "warning: đây là mô phỏng kỳ vọng, không phải độ chính xác thực; "
            "thêm --gold để chấm nhãn thật"
        )

    if args.output:
        payload = {
            "mode": best.mode,
            "assumptions": None if gold is not None else {
                "exact_accuracy": args.exact_accuracy,
                "empty_gold_rate": args.empty_gold_rate,
                "text_score": args.text_score,
                "assertion_score": args.assertion_score,
            },
            "recommended_threshold": best.threshold,
            "points": [asdict(point) for point in points],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
