#!/usr/bin/env bash
# OpenFHE 6 CSV: small/medium/large × {1t,mt}. reps=30.
set -euo pipefail
cd /data/yja/he-bench
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
BIN=build_openfhe/openfhe_bench
for p in small medium large; do
  echo "==> OpenFHE $p mt"
  $BIN -preset "$p" -reps 30 -out "results_openfhe_${p}_mt_dku16c.csv"
  echo "==> OpenFHE $p 1t (OMP_NUM_THREADS=1)"
  OMP_NUM_THREADS=1 $BIN -preset "$p" -reps 30 -out "results_openfhe_${p}_1t_dku16c.csv"
done
echo "ALL_OPENFHE_DONE"
