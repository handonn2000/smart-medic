# proxy_gold_test — 20 tài liệu test được gán nhãn tay

724 span trên 20/100 file của `data/test/`. Lấy mẫu phân tầng theo thể loại;
26 file được yêu cầu gán nhãn, 20 file cho kết quả dùng được (số còn lại hỏng do
vượt giới hạn token hoặc lỗi phân tích JSON). Phân bố thể loại của **20 file
thực tế có mặt ở đây**, đếm lại từ đĩa:

| thể loại | số file |
|---|---|
| hỏi-đáp bệnh nhân | 11 |
| dàn ý bệnh án | 6 |
| khác | 3 |
| **tổng** | **20** |

Offset đã kiểm: 0 lỗi — mọi `raw[start:end]` khớp chính xác trường `text`.

## Đây KHÔNG phải gold của ban tổ chức

Nhãn do LLM sinh rồi định vị offset bằng khớp chuỗi trong kernel. Dùng nó để:

- **so tương đối** giữa hai phiên bản của cùng một pipeline
- **kiểm quy ước** mà ban tổ chức không nói rõ trong đề bài (ví dụ: biên của
  span `***`, tỷ lệ entity mang assertion)

Không dùng nó để:

- **dự báo điểm tuyệt đối** — 36,8 trên proxy so với 22,0 trên leaderboard
- **nghiệm thu bất cứ thứ gì được xây TỪ phân tích lỗi của chính nó.** Từ vựng
  trong `resources/lexicon_vi.yaml` được viết từ danh sách span mà proxy này báo
  là bị sót; proxy vì thế **vô hiệu** khi đánh giá làn lexicon. Đây không phải
  giới hạn về độ chính xác — nó là vòng lặp logic.

## Nhánh candidates: chỉ nghiệm thu bằng leaderboard

Xem `docs/decisions/0006-gold-codes-symptoms.md`. Cả proxy này lẫn gold tổng hợp
đều đã từng đồng ý về một quyết định mà leaderboard bác bỏ (mã CHẨN_ĐOÁN,
−1,82 điểm). Hai nguồn đồng ý không mạnh hơn một nguồn khi cả hai đo sai câu hỏi.

## Dùng trong test

`tests/test_redacted.py::test_boundary_matches_the_annotators` đọc thư mục này
để kiểm biên span `***` (7/7 khớp chính xác). Test tự bỏ qua nếu thư mục vắng.
