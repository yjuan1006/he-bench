#!/usr/bin/env bash
###############################################################################
# setup_dku16c.sh — dku16c (Intel Xeon SapphireRapids, 16 physical cores,
#                    no SMT) 머신용 he-bench 환경 구축 스크립트
#
# 이 스크립트가 하는 일 (4단계):
#   1) Go 1.24.5           → $HOME/.local/go        (+ PATH 설정)
#   2) OpenFHE v1.5.1       → 소스 빌드 (epyc4t 세션과 동일 cmake 옵션)
#   3) Python venv          → pandas + matplotlib
#   4) 검증                 → lscpu / nproc / free -g / go version / 빌드 산출물
#
# 벤치 재측정(step 5)은 이 스크립트가 하지 않는다. SETUP_DKU16C.md의
# "재측정 매트릭스"를 참고할 것.
#
# 사용법:
#   cd /data/he-bench            # 리포를 여기에 clone 했다고 가정
#   ./setup_dku16c.sh            # 전체 실행
#   ./setup_dku16c.sh verify     # 검증 단계만 다시 실행
#
# 경로는 아래 환경변수로 덮어쓸 수 있다:
#   GOROOT_TARGET, OPENFHE_SRC, OPENFHE_INSTALL, VENV_DIR
###############################################################################
set -euo pipefail

# --- 이 스크립트가 위치한 디렉터리 = 리포 루트로 간주 -------------------------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 설정 (환경변수로 덮어쓰기 가능) -----------------------------------------
GO_VERSION="1.24.5"
OPENFHE_TAG="v1.5.1"
GOROOT_TARGET="${GOROOT_TARGET:-$HOME/.local/go}"     # 홈 안: 리셋 방지
OPENFHE_SRC="${OPENFHE_SRC:-/data/openfhe-src}"       # 대용량 → /data
OPENFHE_INSTALL="${OPENFHE_INSTALL:-/data/openfhe-install}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
NPROC="$(nproc)"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

###############################################################################
# 1) Go 1.24.5 → $HOME/.local/go
###############################################################################
install_go() {
  log "Go ${GO_VERSION} 설치 → ${GOROOT_TARGET}"
  if [ -x "${GOROOT_TARGET}/bin/go" ] && \
     "${GOROOT_TARGET}/bin/go" version | grep -q "go${GO_VERSION}"; then
    warn "이미 go${GO_VERSION} 설치됨 — 건너뜀"
  else
    local tarball="go${GO_VERSION}.linux-amd64.tar.gz"
    local url="https://go.dev/dl/${tarball}"
    log "다운로드: ${url}"
    curl -fL --retry 3 -o "/tmp/${tarball}" "${url}"
    mkdir -p "$(dirname "${GOROOT_TARGET}")"
    rm -rf "${GOROOT_TARGET}"
    # tar 압축 해제 시 go/ 디렉터리가 생기므로 상위에 풀고 이름 맞춤
    tar -C "$(dirname "${GOROOT_TARGET}")" -xzf "/tmp/${tarball}"
    [ "$(dirname "${GOROOT_TARGET}")/go" != "${GOROOT_TARGET}" ] && \
      { rm -rf "${GOROOT_TARGET}"; mv "$(dirname "${GOROOT_TARGET}")/go" "${GOROOT_TARGET}"; } || true
    rm -f "/tmp/${tarball}"
  fi
  export PATH="${GOROOT_TARGET}/bin:${PATH}"
  persist_env "export PATH=\"${GOROOT_TARGET}/bin:\$PATH\""
  "${GOROOT_TARGET}/bin/go" version
}

