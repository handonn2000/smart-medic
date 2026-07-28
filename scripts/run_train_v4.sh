#!/usr/bin/env bash
# Train v4 + đo trên holdout — chạy THỦ CÔNG, không chạy trong phiên agent.
#
#     bash scripts/run_train_v4.sh              # chạy thường
#     nohup bash scripts/run_train_v4.sh &      # chạy nền, đóng terminal được
#
# Mọi thứ ghi vào logs/train_v4/. Xong thì đưa lại cho tôi file:
#     logs/train_v4/SUMMARY.txt
#
# Train xong KHÔNG tự ghi đè gì trong data/. models/ sẽ có bundle mới.

set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
PY="$REPO/.venv/bin/python"
LOG="$REPO/logs/train_v4"
mkdir -p "$LOG"
SUM="$LOG/SUMMARY.txt"

# Holdout PHẢI trùng HOLDOUT_FILES trong scripts/train_ner.py, nếu không phép so
# hết công bằng. Đọc thẳng từ script để không lệch khi ai đó sửa một bên.
HOLDOUT=$("$PY" - <<'PY'
import re, pathlib
src = pathlib.Path("scripts/train_ner.py").read_text(encoding="utf-8")
m = re.search(r"HOLDOUT_FILES:\s*tuple\[int, \.\.\.\]\s*=\s*\(([^)]*)\)", src)
print(",".join(x.strip() for x in m.group(1).split(",") if x.strip()))
PY
)

say() { printf '%s\n' "$*" | tee -a "$SUM"; }
step() { printf '\n=== %s ===\n' "$*" | tee -a "$SUM"; }

: > "$SUM"
say "smart-medic v4 — train + đánh giá"
say "bắt đầu : $(date '+%Y-%m-%d %H:%M:%S')"
say "holdout : $HOLDOUT  (đọc từ train_ner.py)"

# httpx trong huggingface_hub 1.x cần gói socksio khi ALL_PROXY là SOCKS.
# Nếu thiếu gói mà biến vẫn set thì tải weights sẽ chết -> bỏ biến đó đi.
if [ -n "${ALL_PROXY:-}${all_proxy:-}" ] && ! "$PY" -c "import socksio" 2>/dev/null; then
  say "gỡ ALL_PROXY (SOCKS) vì thiếu socksio — HTTPS_PROXY vẫn giữ"
  unset ALL_PROXY all_proxy
fi

# ── 0. preflight ─────────────────────────────────────────────────────────────
step "0. Kiểm tra trước khi chạy"
"$PY" - <<'PY' 2>&1 | tee -a "$SUM"
import importlib.metadata as md, json, pathlib, shutil, sys
ok = True
for p in ("torch", "transformers", "onnx", "tokenizers"):
    try:
        print(f"  {p:14} {md.version(p)}")
    except Exception:
        print(f"  {p:14} THIẾU  -> uv pip install --python .venv/bin/python -r requirements-dev.txt")
        ok = False
for d, want in (("data/silver", 80), ("data/dev_gold", 20), ("data/test", 100)):
    n = len(list(pathlib.Path(d).glob("*.json"))) or len(list(pathlib.Path(d).glob("*.txt")))
    print(f"  {d:14} {n} file" + ("" if n == want else f"  (mong đợi {want})"))
    ok &= n == want
free = shutil.disk_usage(".").free / 1e9
print(f"  đĩa trống      {free:.0f} GB" + ("" if free > 8 else "  (cần ~8 GB cho weights + bundle)"))
sys.exit(0 if ok and free > 8 else 1)
PY
[ ${PIPESTATUS[0]} -ne 0 ] && { say "PREFLIGHT THẤT BẠI — dừng."; exit 1; }

# ── 1. baseline v3 trên holdout ──────────────────────────────────────────────
# Cần con số này để trả lời "v4 có thật sự hơn v3" trên dữ liệu v4 CHƯA thấy.
step "1. Baseline v3 trên holdout"
mkdir -p "$LOG/out_v3"
PYTHONPATH=src "$PY" -m smart_medic.infer --extractor v3 --input data/test \
  --output "$LOG/out_v3" > "$LOG/infer_v3.log" 2>&1
# --files chấm đúng 6 file holdout mà không nhân đôi gold ra đĩa (bản nhân đôi
# sẽ trôi khỏi gold gốc khi gold được phân xử thêm).
PYTHONPATH=src "$PY" -m smart_medic.score --pred "$LOG/out_v3" \
  --gold data/dev_gold --src data/test --files "$HOLDOUT" 2>&1 \
  | tee "$LOG/score_v3_holdout.log" | grep -E "FINAL_SCORE|files" | tee -a "$SUM"

# ── 2. train ─────────────────────────────────────────────────────────────────
# Phần lâu. CPU-only, xlm-roberta-base 277M tham số, 3 epoch.
step "2. Train (phần lâu — theo dõi bằng: tail -f $LOG/train.log)"
say "bắt đầu train: $(date '+%H:%M:%S')"
T0=$(date +%s)
PYTHONPATH=src "$PY" scripts/train_ner.py \
  --silver data/silver --gold data/dev_gold --export models \
  > "$LOG/train.log" 2>&1
