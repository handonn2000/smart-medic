# data/external — nguồn dữ liệu ngoài, license và cách tải lại

PRD §5 yêu cầu top ~15 nộp kèm "dữ liệu nhóm sử dụng". Mọi nguồn dưới đây đều
redistribute được. Các nguồn KHÔNG dùng được ghi ở cuối.

## Nguồn 1 — seed từ bảng chuẩn của BTC (`seed/`)
| file | dòng | nguồn | license |
|---|---|---|---|
| `seed/icd_seed.jsonl` | 3.782 | `data/kb/icd10_aliases.csv.gz` (ICD10.csv của BTC) | dữ liệu BTC cấp |
| `seed/rxnorm_seed.jsonl` | 52.417 | `data/kb/rxnorm_aliases.csv.gz` (RXNORM.csv của BTC) | dữ liệu BTC cấp |

Lọc: alias ICD 2-5 từ (TB 4,00 từ, 3.372 mã duy nhất), alias RxNorm 1-5 từ (TB 3,31 từ,
49.468 mã). Dải này chọn theo số đo: alias ICD thật sự xuất hiện trong 100 file test dài
TB 3,14 từ, gold 3,53 từ, pred v4 chỉ 2,36 từ. Dùng để sinh văn bản có nhãn tính bằng code
— nhãn đúng 100%, không qua LLM, nhắm trực tiếp vào lỗi thu ngắn span.

## Nguồn 2 — bệnh án tiếng Anh (`en_notes/`)
| file | dòng | dataset | license |
|---|---|---|---|
| `en_notes/mtsamples_filtered.jsonl` | 457 | `harishnair04/mtsamples` | **Apache-2.0** |

Lọc từ 4.999 note: dài 700-3.000 ký tự, có >=3 section (`SUBJECTIVE:`, `MEDICATIONS:`,
`LABORATORY DATA:`...), dàn đều 34 chuyên khoa, ưu tiên note giàu viết tắt xét nghiệm.
**31% có viết tắt lab (test 8%)** — nhắm vào điểm yếu đã đo: lần dịch thử trước 0/12 file có lab.

Dự phòng cùng license MIT nếu cần thêm: `AGBonnet/augmented-clinical-notes` (30.000 note,
parquet đã tải sẵn ở `raw/augmented_clinical_000.parquet`).

## Nguồn 3 — corpus y khoa tiếng Việt (`vi_corpus/`)
| file | dòng | dataset | license |
|---|---|---|---|
| `vi_corpus/vi_filtered.jsonl` | 3.600 | ba dataset dưới, 1.200 mỗi nguồn | xem dưới |

| src | dataset | license |
|---|---|---|
| `vi_medtext` | `baonguyenhuy/VietnameseMedicalText` | **MIT** |
| `vi_health_blog` | `ai-enthusiasm-community/vietnamese_health_dataset` | **MIT** |
| `vi_medqa` | `hungnm/vietnamese-medical-qa` | **Apache-2.0** |

Lọc: dài 600-3.000 ký tự VÀ chứa >=2 tên bệnh khớp nguyên văn bảng ICD của BTC.
Kết quả: **3,6 tên ICD/file** so với 1,1 khi lấy ngẫu nhiên — nhưng vẫn thấp hơn test (5,5).

## Đối chiếu với 100 file test — đo sau khi lọc
| đặc điểm | TEST | VN đã lọc | mtsamples đã lọc |
|---|---|---|---|
| tên ICD nguyên văn/file | 5,5 | 3,6 | (sau khi dịch: 2,9) |
| có kết quả XN | 30% | 19% | 41% |
| có viết tắt lab | 8% | 1% | 31% |
| có tiêu đề mục bệnh án | 81% | 9% | 100% (>=3 section) |

Đọc bảng: nguồn 3 phủ cách nói dân gian nhưng **không phủ thể loại bệnh án** (9% vs 81%).
Nguồn 2 mới là nguồn khớp thể loại, và sau khi lọc đã vượt test ở cả lab lẫn kết quả XN.

## Nguồn KHÔNG dùng được — đã kiểm, đừng tải lại
| dataset | lý do |
|---|---|
| MIMIC-III / MIMIC-IV | PhysioNet DUA cấm redistribute → không nộp kèm được → BTC không chạy lại được → bị loại theo PRD §5 |
| `bigbio/n2c2_*` | cần ký DUA với Harvard |
| `starmpcc/Asclepius-Synthetic-Clinical-Notes` | CC-BY-NC-SA-4.0, phi thương mại |
| `hungsvdut2k2/vietnamese-medical-notes` | không khai license |
| `tmnam20/vietnamese-medical-article`, `urnus11/Vietnamese-Healthcare` | trả 401, cần token HF |

## Tải lại
`raw/*.parquet` (396 MB) là bản gốc từ endpoint parquet của HuggingFace datasets-server.
Chạy `python scripts/fetch_external_data.py` để tải và lọc lại từ đầu.
Thư mục `raw/` KHÔNG commit; các file `.jsonl` đã lọc thì commit (tổng 14,5 MB).
