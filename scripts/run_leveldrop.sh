#!/usr/bin/env bash
# run_leveldrop.sh — 순수 레벨 강하(leveldrop) 전수 측정. 프리셋 A~D × 3 라이브러리 × 1t.
#
# 기존 8-op 본측정(run_main_v3.sh / run_main_D.sh)과 **완전히 같은 프로토콜**을 쓴다:
#   코어 12 고정 · 30초 사전 가열(run_warm.sh) · 전후 DVFS 프로브 · reps 30 / warmup 3.
# 다른 점은 op 목록뿐이다(exp 9 = leveldrop 계열 4종). 기존 exp 5/7/8 경로는 건드리지 않는다.
#
# mt 는 범위 밖이다 — 직전 분석에서 mt·OpenFHE·key-switch 84쌍 중 cv≤0.05 통과가 0개였다.
#
# ★ 3개 실행 전부 코어 12 고정 — 반드시 순차. 동시에 돌리면 측정이 통째로 오염된다.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

SB="${SCRATCH:-/tmp/claude-1000/-data/a64558f7-bd42-41a4-ab87-1e037d2b52b0/scratchpad}"
RAW="$SB/leveldrop"; mkdir -p "$RAW/probe"
OUTDIR="$ROOT/results/leveldrop"; mkdir -p "$OUTDIR"
CORE="${SOLO_CORE:-12}"
WARM=30
REPS="${REPS:-30}"
WARMUP="${WARMUP:-3}"

LATBIN="$RAW/ps_lat"
go build -o "$LATBIN" src/presetsearch_lattigo.go || { echo "go build 실패"; exit 1; }

# ── 동시 실행 가드 ───────────────────────────────────────────────────────────
# 2026-08-19 사고: 같은 스크립트를 두 번 띄워 **둘 다 코어 12에 핀**되는 바람에
# 프로브가 166ms(= 2 × 83ms turbo)로 나왔다. 코어를 공유하면 측정이 통째로 무의미하다.
# 락을 잡지 못하면 시작하지 않는다.
LOCK="$RAW/.running.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "!! 이미 다른 run_leveldrop.sh 가 돌고 있다 (락: $LOCK). 중단."; exit 3
fi
# 코어 $CORE 에 이미 CPU 를 먹는 프로세스가 있으면 시작하지 않는다.
busy="$(ps -eo pid,psr,pcomm,pcpu --no-headers | awk -v c="$CORE" '$2==c && $4>20 {print $1"("$3")"}' | tr '\n' ' ')"
if [ -n "$busy" ]; then
  echo "!! 코어 $CORE 가 이미 바쁘다: $busy — 중단."; exit 3
fi

fail=0
run_one() {   # tag  cmd...
  local tag=$1; shift
  local pr="$RAW/probe/$tag"
  echo "### $tag (코어 $CORE 고정, ${WARM}s 가열)"
  "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" "$@" >"$RAW/$tag.log" 2>&1
  local rc=$?
  python3 "$HERE/probe_check.py" "$pr" || { echo "  !! $tag: 프로브가 fast 밴드를 벗어났다"; fail=$((fail+1)); }
  [ "$rc" -ne 0 ] && { echo "  !! $tag: rc=$rc"; fail=$((fail+1)); }
  grep -E "^  L=" "$RAW/$tag.log" | head -20
  return 0
}

# preset  openfhe-spec       lattigo-spec       seal-spec
run_preset() {  # label ofs las ses
  local lb=$1 ofs=$2 las=$3 ses=$4
  OMP_NUM_THREADS=1 run_one "of_$lb" ./build_openfhe/presetsearch_openfhe -leveldrop "$ofs" \
    -threads 1t -reps "$REPS" -warmup "$WARMUP" \
    -out "$RAW/of_$lb.csv" -verifyout "$RAW/of_${lb}_verify.csv"
  GOMAXPROCS=1 run_one "la_$lb" "$LATBIN" -leveldrop "$las" \
    -threads 1t -reps "$REPS" -warmup "$WARMUP" \
    -out "$RAW/la_$lb.csv" -verifyout "$RAW/la_${lb}_verify.csv"
  run_one "se_$lb" ./build_seal/presetsearch_seal -leveldrop "$ses" \
    -threads 1t -reps "$REPS" -warmup "$WARMUP" \
    -out "$RAW/se_$lb.csv" -verifyout "$RAW/se_${lb}_verify.csv"
}

# 프리셋 정본은 run_main_v3.sh / run_main_D.sh 와 동일하다.
# 인자로 프리셋을 주면 그것만 돈다(프로브 이탈로 한 프리셋만 재측정할 때 쓴다).
WANT="${*:-A B C D}"
want() { case " $WANT " in *" $1 "*) return 0;; *) return 1;; esac; }
want A && run_preset A "15:12:42:3" "15:12:42:5" "15:12:42"
want B && run_preset B "14:6:42:4"  "14:6:42:2"  "14:6:42"
want C && run_preset C "15:10:48:2" "15:10:48:4" "15:10:48"
want D && run_preset D "14:4:42:2"  "14:4:42:3"  "14:4:42"

merge() {   # dest  src...
  local dest=$1; shift
  head -1 "$1" > "$dest"
  for f in "$@"; do tail -n +2 "$f" >> "$dest"; done
  echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"
}
echo "### 병합"
for lb in $WANT; do
  merge "$OUTDIR/results_leveldrop_${lb}_timing_1t_dku16c.csv" \
        "$RAW/of_$lb.csv" "$RAW/la_$lb.csv" "$RAW/se_$lb.csv"
  merge "$OUTDIR/results_leveldrop_${lb}_verify_1t_dku16c.csv" \
        "$RAW/of_${lb}_verify.csv" "$RAW/la_${lb}_verify.csv" "$RAW/se_${lb}_verify.csv"
done
if [ "$fail" -ne 0 ]; then
  echo "!! LEVELDROP_FAILED fail=$fail — 프로브가 FAST 밴드를 벗어났거나 실행이 실패했다."
  echo "!! 프로토콜상 이 산출물은 **폐기 대상**이다. results/leveldrop/ 에 병합하지 말 것."
fi
echo "LEVELDROP_DONE fail=$fail"
