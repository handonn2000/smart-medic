#!/usr/bin/env python3
"""Chạy prompt pre-annotation qua Claude API → thư mục response cho --ingest.

Đây là bước 2 của ba bước, bước duy nhất cần mạng:

    1. preannotate_dev.py --emit-prompts data/silver_prompts --files 1-100
    2. run_llm_teacher.py --prompts data/silver_prompts --out data/silver_responses   ← FILE NÀY
    3. preannotate_dev.py --ingest data/silver_responses --out data/silver --files 1-100

**KHÔNG thuộc runtime nộp bài.** Không có gì trong src/smart_medic import file này;
requirements.txt (ba wheel CPU) không chứa SDK nào. Cài riêng:

    uv pip install --python .venv/bin/python anthropic

## Vì sao mặc định là Batch API

100 request × ~12 KB, không cần độ trễ thấp — đúng hình dạng Batch API: **giảm
50% giá**, tối đa 100.000 request/batch, phần lớn xong trong 1 giờ (trần 24 giờ),
và không phải tự xoay rate limit. File `{n}.request.json` đã mang `custom_id` nên
map kết quả về đúng file là tra thẳng, không dựa vào thứ tự (kết quả batch trả về
KHÔNG theo thứ tự gửi).

Dùng `--mode stream` khi cần xem kết quả ngay (thử 2–3 file trước khi chạy 100).

## Bốn quyết định đáng biết

**Structured outputs, không phải "mong LLM trả JSON đúng".** `output_config.format`
ràng buộc đầu ra theo schema, nên `type` chỉ nhận đúng 5 nhãn viết đầy đủ có dấu.
Đây là hàng rào cho lỗi từng phá 471 record: nhãn viết tắt (`TÊN_XN`) giờ không
thể sinh ra được, thay vì phải phát hiện ở tầng ingest.

**Prompt caching trên system.** System prompt giống nhau y hệt ở cả 100 request
(~2.8 KB). Ghim `cache_control` vào đó ⇒ phần này tính giá đọc-cache (~0.1×) từ
request thứ hai. Ngưỡng cache tối thiểu của Claude Opus 5 là 512 token nên prompt
này đủ dài để cache.

**max_tokens rộng tay.** Claude Opus 5 BẬT thinking theo mặc định, và `max_tokens`
là trần cho thinking CỘNG output. Lịch sử dự án đã có 2/10 file bị cắt cụt ở
max_tokens (PRD tab 04 §6) nên mặc định để 32.000, không phải vài nghìn.

**Không có temperature/top_p/top_k.** Ba tham số này bị loại bỏ trên Claude Opus 5
và trả 400 nếu gửi. Muốn đa dạng cho self-consistency thì chạy nhiều lần vào
nhiều thư mục --out rồi hợp nhất, đừng tìm cách nâng temperature.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from preannotate_dev import parse_file_selector  # noqa: E402
from smart_medic.schema import Assertion, ConceptType  # noqa: E402

DEFAULT_MODEL = "claude-opus-5"
#: Rộng tay: Opus 5 bật thinking mặc định và max_tokens là trần cho
#: thinking + output. Cắt cụt là lỗi đã xảy ra thật trong dự án này.
DEFAULT_MAX_TOKENS = 32000
POLL_SECONDS = 30


def response_schema() -> dict:
    """Schema ràng buộc đầu ra — cưỡng chế đúng 5 nhãn và 3 assertion.

    Bọc trong object ``{"mentions": [...]}`` vì ingest đã nhận dạng wrapper này,
    và structured outputs cần object ở cấp cao nhất.
    """
    return {
        "type": "object",
        "properties": {
            "mentions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [t.value for t in ConceptType],
                        },
                        "assertions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [a.value for a in Assertion],
                            },
                        },
                        "candidates": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "type", "assertions", "candidates"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["mentions"],
        "additionalProperties": False,
    }


def load_requests(prompt_dir: Path, files: tuple[int, ...]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    missing: list[str] = []
    for n in files:
        path = prompt_dir / f"{n}.request.json"
        if not path.is_file():
            missing.append(str(n))
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        out.append((str(n), payload))
    if missing:
        print(
            f"  ⚠ thiếu {len(missing)} request: {', '.join(missing[:10])}"
            f"{' …' if len(missing) > 10 else ''}",
            file=sys.stderr,
        )
    return out


def already_done(out_dir: Path, name: str) -> bool:
    """Resume: file đã có VÀ parse được thì bỏ qua.

    Chỉ kiểm tra tồn tại là chưa đủ — một lần chạy bị kill giữa lúc ghi để lại
    file JSON dở, và bỏ qua nó sẽ âm thầm mất một file khỏi corpus nhãn bạc.
    """
    path = out_dir / f"{name}.json"
    if not path.is_file():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def build_params(payload: dict, args, *, schema: dict) -> dict:
    """Tham số Messages API cho MỘT file.

    ``cache_control`` ghim vào system: system giống nhau ở mọi request nên từ
    request thứ hai phần này tính giá đọc-cache.
    """
    return {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "system": [
            {
                "type": "text",
                "text": payload["system"],
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": payload["user"]}],
        "output_config": {
            "effort": args.effort,
            "format": {"type": "json_schema", "schema": schema},
        },
    }


def extract_mentions(message) -> list[dict]:
    """Lấy mảng mention ra khỏi message, kiểm stop_reason TRƯỚC khi đọc content.

    ``stop_reason == "refusal"`` trả về HTTP 200 với ``content`` rỗng hoặc dở —
    code đọc thẳng ``content[0]`` sẽ vỡ ở đây, nên phải rẽ nhánh trước.
    """
    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        raise RuntimeError(
            "model từ chối yêu cầu"
            + (f" (category={detail.category})" if detail else "")
        )
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            f"cắt cụt ở max_tokens={message.usage.output_tokens} — "
            "tăng --max-tokens hoặc giảm --effort"
        )
    text = next((b.text for b in message.content if b.type == "text"), "")
    if not text.strip():
        raise RuntimeError(f"content rỗng (stop_reason={message.stop_reason})")
    data = json.loads(text)
    return data["mentions"] if isinstance(data, dict) else data


def _usage_line(usage) -> str:
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={read} cache_write={write}"
    )


# ── chế độ stream: xem ngay, dùng để thử vài file ─────────────────────────────


def run_stream(client, jobs, args, out_dir: Path, schema: dict) -> int:
    import anthropic

    failed = 0
    totals = {"in": 0, "out": 0, "cache_read": 0}
    for index, (name, payload) in enumerate(jobs, 1):
        params = build_params(payload, args, schema=schema)
        for attempt in range(args.max_retries + 1):
            try:
                # Stream vì max_tokens lớn: request non-stream mà SDK ước tính
                # vượt ~10 phút sẽ bị chặn bằng ValueError.
                with client.messages.stream(**params) as stream:
                    message = stream.get_final_message()
                mentions = extract_mentions(message)
                (out_dir / f"{name}.json").write_text(
                    json.dumps(mentions, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                totals["in"] += message.usage.input_tokens
                totals["out"] += message.usage.output_tokens
                totals["cache_read"] += (
                    getattr(message.usage, "cache_read_input_tokens", 0) or 0
                )
                print(
                    f"  [{index}/{len(jobs)}] {name}: {len(mentions)} mention  "
                    f"({_usage_line(message.usage)})"
                )
                break
            except anthropic.RateLimitError as exc:
                wait = int(exc.response.headers.get("retry-after", 2 ** attempt * 5))
                print(f"  [{name}] rate limit, chờ {wait}s", file=sys.stderr)
                time.sleep(wait)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                status = getattr(exc, "status_code", None)
                if status is not None and status < 500 and status != 429:
                    print(f"  [{name}] LỖI không retry được: {exc}", file=sys.stderr)
                    failed += 1
                    break
                time.sleep(2 ** attempt * 3)
            except (RuntimeError, json.JSONDecodeError) as exc:
                print(f"  [{name}] {exc}", file=sys.stderr)
                failed += 1
                break
        else:
            print(f"  [{name}] hết {args.max_retries} lần thử", file=sys.stderr)
            failed += 1
    print(
        f"\n  tổng token: in={totals['in']} out={totals['out']} "
        f"cache_read={totals['cache_read']}"
    )
    return failed


# ── chế độ batch: mặc định, giảm 50% giá ─────────────────────────────────────


def run_batch(client, jobs, args, out_dir: Path, schema: dict) -> int:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    state = out_dir / ".batch_state.json"
    batch_id = None
    if state.is_file() and not args.new_batch:
        batch_id = json.loads(state.read_text(encoding="utf-8")).get("batch_id")
        print(f"  tiếp tục batch đang có: {batch_id}  (--new-batch để gửi mới)")

    if batch_id is None:
        batch = client.messages.batches.create(
            requests=[
                Request(
                    custom_id=name,
                    params=MessageCreateParamsNonStreaming(
                        **build_params(payload, args, schema=schema)
                    ),
                )
                for name, payload in jobs
            ]
        )
        batch_id = batch.id
        state.write_text(
            json.dumps({"batch_id": batch_id, "n": len(jobs)}, indent=2),
            encoding="utf-8",
        )
        print(f"  đã gửi batch {batch_id} · {len(jobs)} request")
        print(f"  state lưu ở {state} — Ctrl-C an toàn, chạy lại là poll tiếp")

    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        counts = batch.request_counts
        print(
            f"  {batch.processing_status}: đang xử lý {counts.processing} · "
            f"xong {counts.succeeded} · lỗi {counts.errored}",
            flush=True,
        )
        time.sleep(POLL_SECONDS)

    failed = 0
    wrote = 0
    for result in client.messages.batches.results(batch_id):
        name = result.custom_id
        kind = result.result.type
        if kind != "succeeded":
            print(f"  [{name}] batch {kind}", file=sys.stderr)
            failed += 1
            continue
        try:
            mentions = extract_mentions(result.result.message)
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(f"  [{name}] {exc}", file=sys.stderr)
            failed += 1
            continue
        (out_dir / f"{name}.json").write_text(
            json.dumps(mentions, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        wrote += 1
    print(f"\n  ghi {wrote} file · lỗi {failed}")
    if failed == 0:
        state.unlink(missing_ok=True)
    else:
        print(f"  giữ {state} để chạy lại chỉ những file còn thiếu")
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Chạy prompt pre-annotation qua Claude API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--prompts", type=Path, default=ROOT / "data/silver_prompts")
    ap.add_argument("--out", type=Path, default=ROOT / "data/silver_responses")
    ap.add_argument("--files", default="1-100", help="'1-100' hoặc '1,3,4'")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mode", default="batch", choices=["batch", "stream"])
    ap.add_argument("--effort", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--max-retries", type=int, default=4,
                    help="chỉ dùng ở --mode stream")
    ap.add_argument("--redo", action="store_true",
                    help="chạy lại cả file đã có response (mặc định: bỏ qua)")
    ap.add_argument("--new-batch", action="store_true",
                    help="bỏ .batch_state.json và gửi batch mới")
    ap.add_argument("--dry-run", action="store_true",
                    help="in việc sẽ làm rồi thoát, không gọi API")
    args = ap.parse_args(argv)

    files = parse_file_selector(args.files)
    jobs = load_requests(args.prompts, files)
    if not jobs:
        print(
            f"LỖI: không có request nào trong {args.prompts}\n"
            "Sinh trước bằng: python3 scripts/preannotate_dev.py --emit-prompts "
            f"{args.prompts} --files {args.files}",
            file=sys.stderr,
        )
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.redo:
        before = len(jobs)
        jobs = [j for j in jobs if not already_done(args.out, j[0])]
        if before != len(jobs):
            print(f"  resume: bỏ qua {before - len(jobs)} file đã có response")
    if not jobs:
        print("  không còn gì để làm — mọi file đã có response.")
        return 0

    print(f"  {len(jobs)} request · model={args.model} · mode={args.mode} "
          f"· effort={args.effort} · max_tokens={args.max_tokens}")
    if args.dry_run:
        print("  --dry-run: thoát, không gọi API.")
        print(f"  sẽ ghi vào {args.out}/{{n}}.json")
        return 0

    try:
        import anthropic
    except ImportError:
        print(
            "LỖI: thiếu SDK Anthropic (chỉ cần cho script này, KHÔNG cần cho "
            "runtime nộp bài).\n"
            "  uv pip install --python .venv/bin/python anthropic",
            file=sys.stderr,
        )
        return 2

    client = anthropic.Anthropic()
    schema = response_schema()
    try:
        runner = run_batch if args.mode == "batch" else run_stream
        failed = runner(client, jobs, args, args.out, schema)
    except anthropic.AuthenticationError:
        print(
            "LỖI xác thực. Đặt ANTHROPIC_API_KEY, hoặc `ant auth login` rồi "
            "chạy lại (SDK tự đọc profile).",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("\n  đã dừng. Chạy lại để tiếp tục (resume tự bỏ qua file đã xong).")
        return 130

    print(
        f"\n  Bước tiếp theo:\n"
        f"    PYTHONPATH=src python3 scripts/preannotate_dev.py "
        f"--ingest {args.out} --out data/silver --files {args.files}"
    )
    if failed:
        print(f"\n  ⚠ {failed} file lỗi — chạy lại để thử tiếp.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
