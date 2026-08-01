#!/usr/bin/env bash
# SEAL 6개 CSV를 openfhe·lattigo와 같은 세션 조건으로 재측정.
# ★ src/seal_bench.cpp 는 수정하지 않는다 — 코드 변경이 아니라 세션 정합이 목적이다.
#
# 조건은 직전 relin 재측정(scripts/run_relin_remeasure.sh)과 동일:
#   scripts/run_warm.sh 경유 · 코어 12 고정 · reps 30 · warmup 3 · 채택/기각 없음
#   SEAL은 내부 병렬화가 없어 1t/mt 모두 단일 코어 고정(run_all_dku16c.sh와 같은 취급).
#   가열은 래퍼가 하므로 seal_bench 자체 -warmsec 은 0.
set -u
# 스크립트가 scripts/ 로 내려갔다(2026-08-01 구조 개편). 산출 CSV는 예전처럼 리포 루트에
# 떨어져야 하므로 BASH_SOURCE 로 루트를 되짚어 cd 한다(하드코딩 경로 대체).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
SB=/tmp/claude-1000/-data/e7b62f21-7738-4bab-bc47-bcb86cb6afd9/scratchpad
TR="$SB/seal_resession"; mkdir -p "$TR"
WARM=30
CORE="${SOLO_CORE:-12}"

echo "# 고정 코어 $CORE, 가열 ${WARM}s"
for p in small medium large; do
  for th in 1t mt; do
    out="results_seal_${p}_${th}_dku16c.csv"
    pr="$TR/seal_${p}_${th}"
    echo "### seal $p $th -> $out"
    "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" \
      ./build_seal/seal_bench -preset "$p" -reps 30 -warmup 3 -warmsec 0 \
      -machine dku16c -threads "$th" -sweep desc -out "$out" >/dev/null 2>&1
    python3 "$HERE/probe_check.py" "$pr" || echo "  !! 프로브가 fast 밴드를 벗어났다"
  done
  git add -f results_seal_${p}_*_dku16c.csv
  git commit -q -m "measure: ${p} SEAL 세션 정합 재측정 (dku16c)

openfhe·lattigo 12개가 이번 세션 측정본인데 SEAL 6개만 직전 세션이라
세션 간 계통 드리프트(~2%)가 3자 비교에 섞여 있었다. 특히 B3 교차점은
비가 1 근처인 판정이라 2% 수직 이동으로도 교차 레벨이 밀린다.
seal_bench.cpp 무수정 — 동일 코드로 세션만 맞춘다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QAUSb1GNgxJ2ga7wyt3GKn" \
    && echo "=== committed ${p}: $(git rev-parse --short HEAD) ===" || echo "=== ${p}: 변경 없음 ==="
done
echo SEAL_RESESSION_DONE
