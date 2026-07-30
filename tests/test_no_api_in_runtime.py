"""Three tests that turn a regulation into a build error.

The rule (ADR 0003): closed-source APIs may generate DATA at build time, under
`scripts/`. The inference pipeline is self-hosted and capped at 9B parameters, and
nothing under `src/smart_medic/` may reach the network.

The realistic failure mode is not "used an API wrongly". It is an API leaking into
runtime through a helper someone imported without thinking — and that only surfaces
at the source-code review round, which is the one risk in this project that cannot
be bought back with points.

1. `test_no_vendor_http_in_runtime` — structural, not a grep. Imports the runtime
   package in a clean interpreter and walks `sys.modules`, so an indirect import
   three levels down is caught too.
2. `test_no_network_at_inference` — `socket` made to raise, then the pipeline runs
   on three real documents. Catches a hand-rolled HTTP client that no import scan
   would recognise.
3. `test_param_budget` — sums `params` in `configs/models.yaml`, asserts < 9e9.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

#: Top-level modules that must never be reachable from the inference pipeline.
FORBIDDEN = {
    "openai",
    "anthropic",
    "google",          # covers google.genai
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "boto3",
    "botocore",
    "cohere",
    "mistralai",
    "ollama",
    "litellm",
    "replicate",
    "transformers_stream_generator",
}

#: `eval/` is L7 — the measurement, deliberately outside the inference path. It
#: reads JSON off disk and never runs during a submission. Excluded so a future
#: plotting dependency there cannot fail this gate for the wrong reason.
EXCLUDED_SUBPACKAGES = {"eval"}

PARAM_BUDGET_FALLBACK = 9_000_000_000


def _runtime_modules() -> list[str]:
    """Every importable module on the inference path, `pipeline` first if it exists."""
    mods: list[str] = ["smart_medic"]
    if (SRC / "smart_medic" / "pipeline.py").exists():
        mods.append("smart_medic.pipeline")
    for path in sorted((SRC / "smart_medic").rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if len(parts) > 1 and parts[1] in EXCLUDED_SUBPACKAGES:
            continue
        name = ".".join(parts)
        if name and name not in mods:
            mods.append(name)
    return mods


def test_no_vendor_http_in_runtime():
    """Import the runtime in a clean interpreter; no vendor HTTP client may appear.

    A subprocess, not an in-process import, for two reasons: `sys.modules` here is
    already polluted by pytest and its plugins, and a clean interpreter is what the
    organisers will actually run.
    """
    modules = _runtime_modules()
    script = (
        "import importlib, json, sys\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"importing the runtime package failed:\n{proc.stderr[-3000:]}"
    )

    loaded = json.loads(proc.stdout.strip().splitlines()[-1])
    leaked = sorted({m.split(".")[0] for m in loaded} & FORBIDDEN)
    culprits = sorted(m for m in loaded if m.split(".")[0] in FORBIDDEN)
    assert not leaked, (
        f"API LEAK INTO RUNTIME — {leaked} reachable from src/smart_medic/.\n"
        f"Loaded: {culprits[:20]}\n"
        f"Modules imported: {len(modules)} ({modules[:6]}…)\n"
        "ADR 0003: every API call lives in scripts/, never in src/smart_medic/. "
        "This leak is only visible at the source-review round, i.e. too late."
    )


def test_no_network_at_inference(monkeypatch):
    """Run the pipeline on three real documents with the network amputated.

    Catches what an import scan cannot: a socket opened by hand, or a lazily
    imported client that only loads on the first call.
    """
    def refuse(*args, **kwargs):
        raise AssertionError(
            "the inference pipeline opened a network connection — see ADR 0003"
        )

    for name in ("socket", "create_connection", "socketpair"):
        monkeypatch.setattr(socket, name, refuse, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", refuse, raising=False)

    from smart_medic import layout, validate
    from smart_medic.io import load_test

    docs = load_test()[:3]
    assert len(docs) == 3, "need three test documents"

    ran = 0
    for doc in docs:
        # L2: the deterministic layers, which is what exists today.
        parsed = layout.parse(doc)
        assert parsed.lines
        # L6: the gate, on a real span taken from the document itself.
        unit = parsed.units[0]
        entity = {
            "text": doc.slice(unit.start, unit.end),
            "type": "TRIỆU_CHỨNG",
            "position": [unit.start, unit.end],
            "assertions": [],
            "candidates": [],
        }
        clean, _ = validate.enforce([entity], doc.raw, None)
        validate.assert_exact(doc.raw, clean, doc.doc_id)
        ran += 1

    # When P1+ lands a pipeline, exercise the real thing as well.
    if (SRC / "smart_medic" / "pipeline.py").exists():
        import importlib

        pipeline = importlib.import_module("smart_medic.pipeline")
        for doc in docs:
            pipeline.run_document(doc)  # type: ignore[attr-defined]

    assert ran == 3


def test_param_budget():
    """Σ `params` over the enabled models must stay under 9e9.

    Reads the YAML directly rather than through `io.config`: a test that guards a
    regulation should not depend on the loader it is guarding.
    """
    cfg = yaml.safe_load((ROOT / "configs" / "models.yaml").read_text(encoding="utf-8"))
    budget = int(cfg.get("param_budget", PARAM_BUDGET_FALLBACK))
    assert budget <= PARAM_BUDGET_FALLBACK, (
        f"configs/models.yaml declares param_budget={budget:,}, above the "
        f"regulation's {PARAM_BUDGET_FALLBACK:,}"
    )

    models = cfg.get("models") or []
    assert models, "configs/models.yaml declares no models"
    for i, m in enumerate(models):
        assert "params" in m, f"models[{i}] ({m.get('name')}) has no `params` field"
        assert isinstance(m["params"], int) and m["params"] > 0, (
            f"models[{i}] params must be a positive int, got {m['params']!r}"
        )

    enabled = [m for m in models if m.get("enabled")]
    total = sum(m["params"] for m in enabled)
    declared = sum(m["params"] for m in models)

    assert total < budget, (
        f"PARAMETER BUDGET EXCEEDED: enabled models total {total:,} >= {budget:,}. "
        f"Enabled: {[m['name'] for m in enabled]}"
    )
    # Guard the next phase too: enabling every declared model must still fit, so
    # P3 cannot overrun the cap by flipping a flag.
    assert declared < budget, (
        f"the DECLARED model set totals {declared:,} >= {budget:,} — enabling them "
        f"all would breach the cap. Trim configs/models.yaml now, not at P3."
    )

    for m in enabled:
        assert m.get("revision_sha"), (
            f"model {m['name']!r} is enabled with no revision_sha. Pin the SHA, not "
            f"a tag: a tag moves, a moved tokenizer moves every offset."
        )


@pytest.mark.parametrize("layer", sorted(EXCLUDED_SUBPACKAGES))
def test_excluded_subpackage_exists(layer):
    """Guard the exclusion list itself: a typo would silently skip a whole layer."""
    assert (SRC / "smart_medic" / layer).is_dir(), (
        f"EXCLUDED_SUBPACKAGES names {layer!r}, which is not a layer — the "
        f"exclusion is silently doing nothing"
    )
