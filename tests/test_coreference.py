"""L4 · masked-drug co-reference. Ships disabled; these tests enable it.

Two things need guarding. First that the feature is OFF by default, because
turning it on is a bet on an unobserved gold convention and the shipped archive
must not carry that bet. Second that when enabled it reproduces the hand-checked
verdicts — including the three filters, each of which exists because of a
specific real failure.

Run:  pytest tests/test_coreference.py -q
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smart_medic.linking import coreference  # noqa: E402

TEST_DIR = ROOT / "data" / "test"


def _raw(doc_id: str) -> str:
    with (TEST_DIR / f"{doc_id}.txt").open(encoding="utf-8", newline="") as fh:
        return fh.read()


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch):
    from smart_medic.io import config

    real_loader = config.load_pipeline
    real_loader.cache_clear()
    loaded = real_loader()
    loaded["linking"]["masked_coreference"]["enabled"] = True
    monkeypatch.setattr(coreference, "load_pipeline", lambda: loaded)
    yield
    real_loader.cache_clear()


def test_disabled_by_default() -> None:
    """The shipped archive must not carry this bet."""
    from smart_medic.io.config import load_pipeline, require

    cfg = require(load_pipeline(), "linking.masked_coreference")
    assert cfg["enabled"] is False
    # And with it off, the function is a no-op regardless of input.
    assert coreference.recover_codes("x", [{"text": "*******", "type": "THUỐC",
                                            "candidates": [], "position": [0, 7]}]) == {}


def test_recovers_aspirin_in_document_100(enabled) -> None:
    """The case the PRD names, end to end from the real document."""
    raw = _raw("100")
    concepts = [
        {"text": "*******", "type": "THUỐC", "candidates": [], "position": [690, 697]},
        {"text": "*******", "type": "THUỐC", "candidates": [], "position": [838, 845]},
        {"text": "aspirin", "type": "THUỐC", "candidates": ["1191"],
         "position": [1114, 1121]},
    ]
    got = coreference.recover_codes(raw, concepts)
    assert got == {690: ("1191",), 838: ("1191",)}


def test_salt_fragment_is_not_a_candidate(enabled) -> None:
    """`citrate` from "Alverin citrate 40mg" must not seed a 7-character match.

    This filter is why documents 7 and 9 stopped proposing a wrong code.
    """
    raw = "Simenic: Alverin citrate 40mg dùng *******"
    concepts = [
        {"text": "citrate", "type": "THUỐC", "candidates": ["114200"],
         "position": [17, 24]},
        {"text": "*******", "type": "THUỐC", "candidates": [], "position": [34, 41]},
    ]
    assert coreference.recover_codes(raw, concepts) == {}
    assert "citrate" in coreference.SALT_FRAGMENTS


def test_lab_assay_mention_is_not_a_candidate(enabled) -> None:
    """"Định lượng Fibrinogen" is an assay, not a prescription (document 40)."""
    raw = "Định lượng Fibrinogen (Yếu tố I) và dùng **********"
    concepts = [
        {"text": "Fibrinogen", "type": "THUỐC", "candidates": ["4385"],
         "position": [11, 21]},
        {"text": "**********", "type": "THUỐC", "candidates": [],
         "position": [41, 51]},
    ]
    assert coreference.recover_codes(raw, concepts) == {}


def test_ambiguous_length_yields_nothing(enabled) -> None:
    """Two different drugs of the same length means the key told us nothing."""
    raw = "dùng warfarin và dùng naproxen rồi ********"
    concepts = [
        {"text": "warfarin", "type": "THUỐC", "candidates": ["11289"],
         "position": [5, 13]},
        {"text": "naproxen", "type": "THUỐC", "candidates": ["7258"],
         "position": [22, 30]},
        {"text": "********", "type": "THUỐC", "candidates": [], "position": [34, 42]},
    ]
    assert coreference.recover_codes(raw, concepts) == {}


def test_length_must_match_exactly(enabled) -> None:
    raw = "dùng aspirin rồi **********"
    concepts = [
        {"text": "aspirin", "type": "THUỐC", "candidates": ["1191"],
         "position": [5, 12]},
        {"text": "**********", "type": "THUỐC", "candidates": [],
         "position": [17, 27]},
    ]
    assert coreference.recover_codes(raw, concepts) == {}


def test_the_flag_actually_reaches_the_pipeline(tmp_path) -> None:
    """Flipping the config must change the OUTPUT, not just the module's return.

    This exists because the first version of this feature shipped unwired: the
    module was importable and unit-tested, `enabled: true` loaded fine, and a
    full run still emitted 0 codes on redacted spans because nothing called
    `recover_codes`. Every other test in this file would have passed. The only
    thing that catches a dead code path is running the real entry point and
    reading the files it wrote.
    """
    import subprocess

    src = ROOT / "src"
    script = (
        "import sys, json, glob, os, pathlib;"
        f"sys.path.insert(0, {str(src)!r});"
        "from smart_medic.io import config;"
        "c = config.load_pipeline();"
        "c['extract']['recall_floor']['redacted']['enabled'] = True;"
        "c['linking']['masked_coreference']['enabled'] = True;"
        "from smart_medic import cli;"
        f"cli.run(pathlib.Path({str(ROOT / 'data' / 'test')!r}),"
        f" pathlib.Path({str(tmp_path)!r}), quiet=True, enforce_rate_band=False);"
        "recs = [e for p in glob.glob(os.path.join("
        f"{str(tmp_path)!r}, '*.json')) for e in json.load(open(p, encoding='utf-8'))];"
        "stars = [e for e in recs if e['text'] and set(e['text']) == {'*'}];"
        "print(len(stars), sum(1 for e in stars if e['candidates']))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT
    )
    assert out.returncode == 0, out.stderr[-2000:]
    n_stars, n_coded = (int(x) for x in out.stdout.split()[-2:])
    assert n_stars == 99, f"{n_stars} redacted spans, expected 99"
    assert n_coded == 12, (
        f"{n_coded} of them carry a code, expected 12 — the config flag is set "
        f"but the recovered codes are not reaching the written output"
    )


def test_scale_on_the_real_corpus(enabled) -> None:
    """12 of the 99 runs resolve — the number the +0.16 điểm estimate rests on.

    Reads the H candidate archive, which is the build this was measured against.
    Skips rather than guesses if that archive is not present.
    """
    archive = ROOT / "output_H_redacted.zip"
    if not archive.is_file():
        pytest.skip("output_H_redacted.zip not built")

    with zipfile.ZipFile(archive) as zf:
        total = 0
        for doc_id in (str(n) for n in range(1, 101)):
            concepts = json.loads(zf.read(f"output/{doc_id}.json"))
            total += len(coreference.recover_codes(_raw(doc_id), concepts))
    assert total == 12, (
        f"{total} runs resolve, expected 12 — the +0.16 điểm estimate and the "
        f"0.688 hand-checked precision both assume this count"
    )
