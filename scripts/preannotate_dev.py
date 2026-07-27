#!/usr/bin/env python3
"""Pre-annotate the frozen 20-file dev set with an LLM — without shipping an LLM.

Vì sao script này tồn tại: dự án **không có gold label**. Tín hiệu accuracy duy
nhất là một con số leaderboard cho mỗi lần nộp, nên mọi thay đổi đều là phỏng
đoán. 20 file dev đã được chốt (phủ đủ tổ hợp genre × NFD × masked token, không
rò rỉ near-duplicate); annotate chúng biến mọi thay đổi sau này từ phỏng đoán
thành phép đo.

Thiết kế **provider-agnostic**: repo có ZERO runtime dependency và không được
thêm SDK của bất kỳ nhà cung cấp LLM nào (NFR1 là tiêu chí loại). Vì vậy script
chia làm hai nửa, ở giữa là con người hoặc một script gọi API tùy chọn:

    --emit-prompts <dir>   ghi payload prompt tự chứa cho từng file dev
    --ingest <dir>         đọc lại JSON trả về, gán position, validate, ghi gold

LUẬT CỨNG: **LLM KHÔNG BAO GIỜ trả position.** Nó chỉ trả *chuỗi* span; code
tự tính offset. Hai lý do đã xảy ra thật trong dự án này:

  * 20/100 file lưu ở dạng NFD (dấu là ký tự tổ hợp) — ``str.find()`` thất bại
    âm thầm, không ném exception, chỉ làm sai ``position``.
  * Một lần LLM diễn giải thay vì trích nguyên văn (1/472 span).

Nên toàn bộ việc định vị đi qua ``textref.build_textref`` + ``stages.locate``:
so khớp trên ``TextRef.norm``, xuất position trên ``TextRef.raw``. Span nào
không thỏa ``Span.verify(raw)`` thì **LOẠI BỎ và báo cáo**, không đoán.

Dùng:
    # 1. sinh prompt
    PYTHONPATH=src python3 scripts/preannotate_dev.py \
        --emit-prompts data/dev_prompts

    # 2. (thủ công / script riêng) chạy từng prompt qua LLM, lưu câu trả lời
    #    vào data/dev_responses/{n}.json — chỉ text/type/assertions/candidates

    # 3. gán position + validate + ghi gold
    PYTHONPATH=src python3 scripts/preannotate_dev.py \
        --ingest data/dev_responses --out data/dev_gold
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from smart_medic.normalize import norm_text  # noqa: E402
from smart_medic.schema import (  # noqa: E402
    ASSERTABLE,
    MAPPABLE,
    Assertion,
    ConceptType,
    Span,
    validate_file,
)
from smart_medic.textref import TextRef, read_textref  # noqa: E402

#: 20 file dev đã chốt — phủ đủ 14 tổ hợp genre × NFD × mask, không near-duplicate.
#: Đừng đổi danh sách này mà không đổi lý do chọn; nó là mẫu, không phải tùy tiện.
DEV_FILES: tuple[int, ...] = (
    1, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 21, 25, 26, 27, 31, 42, 54, 94,
)

#: Tên nhãn PHẢI viết đầy đủ, có dấu. Viết tắt ``TÊN_XN`` một lần đã làm hỏng
#: toàn bộ 471 record trong lịch sử dự án — prompt phải nói rõ điều này.
TYPE_NAMES: tuple[str, ...] = tuple(t.value for t in ConceptType)
ASSERTION_NAMES: tuple[str, ...] = tuple(a.value for a in Assertion)
MAPPABLE_NAMES = frozenset(t.value for t in MAPPABLE)
ASSERTABLE_NAMES = frozenset(t.value for t in ASSERTABLE)


# ── prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Bạn là chuyên gia annotate khái niệm y khoa trong văn bản lâm sàng tiếng Việt \
tự do (ghi chú bác sĩ, giấy ra viện, kết quả xét nghiệm, hỏi đáp bệnh nhân).

NHIỆM VỤ: đọc toàn bộ văn bản và liệt kê MỌI khái niệm y tế xuất hiện trong đó.

## 5 nhãn hợp lệ — viết ĐẦY ĐỦ, CÓ DẤU, ĐÚNG TỪNG KÝ TỰ

| type | nghĩa | ví dụ |
|---|---|---|
| `TRIỆU_CHỨNG` | dấu hiệu/triệu chứng bệnh nhân cảm thấy hoặc được mô tả | `sốt`, `khó thở`, `đau thượng vị`, `táo bón` |
| `TÊN_XÉT_NGHIỆM` | TÊN của một xét nghiệm/thăm dò/thủ thuật chẩn đoán | `công thức máu`, `Glucose`, `siêu âm ổ bụng`, `nội soi dạ dày` |
| `KẾT_QUẢ_XÉT_NGHIỆM` | GIÁ TRỊ hoặc kết luận của xét nghiệm | `5.6 mmol/L`, `âm tính`, `tăng nhẹ`, `HP (+)` |
| `CHẨN_ĐOÁN` | tên bệnh / chẩn đoán xác định hoặc nghi ngờ | `viêm dạ dày`, `đái tháo đường type 2`, `Thiếu men G6PD` |
| `THUỐC` | tên thuốc, kèm hàm lượng/đường dùng/tần suất nếu có liền kề | `omeprazole 20 mg po daily`, `Medrol 16mg`, `*****` |

TUYỆT ĐỐI KHÔNG viết tắt nhãn. Không dùng `TÊN_XN`, `TRIEU_CHUNG`, `CHAN_DOAN`,
không bỏ dấu, không đổi dấu gạch dưới. Sai một ký tự là hỏng toàn bộ file.

## 3 assertion hợp lệ

| assertion | khi nào gán |
|---|---|
| `isNegated` | khái niệm bị PHỦ ĐỊNH (`không sốt`, `chưa ghi nhận đau ngực`, `âm tính với`) |
| `isFamily` | khái niệm thuộc về NGƯỜI NHÀ, không phải bệnh nhân (`mẹ bị đái tháo đường`) |
| `isHistorical` | khái niệm thuộc TIỀN SỬ / quá khứ, không phải tình trạng hiện tại |

`assertions` là mảng, thường RỖNG. Chỉ gán khi văn bản nói rõ. Không đoán.
Chỉ ba type `TRIỆU_CHỨNG`, `CHẨN_ĐOÁN`, `THUỐC` được có assertions;
`TÊN_XÉT_NGHIỆM` và `KẾT_QUẢ_XÉT_NGHIỆM` luôn có `assertions: []`.

## candidates

* `CHẨN_ĐOÁN` → mã ICD-10 (ví dụ `["K21.0"]`), tối đa 2 mã, `[]` nếu không chắc.
* `THUỐC` → mã RxNorm RXCUI dạng chuỗi (ví dụ `["308135"]`), `[]` nếu không chắc.
* Ba type còn lại → **LUÔN LUÔN** `[]`. Không có ngoại lệ.

## QUY TẮC QUAN TRỌNG NHẤT: KHÔNG TRẢ VỀ VỊ TRÍ

Trường `text` phải là **chuỗi con NGUYÊN VĂN** copy từ văn bản đầu vào — đúng
từng ký tự, đúng hoa/thường, đúng dấu, không sửa chính tả, không chuẩn hóa,
không diễn giải, không dịch. Hệ thống sẽ tự dò chuỗi này trong văn bản gốc để
tính offset; nếu bạn viết lại dù chỉ một ký tự thì mention đó bị LOẠI BỎ.

TUYỆT ĐỐI KHÔNG thêm trường `position`, `start`, `end` hay chỉ số ký tự nào.
Bạn không thể đếm đúng offset (20% file dùng Unicode tổ hợp); code sẽ làm việc đó.

## Thứ tự và lặp lại

Liệt kê các mention theo ĐÚNG THỨ TỰ XUẤT HIỆN trong văn bản, từ trên xuống.
Nếu một khái niệm xuất hiện nhiều lần, liệt kê nó nhiều lần — lần thứ n trong
danh sách sẽ được gán cho lần xuất hiện thứ n trong văn bản.

## Định dạng đầu ra

CHỈ một mảng JSON, không markdown fence, không lời dẫn, không giải thích.
Mỗi phần tử đúng 4 trường: `text`, `type`, `assertions`, `candidates`.
"""

