#!/usr/bin/env bash
# 본측정: 3 프리셋 × {1t,mt} × 3 라이브러리 = 18 CSV.
# reps 30, warmup 3, warmsec 30. 파일명 규칙은 PROJECT_CONTEXT.md §4 그대로.
#
# 측정 로직(openfhe_bench.cpp / lattigo_bench.go / seal_bench.cpp)은 손대지 않는다.
# 바꾸는 것은 실행 전 웜업과 실행 중/전후 모니터링뿐이다.
#
# 스레드 제어 (§4): OpenFHE=OMP_NUM_THREADS, Lattigo=GOMAXPROCS.
#   OMP_NUM_THREADS는 Go에 무효이므로 Lattigo 1t는 반드시 GOMAXPROCS=1.
set -u
cd /data/yja/he-bench
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

SB=/tmp/claude-1000/-data/e7b62f21-7738-4bab-bc47-bcb86cb6afd9/scratchpad
TR="$SB/main"; mkdir -p "$TR"
WARM=30; MAXTRY=6
TALLY="$SB/tally.txt"
: > "$TALLY"

run_one() {   # lib preset threads
  local lib=$1 p=$2 th=$3
  local final="results_${lib}_${p}_${th}_dku16c.csv"
  # 하네스는 -out 경로에 매 시도마다 쓴다. 기각된 시도가 확정본을 덮어쓰면 안 되므로
  # 임시 경로에 쓰고 채택됐을 때만 제자리로 옮긴다. (기존 12개 CSV는 git 추적 대상도
  # 아니라 덮어쓰면 복구 불가 — §5.5의 PNG 소실 사고와 같은 구조다.)
  local out="$TR/staging_${lib}_${p}_${th}.csv"
  local prefix="$TR/${lib}_${p}_${th}"
  # mt는 in-run 모니터가 OMP를 교란하므로 전후 확인만 (run_monitored.sh 주석 참조)
  if [ "$th" = "mt" ]; then export MONMODE=prepost; else export MONMODE=inrun; fi

  echo "### $lib $p $th -> $out (MONMODE=$MONMODE)"
  local res
  case "$lib" in
    openfhe)
      if [ "$th" = "1t" ]; then export OMP_NUM_THREADS=1; else unset OMP_NUM_THREADS; fi
      res=$(./run_monitored.sh "$WARM" "$MAXTRY" "$prefix" \
            ./build_openfhe/openfhe_bench -preset "$p" -reps 30 -out "$out")
      ;;
    lattigo)
      if [ "$th" = "1t" ]; then export GOMAXPROCS=1; else unset GOMAXPROCS; fi
      res=$(./run_monitored.sh "$WARM" "$MAXTRY" "$prefix" \
            go run lattigo_bench.go -preset "$p" -reps 30 -out "$out")
      ;;
    seal)
      # SEAL은 내부 병렬화가 없어 1t==mt. 스키마 정합을 위해 두 파일 모두 만든다.
      res=$(./run_monitored.sh "$WARM" "$MAXTRY" "$prefix" \
            ./build_seal/seal_bench -preset "$p" -reps 30 -warmup 3 -warmsec 30 \
            -machine dku16c -threads "$th" -sweep desc -out "$out")
      ;;
  esac
  local rc=$?
  echo "$res" | grep -E "^  try|^TRIES" || true
  echo "${lib}_${p}_${th} $(echo "$res" | grep '^TRIES' || echo 'TRIES=? REJECTS=?') rc=$rc" >> "$TALLY"
  if [ "$rc" -eq 0 ] && [ -s "$out" ]; then
    mv -f "$out" "$final"
    echo "  -> 채택본을 $final 로 확정"
  else
    echo "  -> 채택 실패: $final 은 그대로 둔다(기존값 보존)"
  fi
  return $rc
}

for p in small medium large; do
  for lib in openfhe lattigo seal; do
    for th in 1t mt; do
      run_one "$lib" "$p" "$th" || echo "!!! ${lib} ${p} ${th} 채택 실패"
    done
  done
  # 프리셋 하나 끝날 때마다 즉시 커밋 (§5.5 — 산출물은 .gitignore 대상이라 -f 필요)
  git add -f results_*_${p}_*_dku16c.csv
  git commit -q -m "measure: ${p} preset 재측정 (clock-monitored, dku16c)

호스트 클럭 오염(콜드 코어 ~6.7s 램프, 비 1.66) 제거 조건에서 재측정.
전 코어 30초 웜업 + 캘리브레이션 모니터 채택/기각.
1t는 in-run 모니터, mt는 OMP 교란 회피를 위해 전후 확인.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QAUSb1GNgxJ2ga7wyt3GKn" \
    && echo "=== committed ${p}: $(git rev-parse --short HEAD) ===" || echo "=== ${p} 커밋할 변경 없음 ==="
done
echo MAIN_DONE
