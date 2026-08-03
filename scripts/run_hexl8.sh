#!/usr/bin/env bash
# run_hexl8.sh — HEXL 아암 확장 측정 (프리셋 A, 8-op, 레벨 전수) + baseline mt 대등 재측정.
#
# 왜 별도 스크립트인가: 런이 18개라 한 번에 손으로 돌릴 수 없고, 순서·환경변수를
# 틀리면 조용히 오염된다. 특히 ⚠️ LD_LIBRARY_PATH — RUNPATH 보다 우선하므로
# HEXL 바이너리에 baseline 코어가 로드된 사고 이력이 있다(2026-08-02).
# 각 런 직전에 ldd 로 실제 해석을 찍어 로그에 남긴다.
#
# 측정 모드는 exp 7(-mainrun) 이다 — baseline 본측정과 **완전히 같은 코드 경로**.
# 8-op × 레벨 전수 × 정밀도. 새 모드를 만들지 않는다.
#
# mt 런 수: OpenFHE 5런 / SEAL 3런.
#   OpenFHE mt 는 런 간 편차가 최대 0.437 이라 단일 런으로 판정할 수 없다.
#   (baseline mt 가 단일 런이었다가 9행 중 5행이 5런 범위 밖으로 나온 이력)
# Lattigo 는 HEXL 대응물이 없어 측정하지 않는다 — baseline 값을 그대로 쓴다.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TR=traces/hexl8
mkdir -p "$TR"
LOG="$TR/driver.log"
: > "$LOG"

OF_HEXL_LIB=/data/yja/openfhe-hexl-install/lib
SE_HEXL_LIB="$ROOT/third_party/SEAL/install_hexl/lib"
OF_OFF_LIB=/data/yja/openfhe-install/lib
SE_OFF_LIB="$ROOT/third_party/SEAL/install/lib"

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# ldd 로 실제 로드 경로를 확인하고, 기대한 접두사가 아니면 즉시 멈춘다.
check_ld() {           # check_ld <bin> <expect_prefix> <libpath>
  local bin=$1 want=$2 lib=$3 got
  got=$(LD_LIBRARY_PATH="$lib" ldd "$bin" | grep -E "libOPENFHEcore|libseal\.so" | awk '{print $3}')
  echo "    ldd -> $got" >> "$LOG"
  case "$got" in
    "$want"*) ;;
    *) say "  ✗ 중단: $bin 이 $want 가 아닌 $got 를 물었다"; exit 1;;
  esac
}

# run <tag> <cores> <nwarm> <libpath> <bin> <spec> <threads> <precreps> <timing_out> <prec_out>
run() {
  local tag=$1 cores=$2 nwarm=$3 lib=$4 bin=$5 spec=$6 th=$7 pr=$8 tout=$9 pout=${10}
  say "  $tag"
  LD_LIBRARY_PATH="$lib" OMP_NUM_THREADS=$([ "$th" = mt ] && echo 16 || echo 1) \
  PROBE_CORE=12 \
    scripts/run_warm.sh "$cores" "$nwarm" 30 "$TR/$tag" \
      "$bin" -mainrun "$spec" -reps 30 -warmup 3 -precreps "$pr" -threads "$th" \
      -out "$tout" -precout "$pout" >> "$LOG" 2>&1
  local rc=$?
  [ $rc -ne 0 ] && { say "  ✗ $tag 실패 rc=$rc"; exit 1; }
  # 프로브 요약 — FAST(82.6ms) 이탈 여부를 판정할 원자료를 남긴다
  say "    pre $(head -1 "$TR/${tag}_pre.txt"|awk '{print $3}')..$(tail -1 "$TR/${tag}_pre.txt"|awk '{print $3}')" \
      "post $(head -1 "$TR/${tag}_post.txt"|awk '{print $3}')..$(tail -1 "$TR/${tag}_post.txt"|awk '{print $3}')"
}

OFH=./build_openfhe_hexl/presetsearch_openfhe
SEH=./build_seal_hexl/presetsearch_seal
OFO=./build_openfhe_off_exp8/presetsearch_openfhe
SEO=./build_seal_off_exp8/presetsearch_seal

