"""Huấn luyện tagger — nhóm dependency optional `train`, KHÔNG vào runtime.

Ranh giới giống `synth/`: `stages/` không bao giờ import từ đây. `stages/tagger.py`
chỉ đọc *checkpoint* do đây sinh ra, và nạp torch lười để thiếu torch vẫn chạy
(PRD §5 — cài lại không được thì bị loại).
"""
