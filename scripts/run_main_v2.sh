#!/usr/bin/env bash
# run_main_v2.sh — 확정 프리셋 v2n15d40L13 의 8-op 레벨 전수 본측정 (1t).
#
# 프리셋: logN 15 / q0 60 / Δ 40 / depth 13  (QCount 14, logQ 580, tc128 상한 881)
#   OpenFHE dnum 3 → PCount 4 · logP 240 · logQP 820
#   Lattigo PCount 5 → logP 300 · dnum 3(종속) · logQP 880
#   SEAL    logP 60 (구조상 고정) · logQP 640
#
# ★ 3개 실행 전부 코어 12 고정 — 반드시 순차. 동시에 돌리면 측정이 통째로 오염된다.
# 각 실행은 run_warm.sh 경유(30초 가열 후 exec)이고 전후 프로브를 확인한다.
# FAST 밴드를 벗어난 실행은 폐기 대상이다(fail 카운트로 보고).
#
# 정밀도는 레벨 전수로 함께 잰다(reps 5, 비밀키, 각 레벨에서 새로 암호화).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

PRESET="v2n15d40L13"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/main_$PRESET"; mkdir -p "$RAW"
TR="$RAW/probe"; mkdir -p "$TR"
CORE="${SOLO_CORE:-12}"
WARM=30
REPS="${REPS:-30}"
WARMUP="${WARMUP:-3}"
PRECREPS="${PRECREPS:-5}"

# 가열된 코어에서 컴파일러가 돌면 안 되므로 Go 바이너리는 미리 빌드한다.
LATBIN="$RAW/presetsearch_lattigo"
go build -o "$LATBIN" src/presetsearch_lattigo.go || { echo "go build 실패"; exit 1; }

fail=0
run_one() {   # tag  cmd...
  local tag=$1; shift
  local pr="$TR/$tag"
  echo "### $tag (코어 $CORE 고정, ${WARM}s 가열)"
  "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" "$@" >"$RAW/$tag.log" 2>&1
  local rc=$?
  if ! python3 "$HERE/probe_check.py" "$pr"; then
    echo "  !! $tag: 프로브가 fast 밴드를 벗어났다 — 폐기하고 재실행할 것"
    fail=$((fail + 1))
  fi
  [ "$rc" -ne 0 ] && { echo "  !! $tag: rc=$rc"; fail=$((fail + 1)); }
  return 0
}

OMP_NUM_THREADS=1 run_one openfhe ./build_openfhe/presetsearch_openfhe \
  -exp 3 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/openfhe.csv" -precout "$RAW/openfhe_prec.csv"

GOMAXPROCS=1 run_one lattigo "$LATBIN" \
  -exp 3 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/lattigo.csv" -precout "$RAW/lattigo_prec.csv"

run_one seal ./build_seal/presetsearch_seal \
  -exp 3 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/seal.csv" -precout "$RAW/seal_prec.csv"

merge() {   # dest  src...
  local dest=$1; shift
  head -1 "$1" > "$dest"
  for f in "$@"; do tail -n +2 "$f" >> "$dest"; done
  echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"
}
echo "### 병합"
merge "$ROOT/results_${PRESET}_timing_1t_dku16c.csv" \
      "$RAW/openfhe.csv" "$RAW/lattigo.csv" "$RAW/seal.csv"
merge "$ROOT/results_${PRESET}_precision_1t_dku16c.csv" \
      "$RAW/openfhe_prec.csv" "$RAW/lattigo_prec.csv" "$RAW/seal_prec.csv"

echo "MAIN_V2_DONE fail=$fail"
exit 0
