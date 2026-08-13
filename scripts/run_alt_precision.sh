#!/usr/bin/env bash
# run_alt_precision.sh — 대안 프리셋 후보의 rot1 정밀도 측정 (탐색 단계, 본측정 아님).
#
# 후보는 explore/params/params_alt_grid.csv 에서 기준 2·3을 통과한 15개 (depth, Δ) 쌍이다:
#   Lattigo logP 300 여유 ≥5비트 & OpenFHE logP 240 가능 & SEAL P 60(항상 가능)
# 각 라이브러리는 자기 관례 P를 쓴다 — OpenFHE dnum 3(logP 240) / Lattigo PCount 5(logP 300) / SEAL 60.
#
# reps 기본 12 — 기존 5로는 OpenFHE rot1 산포(σ 0.279)를 제대로 잡지 못했다.
# 판정은 평균이 아니라 **최소값** 기준이므로 표본을 늘리는 것이 목적이다.
#
# ★ 3개 실행 전부 코어 12 고정 — 순차 실행.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# 산출물 목적지 규칙 (2026-08-08 results/ 트리 개편) — scripts/respath.sh
# shellcheck source=respath.sh
source "$HERE/respath.sh"
cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
RAW="$SB/alt_precision"; mkdir -p "$RAW"; TR="$RAW/probe"; mkdir -p "$TR"
CORE="${SOLO_CORE:-12}"; WARM=30; REPS="${REPS:-12}"
OUT="$ROOT/explore"; mkdir -p "$OUT"

# (depth, Δ) 후보 — 격자 필터 결과 그대로.
PAIRS="12:43 12:42 12:41 12:40 11:46 11:45 11:44 10:51 10:50 10:49 10:48 9:57 9:56 9:55 9:54"
OF=""; LA=""; SE=""
for p in $PAIRS; do
  OF="${OF:+$OF,}${p}:3"     # OpenFHE dnum 3 → logP 240
  LA="${LA:+$LA,}${p}:5"     # Lattigo PCount 5 → logP 300
  SE="${SE:+$SE,}${p}"       # SEAL P 60 고정
done

LATBIN="$RAW/ksprec_lattigo"
go build -o "$LATBIN" src/ksprec_lattigo.go || { echo "go build 실패"; exit 1; }

fail=0
run_one() {   # tag  out  cmd...
  local tag=$1 out=$2; shift 2
  local pr="$TR/$tag"
  echo "### $tag (코어 $CORE 고정, ${WARM}s 가열)"
  "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" "$@" >"$out" 2>"$RAW/$tag.err"
  local rc=$?
  python3 "$HERE/probe_check.py" "$pr" || { echo "  !! $tag 프로브 이탈"; fail=$((fail+1)); }
  [ "$rc" -ne 0 ] && { echo "  !! $tag rc=$rc"; fail=$((fail+1)); }
  return 0
}

OMP_NUM_THREADS=1 run_one openfhe "$RAW/of.csv" \
  ./build_openfhe/ksprec_openfhe -combos "$OF" -reps "$REPS"
GOMAXPROCS=1 run_one lattigo "$RAW/la.csv" "$LATBIN" -combos "$LA" -reps "$REPS"
run_one seal "$RAW/se.csv" ./build_seal/ksprec_seal -combos "$SE" -reps "$REPS"

DEST="$(res_out "$ROOT" "params_alt_precision.csv")"
head -1 "$RAW/of.csv" > "$DEST"
for f in "$RAW/of.csv" "$RAW/la.csv" "$RAW/se.csv"; do tail -n +2 "$f" >> "$DEST"; done
echo "  $DEST  ($(( $(wc -l < "$DEST") - 1 ))행)"
echo "ALT_PRECISION_DONE fail=$fail"
exit 0
