"""Bộ sinh corpus huấn luyện — chỉ chạy lúc BUILD, không nằm trên đường chạy.

★ RANH GIỚI BẮT BUỘC: `synth/` KHÔNG BAO GIỜ được import từ `stages/`.
Đó là ranh giới build/runtime, cùng tinh thần với ranh giới ĐẮT/RẺ của KB
pipeline, và là điều kiện để Phase 6 đóng gói được image runtime không có torch.
Chiều ngược lại thì được: `synth/` đọc `stages/` để dùng lại bộ chấm và bộ kiểm
bất biến — dùng lại chính bộ kiểm của bài nộp là cách chắc nhất để corpus không
bao giờ lệch định dạng với thứ được chấm.
"""
