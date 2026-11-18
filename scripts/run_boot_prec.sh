#!/usr/bin/env bash
# run_boot_prec.sh — 부트스트래핑 2단계(정밀도 곡선) 측정 드라이버. **1t 전용.**
#
# 대상점은 `explore/boot_params/boot_stage2_points.csv` (1단계 격자에서 추린 21점).
# 각 점을 **OpenFHE → Lattigo 순차**로 돌린다. ⚠️ 동시 실행 금지 — 평가키가 10~20 GB 급이다.
#
# 프로토콜은 8-op 1t 와 동일하다 (§8.6):
#   코어 고정 + 30초 사전 가열 + 전후 프로브 (`run_warm.sh`, exec 전환)
#   OpenFHE: OMP_NUM_THREADS=1 / Lattigo: GOMAXPROCS=1 (OMP_NUM_THREADS 는 Go 에 무효)
#
# ⚠️ **스크리닝이다.** reps 3 / warmup 3. 지연시간은 참고값이고 확정값이 아니다(본측정은 3단계).
# ⚠️ 산출 CSV 는 **rep 마다 append + flush** 된다 — 중간에 끊겨도 이미 잰 rep 은 남는다.
#    같은 파일에 이어 붙이므로 재실행 전에 해당 점의 기존 행을 지울지 판단할 것.
#
# 사용법:
#   scripts/run_boot_prec.sh                 # 21점 전량 (Lsweep 먼저, 그다음 curve)
#   scripts/run_boot_prec.sh --calib         # 보정 1점 (45, 40, L=12) 만
#   scripts/run_boot_prec.sh --role Lsweep   # 역할별
#   ONLY="45,40,12" scripts/run_boot_prec.sh # 한 점만
#   LIB=of scripts/run_boot_prec.sh          # 한 라이브러리만 (of|la|both, 기본 both)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=respath.sh
source "$HERE/respath.sh"
cd "$ROOT"

export LD_LIBRARY_PATH="/data/yja/openfhe-install/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/go/bin:$PATH"

POINTS="${POINTS:-explore/boot_params/boot_stage2_points2.csv}"   # 2026-08-12: 새 축 목록이 기본
SB="${SCRATCH:-/tmp/claude-1000/-data/8e830feb-bacb-46cc-b2af-afc4519f226d/scratchpad}"
RAW="$SB/boot_prec"; mkdir -p "$RAW"
TR="$ROOT/traces/boot"; mkdir -p "$TR"
CORE="${SOLO_CORE:-12}"
WARM=30
REPS="${REPS:-3}"
WARMUP="${WARMUP:-3}"
LIB="${LIB:-both}"
ROLE="${ROLE:-}"
ONLY="${ONLY:-}"

OUT_OF=$(res_out "$ROOT" "boot_prec_openfhe_1t_dku16c.csv")
OUT_LA=$(res_out "$ROOT" "boot_prec_lattigo_1t_dku16c.csv")

for a in "$@"; do
  case "$a" in
    --calib) ONLY="45,40,12" ;;
    --role) ;;                       # 값은 아래 ROLE 로 받는다
    Lsweep|curve) ROLE="$a" ;;
    *) echo "알 수 없는 인자: $a"; exit 2 ;;
  esac
done

# 가열된 코어에서 컴파일러가 돌면 안 되므로 Go 바이너리를 미리 빌드한다 (§8.6 관례).
LATBIN="$RAW/boot_bench_lattigo"
go build -o "$LATBIN" src/boot_bench_lattigo.go || { echo "go build 실패"; exit 1; }
OFBIN="$ROOT/build_openfhe/boot_bench_openfhe"
[ -x "$OFBIN" ] || { echo "$OFBIN 없음 — cmake --build build_openfhe --target boot_bench_openfhe"; exit 1; }

