#!/usr/bin/env bash
# Lattigo 6 CSV: small/medium/large × {1t,mt}. reps=30.
# 1t = GOMAXPROCS=1 (OMP_NUM_THREADS는 Go에 무효 — CLAUDE.md/epyc4t 확인).
set -euo pipefail
# 스크립트가 scripts/ 로 내려갔다(2026-08-01 구조 개편). 산출 CSV는 예전처럼 리포 루트에
# 떨어져야 하므로 BASH_SOURCE 로 루트를 되짚어 cd 한다(하드코딩 경로 대체).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/go/bin:$PATH"
for p in small medium large; do
  echo "==> Lattigo $p mt"
  go run src/lattigo_bench.go -preset "$p" -reps 30 -out "results_lattigo_${p}_mt_dku16c.csv"
  echo "==> Lattigo $p 1t (GOMAXPROCS=1)"
  GOMAXPROCS=1 go run src/lattigo_bench.go -preset "$p" -reps 30 -out "results_lattigo_${p}_1t_dku16c.csv"
done
echo "ALL_LATTIGO_DONE"
