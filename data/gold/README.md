# `data/gold` — corpus huấn luyện SINH RA, không phải gán tay

> ⚠️ **Đọc trước khi dùng.** Thư mục tên `gold` nhưng đây **không phải** dữ liệu
> do người gán nhãn. Đây là **corpus tổng hợp** do máy sinh
> (annotation-first: có nhãn trước → sinh văn bản sau).
>
> Dự án đã có ba bộ gán tay thật, đừng nhầm với chúng:
>
> | bộ | nguồn | vai trò |
> |---|---|---|
> | `data/probe/gold_real/` | 9 file nguyên văn từ `data/test`, gán tay | ★ tín hiệu không thiên lệch duy nhất |
> | `data/probe/gold/` | 20 bệnh án dự án tự viết | regression guard |
> | `data/probe/gold_batch1/` | 21 file MTSamples dịch | khái quát hoá ngoài miền |

## Nội dung

```
text/         500 file .txt
annotations/  500 file .json  (cùng định dạng bài nộp)
manifest.json seed · sha256 · số span
splits.json   train / dev  ← dev là TỔNG HỢP, dùng cho early stopping
```

| đại lượng | giá trị |
|---|---|
| tài liệu | 500 |
| span có nhãn | 40.312 |
| cụm gây nhiễu **không** gán nhãn | ~13.700 (~25%) |
| độ dài trung vị | ~1.990 ký tự (đích thật: 1.838) |
| seed | `20260802` |
| `corpus_sha256` | `7f8bbfc64507dc41…` |

## Bốn bất biến, đã kiểm trên 500/500 tài liệu

1. `text[start:end] == span.text` với **mọi** span
2. span không chồng lấn
3. `candidates` rỗng với `TRIỆU_CHỨNG` / `TÊN_XÉT_NGHIỆM` / `KẾT_QUẢ_XÉT_NGHIỆM`
4. chấm được bằng bộ chấm của bài nộp mà không sửa gì

Kiểm bằng **chính** `stages.solve.check_invariants` — cùng hàm gác cổng bài nộp,
nên corpus không thể lệch định dạng với thứ được chấm.

★ **Offset ghi LÚC CHÈN chuỗi**, không đi tìm lại bằng `txt.index()`. Đó là lý do
tồn tại của cả hướng annotation-first: `sample_output.json` của BTC từng lệch
offset 19/19 mục vì CRLF, và 20/100 file `data/test` không ở dạng NFC.

## Nguồn cách nói bề mặt

| nhánh | nguồn | có gọi LLM không |
|---|---|---|
| XÉT NGHIỆM | `data/curated/lab_panels.v1.yaml` | không — tất định |
| THUỐC | bảng ATC/DDD của Bộ Y tế + mask `***` + biệt dược không mã | không — tất định |
| CHẨN_ĐOÁN + TRIỆU_CHỨNG | `data/curated/surface_forms.v1.jsonl` | **có**, sinh MỘT lần rồi đóng băng kèm `.sha256` |

Hai phép đo đã ghi cho nhánh LLM: hợp lý y khoa **92/100** cặp duyệt tay;
độ mới **51,0%** cách nói không khớp bất kỳ term nào trong gazetteer KB.

## Tái tạo

Trên nhánh `feature/solution_v7.2`:

```bash
smk synth build -n 500 --report docs/reports/phase2-corpus-stats.json
```

Seed ghim + nguồn đóng băng ⇒ cho lại đúng `corpus_sha256` ở trên.

## Giới hạn đã biết

- Vòng tròn mã hoá→giải mã BIO **mất 1,85% span** vì tokenizer dán dấu câu vào
  token cuối (`"64.5"` → `"64.5."`). Đó là trần của mọi model huấn luyện trên đây.
- Tagger XLM-R huấn luyện trên corpus này đạt **F1 0,97 trên dev tổng hợp** nhưng
  chỉ **precision 0,51** trên `gold_real`. Con số 0,97 đo năng lực học **bộ sinh**,
  không phải học **miền**. Đừng dùng nó làm chỉ báo năng lực.
