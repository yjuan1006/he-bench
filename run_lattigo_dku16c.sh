#!/usr/bin/env bash
# Lattigo 6 CSV: small/medium/large × {1t,mt}. reps=30.
# 1t = GOMAXPROCS=1 (OMP_NUM_THREADS는 Go에 무효 — CLAUDE.md/epyc4t 확인).
set -euo pipefail
cd /data/yja/he-bench
export PATH="$HOME/.local/go/bin:$PATH"
for p in small medium large; do
  echo "==> Lattigo $p mt"
  go run lattigo_bench.go -preset "$p" -reps 30 -out "results_lattigo_${p}_mt_dku16c.csv"
  echo "==> Lattigo $p 1t (GOMAXPROCS=1)"
  GOMAXPROCS=1 go run lattigo_bench.go -preset "$p" -reps 30 -out "results_lattigo_${p}_1t_dku16c.csv"
done
echo "ALL_LATTIGO_DONE"
