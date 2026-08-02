#!/usr/bin/env bash
# run_bc_optp.sh — B·C 후보의 최적 P 선정 측정 (maxLevel, heavy 3종). 탐색 단계.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/bc_optp"; mkdir -p "$RAW/probe"; CORE=12; WARM=30; REPS="${REPS:-30}"
LAT="$RAW/ps_lat"; go build -o "$LAT" src/presetsearch_lattigo.go || exit 1
OF=$(cat "$SB/of_combos.txt"); LA=$(cat "$SB/la_combos.txt")
fail=0
run(){ local tag=$1; shift
  "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$RAW/probe/$tag" "$@" >"$RAW/$tag.log" 2>&1
  python3 "$HERE/probe_check.py" "$RAW/probe/$tag" || fail=$((fail+1)); }
OMP_NUM_THREADS=1 run openfhe ./build_openfhe/presetsearch_openfhe -combos "$OF" -reps "$REPS" -warmup 3 -out "$RAW/of.csv"
GOMAXPROCS=1 run lattigo "$LAT" -combos "$LA" -reps "$REPS" -warmup 3 -out "$RAW/la.csv"
D="$ROOT/explore/params_bc_optp.csv"; head -1 "$RAW/of.csv" > "$D"
tail -n +2 "$RAW/of.csv" >> "$D"; tail -n +2 "$RAW/la.csv" >> "$D"
echo "  $D  ($(( $(wc -l < "$D") - 1 ))행)"
echo "BC_OPTP_DONE fail=$fail"