FEW_SHOT = """\
## Ví dụ

### Ví dụ 1 — đơn thuốc (trích từ ví dụ chính thức của đề bài)

Đầu vào:
```
Thuốc dùng trước nhập viện:
1. amlodipine 10 mg po daily
2. aspirin 81 mg po daily
8. docusate sodium 100 mg po bid điều trị táo bón
```

Đầu ra:
```json
[
  {"text": "amlodipine 10 mg po daily", "type": "THUỐC", "assertions": ["isHistorical"], "candidates": ["308135"]},
  {"text": "aspirin 81 mg po daily", "type": "THUỐC", "assertions": ["isHistorical"], "candidates": ["243670"]},
  {"text": "docusate sodium 100 mg po bid", "type": "THUỐC", "assertions": ["isHistorical"], "candidates": []},
  {"text": "táo bón", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []}
]
```

Lưu ý: span thuốc giữ trọn hàm lượng + đường dùng + tần suất, nhưng KHÔNG nuốt
phần `điều trị táo bón` — đó là chỉ định, và `táo bón` là một mention riêng.

### Ví dụ 2 — ghi chú lâm sàng có phủ định, tiền sử, người nhà

Đầu vào:
```
Bệnh nhân sốt 39 độ, không khó thở. Tiền sử: viêm dạ dày.
Mẹ bị đái tháo đường type 2. Glucose máu 8.5 mmol/L, HbA1c 7.2%.
Siêu âm ổ bụng: chưa phát hiện bất thường.
```

Đầu ra:
```json
[
  {"text": "sốt", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
  {"text": "khó thở", "type": "TRIỆU_CHỨNG", "assertions": ["isNegated"], "candidates": []},
  {"text": "viêm dạ dày", "type": "CHẨN_ĐOÁN", "assertions": ["isHistorical"], "candidates": ["K29.7"]},
  {"text": "đái tháo đường type 2", "type": "CHẨN_ĐOÁN", "assertions": ["isFamily"], "candidates": ["E11"]},
  {"text": "Glucose máu", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
  {"text": "8.5 mmol/L", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": [], "candidates": []},
  {"text": "HbA1c", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
  {"text": "7.2%", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": [], "candidates": []},
  {"text": "Siêu âm ổ bụng", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
  {"text": "chưa phát hiện bất thường", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": [], "candidates": []}
]
```

Lưu ý: `TÊN_XÉT_NGHIỆM` và `KẾT_QUẢ_XÉT_NGHIỆM` có `candidates: []` và
`assertions: []` — kể cả khi kết quả là âm tính. Phủ định của một *kết quả* nằm
trong chính chuỗi kết quả, không phải trong assertion.

### Ví dụ 3 — token bị che

Đầu vào:
```
Bệnh nhân được điều trị bằng ***** 500mg mỗi 8 giờ.
```

Đầu ra:
```json
[
  {"text": "***** 500mg", "type": "THUỐC", "assertions": [], "candidates": []}
]
```

Token bị che vẫn là một mention `THUỐC`; giữ nguyên dấu sao, `candidates` rỗng
vì không có bằng chứng nào xác định được hoạt chất.
"""