check_ld "$OFH" "$OF_HEXL_LIB" "$OF_HEXL_LIB"
check_ld "$SEH" "$SE_HEXL_LIB" "$SE_HEXL_LIB"
check_ld "$OFO" "$OF_OFF_LIB"  "$OF_OFF_LIB"
check_ld "$SEO" "$ROOT/third_party/SEAL/install/lib" "$SE_OFF_LIB"
say "ldd 확인 통과 — HEXL 2개 / baseline 2개"

P=results_v3n15d42L12

# ── 1t (HEXL) : 타이밍 + 정밀도를 한 런에. baseline 본측정(exp5)과 같은 방식이다.
say "[1t HEXL]"
run of_hexl8_1t   12   1 "$OF_HEXL_LIB" "$OFH" "15:12:42:3" 1t 12 \
    ${P}_hexl8_timing_1t_dku16c.csv ${P}_hexl8_precision_1t_dku16c.csv
run se_hexl8_1t   12   1 "$SE_HEXL_LIB" "$SEH" "15:12:42"   1t 12 \
    ${P}_hexl8_timing_1t_seal_dku16c.csv ${P}_hexl8_precision_1t_seal_dku16c.csv

# ── mt (HEXL) : 타이밍은 복수 런, 정밀도는 **별도 런**.
#    한 프로세스에 정밀도를 붙이면 그 구간이 직렬이라 post 프로브가 식은 클럭을 잰다.
say "[mt HEXL · OpenFHE 타이밍 5런]"
for i in 1 2 3 4 5; do
  run of_hexl8_mt_r$i 0-15 16 "$OF_HEXL_LIB" "$OFH" "15:12:42:3" mt 0 \
      ${P}_hexl8_timing_mt_run${i}_dku16c.csv /dev/null
done
say "[mt HEXL · SEAL 타이밍 3런]"
for i in 1 2 3; do
  run se_hexl8_mt_r$i 12 1 "$SE_HEXL_LIB" "$SEH" "15:12:42" mt 0 \
      ${P}_hexl8_timing_mt_seal_run${i}_dku16c.csv /dev/null
done
say "[mt HEXL · 정밀도]"
LD_LIBRARY_PATH="$OF_HEXL_LIB" OMP_NUM_THREADS=16 PROBE_CORE=12 \
  scripts/run_warm.sh 0-15 16 10 "$TR/of_hexl8_mt_prec" "$OFH" -mainrun "15:12:42:3" \
    -reps 1 -warmup 0 -precreps 12 -threads mt \
    -out /dev/null -precout ${P}_hexl8_precision_mt_dku16c.csv >> "$LOG" 2>&1
LD_LIBRARY_PATH="$SE_HEXL_LIB" OMP_NUM_THREADS=16 PROBE_CORE=12 \
  scripts/run_warm.sh 12 1 10 "$TR/se_hexl8_mt_prec" "$SEH" -mainrun "15:12:42" \
    -reps 1 -warmup 0 -precreps 12 -threads mt \
    -out /dev/null -precout ${P}_hexl8_precision_mt_seal_dku16c.csv >> "$LOG" 2>&1

# ── 2단계: baseline mt 를 같은 범위로 재측정.
#    기존 results_v3n15d42L12_timing_mt_dku16c.csv 는 **덮지 않는다** — 별도 파일(off8)이다.
say "[mt baseline · OpenFHE 타이밍 5런]"
for i in 1 2 3 4 5; do
  run of_off8_mt_r$i 0-15 16 "$OF_OFF_LIB" "$OFO" "15:12:42:3" mt 0 \
      ${P}_off8_timing_mt_run${i}_dku16c.csv /dev/null
done
say "[mt baseline · SEAL 타이밍 3런]"
for i in 1 2 3; do
  run se_off8_mt_r$i 12 1 "$SE_OFF_LIB" "$SEO" "15:12:42" mt 0 \
      ${P}_off8_timing_mt_seal_run${i}_dku16c.csv /dev/null
done

say "완료"
