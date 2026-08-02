#!/usr/bin/env bash
# run_D_search.sh — 프리셋 D 후보(logN14 depth4/5, Δ42) 정밀도 + 최적 P. 탐색 단계.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/D_search"; mkdir -p "$RAW/probe"; CORE=12; WARM=30
KP="$RAW/ksprec_lat"; PS="$RAW/ps_lat"
go build -o "$KP" src/ksprec_lattigo.go || exit 1
go build -o "$PS" src/presetsearch_lattigo.go || exit 1

# depth 4: OpenFHE dnum 2(P180)/3(P120)/5(P60), Lattigo PC3(dnum2)/PC2(dnum3)/PC1(dnum5)
# depth 5: OpenFHE dnum 3(P120)/6(P60),          Lattigo PC2(dnum3)/PC1(dnum6)
OFP="4:42:2,4:42:3,4:42:5,5:42:3,5:42:6"
LAP="4:42:3,4:42:2,4:42:1,5:42:2,5:42:1"
SEP="4:42,5:42"
OFT="14:4:42:2,14:4:42:3,14:4:42:5,14:5:42:3,14:5:42:6"
LAT="14:4:42:3,14:4:42:2,14:4:42:1,14:5:42:2,14:5:42:1"

fail=0
run(){ local t=$1 out=$2; shift 2
  echo "### $t"
  PROBE_CORE="$CORE" "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$RAW/probe/$t" "$@" >"$out" 2>"$RAW/$t.err"
  python3 "$HERE/probe_check.py" "$RAW/probe/$t" || fail=$((fail+1)); }

# --- 3단계: 정밀도 (reps 12) ---
OMP_NUM_THREADS=1 run p_of "$RAW/p_of.csv" ./build_openfhe/ksprec_openfhe -logN 14 -combos "$OFP" -reps 12
GOMAXPROCS=1     run p_la "$RAW/p_la.csv" "$KP" -logN 14 -combos "$LAP" -reps 12
                 run p_se "$RAW/p_se.csv" ./build_seal/ksprec_seal -logN 14 -combos "$SEP" -reps 12
D1="$ROOT/explore/params_D_precision.csv"; head -1 "$RAW/p_of.csv" > "$D1"
for f in p_of p_la p_se; do tail -n +2 "$RAW/$f.csv" >> "$D1"; done
echo "  $D1  ($(( $(wc -l < "$D1") - 1 ))행)"

# --- 4단계: 최적 P (maxLevel heavy 3종, reps 30) ---
OMP_NUM_THREADS=1 run t_of /dev/null ./build_openfhe/presetsearch_openfhe -combos "$OFT" -reps 30 -warmup 3 -out "$RAW/t_of.csv"
GOMAXPROCS=1     run t_la /dev/null "$PS" -combos "$LAT" -reps 30 -warmup 3 -out "$RAW/t_la.csv"
D2="$ROOT/explore/params_D_optp.csv"; head -1 "$RAW/t_of.csv" > "$D2"
tail -n +2 "$RAW/t_of.csv" >> "$D2"; tail -n +2 "$RAW/t_la.csv" >> "$D2"
echo "  $D2  ($(( $(wc -l < "$D2") - 1 ))행)"
echo "D_SEARCH_DONE fail=$fail"