USER_TEMPLATE = """\
{few_shot}

## Văn bản cần annotate (file {name})

Đây là toàn bộ nội dung file. Copy span NGUYÊN VĂN từ đây.

<document>
{text}
</document>

Trả về CHỈ mảng JSON các mention, theo thứ tự xuất hiện, không kèm `position`.
"""


def build_prompt(name: str, raw: str) -> dict[str, Any]:
    """Payload tự chứa, không gắn với provider nào.

    Trả về ``{"custom_id", "system", "user"}`` — mọi SDK đều dựng được request
    từ ba trường này mà không cần script biết gì về nhà cung cấp.
    """
    return {
        "custom_id": name,
        "system": SYSTEM_PROMPT,
        "user": USER_TEMPLATE.format(few_shot=FEW_SHOT, name=name, text=raw),
        "response_format": "json_array",
        "schema_hint": {
            "types": list(TYPE_NAMES),
            "assertions": list(ASSERTION_NAMES),
            "fields": ["text", "type", "assertions", "candidates"],
            "forbidden_fields": ["position", "start", "end", "offset"],
        },
    }


def emit_prompts(input_dir: Path, out_dir: Path, files: Iterable[int]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    for n in files:
        src = input_dir / f"{n}.txt"
        if not src.exists():
            print(f"  ✗ {n}: thiếu {src}", file=sys.stderr)
            return 2
        raw = src.read_text(encoding="utf-8")
        payload = build_prompt(str(n), raw)

        (out_dir / f"{n}.request.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # Bản phẳng để dán tay vào một chat UI bất kỳ.
        (out_dir / f"{n}.prompt.txt").write_text(
            payload["system"] + "\n\n" + payload["user"], encoding="utf-8"
        )
        index.append({"file": str(n), "chars": len(raw), "request": f"{n}.request.json"})
        print(f"  ✓ {n}: {len(raw):>6} ký tự → {n}.request.json / {n}.prompt.txt")

    (out_dir / "index.json").write_text(
        json.dumps(
            {
                "dev_files": [int(x["file"]) for x in index],
                "prompts": index,
                "instructions": (
                    "Chạy từng request qua LLM bất kỳ. Lưu mảng JSON trả về vào "
                    "<dir>/{file}.json rồi chạy --ingest <dir>. "
                    "Câu trả lời KHÔNG được chứa 'position'."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n  {len(index)} prompt → {out_dir}")
    return 0


# ── định vị ───────────────────────────────────────────────────────────────────

#: Ký tự "trong từ" khi kiểm ranh giới. Dấu sao nằm trong danh sách vì token bị
#: che là chuỗi `*` liền nhau — nếu không, `********` khớp lọt vào giữa
#: `**********` và position lệch 43 ký tự (đo được trên file 1 và 7).
def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "*"


class DevLocator:
    """Chọn lần xuất hiện đúng cho một chuỗi span, rồi gán offset.

    Vì sao KHÔNG dùng thẳng ``stages.locate.Locator``: luật của nó là "mention
    thứ n khớp lần xuất hiện thứ n", đúng cho extractor rule-based vốn duyệt hết
    văn bản và không bao giờ bỏ sót lần nào. Một bản pre-annotation của LLM thì
    **có bỏ sót** — đo được trên chính artifact v3: 30/423 mention có một lần
    xuất hiện sớm hơn trong văn bản mà v3 không annotate, nên đếm tuần tự thuần
    túy gán nhầm 30 span. Thêm nữa, needle ngắn như ``ho`` nằm lọt trong
    ``khó``/``cho``/``họ``, việc mà ``str.find()`` không hề biết.

    Nên tầng này chỉ thêm phần **chọn ứng viên**; toàn bộ số học offset vẫn là
    ``TextRef.to_raw`` và bất biến vẫn là ``Span.verify`` — không có logic offset
    mới nào được viết ở đây.

    Thứ tự ưu tiên ứng viên:
      1. đúng ranh giới từ, và không lùi trước mention trước đó
      2. đúng ranh giới từ, ở bất kỳ đâu
      3. lọt giữa từ, nhưng không lùi
      4. lọt giữa từ, ở bất kỳ đâu
    Lần xuất hiện đã dùng cho cùng một chuỗi thì không dùng lại → mention thứ n
    vẫn rơi vào lần xuất hiện thứ n khi annotation liệt kê đủ.
    """

    def __init__(self, tref: TextRef) -> None:
        self.tref = tref
        self._used: dict[str, set[int]] = {}
        self._cursor = 0
        self.method = ""

    def _occurrences(self, needle: str) -> list[int]:
        hay = self.tref.norm
        out: list[int] = []
        i = hay.find(needle)
        while i >= 0:
            out.append(i)
            i = hay.find(needle, i + 1)   # +1: lần xuất hiện chồng lấn vẫn tính
        return out

    def _boundary_ok(self, ns: int, ne: int) -> bool:
        hay = self.tref.norm
        left = ns == 0 or not _is_word_char(hay[ns - 1])
        right = ne >= len(hay) or not _is_word_char(hay[ne])
        return left and right

    def locate(self, text: str) -> Span | None:
        needle = norm_text(text)
        if not needle:
            return None

        used = self._used.setdefault(needle, set())
        candidates = [ns for ns in self._occurrences(needle) if ns not in used]
        if not candidates:
            return None

        length = len(needle)
        ranked = sorted(
            candidates,
            key=lambda ns: (
                not self._boundary_ok(ns, ns + length),
                ns < self._cursor,
                ns,
            ),
        )
        ns = ranked[0]
        ne = ns + length

        rs, re_ = self.tref.to_raw(ns, ne)
        span = Span(rs, re_, self.tref.raw[rs:re_])
        if not span.verify(self.tref.raw):
            return None                   # bất biến vỡ → loại, không đoán

        used.add(ns)
        self._cursor = ns
        self.method = (
            "boundary" if self._boundary_ok(ns, ne) else "infix"
        ) + ("" if len(candidates) == 1 else "_ambiguous")
        return span


# ── đọc lại câu trả lời ───────────────────────────────────────────────────────


def strip_fences(text: str) -> str:
    """Bóc markdown fence. LLM bọc JSON trong ```json ... ``` thường xuyên."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    lines = lines[1:]                       # bỏ ```json
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def parse_response(text: str) -> tuple[list[Any], str]:
    """Parse mảng JSON, chịu được cắt cụt ở max_tokens.

    Đã gặp thật: câu trả lời bị cắt giữa chừng vì hết token budget, ``json.loads``
    ném lỗi và toàn bộ file mất trắng. Ở đây ta phục hồi **tiền tố dài nhất gồm
    các object hoàn chỉnh** thay vì vứt đi tất cả — 90% annotation vẫn dùng được,
    và số object bị mất được báo cáo để người adjudicate biết phải làm nốt.
    """
    body = strip_fences(text)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(data, dict):          # {"mentions": [...]} cũng chấp nhận
            for key in ("mentions", "concepts", "results", "data"):
                if isinstance(data.get(key), list):
                    return data[key], "object_wrapper"
            return [], "not_a_list"
        if isinstance(data, list):
            return data, "clean"
        return [], "not_a_list"

    start = body.find("[")
    if start < 0:
        return [], "no_array"

    decoder = json.JSONDecoder()
    items: list[Any] = []
    i = start + 1
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n,":
            i += 1
        if i >= n or body[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(body, i)
        except ValueError:
            break                            # object cuối bị cắt → dừng ở đây
        items.append(obj)
    return items, "truncated_prefix" if items else "unparseable"


# ── ingest ────────────────────────────────────────────────────────────────────


@dataclass
class FileReport:
    """Tóm tắt một file để người adjudicate đọc và quyết định."""

    name: str
    parse_mode: str = ""
    raw_items: int = 0
    accepted: int = 0
    dropped_unlocatable: list[str] = field(default_factory=list)
    dropped_bad_type: list[str] = field(default_factory=list)
    dropped_malformed: list[str] = field(default_factory=list)
    stripped_candidates: list[str] = field(default_factory=list)
    stripped_assertions: list[str] = field(default_factory=list)
    ignored_positions: int = 0
    schema_errors: list[str] = field(default_factory=list)
    written: bool = False

    @property
    def dropped(self) -> int:
        return (
            len(self.dropped_unlocatable)
            + len(self.dropped_bad_type)
            + len(self.dropped_malformed)
        )


def _clean_assertions(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    valid = {a.value for a in Assertion}
    return sorted({v for v in values if isinstance(v, str) and v in valid})


def _clean_candidates(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        code = str(v).strip()
        if code and code not in out:
            out.append(code)
    return out


def ingest_file(name: str, tref: TextRef, items: list[Any], report: FileReport) -> list[dict]:
    """Gán position cho từng item; span nào không verify được thì loại.

    ``DevLocator`` giữ trạng thái qua cả file nên mention thứ n của cùng một
    chuỗi rơi vào lần xuất hiện thứ n — đúng hợp đồng nêu trong prompt.
    """
    locator = DevLocator(tref)
    records: list[dict] = []

    for item in items:
        if not isinstance(item, dict):
            report.dropped_malformed.append(repr(item)[:60])
            continue
        text = item.get("text")
        type_name = item.get("type")
        if not isinstance(text, str) or not text.strip():
            report.dropped_malformed.append(repr(item)[:60])
            continue
        if type_name not in set(TYPE_NAMES):
            report.dropped_bad_type.append(f"{text!r} → {type_name!r}")
            continue

        if any(k in item for k in ("position", "start", "end", "offset")):
            report.ignored_positions += 1   # LLM không được phép; ta bỏ qua

        candidates = _clean_candidates(item.get("candidates"))
        if candidates and type_name not in MAPPABLE_NAMES:
            # Type gate: ba type triệu chứng/xét nghiệm luôn có candidates rỗng.
            report.stripped_candidates.append(f"{text!r} ({type_name}) {candidates}")
            candidates = []

        assertions = _clean_assertions(item.get("assertions"))
        if assertions and type_name not in ASSERTABLE_NAMES:
            report.stripped_assertions.append(f"{text!r} ({type_name}) {assertions}")
            assertions = []

        span = locator.locate(text)
        if span is None:
            # Không định vị được, hoặc định vị được nhưng bất biến vỡ. Cả hai
            # trường hợp đều LOẠI — không bao giờ xuất span không verify được.
            report.dropped_unlocatable.append(text)
            continue

        records.append(
            {
                "text": span.text,
                "type": type_name,
                "candidates": candidates,
                "assertions": assertions,
                "position": [span.start, span.end],
            }
        )

    records.sort(key=lambda r: (r["position"][0], r["position"][1]))
    report.accepted = len(records)
    return records


def _read_response(response_dir: Path, name: str) -> str | None:
    for candidate in (f"{name}.json", f"{name}.response.json", f"{name}.txt", f"{name}.md"):
        path = response_dir / candidate
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def ingest(response_dir: Path, input_dir: Path, out_dir: Path,
           files: Iterable[int]) -> tuple[int, list[FileReport]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[FileReport] = []
    failed = 0

    for n in files:
        name = str(n)
        report = FileReport(name=name)
        reports.append(report)

        body = _read_response(response_dir, name)
        if body is None:
            report.parse_mode = "missing"
            continue

        src = input_dir / f"{name}.txt"
        if not src.exists():
            report.parse_mode = "missing_source"
            failed += 1
            continue

        tref = read_textref(src)
        items, mode = parse_response(body)
        report.parse_mode = mode
        report.raw_items = len(items)

        records = ingest_file(name, tref, items, report)
        errors = validate_file(records, tref.raw)
        report.schema_errors = errors
        if errors:
            # Từ chối ghi file có lỗi schema — gold sai còn tệ hơn không có gold.
            failed += 1
            continue

        (out_dir / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report.written = True

    return failed, reports


def print_reports(reports: list[FileReport], out_dir: Path) -> None:
    print(f"\n  {'file':>5}  {'parse':<17} {'in':>4} {'ok':>4} {'drop':>5}  ghi chú")
    print(f"  {'─' * 74}")
    for r in reports:
        note = []
        if r.dropped_unlocatable:
            note.append(f"{len(r.dropped_unlocatable)} không định vị")
        if r.dropped_bad_type:
            note.append(f"{len(r.dropped_bad_type)} sai type")
        if r.dropped_malformed:
            note.append(f"{len(r.dropped_malformed)} hỏng")
        if r.stripped_candidates:
            note.append(f"{len(r.stripped_candidates)} type-gate")
        if r.stripped_assertions:
            note.append(f"{len(r.stripped_assertions)} assert-gate")
        if r.ignored_positions:
            note.append(f"{r.ignored_positions} position bị bỏ qua")
        if r.schema_errors:
            note.append(f"✗ {len(r.schema_errors)} LỖI SCHEMA — KHÔNG GHI")
        if r.parse_mode in {"missing", "missing_source", "unparseable", "no_array", "not_a_list"}:
            note.append("✗ không đọc được câu trả lời")
        print(
            f"  {r.name:>5}  {r.parse_mode:<17} {r.raw_items:>4} {r.accepted:>4} "
            f"{r.dropped:>5}  {'; '.join(note)}"
        )

    total_in = sum(r.raw_items for r in reports)
    total_ok = sum(r.accepted for r in reports)
    total_drop = sum(r.dropped for r in reports)
    written = sum(1 for r in reports if r.written)
    print(f"  {'─' * 74}")
    print(f"  {'TỔNG':>5}  {'':<17} {total_in:>4} {total_ok:>4} {total_drop:>5}")
    print(f"\n  ghi {written}/{len(reports)} file → {out_dir}")

    # Chi tiết để người adjudicate sửa tay — đây là điểm cả quy trình tồn tại.
    for r in reports:
        details = (
            [f"không định vị được: {t!r}" for t in r.dropped_unlocatable]
            + [f"type không hợp lệ: {t}" for t in r.dropped_bad_type]
            + [f"item hỏng: {t}" for t in r.dropped_malformed]
            + [f"type gate xóa candidates: {t}" for t in r.stripped_candidates]
            + [f"type gate xóa assertions: {t}" for t in r.stripped_assertions]
            + [f"schema: {e}" for e in r.schema_errors]
        )
        if details:
            print(f"\n  [{r.name}] cần người xem lại ({len(details)}):")
            for d in details[:40]:
                print(f"      {d}")
            if len(details) > 40:
                print(f"      … còn {len(details) - 40} mục")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-annotate 20 file dev bằng LLM (provider-agnostic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--emit-prompts", type=Path, metavar="DIR",
                       help="ghi payload prompt tự chứa cho từng file dev")
    group.add_argument("--ingest", type=Path, metavar="DIR",
                       help="đọc câu trả lời LLM, gán position, validate, ghi gold")
    parser.add_argument("--input", type=Path, default=ROOT / "data/test",
                        help="thư mục .txt gốc (mặc định data/test)")
    parser.add_argument("--out", type=Path, default=ROOT / "data/dev_gold",
                        help="thư mục gold đầu ra cho --ingest (mặc định data/dev_gold)")
    parser.add_argument("--files", default=None,
                        help="ghi đè danh sách file dev, ví dụ '1,3,4'")
    args = parser.parse_args(argv)

    if args.files:
        files = tuple(int(x) for x in args.files.replace(",", " ").split())
    else:
        files = DEV_FILES

    if args.emit_prompts is not None:
        print(f"  sinh prompt cho {len(files)} file dev")
        return emit_prompts(args.input, args.emit_prompts, files)

    failed, reports = ingest(args.ingest, args.input, args.out, files)
    print_reports(reports, args.out)
    if failed:
        print(f"\n  ✗ {failed} file KHÔNG được ghi — sửa rồi chạy lại.", file=sys.stderr)
        return 1
    missing = [r.name for r in reports if r.parse_mode == "missing"]
    if missing:
        print(f"\n  ⚠ thiếu câu trả lời cho: {', '.join(missing)}", file=sys.stderr)
    print("\n  Lưu ý: đây là PRE-annotation. Gold chỉ đúng sau khi người "
          "adjudicate đọc lại, đặc biệt các mục liệt kê ở trên.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
