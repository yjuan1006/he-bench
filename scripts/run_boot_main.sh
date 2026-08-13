#!/usr/bin/env bash
# run_boot_main.sh — 부트스트래핑 3단계 **본측정** 드라이버.
#
# 대상: BT1 (q0=60, Δ=59, L=4) · BT2 (q0=60, Δ=58, L=4) × 분해깊이 5종 × 양쪽 라이브러리.
# 프로토콜은 §8.6 그대로다 — 코어 고정 + 30초 가열 + 전후 프로브(`run_warm.sh`, exec 전환).
#
#   1t : OpenFHE OMP_NUM_THREADS=1 / Lattigo GOMAXPROCS=1, 코어 12 단일 고정.
#        타이밍과 정밀도를 한 실행에서 함께 잰다(`-mode both`).
#   mt : ⚠️ **타이밍과 정밀도를 분리 실행**한다(§8.6-2). 한 프로세스에서 정밀도가 뒤에
#        오면 그 구간이 대부분 직렬이라 post 프로브가 식은 구간을 잰다.
#        · OpenFHE: 전 코어(0-15) 고정 + 전 코어 가열 + OMP_NUM_THREADS=16 + PROBE_CORE
#        · Lattigo: **코어 12 단일 고정** + GOMAXPROCS=16 — 내부 병렬화가 없어 8-op 에서
#          mt/1t 0.97~1.07 로 확인됐다(§8.6-3). 전 코어를 주면 프로브가 유휴 코어에 얹힌다.
#
# ⚠️ reps 10 / warmup 3. **rep 마다 새로 암호화**한다(하네스 수정, §4 의 표본표준편차 규칙).
# ⚠️ 실패해도 멈추지 않는다. rep 별 증분 CSV 라 중단돼도 이미 잰 rep 은 남는다.
# ⚠️ 결과 파일을 지우지 마라 — 재실행 전에 `results/boot/superseded/` 로 옮길 것.
#
# 사용법:
#   scripts/run_boot_main.sh 1t     # 20실행 (~2.7h)
#   scripts/run_boot_main.sh mt     # 40실행 (~3.3h)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"
export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

MODE="${1:-1t}"
POINTS="explore/boot_params/boot_stage3_points.csv"
SB="${SCRATCH:-/tmp/claude-1000/-data/8e830feb-bacb-46cc-b2af-afc4519f226d/scratchpad}"
RAW="$SB/boot_main"; mkdir -p "$RAW"
TR="$ROOT/traces/boot_main"; mkdir -p "$TR"
REPS="${REPS:-10}"; WARMUP="${WARMUP:-3}"; WARM=30
OUT_OF="$ROOT/results/boot/boot_main_openfhe_${MODE}_dku16c.csv"
OUT_LA="$ROOT/results/boot/boot_main_lattigo_${MODE}_dku16c.csv"

LATBIN="$RAW/boot_bench_lattigo"
go build -o "$LATBIN" src/boot_bench_lattigo.go || { echo "go build 실패"; exit 1; }
OFBIN="$ROOT/build_openfhe/boot_bench_openfhe"
[ -x "$OFBIN" ] || { echo "$OFBIN 없음"; exit 1; }

fail=0
run_one() {   # tag  cores  nwarm  probecore  cmd...
  local tag=$1 cores=$2 nwarm=$3 pcore=$4; shift 4
  local pr="$TR/$tag"
  # ⚠️ 스와핑이 일어나면 측정값을 신뢰할 수 없다. 실행 전후 pswpout 을 읽어 증가분을 본다.
  local sw0 sw1
  sw0=$(awk '/^pswpout/{print $2}' /proc/vmstat)
  echo "### $tag (코어 $cores, 가열스레드 $nwarm, 프로브코어 $pcore)"
  PROBE_CORE="$pcore" timeout 5400 "$HERE/run_warm.sh" "$cores" "$nwarm" "$WARM" "$pr" "$@" \
    2>&1 | tee "$RAW/$tag.log"
  local rc=${PIPESTATUS[0]}
  python3 "$HERE/probe_check.py" "$pr" || { echo "  !! $tag 프로브 이탈"; fail=$((fail+1)); }
  sw1=$(awk '/^pswpout/{print $2}' /proc/vmstat)
  if [ "$sw1" -ne "$sw0" ]; then
    echo "  !! $tag: 스와핑 발생 (pswpout $sw0 → $sw1) — 이 실행의 측정값은 신뢰 불가"
    echo "$tag,$sw0,$sw1" >> "$TR/swap_events.txt"
    fail=$((fail+1))
  fi
  [ "$rc" -ne 0 ] && { echo "  !! $tag rc=$rc"; fail=$((fail+1)); }
  return 0
}

# 분해깊이 순서: {2,2} → {3,3} → {3,4} → {4,3} → {4,4}. ⚠️ {4,4} 는 OpenFHE dnum 14 로
# keygen 185초라 **마지막**에 둔다 — 앞 실행이 안전하게 끝난 뒤 위험을 감수한다.
n=0
for lb in "2 2" "3 3" "3 4" "4 3" "4 4"; do
  set -- $lb; B0=$1; B1=$2
  while IFS=, read -r preset q0 d L c2s s2c dnof pcla scla mr qpof qpla mof mla; do
    [ "$preset" = "preset" ] && continue
    [ "$c2s" != "$B0" ] && continue
    [ "$s2c" != "$B1" ] && continue
    n=$((n+1))
    tag="${preset}_lb${B0}${B1}"

    if [ "$MODE" = 1t ]; then
      run_one "of_${tag}_1t" 12 1 12 \
        env OMP_NUM_THREADS=1 "$OFBIN" -out "$OUT_OF" -q0 "$q0" -delta "$d" -L "$L" \
          -lb "$c2s" "$s2c" -dnum "$dnof" -reps "$REPS" -warmup "$WARMUP" -mode both
      run_one "la_${tag}_1t" 12 1 12 \
        env GOMAXPROCS=1 "$LATBIN" -out "$OUT_LA" -q0 "$q0" -delta "$d" -L "$L" \
          -c2s "$c2s" -s2c "$s2c" -pcount "$pcla" -evalmod-scale "$scla" \
          -reps "$REPS" -warmup "$WARMUP" -mode both
    else
      # ⚠️ mt: 타이밍 / 정밀도를 **따로** 돈다.
      for sub in timing precision; do
        run_one "of_${tag}_mt_${sub}" 0-15 16 0 \
          env OMP_NUM_THREADS=16 "$OFBIN" -out "$OUT_OF" -q0 "$q0" -delta "$d" -L "$L" \
            -lb "$c2s" "$s2c" -dnum "$dnof" -reps "$REPS" -warmup "$WARMUP" -mode "$sub"
        run_one "la_${tag}_mt_${sub}" 12 1 12 \
          env GOMAXPROCS=16 "$LATBIN" -out "$OUT_LA" -q0 "$q0" -delta "$d" -L "$L" \
            -c2s "$c2s" -s2c "$s2c" -pcount "$pcla" -evalmod-scale "$scla" \
            -reps "$REPS" -warmup "$WARMUP" -mode "$sub"
      done
    fi
  done < "$POINTS"
done

echo
echo "=== $MODE 완료: $n 조합 ==="
echo "  OpenFHE → ${OUT_OF#"$ROOT"/}"
echo "  Lattigo → ${OUT_LA#"$ROOT"/}"
[ "$fail" -ne 0 ] && echo "  !! 경고 $fail 건"
exit 0
