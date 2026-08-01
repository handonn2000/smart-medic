"""Điều phối 4 pha. CLI chỉ gọi vào đây, không gọi thẳng module con.

Mỗi hàm trả về exit code kiểu Unix: 0 là thành công.
"""

from __future__ import annotations

import time
from pathlib import Path


def _banner(title: str) -> float:
    print(f"\n╔═ {title} " + "═" * max(0, 58 - len(title)))
    return time.perf_counter()


def _done(t0: float) -> None:
    print(f"╚═ xong sau {time.perf_counter() - t0:.1f}s")


def run_extract(*, source: str = "all", force: bool = False) -> int:
    from smart_medic.kb import extract

    t0 = _banner(f"extract · {source}")
    counts = extract.run(source=source, force=force)
    print(f"  staging/raw: {counts}")
    _done(t0)
    return 0


def run_normalize() -> int:
    from smart_medic.kb import normalize

    t0 = _banner("normalize")
    counts = normalize.run()
    print(f"  staging/norm: {counts}")
    _done(t0)
    return 0


def run_enrich(*, only: str | None = None, skip: str | None = None) -> int:
    from smart_medic.kb import enrich

    t0 = _banner("enrich")
    counts = enrich.run(only=only, skip=skip)
    print(f"  staging/enrich: {counts}")
    _done(t0)
    return 0


def run_load(*, out: str | None = None) -> int:
    from smart_medic.kb import load

    t0 = _banner("load")
    result = load.run(out=out)
    print(f"  bảng: {result['stats']}")
    print(f"  artifact_sha256: {result['manifest']['artifact_sha256'][:16]}…")
    _done(t0)
    return 0


def run_validate(*, db: str | None = None) -> int:
    from smart_medic.kb.validate import report

    t0 = _banner("validate")
    code = report.run(Path(db) if db else None)
    _done(t0)
    return code


def run_dense(*, db: str | None = None, out: str | None = None) -> int:
    from smart_medic.kb import dense

    t0 = _banner("dense")
    meta = dense.build(Path(db) if db else None, Path(out) if out else None)
    print(f"  {meta.n_vectors:,} vector · dim {meta.dim} · model {meta.model}")
    print(f"  gắn với nội dung artifact {meta.content_sha256[:16]}…")
    _done(t0)
    return 0


def run_eval(
    *,
    db: str | None = None,
    probe: str | None = None,
    tiers: str | None = None,
    max_fan_in: int | None = None,
    save: str | None = None,
    compare: str | None = None,
) -> int:
    from smart_medic.kb import evaluate

    t0 = _banner("eval")
    code = evaluate.run(
        db=Path(db) if db else None,
        probe=Path(probe) if probe else None,
        tiers=tuple(t.strip() for t in tiers.split(",")) if tiers else None,
        max_fan_in=max_fan_in,
        save=Path(save) if save else None,
        compare=Path(compare) if compare else None,
    )
    _done(t0)
    return code


def run_build(*, source: str = "all", force: bool = False) -> int:
    t0 = time.perf_counter()
    for step in (
        lambda: run_extract(source=source, force=force),
        run_normalize,
        run_enrich,
        run_load,
        run_validate,
    ):
        code = step()
        if code:
            print(f"\n✗ Dừng: pha trả về mã lỗi {code}")
            return code
    print(f"\n✓ Build xong sau {time.perf_counter() - t0:.1f}s")
    return 0
