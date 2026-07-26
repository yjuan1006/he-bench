#!/usr/bin/env bash
# 본측정: 3 프리셋 × {1t,mt} × 3 라이브러리 = 18 CSV. reps 30, warmup 3.
# 파일명 규칙은 PROJECT_CONTEXT.md §4 그대로.
#
# 오염 대책 = 코어 고정 + 사전 가열 (run_warm.sh). 채택/기각 장치는 쓰지 않는다.
#   dku16c의 오염원은 코어 단위 DVFS다(유휴→base 2.2GHz, 부하 후 ~6.7초→turbo 3.7GHz,
#   유휴 ~1초면 base 복귀, 비 1.675). 핀한 코어를 미리 달궈 두면 원인 자체가 없어진다.
# 인-런 모니터는 쓰지 않는다 — 코어를 뺏겨 OpenFHE mt의 OMP 조건이 깨진다
#   (실측: rot1/relin 4.3~5.2배 왜곡).
#
# 측정 로직(openfhe_bench.cpp / lattigo_bench.go / seal_bench.cpp)은 무수정.
# seal_bench의 -warmsec은 0으로 두고 가열을 래퍼로 통일한다 — 세 라이브러리가
# 동일한 가열 절차를 받아야 한다.
#
# 스레드 제어 (§4): OpenFHE=OMP_NUM_THREADS, Lattigo=GOMAXPROCS.
#   OMP_NUM_THREADS는 Go에 무효이므로 Lattigo 1t는 반드시 GOMAXPROCS=1.
set -u
cd /data/yja/he-bench
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

SB=/tmp/claude-1000/-data/e7b62f21-7738-4bab-bc47-bcb86cb6afd9/scratchpad
TR="$SB/main2"; mkdir -p "$TR"
WARM=30
NCORE="$(nproc)"
SOLO_CORE="${SOLO_CORE:-12}"          # 단일스레드 실행 고정 코어. 코어 0은 피한다.
ALL_CORES="0-$((NCORE - 1))"          # OpenFHE mt: 전 코어 집합에 고정 + 전 코어 가열

echo "# 고정 코어: 단일스레드=$SOLO_CORE, OpenFHE mt=$ALL_CORES (가열 ${WARM}s)"

run_one() {   # lib preset threads
  local lib=$1 p=$2 th=$3
  local out="results_${lib}_${p}_${th}_dku16c.csv"
  local pr="$TR/${lib}_${p}_${th}"
  local cores="$SOLO_CORE" nwarm=1

  # OpenFHE mt만 실제로 멀티스레드다. Lattigo/SEAL은 내부 병렬화가 없어 mt==1t이므로
  # 단일 코어 고정을 유지한다(§4의 mt 조건을 형식적으로 맞추되 조건은 동일).
  if [ "$lib" = "openfhe" ] && [ "$th" = "mt" ]; then
    cores="$ALL_CORES"; nwarm="$NCORE"
  fi

  echo "### $lib $p $th -> $out (cores=$cores warm_threads=$nwarm)"
  case "$lib" in
    openfhe)
      if [ "$th" = "1t" ]; then export OMP_NUM_THREADS=1; else unset OMP_NUM_THREADS; fi
      ./run_warm.sh "$cores" "$nwarm" "$WARM" "$pr" \
        ./build_openfhe/openfhe_bench -preset "$p" -reps 30 -out "$out" >/dev/null 2>&1
      ;;
    lattigo)
      if [ "$th" = "1t" ]; then export GOMAXPROCS=1; else unset GOMAXPROCS; fi
      ./run_warm.sh "$cores" "$nwarm" "$WARM" "$pr" \
        go run lattigo_bench.go -preset "$p" -reps 30 -out "$out" >/dev/null 2>&1
      ;;
    seal)
      ./run_warm.sh "$cores" "$nwarm" "$WARM" "$pr" \
        ./build_seal/seal_bench -preset "$p" -reps 30 -warmup 3 -warmsec 0 \
        -machine dku16c -threads "$th" -sweep desc -out "$out" >/dev/null 2>&1
      ;;
  esac
  local rc=$?
  python3 probe_check.py "$pr" || echo "  !! 프로브가 fast 밴드를 벗어났다 — 기록해 둘 것"
  [ "$rc" -ne 0 ] && echo "  !! rc=$rc"
  return 0
}

for p in small medium large; do
  for lib in openfhe lattigo seal; do
    for th in 1t mt; do
      run_one "$lib" "$p" "$th"
    done
  done
  git add -f results_*_${p}_*_dku16c.csv
  git commit -q -m "measure: ${p} 프리셋 재측정 (코어 고정 + 사전 가열, dku16c)

코어 단위 DVFS 오염 제거 조건에서 재측정.
run_warm.sh: 핀한 코어에서 30초 가열 후 exec 전환(유휴 틈 없음).
단일스레드=코어 ${SOLO_CORE} 고정, OpenFHE mt=전 코어 고정+전 코어 가열.
채택/기각 장치 없음. 측정 로직 무수정.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QAUSb1GNgxJ2ga7wyt3GKn" \
    && echo "=== committed ${p}: $(git rev-parse --short HEAD) ===" || echo "=== ${p}: 커밋할 변경 없음 ==="
done
echo MAIN_DONE
