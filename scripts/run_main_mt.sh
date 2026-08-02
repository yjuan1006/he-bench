#!/usr/bin/env bash
# run_main_mt.sh — 프리셋 A/B/C 의 8-op 레벨 전수 본측정 (mt). 1t 와 동일 프리셋.
#
# ⚠️ 이 측정의 축은 "op 내부 병렬화가 있는 라이브러리가 얼마나 이득을 보는가"다.
#   OpenFHE 만 OpenMP 로 단건 연산 내부를 병렬화한다. Lattigo·SEAL 은 내부 병렬화가 없어
#   op 자체는 단일 스레드로 돈다(Lattigo 는 런타임/GC 가 여분 코어를 쓸 수 있을 뿐).
#   독립 암호문을 코어에 분배하는 애플리케이션 수준 병렬화와는 다른 축이다.
#
# 코어 고정 (2026-08-02 정정):
#   OpenFHE 만 op 내부를 병렬화하므로 **OpenFHE 는 전 코어(0..N-1) 고정 + 전 코어 가열**.
#   Lattigo·SEAL 은 내부 병렬화가 없어 전 코어를 줘도 op 는 코어 하나만 쓴다 →
#   v1 프로토콜대로 **단일 코어(SOLO) 고정**을 유지하고 GOMAXPROCS 만 코어 수로 둔다.
#   (mt 조건을 형식적으로 맞추되 물리 조건은 1t 와 동일하게 둔다는 v1 §4 방침 그대로)
#
# ⚠️ 프로브는 PROBE_CORE 로 **실제 바쁜 코어 하나**에 고정한다.
#   전 코어 집합에 프로브를 풀어두면 calib 이 식은 코어로 이주해 138ms(base)가 찍힌다
#   — 측정이 아니라 프로브의 아티팩트다(첫 실행에서 4건 발생, mt/1t 비로 오염 아님을 확인).
# 인-런 모니터는 쓰지 않는다 — 코어를 뺏으면 OpenFHE OMP 조건이 깨진다(v1 실측 4.3~5.2배 왜곡).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"; cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"
SB="${SCRATCH:-/tmp/claude-1000/-data/7cf884b9-bd1e-4758-b15c-d8ff0b9568b3/scratchpad}"
NCORE="$(nproc)"; CORES="0-$((NCORE-1))"; SOLO="${SOLO_CORE:-12}"; WARM=30
REPS="${REPS:-30}"; WARMUP="${WARMUP:-3}"; PRECREPS="${PRECREPS:-12}"
echo "# 물리 코어 $NCORE | OpenFHE=전 코어 $CORES + ${NCORE}스레드 가열 | Lattigo·SEAL=코어 $SOLO 단일 | 프로브 코어 $SOLO"
fail=0

run_preset(){  # tag ofspec laspec sespec
  local tag=$1 ofs=$2 las=$3 ses=$4
  local RAW="$SB/mt_$tag"; mkdir -p "$RAW/probe"
  local LAT="$RAW/ps_lat"; go build -o "$LAT" src/presetsearch_lattigo.go || exit 1
  # one <tag> <core-spec> <warm-threads> -- cmd...
  one(){ local t=$1 cs=$2 nw=$3; shift 3
    echo "### $tag/$t (코어 $cs, 가열 ${nw}스레드 ${WARM}s, 프로브 코어 $SOLO)"
    PROBE_CORE="$SOLO" "$HERE/run_warm.sh" "$cs" "$nw" "$WARM" "$RAW/probe/$t" "$@" >"$RAW/$t.log" 2>&1
    local rc=$?
    python3 "$HERE/probe_check.py" "$RAW/probe/$t" || { echo "  !! 프로브 이탈"; fail=$((fail+1)); }
    [ "$rc" -ne 0 ] && { echo "  !! rc=$rc"; fail=$((fail+1)); }; return 0; }

  OMP_NUM_THREADS="$NCORE" one openfhe "$CORES" "$NCORE" ./build_openfhe/presetsearch_openfhe -mainrun "$ofs" -threads mt \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/of.csv" -precout "$RAW/of_prec.csv"
  GOMAXPROCS="$NCORE" one lattigo "$SOLO" 1 "$LAT" -mainrun "$las" -threads mt \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/la.csv" -precout "$RAW/la_prec.csv"
  one seal "$SOLO" 1 ./build_seal/presetsearch_seal -mainrun "$ses" -threads mt \
    -reps "$REPS" -warmup "$WARMUP" -precreps "$PRECREPS" -out "$RAW/se.csv" -precout "$RAW/se_prec.csv"

  for kind in timing precision; do
    local dest="$ROOT/results_${tag}_${kind}_mt_dku16c.csv"; local sfx=""
    [ "$kind" = precision ] && sfx="_prec"
    head -1 "$RAW/of${sfx}.csv" > "$dest"
    for f in of la se; do tail -n +2 "$RAW/${f}${sfx}.csv" >> "$dest"; done
    echo "  $dest  ($(( $(wc -l < "$dest") - 1 ))행)"
  done
}

run_preset v3n15d42L12   "15:12:42:3"  "15:12:42:5"  "15:12:42"
run_preset v3Bn14d42L6   "14:6:42:4"   "14:6:42:2"   "14:6:42"
run_preset v3Cn15d48L10  "15:10:48:2"  "15:10:48:4"  "15:10:48"
echo "MAIN_MT_DONE fail=$fail"
