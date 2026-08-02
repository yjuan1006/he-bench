#!/usr/bin/env bash
# run_bc_precision.sh — 프리셋 B(logN14)·C(logN15 얕은 depth) 후보의 rot1 정밀도 (reps 12).
# 탐색 단계. 비밀키 암호화 · maxLevel · run_warm.sh 코어 고정 + 30초 가열.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/bc_precision"; mkdir -p "$RAW/probe"; CORE=12; WARM=30; REPS="${REPS:-12}"
LAT="$RAW/ksprec_lattigo"; go build -o "$LAT" src/ksprec_lattigo.go || exit 1

# B(logN14): depth6 은 OpenFHE dnum4(logP120)/Lattigo PC2, depth7 은 dnum8(logP60)/PC1
# C(logN15): 전부 OpenFHE dnum3(logP240)/Lattigo PC5(logP300)
OF14="6:40:4,6:42:4,7:42:8"; LA14="6:40:2,6:42:2,7:42:1"; SE14="6:40,6:42,7:42"
OF15="10:48:3,10:50:3,11:46:3,9:54:3"; LA15="10:48:5,10:50:5,11:46:5,9:54:5"; SE15="10:48,10:50,11:46,9:54"

fail=0
run(){ local tag=$1 out=$2; shift 2
  "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$RAW/probe/$tag" "$@" >"$out" 2>"$RAW/$tag.err"
  python3 "$HERE/probe_check.py" "$RAW/probe/$tag" || fail=$((fail+1)); }

OMP_NUM_THREADS=1 run of14 "$RAW/of14.csv" ./build_openfhe/ksprec_openfhe -logN 14 -combos "$OF14" -reps "$REPS"
OMP_NUM_THREADS=1 run of15 "$RAW/of15.csv" ./build_openfhe/ksprec_openfhe -logN 15 -combos "$OF15" -reps "$REPS"
GOMAXPROCS=1 run la14 "$RAW/la14.csv" "$LAT" -logN 14 -combos "$LA14" -reps "$REPS"
GOMAXPROCS=1 run la15 "$RAW/la15.csv" "$LAT" -logN 15 -combos "$LA15" -reps "$REPS"
run se14 "$RAW/se14.csv" ./build_seal/ksprec_seal -logN 14 -combos "$SE14" -reps "$REPS"
run se15 "$RAW/se15.csv" ./build_seal/ksprec_seal -logN 15 -combos "$SE15" -reps "$REPS"

D="$ROOT/explore/params_bc_precision.csv"; head -1 "$RAW/of14.csv" > "$D"
for f in of14 of15 la14 la15 se14 se15; do tail -n +2 "$RAW/$f.csv" >> "$D"; done
echo "  $D  ($(( $(wc -l < "$D") - 1 ))행)"
echo "BC_PRECISION_DONE fail=$fail"