fail=0
run_one() {   # tag  cmd...
  local tag=$1; shift
  local pr="$TR/$tag"
  echo "### $tag (코어 $CORE 고정, ${WARM}s 가열)"
  # ⚠️ 점당 90분 타임아웃. 한 점이 멈춰도 전체가 서지 않는다.
  timeout 5400 "$HERE/run_warm.sh" "$CORE" 1 "$WARM" "$pr" "$@" 2>&1 | tee "$RAW/$tag.log"
  local rc=${PIPESTATUS[0]}
  if ! python3 "$HERE/probe_check.py" "$pr"; then
    echo "  !! $tag: 프로브가 fast 밴드를 벗어났다 — 폐기하고 재실행할 것"
    fail=$((fail + 1))
  fi
  [ "$rc" -ne 0 ] && { echo "  !! $tag: rc=$rc"; fail=$((fail + 1)); }
  return 0
}

# CSV 헤더에서 열 위치를 찾는다 (열 순서가 바뀌어도 깨지지 않게).
col() { awk -F, -v n="$1" 'NR==1{for(i=1;i<=NF;i++) if($i==n){print i; exit}}' "$POINTS"; }
C_ROLE=$(col role); C_Q0=$(col q0); C_D=$(col delta); C_L=$(col residual_L)
C_B0=$(col levelBudget_c2s); C_B1=$(col levelBudget_s2c)
C_DNOF=$(col dnum_of); C_PCLA=$(col PCount_boot_la); C_SCLA=$(col evalmod_scale_la)
[ -z "$C_SCLA" ] && C_SCLA=$(col evalmod_scale_la_x)

n=0
while IFS=, read -r -a f; do
  role=${f[$((C_ROLE-1))]}; q0=${f[$((C_Q0-1))]}; d=${f[$((C_D-1))]}
  L=${f[$((C_L-1))]}; b0=${f[$((C_B0-1))]}; b1=${f[$((C_B1-1))]}
  dnum=${f[$((C_DNOF-1))]}; pcla=${f[$((C_PCLA-1))]}; scla=${f[$((C_SCLA-1))]}
  [ "$role" = "role" ] && continue
  [ -n "$ROLE" ] && [ "$role" != "$ROLE" ] && continue
  # ⚠️ CSV 의 정수 열이 pandas 를 거치며 "4.0" 으로 나온다 — **ONLY 비교 전에** 자른다.
  #    (2026-08-12: 뒤에서 자르는 바람에 "60.0,59.0,4.0" != "60,59,4" 로 0점이 돌았다.)
  dnum=${dnum%%.*}; pcla=${pcla%%.*}; scla=${scla%%.*}; b0=${b0%%.*}; b1=${b1%%.*}
  q0=${q0%%.*}; d=${d%%.*}; L=${L%%.*}
  [ -n "$ONLY" ] && [ "$q0,$d,$L,$b0$b1" != "$ONLY" ] && continue
  n=$((n + 1))

  if [ "$LIB" = both ] || [ "$LIB" = of ]; then
    OMP_NUM_THREADS=1 run_one "of_q${q0}d${d}L${L}" \
      env OMP_NUM_THREADS=1 "$OFBIN" -out "$OUT_OF" \
      -q0 "$q0" -delta "$d" -L "$L" -lb "$b0" "$b1" -dnum "$dnum" \
      -reps "$REPS" -warmup "$WARMUP"
  fi
  if [ "$LIB" = both ] || [ "$LIB" = la ]; then
    run_one "la_q${q0}d${d}L${L}" \
      env GOMAXPROCS=1 "$LATBIN" -out "$OUT_LA" \
      -q0 "$q0" -delta "$d" -L "$L" -c2s "$b0" -s2c "$b1" -pcount "$pcla" \
      -evalmod-scale "$scla" \
      -reps "$REPS" -warmup "$WARMUP"
  fi
done < "$POINTS"

echo
echo "=== 완료: $n 점 (LIB=$LIB, ROLE=${ROLE:-전체}, ONLY=${ONLY:-없음}) ==="
echo "  OpenFHE → ${OUT_OF#"$ROOT"/}"
echo "  Lattigo → ${OUT_LA#"$ROOT"/}"
[ "$fail" -ne 0 ] && echo "  !! 경고 $fail 건 (프로브/종료코드) — 위 로그 확인"
exit 0
