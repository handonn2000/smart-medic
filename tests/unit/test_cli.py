"""CLI phải phơi đủ 5 lệnh con và không nạp dependency nặng khi chỉ xem help."""

from __future__ import annotations

import pytest

from smart_medic.cli import build_parser

# 5 lệnh của 4 pha + `eval` (thêm ở Phase 2.5 — bộ đo Recall@k trên probe set)
PIPELINE_CMDS = {"extract", "normalize", "load", "validate", "build"}
# `eval` thêm ở Phase 2.5, `enrich` ở Phase 3, `dense` ở Phase 5
EXPECTED = PIPELINE_CMDS | {"enrich", "eval", "dense"}


def _kb_subcommands() -> set[str]:
    parser = build_parser()
    top = next(a for a in parser._actions if a.dest == "cmd")
    kb = top.choices["kb"]
    kb_sub = next(a for a in kb._actions if a.dest == "kb_cmd")
    return set(kb_sub.choices)


def test_kb_co_du_lenh_con():
    assert _kb_subcommands() == EXPECTED


def test_du_5_lenh_cua_4_pha():
    assert _kb_subcommands() >= PIPELINE_CMDS


@pytest.mark.parametrize("cmd", sorted(EXPECTED))
def test_moi_lenh_con_parse_duoc(cmd):
    args = build_parser().parse_args(["kb", cmd])
    assert args.cmd == "kb"
    assert args.kb_cmd == cmd


def test_thieu_lenh_con_thi_loi():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["kb"])


def test_source_chi_nhan_gia_tri_hop_le():
    assert build_parser().parse_args(["kb", "build", "--source", "icd"]).source == "icd"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["kb", "build", "--source", "loinc"])
