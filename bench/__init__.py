"""bench — hạ tầng đo lường độc lập cho Smart Medic.

Mục tiêu khác với ``smart_medic.score``: script kia trả về **một con số** để so
hai lần nộp. Gói này trả lời câu hỏi **"điểm đang mất ở đâu và chênh lệch có
thật không"** — thứ quyết định nên đầu tư vào giải pháp nào.

Bốn thứ ``score.py`` không có và benchmark bắt buộc phải có:

1. **Khoảng tin cậy.** Dev set là 20 file. Chênh 0,02 giữa hai hệ hoàn toàn có
   thể là nhiễu lấy mẫu. Không có CI thì mọi so sánh A/B đều là đoán.
2. **Ghép tối ưu (Hungarian).** Ghép greedy theo IoU giảm dần *không* cực đại
   hóa tổng IoU. Chạy cả hai cho ta biên trên/biên dưới của phần điểm do cách
   ghép gây ra, tách khỏi phần do model gây ra.
3. **Oracle ablation.** Thay lần lượt từng trường bằng đáp án để đo trần điểm
   của mỗi module. Không có nó thì không biết nên sửa NER hay sửa linking.
4. **Tầng quyết định theo metric.** Ngưỡng phát/không phát mention tối ưu suy
   ra từ chính công thức chấm, không phải từ F1.

Toàn bộ gói chỉ dùng thư viện chuẩn — chạy được trên máy sạch, không cài gì.
"""

from .metric import ComponentScores, score_corpus, score_file
from .matching import match_greedy, match_hungarian
from .stats import bootstrap_ci, paired_permutation
from .decision import best_candidate_set, emission_threshold, expected_jaccard

__all__ = [
    "ComponentScores",
    "score_file",
    "score_corpus",
    "match_greedy",
    "match_hungarian",
    "bootstrap_ci",
    "paired_permutation",
    "emission_threshold",
    "expected_jaccard",
    "best_candidate_set",
]
