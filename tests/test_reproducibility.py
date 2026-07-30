"""The submission has to survive the organisers' machine, not just ours.

PRD §5: the top ~15 teams hand over source code, and *"nếu BTC không cài đặt lại
được source code của nhóm → nhóm thi sẽ bị loại"*. That makes "runs on an
interpreter we did not choose" a scored property, and it is the one risk that
cannot be bought back with points later.

Two guards, both cheap and both for failures we actually hit:

1. `test_runtime_imports_are_declared` — every non-stdlib module the inference
   path imports must appear in `requirements.txt`. `requirements.txt` shipped
   empty for most of this project's life while the pipeline needed PyYAML; the
   pipeline ran fine locally because the dependency was already installed, which
   is exactly why a human never noticed.

2. `test_no_version_gated_pathlib_kwargs` — `Path.read_text(newline=...)` and
   `Path.write_text(newline=...)` are Python 3.13+, while `pyproject.toml`
   promises 3.11. Both were present, and on a 3.11 interpreter the pipeline died
   with a `TypeError` on the first document. `open(newline=...)` is equivalent
   and has worked since 3.0. The keyword itself is load-bearing (it stops CRLF
   translation, which would shift every offset after the first line break), so
   the fix is the call, not the argument.

Cross-version byte-identity of the archive is verified by
`make verify-repro`, which runs the pipeline under two interpreters and compares
digests — it needs a second interpreter, so it is a Makefile target rather than a
unit test that would skip silently in CI.

Run:  pytest tests/test_reproducibility.py -q
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "smart_medic"
REQUIREMENTS = ROOT / "requirements.txt"

#: Modules that are ours, not dependencies.
LOCAL = {"smart_medic"}

#: `Path` methods whose `newline=` keyword only exists from Python 3.13.
VERSION_GATED = {"read_text", "write_text"}


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _toplevel_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: our own package.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _declared_requirements() -> set[str]:
    if not REQUIREMENTS.is_file():
        return set()
    out: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
        if name:
            out.add(name.lower().replace("-", "_"))
    return out


#: pip name -> import name, where they differ.
DISTRIBUTION_ALIASES = {"pyyaml": "yaml"}


def test_runtime_imports_are_declared():
    """Every third-party module src/ imports is installable from requirements.txt."""
    stdlib = set(sys.stdlib_module_names)

    imported: dict[str, list[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _toplevel_imports(tree):
            if name in stdlib or name in LOCAL or name.startswith("_"):
                continue
            imported.setdefault(name, []).append(str(path.relative_to(ROOT)))

    declared = _declared_requirements()
    declared |= {DISTRIBUTION_ALIASES.get(d, d) for d in declared}

    missing = {mod: files for mod, files in imported.items() if mod not in declared}
    assert not missing, (
        "src/ imports modules that requirements.txt does not declare, so a fresh "
        "`pip install -r requirements.txt` produces a pipeline that cannot start:\n"
        + "\n".join(f"  {mod}  ← {', '.join(sorted(set(f)))}"
                    for mod, f in sorted(missing.items()))
    )


def test_no_version_gated_pathlib_kwargs():
    """No `Path.read_text/write_text(newline=...)` — that keyword is 3.13+.

    `pyproject.toml` declares `requires-python = ">=3.11"`. A call that needs 3.13
    turns that declaration into a lie and the pipeline into a `TypeError` on the
    grader's machine. Use `Path.open(..., newline=...)` instead: same behaviour,
    available since 3.0.
    """
    offenders: list[str] = []
    for path in sorted(list(_python_files()) + list((ROOT / "tests").glob("*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in VERSION_GATED:
                continue
            if any(kw.arg == "newline" for kw in node.keywords):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: "
                    f".{func.attr}(newline=...) requires Python 3.13"
                )

    assert not offenders, (
        "Python 3.13+ API used in a project that declares >=3.11 — replace with "
        "`Path.open(..., newline=...)`:\n" + "\n".join(offenders)
    )


def test_every_runtime_data_file_is_tracked_by_git():
    """A clean checkout must be able to run inference.

    Found by rehearsal, not by reasoning: `git archive HEAD` into a temp
    directory, install, run — and it died with

        ConfigError: data/knowledge_base/brand_to_ingredient.json not found

    `.gitignore` excluded `/data/knowledge_base` (the raw UMLS drops are 660 MB
    and licence-gated) and `data/artifacts/` (marked "regenerable"). Regenerable
    was true and beside the point: the rebuild needs those same 660 MB the
    organisers will not have. Three derived files, 11 MB together, are what the
    inference path actually opens, and without them a fresh clone raises on the
    first document.

    Under PRD §5 that is a disqualification, so this is checked mechanically
    rather than left to whoever remembers to rehearse.

    A static scan of the source is NOT enough, and the first version of this test
    proved it: `edge_verify.py` builds its path as `Path(kb_paths()["root"]) /
    "RXNCUI.RRF"`, so no regex over the source sees `data/knowledge_base/...`,
    and the second rehearsal died on exactly that file. This runs the real
    pipeline over the real test set with `open` and `Path.read_text`
    instrumented, so what it checks is what the process opened.
    """
    import builtins
    import subprocess

    opened: set[str] = set()

    def note(target) -> None:
        try:
            resolved = Path(target).resolve()
            rel = resolved.relative_to(ROOT)
        except (ValueError, OSError, TypeError):
            return
        if rel.parts and rel.parts[0] == "data" and rel.parts[1] != "test":
            opened.add(rel.as_posix())

    real_open, real_read_text = builtins.open, Path.read_text

    def spy_open(file, *a, **k):
        note(file)
        return real_open(file, *a, **k)

    def spy_read_text(self, *a, **k):
        note(self)
        return real_read_text(self, *a, **k)

    import tempfile

    from smart_medic import cli

    builtins.open, Path.read_text = spy_open, spy_read_text
    try:
        with tempfile.TemporaryDirectory() as out:
            cli.run(ROOT / "data" / "test", out, quiet=True)
    finally:
        builtins.open, Path.read_text = real_open, real_read_text

    assert opened, "instrumentation caught nothing — the spy is broken, not the repo"

    tracked = set(
        subprocess.run(
            ["git", "ls-files", "data/"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        ).stdout.split()
    )
    if not tracked:  # not a git checkout (e.g. unpacked tarball) — nothing to assert
        return

    missing = sorted(r for r in opened if r not in tracked and not r.startswith("data/output"))
    assert not missing, (
        "the inference path reads data files that git does not track, so a fresh "
        "clone cannot run:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\n\nAdd them with `git add -f`, or stop reading them at inference time. "
        "Do not rely on `make index` — that rebuild needs the licence-gated raw "
        "drops the organisers will not have."
    )


def test_declared_python_floor_is_honoured():
    """`requires-python` must not promise a version the code cannot run on."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
    assert match, "pyproject.toml has no requires-python"
    floor = re.search(r">=\s*(\d+)\.(\d+)", match.group(1))
    assert floor, f"cannot parse a floor from {match.group(1)!r}"
    major, minor = int(floor.group(1)), int(floor.group(2))
    assert (major, minor) >= (3, 11), "3.11 is the oldest interpreter we verify on"
    # The guard above proves the code is compatible with the floor; this proves
    # the floor is not quietly raised to paper over an incompatibility instead.
    assert (major, minor) <= (3, 11), (
        f"requires-python was raised to {major}.{minor}. That is allowed, but it "
        f"narrows the interpreters the organisers may use — raise it only "
        f"deliberately, and re-run `make verify-repro` on the new floor."
    )
