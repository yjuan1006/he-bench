#!/usr/bin/env bash
# run_main_D.sh — 프리셋 D 본측정 (1t + mt). A·B·C 와 동일 절차.
#
# D: logN 14 / q0 60 / Δ 42 / depth 4 (QCount 5, logQ 228, 상한 438)
#      OpenFHE dnum 2 → PCount 3 · logP 180 · logQP 408 · 여유  30
#      Lattigo PCount 3 → logP 180 · dnum 2(종속) · logQP 408 · 여유  30
#      SEAL    logP 60                       · logQP 288 · 여유 150
#
# 1t: 코어 12 단일 고정. 타이밍+정밀도 한 프로세스(A·B·C 1t 와 동일).
# mt: OpenFHE 전 코어 0-15 + 16스레드 가열 / Lattigo·SEAL 코어 12 단일.
#     ★ 타이밍과 정밀도를 분리 실행한다 — 한 프로세스에서 정밀도가 뒤에 오면
#       post 프로브가 타이밍이 아니라 (대부분 직렬인) 정밀도 구간의 클럭을 잰다.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
# 산출물 목적지 규칙 (2026-08-08 results/ 트리 개편) — scripts/respath.sh
# shellcheck source=respath.sh
source "$HERE/respath.sh"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/main_D"; mkdir -p "$RAW/probe"
TAG="v3Dn14d42L4"; NCORE="$(nproc)"; ALL="0-$((NCORE-1))"; SOLO="${SOLO_CORE:-12}"; WARM=30
REPS="${REPS:-30}"; WARMUP="${WARMUP:-3}"; PRECREPS="${PRECREPS:-12}"
OFS="14:4:42:2"; LAS="14:4:42:3"; SES="14:4:42"
LAT="$RAW/ps_lat"; go build -o "$LAT" src/presetsearch_lattigo.go || exit 1
fail=0
one(){ local t=$1 cs=$2 nw=$3; shift 3
  echo "### $t (코어 $cs, 가열 ${nw}스레드, 프로브 코어 $SOLO)"
  PROBE_CORE="$SOLO" "$HERE/run_warm.sh" "$cs" "$nw" "$WARM" "$RAW/probe/$t" "$@" >"$RAW/$t.log" 2>&1
  local rc=$?
  python3 "$HERE/probe_check.py" "$RAW/probe/$t" || { echo "  !! 프로브 이탈"; fail=$((fail+1)); }
  [ "$rc" -ne 0 ] && { echo "  !! rc=$rc"; fail=$((fail+1)); }; return 0; }

# ---------- 1t : 타이밍 + 정밀도 한 프로세스 ----------
OMP_NUM_THREADS=1 one of_1t "$SOLO" 1 ./build_openfhe/presetsearch_openfhe -mainrun "$OFS" -threads 1t \
  -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/of_1t.csv" -precout "$RAW/of_1t_prec.csv"
GOMAXPROCS=1 one la_1t "$SOLO" 1 "$LAT" -mainrun "$LAS" -threads 1t \
  -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/la_1t.csv" -precout "$RAW/la_1t_prec.csv"
one se_1t "$SOLO" 1 ./build_seal/presetsearch_seal -mainrun "$SES" -threads 1t \
  -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/se_1t.csv" -precout "$RAW/se_1t_prec.csv"

# ---------- mt : 타이밍 전용 → 정밀도 별도 ----------
OMP_NUM_THREADS="$NCORE" one of_mt "$ALL" "$NCORE" ./build_openfhe/presetsearch_openfhe -mainrun "$OFS" -threads mt \
  -reps "$REPS" -warmup "$WARMUP" -precreps 0 -out "$RAW/of_mt.csv" -precout "$RAW/of_mt_p0.csv"
GOMAXPROCS="$NCORE" one la_mt "$SOLO" 1 "$LAT" -mainrun "$LAS" -threads mt \
  -reps "$REPS" -warmup "$WARMUP" -precreps 0 -out "$RAW/la_mt.csv" -precout "$RAW/la_mt_p0.csv"
one se_mt "$SOLO" 1 ./build_seal/presetsearch_seal -mainrun "$SES" -threads mt \
  -reps "$REPS" -warmup "$WARMUP" -precreps 0 -out "$RAW/se_mt.csv" -precout "$RAW/se_mt_p0.csv"

merge(){ local dest=$1; shift; head -1 "$1" > "$dest"
  for f in "$@"; do tail -n +2 "$f" >> "$dest"; done
  echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"; }
merge "$(res_out "$ROOT" "results_${TAG}_timing_1t_dku16c.csv")"    "$RAW/of_1t.csv" "$RAW/la_1t.csv" "$RAW/se_1t.csv"
merge "$(res_out "$ROOT" "results_${TAG}_precision_1t_dku16c.csv")" "$RAW/of_1t_prec.csv" "$RAW/la_1t_prec.csv" "$RAW/se_1t_prec.csv"
merge "$(res_out "$ROOT" "results_${TAG}_timing_mt_dku16c.csv")"    "$RAW/of_mt.csv" "$RAW/la_mt.csv" "$RAW/se_mt.csv"
echo "MAIN_D_DONE fail=$fail"
