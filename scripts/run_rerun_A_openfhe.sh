#!/usr/bin/env bash
# run_rerun_A_openfhe.sh — 프리셋 A / OpenFHE, 독립 실행 3회 재현성 검증.
#
# 목적: v3 본측정의 "한 실행 내부 30회 반복" 불확실성과 달리, **실행 단위** 재현성을
#   검증한다. 8개 조건 중 분리 간격이 가장 작은(0.059) 프리셋 A/OpenFHE 만 본다.
#
# 각 회차는 반드시 별도 프로세스(이 스크립트가 presetsearch_openfhe 를 3번 exec) ·
# 키 생성부터 새로(프로세스가 갈리므로 자동으로 만족) · 회차 사이 냉각 후 재가열이다.
#
# 연산은 4종만(mul_cc_rlk, relin, rot1, rescale) — 2026-09-02 -ops 필터 추가로
# 경량 4종을 아예 측정하지 않아 시간을 아낀다(presetsearch_openfhe.cpp).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"

OUTBASE="$ROOT/results/rerun_A_openfhe"
mkdir -p "$OUTBASE"

CORE="${SOLO_CORE:-12}"
WARM=30
REPS="${REPS:-30}"
WARMUP="${WARMUP:-3}"
PRECREPS="${PRECREPS:-5}"
COOLDOWN="${COOLDOWN:-330}"     # 최소 5분(300s) 요구 + 여유
OPS="mul_cc_rlk,relin,rot1,rescale"
BIN="$ROOT/build_openfhe/presetsearch_openfhe"

fail=0
run_one() {
  local n=$1
  local dir="$OUTBASE/run$n"
  mkdir -p "$dir"
  local pr="$dir/probe"
  echo "### run$n start $(date -Iseconds) (코어 $CORE 고정, ${WARM}s 가열)"
  OMP_NUM_THREADS=1 "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" \
    "$BIN" -exp 5 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
    -ops "$OPS" -threads 1t \
    -out "$dir/openfhe_timing.csv" -precout "$dir/openfhe_precision.csv" \
    >"$dir/run.log" 2>&1
  local rc=$?
  if ! python3 "$HERE/probe_check.py" "$pr" >"$dir/probe_check.txt" 2>&1; then
    echo "  !! run$n: 프로브가 fast 밴드를 벗어났다 — 결과를 폐기 대상으로 표시"
    touch "$dir/PROBE_FAIL"
    fail=$((fail + 1))
  fi
  cat "$dir/probe_check.txt"
  [ "$rc" -ne 0 ] && { echo "  !! run$n: rc=$rc"; touch "$dir/RC_FAIL"; fail=$((fail + 1)); }
  echo "### run$n end   $(date -Iseconds)"
}

run_one 1
echo "--- cooldown ${COOLDOWN}s before run2 ---"
sleep "$COOLDOWN"
run_one 2
echo "--- cooldown ${COOLDOWN}s before run3 ---"
sleep "$COOLDOWN"
run_one 3

echo "RERUN_A_OPENFHE_DONE fail=$fail"
exit 0
