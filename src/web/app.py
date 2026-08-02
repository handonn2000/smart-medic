#!/usr/bin/env python3
"""
One-page web UI for scripts/validate_annotation.py.

Loads ICD10_VN.csv + RXNORM.csv the same way the CLI does, then validates
pasted note text + annotation JSON.

  python src/web/app.py
  # open http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import sys
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
WEB_DIR = Path(__file__).resolve().parent
ICD_PATH = ROOT / "data" / "knowledge_base" / "ICD10_VN.csv"
RXNORM_PATH = ROOT / "data" / "knowledge_base" / "RXNORM.csv"
HOST, PORT = "127.0.0.1", 8765

sys.path.insert(0, str(SCRIPTS))
from validate_annotation import (  # noqa: E402
    build_icd_sapbert_linker,
    check_doc,
    cross_doc_checks,
    load_icd,
    load_rxnorm,
)

STATE: dict = {
    "ready": False,
    "error": None,
    "icd": None,
    "icd_idx": None,
    "rx_names": None,
    "rx_tty": None,
    "rx_idx": None,
    "icd_linker": None,       # lazy SapBERT
    "icd_linker_error": None,
}


def json_line_map_from_text(raw: str) -> list[int]:
    """Same as validate_annotation.json_line_map, but for an in-memory string."""
    lines, depth, in_str, esc, line = [], 0, False, False, 1
    for ch in raw:
        if ch == "\n":
            line += 1
            continue
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if ch == "{" and depth == 2:
                lines.append(line)
        elif ch in "]}":
            depth -= 1
    return lines


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load_dictionaries() -> None:
    print(f"Loading ICD-10 from {ICD_PATH} ...", flush=True)
    icd, icd_idx = load_icd(str(ICD_PATH))
    print(f"  {len(icd):,} ICD codes.", flush=True)
    print(f"Loading RxNorm from {RXNORM_PATH} ...", flush=True)
    rx_names, rx_tty, rx_idx = load_rxnorm(str(RXNORM_PATH))
    print(f"  {len(rx_names):,} RxCUI.", flush=True)
    STATE.update(
        ready=True,
        icd=icd,
        icd_idx=icd_idx,
        rx_names=rx_names,
        rx_tty=rx_tty,
        rx_idx=rx_idx,
    )


def _ensure_sapbert_linker():
    """Load SapBERT once on first use (heavy); reuse afterward."""
    if STATE["icd_linker"] is not None:
        return STATE["icd_linker"]
    if STATE["icd_linker_error"]:
        raise RuntimeError(STATE["icd_linker_error"])
    print("Loading SapBERT ICD linker (first use) ...", flush=True)
    try:
        STATE["icd_linker"] = build_icd_sapbert_linker(str(ICD_PATH))
    except Exception as e:
        STATE["icd_linker_error"] = f"Không nạp được SapBERT: {e}"
        raise RuntimeError(STATE["icd_linker_error"]) from e
    print("  SapBERT ICD linker ready.", flush=True)
    return STATE["icd_linker"]


def run_check(
    txt: str,
    concepts_raw: str,
    suggest_cutoff: int = 70,
    linker: str = "rapidfuzz",
) -> dict:
    if not STATE["ready"]:
        raise RuntimeError(STATE["error"] or "Từ điển chưa sẵn sàng.")

    linker = (linker or "rapidfuzz").strip().lower()
    if linker not in ("rapidfuzz", "sapbert"):
        raise ValueError("linker phải là 'rapidfuzz' hoặc 'sapbert'.")

    concepts = json.loads(concepts_raw)
    if not isinstance(concepts, list):
        raise ValueError("Annotation JSON phải là một mảng các concept.")

    icd_linker = _ensure_sapbert_linker() if linker == "sapbert" else None

    lines = json_line_map_from_text(concepts_raw)
    doc = "<paste>"
    issues = check_doc(
        doc,
        txt,
        concepts,
        lines,
        STATE["icd"],
        STATE["icd_idx"],
        STATE["rx_names"],
        STATE["rx_tty"],
        STATE["rx_idx"],
        suggest_cutoff=suggest_cutoff,
        linker=linker,
        icd_linker=icd_linker,
    )
    issues += cross_doc_checks({doc: concepts})

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    issues.sort(key=lambda x: (order[x.level], x.code, x.doc, x.line))

    rows = [
        {
            "level": it.level,
            "code": it.code,
            "doc": it.doc,
            "line": it.line,
            "idx": it.idx,
            "text": it.text,
            "msg": it.msg,
        }
        for it in issues
    ]
    summary = {
        "documents": 1,
        "concepts": len(concepts),
        "linker": linker,
        "ERROR": sum(1 for i in issues if i.level == "ERROR"),
        "WARN": sum(1 for i in issues if i.level == "WARN"),
        "INFO": sum(1 for i in issues if i.level == "INFO"),
        "by_code": {},
    }
    for it in issues:
        summary["by_code"][it.code] = summary["by_code"].get(it.code, 0) + 1
    return {"issues": rows, "summary": summary}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self._send_json(
                200,
                {
                    "ready": STATE["ready"],
                    "error": STATE["error"],
                    "icd_codes": len(STATE["icd"] or {}),
                    "rx_codes": len(STATE["rx_names"] or {}),
                },
            )
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def _read_body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except Exception:
            return None, "Body phải là JSON."

    def _handle_read(self):
        payload, err = self._read_body_json()
        if err:
            self._send_json(400, {"error": err})
            return
        raw = payload.get("path")
        if not isinstance(raw, str) or not raw.strip():
            self._send_json(400, {"error": "Cần trường 'path' (string)."})
            return
        try:
            resolved = Path(raw).expanduser()
            if not resolved.is_absolute():
                resolved = (ROOT / resolved).resolve()
            else:
                resolved = resolved.resolve()
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            self._send_json(400, {"error": "Chỉ được đọc file trong thư mục project."})
            return
        except Exception as e:
            self._send_json(400, {"error": f"Đường dẫn không hợp lệ: {e}"})
            return
        if not resolved.is_file():
            self._send_json(404, {"error": f"Không tìm thấy file: {resolved}"})
            return
        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            self._send_json(500, {"error": f"Không đọc được file: {e}"})
            return
        self._send_json(200, {"path": str(resolved), "content": content})

    def _handle_check(self):
        payload, err = self._read_body_json()
        if err:
            self._send_json(400, {"error": err})
            return

        txt = payload.get("text")
        concepts_raw = payload.get("json")
        if not isinstance(txt, str) or not isinstance(concepts_raw, str):
            self._send_json(400, {"error": "Cần các trường 'text' và 'json' (string)."})
            return
        if not txt.strip():
            self._send_json(400, {"error": "Text bệnh án trống."})
            return
        if not concepts_raw.strip():
            self._send_json(400, {"error": "Annotation JSON trống."})
            return

        try:
            cutoff = int(payload.get("suggest_cutoff", 70))
        except (TypeError, ValueError):
            cutoff = 70

        linker = payload.get("linker", "rapidfuzz")
        if not isinstance(linker, str):
            linker = "rapidfuzz"

        try:
            result = run_check(
                txt, concepts_raw, suggest_cutoff=cutoff, linker=linker
            )
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Annotation JSON không hợp lệ: {e}"})
            return
        except Exception as e:
            traceback.print_exc()
            self._send_json(500, {"error": str(e)})
            return

        self._send_json(200, result)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/read":
            self._handle_read()
            return
        if path == "/api/check":
            self._handle_check()
            return
        self._send_json(404, {"error": "not found"})


def main():
    _ensure_utf8_stdio()
    if not ICD_PATH.is_file():
        sys.exit(f"Missing file: {ICD_PATH}")
    if not RXNORM_PATH.is_file():
        sys.exit(f"Missing file: {RXNORM_PATH}")

    try:
        load_dictionaries()
    except Exception as e:
        STATE["error"] = str(e)
        traceback.print_exc()
        sys.exit(f"Failed to load dictionaries: {e}")

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"\nAnnotation checker -> http://{HOST}:{PORT}\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
