"""Chạy cổng chất lượng và in báo cáo. Trả exit code kiểu Unix."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from smart_medic.kb import config
from smart_medic.kb.validate.rules import Rule, rules_for

SMOKE_PATH = Path(__file__).with_name("smoke_queries.yaml")


def _run_rules(conn: sqlite3.Connection) -> tuple[int, int, list[str]]:
    rules: list[Rule] = rules_for(conn)
    failures: list[str] = []
    print(f"\n── Rule ({len(rules)}) " + "─" * 46)
    for rule in rules:
        ok, value = rule.run(conn)
        mark = "✓" if ok else "✗"
        print(f"  {mark} {rule.name:<34} {value:>10,}   kỳ vọng {rule.expected}")
        if not ok:
            failures.append(f"{rule.name}: được {value:,}, kỳ vọng {rule.expected}")
    return len(rules) - len(failures), len(rules), failures


def _run_smoke(db: Path) -> tuple[int, int, list[str]]:
    from smart_medic.kb.query import KBStore, search_lexical

    if not SMOKE_PATH.is_file():
        return 0, 0, []
    cases = yaml.safe_load(SMOKE_PATH.read_text(encoding="utf-8")) or []
    if not cases:
        return 0, 0, []

    failures: list[str] = []
    print(f"\n── Smoke query ({len(cases)}) " + "─" * 38)
    with KBStore(db) as store:
        for case in cases:
            hits = search_lexical(
                store,
                case["query"],
                vocab=case.get("vocab"),
                top_k=case.get("top_k", 10),
            )
            codes = [h.code for h in hits]
            # ICD có phân cấp theo tiền tố (K21 ⊃ K21.0) nên khớp tiền tố là đủ.
            # RxNorm thì KHÔNG — mã "161" mà khớp tiền tố sẽ ăn nhầm "1610",
            # nên các ca RxNorm phải dùng `expect_code` (khớp chính xác).
            if "expect_code" in case:
                want = case["expect_code"]
                match = codes.index(want) + 1 if want in codes else None
            else:
                want = case["expect_prefix"]
                match = next((i + 1 for i, c in enumerate(codes) if c.startswith(want)), None)
            mark = "✓" if match else "✗"
            pos = f"#{match}" if match else "—"
            print(f"  {mark} {case['query'][:36]:<38} → {want:<8} {pos:>4}")
            if not match:
                failures.append(f"{case['query']!r} → mong {want}, được {codes[:5]}")
    return len(cases) - len(failures), len(cases), failures


def run(db: Path | None = None) -> int:
    db = db or config.KB_SQLITE
    if not db.is_file():
        print(f"✗ Không tìm thấy artifact: {db}")
        return 1

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rule_ok, rule_n, rule_fail = _run_rules(conn)
    finally:
        conn.close()

    smoke_ok, smoke_n, smoke_fail = _run_smoke(db)

    failures = rule_fail + smoke_fail
    print("\n" + "═" * 62)
    print(f"  Rule        {rule_ok}/{rule_n}")
    print(f"  Smoke query {smoke_ok}/{smoke_n}")
    if failures:
        print(f"\n✗ {len(failures)} cổng KHÔNG đạt:")
        for f in failures:
            print(f"    · {f}")
        return 1
    print("\n✓ Tất cả cổng đạt.")
    return 0
