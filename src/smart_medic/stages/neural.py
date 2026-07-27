"""NeuralExtractor — provider phát hiện mention bằng encoder đã distill.

**Vì sao có tầng này.** Đo được trên artifact v3.3: recall mention ≈ 31%, và đó
là nút thắt điểm duy nhất đáng kể (docs/reports/2026-07-26-v4-research-directions.md
§1). Mọi thành phần điểm đều bị nhân với ``M/(G+P−M)``, nên 31% → 65% recall gần
như NHÂN ĐÔI điểm, trong khi hoàn thiện toàn bộ mapping chỉ đáng ≈ +1.4.

Luật viết tay đã chạm trần: v3.1→v3.3 thêm phrase family từng cụm một mà số
mention còn GIẢM (1.668 → 1.585). Đuôi dài cách diễn đạt lâm sàng tiếng Việt
không liệt kê được bằng tay — file 5 có ~40 concept, rule tìm được 13.

**Vai trò trong pipeline.** Provider này CHỈ phát hiện mention và gán type. Nó
KHÔNG bao giờ sinh candidates: linking là việc của KB, và mọi mã phải truy được
về một dòng KB cụ thể (NFR5). Một model nhớ ra mã ICD là đúng hiện tượng
"LLM bịa mã" mà checklist đề bài cấm.

Provider luật vẫn là PRIMARY trong :class:`CompositeExtractor` — chúng mang
provenance KB và khớp chính xác. Tầng này lấp phần đuôi.

**Hợp đồng offset.** Model chạy trên ``tref.norm``, y hệt mọi provider khác, và
``to_raw()`` là cây cầu duy nhất về ``raw``. Casefold trong norm làm mất một ít
tín hiệu chữ hoa cho model, nhưng đi chệch hợp đồng đó là mở lại đúng lớp lỗi
offset đã làm hỏng 20 file NFD — nhất quán thắng.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..modelstore import ModelBundle, load_bundle
from ..schema import ConceptType, Provenance, Span
from ..textref import TextRef
from .extract import Candidate

#: Ngưỡng xác suất tối thiểu cho token mở đầu (B-) một mention.
#:
#: PLACEHOLDER — chưa hiệu chuẩn. Phải quét trên data/dev_gold/ (đang dựng, chưa
#: có trong repo) để tối đa hóa điểm THẬT, không phải F1: metric phạt mention
#: thừa và mention thiếu ĐỐI XỨNG qua mẫu số (G+P−M), nên điểm tối ưu không
#: trùng ngưỡng tối ưu F1.
DEFAULT_MIN_SCORE = 0.50


@dataclass(frozen=True)
class _Chunk:
    """Một cửa sổ token kèm offset ký tự trên norm."""

    ids: list[int]
    offsets: list[tuple[int, int]]
    #: token nào thuộc phần "mới" của cửa sổ (không nằm trong vùng chồng lấn)
    keep: list[bool]


class NeuralExtractor:
    """Token-classification BIO trên 5 ConceptType, chạy bằng ONNX Runtime.

    Runtime nặng (``onnxruntime``, ``tokenizers``, ``numpy``) được nạp LƯỜI ở
    ``__init__`` chứ không phải lúc import module, để nhánh v0–v3 vẫn chạy được
    trên máy chỉ có thư viện chuẩn.
    """

    name = "neural_v4"

    def __init__(
        self,
        bundle: ModelBundle | None = None,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        self.bundle = bundle if bundle is not None else load_bundle()
        self.min_score = min_score

        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:  # noqa: BLE001
            raise ImportError(
                f"--extractor v4 cần runtime inference: {exc}\n"
                "Cài: pip install -r requirements.txt\n"
                "Nhánh v0–v3 không cần: --extractor v3"
            ) from exc

        self._np = np
        self._tokenizer = Tokenizer.from_file(str(self.bundle.tokenizer_path))

        # Tất định là bắt buộc (NFR3): một luồng, không tối ưu hóa phụ thuộc
        # phần cứng, CPU provider duy nhất. Chạy hai lần phải ra byte giống nhau
        # kể cả trên máy BTC.
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        self._session = ort.InferenceSession(
            str(self.bundle.onnx_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._labels = self.bundle.labels

    # ── tokenize + cửa sổ trượt ───────────────────────────────────────────────

    def _chunks(self, norm: str) -> list[_Chunk]:
        """Cắt cửa sổ có chồng lấn; đánh dấu token nào được giữ ở mỗi cửa sổ.

        File dài nhất trong corpus công khai là 4.481 ký tự nên thường chỉ có
        một cửa sổ, nhưng private test có thể dài hơn — và một mention bị cắt
        đôi ở biên là mất điểm âm thầm, đúng loại lỗi phải chặn từ thiết kế.
        """
        encoding = self._tokenizer.encode(norm, add_special_tokens=False)
        ids, offsets = list(encoding.ids), list(encoding.offsets)
        if not ids:
            return []

        # trừ 2 cho <s> và </s>
        width = self.bundle.max_length - 2
        stride = self.bundle.stride
        step = max(1, width - stride)

        out: list[_Chunk] = []
        start = 0
        decided = 0          # token < decided đã được một cửa sổ trước quyết định
        while start < len(ids):
            end = min(start + width, len(ids))
            # Token trong vùng chồng lấn đã được cửa sổ trước quyết định rồi;
            # chỉ cửa sổ ĐẦU TIÊN chứa một token mới được nói về nó, nếu không
            # hai cửa sổ sẽ sinh hai span trùng nhau ở biên.
            out.append(
                _Chunk(
                    ids=ids[start:end],
                    offsets=offsets[start:end],
                    keep=[(start + k) >= decided for k in range(end - start)],
                )
            )
            decided = end
            if end == len(ids):
                break
            start += step
        return out

    def _logits(self, chunk: _Chunk):
        np = self._np
        cls_id, sep_id = self._tokenizer.token_to_id("<s>"), self._tokenizer.token_to_id("</s>")
        ids = [cls_id, *chunk.ids, sep_id]
        feed = {"input_ids": np.array([ids], dtype=np.int64)}
        if "attention_mask" in self._input_names:
            feed["attention_mask"] = np.ones((1, len(ids)), dtype=np.int64)
        logits = self._session.run(None, feed)[0][0]
        return logits[1:-1]  # bỏ <s> và </s>

    @staticmethod
    def _softmax(np, row):
        shifted = row - row.max()
        exp = np.exp(shifted)
        return exp / exp.sum()

    # ── gán nhãn từng token, khâu liền qua các cửa sổ ─────────────────────────

    def _token_labels(self, norm: str) -> list[tuple[int, int, str, float]]:
        """Trả (cs, ce, label, score) cho MỌI token của văn bản, theo thứ tự.

        Phải khâu nhãn trước rồi mới giải mã BIO — KHÔNG giải mã trong từng cửa
        sổ rồi gộp span. Một mention nằm vắt qua đường cắt cửa sổ sẽ bị chặt đôi
        (đo được: ``sốt cao`` → ``sốt`` + ``cao``), và cả hai mảnh vẫn verify
        được trên raw nên lỗi này KHÔNG ném exception — nó chỉ âm thầm biến một
        mention đúng thành hai mention sai, tức mất điểm hai lần dưới mẫu số
        ``G+P−M``.
        """
        np = self._np
        out: list[tuple[int, int, str, float]] = []
        for chunk in self._chunks(norm):
            logits = self._logits(chunk)
            for index, row in enumerate(logits):
                if not chunk.keep[index]:
                    continue
                probs = self._softmax(np, row)
                best = int(probs.argmax())
                cs, ce = chunk.offsets[index]
                out.append((cs, ce, self._labels[best], float(probs[best])))
        return out

    # ── giải mã BIO ───────────────────────────────────────────────────────────

    def _decode(
        self, tokens: list[tuple[int, int, str, float]]
    ) -> list[tuple[int, int, ConceptType, float]]:
        """BIO → (ns, ne, type, score) trên norm. Score = min prob của span."""
        spans: list[tuple[int, int, ConceptType, float]] = []
        cur_type: ConceptType | None = None
        cur_start = cur_end = 0
        cur_scores: list[float] = []

        def flush() -> None:
            nonlocal cur_type
            if cur_type is not None and cur_end > cur_start:
                spans.append((cur_start, cur_end, cur_type, min(cur_scores)))
            cur_type = None

        for cs, ce, label, score in tokens:
            if label == "O":
                flush()
                continue
            prefix, _, value = label.partition("-")
            try:
                ctype = ConceptType(value)
            except ValueError:  # nhãn lạ trong artifact → bỏ, không đoán
                flush()
                continue

            # ``I-`` mồ côi (không có ``B-`` cùng type đứng trước) được NÂNG
            # thành mở đầu span, không bị bỏ. Metric phạt mention thiếu và
            # mention thừa đối xứng, nên khi model đã tin đây là một phần của
            # concept thì giữ lại có kỳ vọng cao hơn là vứt đi.
            continues = prefix == "I" and cur_type is ctype
            if continues:
                cur_end = ce
                cur_scores.append(score)
                continue

            flush()
            if score < self.min_score:
                continue                          # mở đầu yếu → không mở span
            cur_type, cur_start, cur_scores = ctype, cs, [score]
            cur_end = ce
        flush()
        return spans

    # ── Extractor protocol ────────────────────────────────────────────────────

    def extract(self, tref: TextRef) -> list[Candidate]:
        out: list[Candidate] = []
        seen: set[tuple[int, int]] = set()

        for ns, ne, ctype, score in self._decode(self._token_labels(tref.norm)):
            if ns >= ne or ne > len(tref.norm):
                continue
            rs, re_ = tref.to_raw(ns, ne)
            span = Span(rs, re_, tref.raw[rs:re_])
            # Bất biến trung tâm. Không verify được thì LOẠI — không đoán,
            # không sửa. Đây là lớp lọc đã cứu 1/472 span ở vòng LLM trước.
            if not span.verify(tref.raw):
                continue
            if not span.text.strip():
                continue
            if (rs, re_) in seen:
                continue
            seen.add((rs, re_))

            out.append(
                Candidate(
                    span,
                    ctype,
                    (),                            # KHÔNG BAO GIỜ sinh mã
                    Provenance(
                        extractor=self.name,
                        locate_method="neural_bio_decode",
                        link_path="neural_unlinked",
                        kb_rows=[],
                        scores={"confidence": round(score, 6)},
                        # Tầng quyết định của pipeline dùng p_t để chọn bỏ
                        # trống candidates. Model là nguồn duy nhất có ước
                        # lượng hiệu chuẩn về type ở đây.
                        type_confidence=round(score, 6),
                        evidence={"model_version": self.bundle.model_version},
                    ),
                )
            )
        out.sort(key=lambda c: (c.span.start, -(c.span.end - c.span.start)))
        return out
