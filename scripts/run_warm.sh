#!/usr/bin/env bash
# run_warm.sh — 코어 고정 + 사전 가열 실행 래퍼.
#
# 배경 (dku16c, 2026-07-26 실측): 오염원은 코어 단위 DVFS다.
#   유휴 코어 = base 2.2GHz (calib 138ms) / 부하 후 ~6.7초에 turbo 3.7GHz (calib 83ms), 비 1.675.
#   부하가 끊기면 ~1초 만에 base로 복귀한다.
#   스윕이 maxLevel에서 시작하므로 콜드 상태로 시작하면 높은 레벨만 부풀려지고
#   레벨-지연 기울기가 가짜로 가팔라진다.
#
# 핵심 요건: 워머 종료와 측정 시작 사이에 코어가 유휴가 되면 안 된다.
#   → 핀한 단일 bash 안에서 가열한 뒤 **exec**으로 벤치 바이너리로 전환한다.
#     프로세스를 새로 띄우면 그 틈에 base로 떨어진다(~1초).
#
# 측정 로직은 건드리지 않는다. 이 스크립트가 바꾸는 것은 실행 전 코어 상태뿐이다.
#
# 사용법:
#   run_warm.sh <core_spec> <n_warm_threads> <warm_sec> <probe_prefix> <cmd...>
# 예:
#   scripts/run_warm.sh 12    1  30 traces/of_1t  ./build_openfhe/openfhe_bench -preset small ...
#   scripts/run_warm.sh 0-15 16  30 traces/of_mt  ./build_openfhe/openfhe_bench -preset small ...
set -u
# 스크립트는 scripts/ 에 있고 calib 바이너리는 리포 루트에 있다(2026-08-01 구조 개편).
# ROOT = 리포 루트, HERE = scripts/.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

CORES=$1; NTHREADS=$2; WARM=$3; PROBE=$4; shift 4
mkdir -p "$(dirname "$PROBE")"

# 프로브를 어느 코어에서 잴 것인가. 기본값은 작업과 같은 집합(=1t 기존 동작 그대로).
#
# ⚠️ mt 에서 CORES 가 여러 코어면 calib 이 코어 사이를 이주하다 **식은 코어**에 얹혀
#   82.6ms(turbo) 로 시작했다가 138ms(base) 로 튄다. 실측(2026-08-02):
#     openfhe mt pre  82.57 82.64 ... 133.91 138.41 138.06
#     lattigo mt post 138.41 137.92 ... (전부 base)
#   측정 스레드가 점유한 코어는 뜨겁지만 나머지는 유휴라 프로브가 그 코어를 못 맞춘다.
#   → mt 에서는 PROBE_CORE 로 **실제로 바쁜 코어 하나**를 지정해 프로브를 고정한다.
PROBE_CORE="${PROBE_CORE:-$CORES}"

# 핀한 셸 안에서: 가열 → 사전 프로브 → exec.
# 사전 프로브도 같은 핀된 코어에서 돌므로 그 자체가 코어를 계속 바쁘게 유지한다.
taskset -c "$CORES" bash -c '
  ROOT="$1"; NT="$2"; WARM="$3"; PROBE="$4"; PC="$5"; shift 5
  pids=""
  i=1
  while [ "$i" -lt "$NT" ]; do
    ( end=$((SECONDS+WARM)); while [ $SECONDS -lt $end ]; do :; done ) &
    pids="$pids $!"
    i=$((i+1))
  done
  # 메인 셸도 직접 돈다 → 이 프로세스가 올라앉은 코어가 확실히 가열된다
  end=$((SECONDS+WARM)); while [ $SECONDS -lt $end ]; do :; done
  for p in $pids; do wait "$p" 2>/dev/null; done
  # 사전 프로브: 유휴 틈 없이 바로 이어서
  taskset -c "$PC" "$ROOT/calib" 1 > "${PROBE}_pre.txt" 2>/dev/null
  exec "$@"
' _ "$ROOT" "$NTHREADS" "$WARM" "$PROBE" "$PROBE_CORE" "$@"
rc=$?

# 사후 프로브: 벤치가 방금까지 코어를 점유했으므로 즉시 재면 turbo 상태여야 한다
taskset -c "$PROBE_CORE" "$ROOT/calib" 1 > "${PROBE}_post.txt" 2>/dev/null

exit "$rc"
