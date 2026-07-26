#!/usr/bin/env bash
# run_monitored.sh — 클럭 오염 실행을 기각하고 재시도하는 공용 러너.
#
# 배경 (2026-07-25 진단): dku16c는 KVM 게스트이고 호스트 클럭이 두 상태를 오간다
#   fast ~82 ms / slow ~138 ms (calib 커널 기준, 비 1.675).
# 부하 시작 후 ~6초 램프 + 실행 중 무작위 dropout이 있다. 스윕이 maxLevel에서
# 시작하므로 오염되면 높은 레벨만 선택적으로 부풀려지고 레벨-지연 기울기가 가짜로
# 가팔라진다. 기존 dku16c 12개 CSV가 실제로 이 편향을 갖고 있었다.
#
# 이 스크립트가 하는 일은 두 가지뿐이다 (§4 측정 규칙·하네스 측정 로직 무수정):
#   1) 측정 전 머신 웜업 (램프 제거)
#   2) 측정 중 캘리브레이션 모니터 → 전 구간 fast 밴드일 때만 채택, 아니면 재시도
#
# 사용법:
#   run_monitored.sh <warm_sec> <max_tries> <trace_prefix> <cmd...>
# 종료:
#   0 = 채택된 실행 있음 (cmd의 -out 파일이 유효)
#   1 = max_tries 안에 채택 실패
# 표준출력 마지막 줄: "TRIES=<시도수> REJECTS=<기각수>"

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CALIB="${CALIB_BIN:-$HERE/calib}"
MONCORE="${MONCORE:-15}"     # 모니터 전용 코어. 측정은 핀하지 않는다.
# 전 코어를 데운다. 램프는 코어 단위이고(실측: 핫 코어 83ms / 콜드 코어 138ms 동시 관측),
# 측정 프로세스는 핀하지 않으므로 어느 코어에 올라가도 핫이어야 한다.
# 코어는 10초 유휴까지는 핫을 유지하고 30초 유휴면 콜드로 돌아간다(실측) →
# 웜업 직후 바로 측정을 시작해야 한다.
NCORE="$(nproc)"
WARMCORES="${WARMCORES:-$(seq 0 $((NCORE - 1)))}"

WARM=$1; MAXTRY=$2; TRACE_PREFIX=$3; shift 3

if [ ! -x "$CALIB" ]; then
  echo "[run_monitored] calib 바이너리 없음: $CALIB" >&2; exit 2
fi

rejects=0
for try in $(seq 1 "$MAXTRY"); do
  # --- 1) 웜업: 램프 구간을 측정 밖으로 밀어낸다 ---
  if [ "$WARM" -gt 0 ]; then
    for c in $WARMCORES; do
      taskset -c "$c" bash -c "end=\$((SECONDS+$WARM)); while [ \$SECONDS -lt \$end ]; do :; done" &
    done
    wait
  fi

  # --- 1b) 프리롤 게이트 ---
  # 웜업 직후 클럭이 이미 fast인지 먼저 확인하고 시작한다. 이게 없으면
  # "느린 구간에서 시작 → 도중에 fast로 전환"된 실행이 채택될 수 있다.
  # 그런 실행은 앞쪽 레벨만 부풀려지는데, 모니터 코어는 계속 바빠서 fast로 보이므로
  # in-run 모니터만으로는 못 잡는다 (실측: 채택된 실행이 L5/L1=5.75, 정상은 3.6~3.9).
  preroll="${TRACE_PREFIX}_try${try}_preroll.txt"
  taskset -c "$MONCORE" "$CALIB" 3 > "$preroll" 2>/dev/null
  if ! python3 "$HERE/clock_verdict.py" "$preroll" > "${preroll}.verdict" 2>&1; then
    echo "  try$try PREROLL-REJECT $(cat "${preroll}.verdict")"
    rejects=$((rejects + 1))
    continue
  fi

  # --- 2) 측정 + 클럭 상태 기록 ---
  # MONMODE=inrun  : 전용 코어에서 실행 내내 모니터 (1t 전용)
  # MONMODE=prepost: 측정 전후로만 확인 (mt 전용)
  #   mt에 in-run 모니터를 쓰면 안 된다 — 실측(2026-07-26): 모니터가 코어 하나를
  #   가져가면 OpenFHE mt의 rot1/relin이 4.3~5.2배 느려진다. OMP 16스레드가
  #   가용 15코어에 얹히면서 배리어에서 스핀하는 oversubscription 절벽이다.
  #   측정 로직이 아니라 측정 조건이 바뀌는 것이므로 mt에서는 금지한다.
  trace="${TRACE_PREFIX}_try${try}.txt"
  if [ "${MONMODE:-inrun}" = "inrun" ]; then
    taskset -c "$MONCORE" "$CALIB" 100000 > "$trace" 2>/dev/null &
    mon=$!
    "$@"
    rc=$?
    kill "$mon" 2>/dev/null; wait "$mon" 2>/dev/null
  else
    taskset -c "$MONCORE" "$CALIB" 3 > "$trace" 2>/dev/null
    "$@"
    rc=$?
    taskset -c "$MONCORE" "$CALIB" 3 >> "$trace" 2>/dev/null
  fi

  if [ "$rc" -ne 0 ]; then
    echo "[run_monitored] 명령이 rc=$rc 로 실패 — 재시도하지 않음" >&2
    echo "TRIES=$try REJECTS=$rejects"
    exit "$rc"
  fi

  # --- 3) 절대 밴드 판정 ---
  if python3 "$HERE/clock_verdict.py" "$trace" > "${trace}.verdict" 2>&1; then
    echo "  try$try $(cat "${trace}.verdict")"
    echo "TRIES=$try REJECTS=$rejects"
    exit 0
  fi
  echo "  try$try $(cat "${trace}.verdict")"
  rejects=$((rejects + 1))
done

echo "[run_monitored] $MAXTRY회 안에 채택 실패" >&2
echo "TRIES=$MAXTRY REJECTS=$rejects"
exit 1
