#!/usr/bin/env bash
# OpenFHE 6 CSV: small/medium/large × {1t,mt}. reps=30.
set -euo pipefail
# 스크립트가 scripts/ 로 내려갔다(2026-08-01 구조 개편). 산출 CSV는 예전처럼 리포 루트에
# 떨어져야 하므로 BASH_SOURCE 로 루트를 되짚어 cd 한다(하드코딩 경로 대체).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
BIN=build_openfhe/openfhe_bench
for p in small medium large; do
  echo "==> OpenFHE $p mt"
  $BIN -preset "$p" -reps 30 -out "results_openfhe_${p}_mt_dku16c.csv"
  echo "==> OpenFHE $p 1t (OMP_NUM_THREADS=1)"
  OMP_NUM_THREADS=1 $BIN -preset "$p" -reps 30 -out "results_openfhe_${p}_1t_dku16c.csv"
done
echo "ALL_OPENFHE_DONE"