###############################################################################
# 2) OpenFHE v1.5.1 소스 빌드 (epyc4t 세션과 동일 옵션)
#    Release / shared / OpenMP=ON / NATIVEOPT=OFF / INTEL_HEXL=OFF
###############################################################################
install_openfhe() {
  log "OpenFHE ${OPENFHE_TAG} 소스 빌드 → ${OPENFHE_INSTALL}"
  if [ -f "${OPENFHE_INSTALL}/lib/OpenFHE/OpenFHEConfig.cmake" ]; then
    warn "이미 설치됨 (${OPENFHE_INSTALL}) — 건너뜀. 재빌드하려면 해당 디렉터리 삭제."
  else
    if [ ! -d "${OPENFHE_SRC}/.git" ]; then
      git clone --branch "${OPENFHE_TAG}" --depth 1 \
        https://github.com/openfheorg/openfhe-development.git "${OPENFHE_SRC}"
    fi
    mkdir -p "${OPENFHE_SRC}/build"
    ( cd "${OPENFHE_SRC}/build"
      # ── epyc4t 빌드와 동일한 cmake 옵션 ──────────────────────────────────
      # WITH_INTEL_HEXL 은 기본 OFF (근거: SETUP_DKU16C.md §1 참고).
      cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="${OPENFHE_INSTALL}" \
        -DBUILD_SHARED=ON \
        -DBUILD_STATIC=OFF \
        -DBUILD_UNITTESTS=OFF \
        -DBUILD_EXAMPLES=OFF \
        -DBUILD_BENCHMARKS=OFF \
        -DWITH_OPENMP=ON \
        -DWITH_NATIVEOPT=OFF \
        -DWITH_INTEL_HEXL=OFF \
        ..
      make -j"${NPROC}"
      make install
    )
  fi
  export LD_LIBRARY_PATH="${OPENFHE_INSTALL}/lib:${LD_LIBRARY_PATH:-}"
  export CMAKE_PREFIX_PATH="${OPENFHE_INSTALL}:${CMAKE_PREFIX_PATH:-}"
  persist_env "export LD_LIBRARY_PATH=\"${OPENFHE_INSTALL}/lib:\${LD_LIBRARY_PATH:-}\""
  persist_env "export CMAKE_PREFIX_PATH=\"${OPENFHE_INSTALL}:\${CMAKE_PREFIX_PATH:-}\""
}

###############################################################################
# 3) Python venv + pandas / matplotlib
###############################################################################
install_venv() {
  log "Python venv → ${VENV_DIR} (pandas + matplotlib)"
  command -v python3 >/dev/null || die "python3 없음"
  [ -d "${VENV_DIR}" ] || python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
  "${VENV_DIR}/bin/pip" install pandas matplotlib
  "${VENV_DIR}/bin/python" -c "import pandas, matplotlib; \
    print('pandas', pandas.__version__, '/ matplotlib', matplotlib.__version__)"
}

###############################################################################
# 4) 검증
###############################################################################
verify() {
  local report="${REPO_DIR}/ENV_dku16c.txt"
  log "환경 검증 → ${report} 에도 기록"
  {
    echo "# he-bench 환경 검증 — dku16c"
    echo "# 생성: $(date -Is)"
    echo
    echo "## lscpu (요약)"
    lscpu | grep -iE "Model name|Architecture|^CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket|Flags.*avx512|avx512" || lscpu
    echo
    echo "## nproc"; nproc
    echo
    echo "## free -g"; free -g
    echo
    echo "## go version"
    "${GOROOT_TARGET}/bin/go" version 2>&1 || echo "go 없음"
    echo
    echo "## OpenFHE 설치"
    ls -1 "${OPENFHE_INSTALL}/lib/" 2>/dev/null | grep -i openfhe || echo "OpenFHE lib 없음"
    echo
    echo "## Python venv"
    "${VENV_DIR}/bin/python" --version 2>&1 || echo "venv 없음"
  } | tee "${report}"

  # --- 빌드 산출물 확인: 두 벤치를 실제로 빌드해 본다 ------------------------
  log "빌드 산출물 확인 — Lattigo"
  ( cd "${REPO_DIR}" && "${GOROOT_TARGET}/bin/go" build -o /tmp/lattigo_bench_check lattigo_bench.go \
      && echo "OK: lattigo_bench 빌드 성공" ) || warn "Lattigo 빌드 실패 — 로그 확인"

  log "빌드 산출물 확인 — OpenFHE"
  ( mkdir -p "${REPO_DIR}/build_openfhe" && cd "${REPO_DIR}/build_openfhe" \
      && cmake -DCMAKE_PREFIX_PATH="${OPENFHE_INSTALL}" "${REPO_DIR}" >/dev/null \
      && make -j"${NPROC}" openfhe_bench >/dev/null \
      && test -x ./openfhe_bench \
      && echo "OK: openfhe_bench 빌드 성공" ) || warn "OpenFHE 벤치 빌드 실패 — 로그 확인"

  log "검증 완료. ${report} 의 CPU 스펙을 README에 기록할 것 (SETUP_DKU16C.md §4)."
}

###############################################################################
# 유틸: ~/.bashrc 에 중복 없이 환경설정 추가
###############################################################################
persist_env() {
  local line="$1" rc="$HOME/.bashrc"
  grep -qF -- "${line}" "${rc}" 2>/dev/null || echo "${line}" >> "${rc}"
}

###############################################################################
main() {
  case "${1:-all}" in
    all)      install_go; install_openfhe; install_venv; verify ;;
    go)       install_go ;;
    openfhe)  install_openfhe ;;
    venv)     install_venv ;;
    verify)   verify ;;
    *)        die "알 수 없는 인자: ${1}. (all|go|openfhe|venv|verify)" ;;
  esac
  log "완료."
}
main "$@"
