#!/usr/bin/env bash
# run_main_bc.sh — 프리셋 B·C 의 8-op 레벨 전수 본측정 (1t). A(v3) 와 동일 절차.
#
# B: logN 14 / q0 60 / Δ 42 / depth 6  (QCount 7,  logQ 312, 상한 438)
#      OpenFHE dnum 4 → PCount 2 · logP 120 · logQP 432 · 여유  6
#      Lattigo PCount 2 → logP 120 · dnum 4(종속) · logQP 432 · 여유  6
#      SEAL    logP 60                      · logQP 372 · 여유 66
# C: logN 15 / q0 60 / Δ 48 / depth 10 (QCount 11, logQ 540, 상한 881)
#      OpenFHE dnum 2 → PCount 5 · logP 300 · logQP 840 · 여유  41
#      Lattigo PCount 4 → logP 240 · dnum 3(종속) · logQP 780 · 여유 101
#      SEAL    logP 60                      · logQP 600 · 여유 281
#
# ★ 6개 실행 전부 코어 12 고정 — 반드시 순차. 프로브 전후 확인.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
CORE=12; WARM=30; REPS="${REPS:-30}"; WARMUP="${WARMUP:-3}"; PRECREPS="${PRECREPS:-12}"
fail=0

run_preset(){  # tag  ofspec  laspec  sespec
  local tag=$1 ofs=$2 las=$3 ses=$4
  local RAW="$SB/main_$tag"; mkdir -p "$RAW/probe"
  local LAT="$RAW/ps_lat"; go build -o "$LAT" src/presetsearch_lattigo.go || exit 1
  one(){ local t=$1; shift
    echo "### $tag/$t (코어 $CORE, ${WARM}s 가열)"
    "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$RAW/probe/$t" "$@" >"$RAW/$t.log" 2>&1
    local rc=$?
    python3 "$HERE/probe_check.py" "$RAW/probe/$t" || { echo "  !! 프로브 이탈"; fail=$((fail+1)); }
    [ "$rc" -ne 0 ] && { echo "  !! rc=$rc"; fail=$((fail+1)); }; return 0; }

  OMP_NUM_THREADS=1 one openfhe ./build_openfhe/presetsearch_openfhe -mainrun "$ofs" \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/of.csv" -precout "$RAW/of_prec.csv"
  GOMAXPROCS=1 one lattigo "$LAT" -mainrun "$las" \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/la.csv" -precout "$RAW/la_prec.csv"
  one seal ./build_seal/presetsearch_seal -mainrun "$ses" \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/se.csv" -precout "$RAW/se_prec.csv"

  for kind in timing precision; do
    local dest="$ROOT/results_${tag}_${kind}_1t_dku16c.csv"
    local sfx=""; [ "$kind" = precision ] && sfx="_prec"
    head -1 "$RAW/of${sfx}.csv" > "$dest"
    for f in of la se; do tail -n +2 "$RAW/${f}${sfx}.csv" >> "$dest"; done
    echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"
  done
}

run_preset v3Bn14d42L6  "14:6:42:4"   "14:6:42:2"   "14:6:42"
run_preset v3Cn15d48L10 "15:10:48:2"  "15:10:48:4"  "15:10:48"
echo "MAIN_BC_DONE fail=$fail"
