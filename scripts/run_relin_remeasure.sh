#!/usr/bin/env bash
# relin 직접 계측 전환에 따른 openfhe·lattigo 12개 CSV 재측정.
# ★ SEAL 6개는 원래부터 직접 계측이라 재측정하지 않는다.
#
# 조건은 직전 본측정(scripts/run_all_dku16c.sh)과 동일:
#   scripts/run_warm.sh 경유 · 코어 12 고정(openfhe mt만 0-15 + 16스레드 가열)
#   reps 30 · warmup 3 · 채택/기각 장치 없음
set -u
# 스크립트가 scripts/ 로 내려갔다(2026-08-01 구조 개편). 산출 CSV는 예전처럼 리포 루트에
# 떨어져야 하므로 BASH_SOURCE 로 루트를 되짚어 cd 한다(하드코딩 경로 대체).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

SB=/tmp/claude-1000/-data/e7b62f21-7738-4bab-bc47-bcb86cb6afd9/scratchpad
TR="$SB/relin"; mkdir -p "$TR"
WARM=30
NCORE="$(nproc)"
SOLO_CORE="${SOLO_CORE:-12}"
ALL_CORES="0-$((NCORE - 1))"

echo "# 고정 코어: 단일스레드=$SOLO_CORE, OpenFHE mt=$ALL_CORES (가열 ${WARM}s)"

for p in small medium large; do
  for lib in openfhe lattigo; do
    for th in 1t mt; do
      out="results_${lib}_${p}_${th}_dku16c.csv"
      pr="$TR/${lib}_${p}_${th}"
      cores="$SOLO_CORE"; nwarm=1
      if [ "$lib" = "openfhe" ] && [ "$th" = "mt" ]; then
        cores="$ALL_CORES"; nwarm="$NCORE"
      fi
      echo "### $lib $p $th -> $out (cores=$cores warm=$nwarm)"
      if [ "$lib" = "openfhe" ]; then
        if [ "$th" = "1t" ]; then export OMP_NUM_THREADS=1; else unset OMP_NUM_THREADS; fi
        "$HERE/run_warm.sh" "$cores" "$nwarm" "$WARM" "$pr" \
          ./build_openfhe/openfhe_bench -preset "$p" -reps 30 -out "$out" >/dev/null 2>&1
      else
        if [ "$th" = "1t" ]; then export GOMAXPROCS=1; else unset GOMAXPROCS; fi
        "$HERE/run_warm.sh" "$cores" "$nwarm" "$WARM" "$pr" \
          go run src/lattigo_bench.go -preset "$p" -reps 30 -out "$out" >/dev/null 2>&1
      fi
      python3 "$HERE/probe_check.py" "$pr" || echo "  !! 프로브가 fast 밴드를 벗어났다"
    done
  done
  # SEAL CSV는 건드리지 않는다 — openfhe·lattigo만 스테이징
  git add -f results_openfhe_${p}_*_dku16c.csv results_lattigo_${p}_*_dku16c.csv
  git commit -q -m "measure: ${p} relin 직접 계측 재측정 (openfhe·lattigo, dku16c)

relin을 파생값(mul_cc_rlk - mul_cc, std=0)에서 직접 계측으로 전환한 뒤 재측정.
SEAL 6개 CSV는 원래부터 직접 계측이라 재측정하지 않았다.
조건은 직전 본측정과 동일(코어 고정 + 사전 가열, reps 30, 채택/기각 없음).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QAUSb1GNgxJ2ga7wyt3GKn" \
    && echo "=== committed ${p}: $(git rev-parse --short HEAD) ===" || echo "=== ${p}: 커밋할 변경 없음 ==="
done
echo RELIN_REMEASURE_DONE
