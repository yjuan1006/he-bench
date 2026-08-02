#!/usr/bin/env bash
# run_presetsearch.sh — 프리셋 확정용 탐색 측정 드라이버. 본측정 아님.
#
# 실험 1: P 탐색   (logN15 q0 60 Δ40 depth13, OpenFHE dnum / Lattigo PCount 스윕, SEAL 1점)
# 실험 2: Δ 스윕   (logP 120 고정, Δ 40..50, maxLevel 한 점, 8-op)
#
# ★ 6개 실행 전부 코어 12에 고정된다 — 반드시 순차로 돌려야 한다.
#   동시에 돌리면 같은 코어를 다투어 측정이 통째로 오염된다.
# 각 실행은 scripts/run_warm.sh 경유(코어 고정 + 30초 가열 후 exec)이고
# 측정 전후 프로브를 probe_check.py로 확인한다. FAST 밴드를 벗어나면 그 실행은 폐기 대상이다.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

OUT="$ROOT/explore"
mkdir -p "$OUT"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/presetsearch"; mkdir -p "$RAW"
TR="$RAW/probe"; mkdir -p "$TR"
CORE="${SOLO_CORE:-12}"
WARM=30
REPS="${REPS:-30}"
WARMUP="${WARMUP:-3}"
PRECREPS="${PRECREPS:-5}"

# Lattigo는 go 바이너리를 미리 빌드해 둔다 — 가열된 코어에서 컴파일러가 돌면 안 된다.
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
    echo "  !! $tag: 프로브가 fast 밴드를 벗어났다 — 이 측정은 폐기하고 재실행할 것"
    fail=$((fail + 1))
  fi
  [ "$rc" -ne 0 ] && { echo "  !! $tag: rc=$rc"; fail=$((fail + 1)); }
  return 0
}

# ---------- 실험 1 : P 탐색 ----------
OMP_NUM_THREADS=1 run_one exp1_openfhe ./build_openfhe/presetsearch_openfhe \
  -exp 1 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/exp1_openfhe.csv" -precout "$RAW/exp1_openfhe_prec.csv"

GOMAXPROCS=1 run_one exp1_lattigo "$LATBIN" \
  -exp 1 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/exp1_lattigo.csv" -precout "$RAW/exp1_lattigo_prec.csv"

run_one exp1_seal ./build_seal/presetsearch_seal \
  -exp 1 -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" \
  -out "$RAW/exp1_seal.csv" -precout "$RAW/exp1_seal_prec.csv"

# ---------- 실험 2 : Δ 스윕 ----------
OMP_NUM_THREADS=1 run_one exp2_openfhe ./build_openfhe/presetsearch_openfhe \
  -exp 2 -reps "$REPS" -warmup "$WARMUP" -out "$RAW/exp2_openfhe.csv"

GOMAXPROCS=1 run_one exp2_lattigo "$LATBIN" \
  -exp 2 -reps "$REPS" -warmup "$WARMUP" -out "$RAW/exp2_lattigo.csv"

run_one exp2_seal ./build_seal/presetsearch_seal \
  -exp 2 -reps "$REPS" -warmup "$WARMUP" -out "$RAW/exp2_seal.csv"

# ---------- 병합 ----------
merge() {   # dest  src...
  local dest=$1; shift
  head -1 "$1" > "$dest"
  for f in "$@"; do tail -n +2 "$f" >> "$dest"; done
  echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"
}
echo "### 병합"
merge "$OUT/exp1_p_search_timing.csv"    "$RAW/exp1_openfhe.csv" "$RAW/exp1_lattigo.csv" "$RAW/exp1_seal.csv"
merge "$OUT/exp1_p_search_precision.csv" "$RAW/exp1_openfhe_prec.csv" "$RAW/exp1_lattigo_prec.csv" "$RAW/exp1_seal_prec.csv"
merge "$OUT/exp2_delta_sweep_timing.csv" "$RAW/exp2_openfhe.csv" "$RAW/exp2_lattigo.csv" "$RAW/exp2_seal.csv"

echo "PRESETSEARCH_DONE fail=$fail"
exit 0
