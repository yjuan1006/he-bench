# shellcheck shell=bash
# respath.sh — 측정 산출물의 목적지 디렉터리 (2026-08-08 `results/` 트리 개편).
#
# 개편 전에는 run_*.sh 가 `-out "$ROOT/results_....csv"` 로 전부 리포 루트에 떨어뜨렸고,
# 68개가 평평하게 쌓였다. 분류 규칙을 여기 한 곳에 두어 드라이버마다 경로를
# 하드코딩하지 않는다. 읽는 쪽 규칙은 `scripts/respath.py` 에 있고 **같은 분류**를 쓴다.
#
# ⚠️ 규칙을 바꾸면 respath.py 의 SEARCH_DIRS 와 각 디렉터리 README.md 도 함께 고칠 것.
#
# 사용법:
#   source "$HERE/respath.sh"
#   out=$(res_out "$ROOT" "results_v3n15d42L12_timing_1t_dku16c.csv")   # 디렉터리 자동 생성

# res_dir <파일명> → 리포 상대 디렉터리 (모르면 빈 문자열 = 루트 유지)
res_dir() {
  case "$1" in
    boot_prec_*)           echo "results/boot" ;;
    boot_*)                echo "explore/boot_params" ;;
    params_*)              echo "explore/params" ;;
    *_hexl8_*)             echo "results/hexl/arm" ;;
    *_hexl_*)              echo "results/hexl/superseded" ;;
    *_off8_*)              echo "results/baseline_mt_runs" ;;
    *_off_*)               echo "results/baseline_mt_runs/superseded" ;;
    *v2n15d40L13*run2lattigo*)  echo "results/v2_discarded/runs" ;;
    *v2n15d40L13*)         echo "results/v2_discarded" ;;
    *v3Bn14d42L6*)         echo "results/v3/B" ;;
    *v3Cn15d48L10*)        echo "results/v3/C" ;;
    *v3Dn14d42L4*)         echo "results/v3/D" ;;
    *v3n15d42L12*run2lattigo*)  echo "results/v3/A/runs" ;;
    *v3n15d42L12*)         echo "results/v3/A" ;;
    *)                     echo "" ;;
  esac
}

# res_out <ROOT> <파일명> → 절대 목적지 경로. 목적지 디렉터리를 만들어 둔다.
# /dev/null 은 그대로 통과시킨다 (드라이버가 -out /dev/null 로 버리는 경우가 있다).
res_out() {
  local root=$1 name=$2 d
  [ "$name" = /dev/null ] && { echo /dev/null; return; }
  d=$(res_dir "$name")
  if [ -z "$d" ]; then echo "$root/$name"; else mkdir -p "$root/$d"; echo "$root/$d/$name"; fi
}