RC=$?
T1=$(date +%s)
say "kết thúc train: $(date '+%H:%M:%S')  ($(( (T1-T0)/60 )) phút, exit=$RC)"
grep -E "holdout|document →|epoch|✓ bundle|MB " "$LOG/train.log" | tee -a "$SUM"
[ $RC -ne 0 ] && { say "TRAIN THẤT BẠI — xem $LOG/train.log"; tail -20 "$LOG/train.log" | tee -a "$SUM"; exit 1; }

# ── 3. bundle export ra đúng chưa ────────────────────────────────────────────
step "3. Bundle"
"$PY" - <<'PY' 2>&1 | tee -a "$SUM"
import json, pathlib
d = pathlib.Path("models")
mf = d / "manifest.json"
if not mf.exists():
    print("  THIẾU manifest.json"); raise SystemExit(1)
m = json.loads(mf.read_text(encoding="utf-8"))
print(f"  model_version  {m.get('model_version')}")
print(f"  base_model     {m.get('base_model')}")
print(f"  labels         {len(m.get('labels', []))}")
for name, meta in sorted(m.get("artifacts", {}).items()):
    p = d / name
    real = p.stat().st_size if p.exists() else -1
    flag = "OK" if real == meta["bytes"] else f"LỆCH (đĩa {real})"
    print(f"  {name:16} {meta['bytes']/1e6:>8.1f} MB  {flag}")
PY

# ── 4. v4: đo trên holdout (phép so công bằng) rồi trên toàn gold (số của §4c) ─
step "4. v4 — chạy suy luận"
PYTHONPATH=src "$PY" -m smart_medic.infer --extractor v4 --input data/test \
  --output "$LOG/out_v4" --explain > "$LOG/infer_v4.log" 2>&1 \
  || { say "INFER v4 THẤT BẠI — xem $LOG/infer_v4.log"; tail -20 "$LOG/infer_v4.log" | tee -a "$SUM"; exit 1; }
grep -E "schema|mask" "$LOG/infer_v4.log" | tail -3 | tee -a "$SUM"

step "4a. v4 trên HOLDOUT — đây là con số quyết định"
PYTHONPATH=src "$PY" -m smart_medic.score --pred "$LOG/out_v4" \
  --gold data/dev_gold --src data/test --files "$HOLDOUT" 2>&1 \
  | tee "$LOG/score_v4_holdout.log" | grep -E "FINAL_SCORE|_score|files" | tee -a "$SUM"

step "4b. v4 trên toàn 20 file gold — số của TODO §4c (lạc quan: 14/20 file đã train)"
PYTHONPATH=src "$PY" -m smart_medic.score --pred "$LOG/out_v4" \
  --gold data/dev_gold --src data/test 2>&1 | tee "$LOG/score_v4_all.log" \
  | grep -E "FINAL_SCORE|files" | tee -a "$SUM"
PYTHONPATH=src "$PY" -m smart_medic.score --pred "$LOG/out_v3" \
  --gold data/dev_gold --src data/test 2>&1 | tee "$LOG/score_v3_all.log" \
  | grep -E "FINAL_SCORE" | sed 's/^/  (v3 để so) /' | tee -a "$SUM"

# ── 5. phán quyết ────────────────────────────────────────────────────────────
step "5. Phán quyết"
"$PY" - <<'PY' 2>&1 | tee -a "$SUM"
import pathlib, re
def score(p):
    t = pathlib.Path(p).read_text(encoding="utf-8")
    m = re.search(r"FINAL_SCORE\s*:\s*([0-9.]+)", t)
    return float(m.group(1)) if m else None
L = "logs/train_v4/"
h3, h4 = score(L + "score_v3_holdout.log"), score(L + "score_v4_holdout.log")
a3, a4 = score(L + "score_v3_all.log"), score(L + "score_v4_all.log")
print(f"  holdout (6 file, v4 CHƯA thấy): v3 {h3:.4f} → v4 {h4:.4f}   {h4-h3:+.4f}")
print(f"  toàn gold (20 file, có rò rỉ) : v3 {a3:.4f} → v4 {a4:.4f}   {a4-a3:+.4f}")
if h4 > h3:
    print("\n  => v4 THẮNG trên holdout. Nhãn bạc có giá trị thật.")
    print("     Bước sau: train lại trên đủ 20 file gold (--holdout '') rồi nộp.")
else:
    print("\n  => v4 KHÔNG thắng trên holdout. ĐỪNG NỘP.")
    print("     Phần tăng ở 'toàn gold' (nếu có) chỉ là ghi nhớ 14 file đã train.")
    print("     Quay lại TODO §3: xem chất lượng nhãn bạc.")
PY

say ""
say "xong: $(date '+%Y-%m-%d %H:%M:%S')"
say "log đầy đủ: $LOG/"
printf '\n>>> Đưa lại cho agent: %s\n' "$SUM"
