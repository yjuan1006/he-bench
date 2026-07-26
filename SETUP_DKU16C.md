# SETUP_DKU16C.md — 새 벤치 머신(dku16c) 환경 구축 가이드

기존 벤치는 **epyc4t**(AMD EPYC 7643, 2코어×SMT2 = 4스레드) 샌드박스에서 측정했다.
이 문서는 새 머신 **dku16c**에서 동일 환경을 재현하고 8-op 벤치를 재측정하기 위한 절차다.

## 새 머신 스펙 (dku16c)

| 항목 | 값 |
|------|-----|
| CPU | Intel Xeon SapphireRapids |
| 물리 코어 | 16 (SMT 없음 — `Thread(s) per core: 1`) |
| 벡터 확장 | AVX-512 지원 |
| RAM | 62 GB |
| 작업 경로 | `/data/he-bench` (디스크 216G, 여유 202G) |
| 사전 설치 | Docker만 있음. **Claude Code 미설치.** |

> Claude Code가 없으므로 이 머신에서는 스크립트를 **직접(bash) 실행**한다.
> 컨테이너 안에서 돌릴 경우 `/data`를 볼륨 마운트할 것.

## 빠른 시작

```bash
git clone -b third-lib https://github.com/yjuan1006/he-bench.git /data/he-bench
cd /data/he-bench
./setup_dku16c.sh          # 1~4단계 전체
# 개별 단계: ./setup_dku16c.sh {go|openfhe|venv|verify}
```

경로 오버라이드(선택):
`GOROOT_TARGET`, `OPENFHE_SRC`, `OPENFHE_INSTALL`, `VENV_DIR` 환경변수.

## `setup_dku16c.sh`가 하는 일

| 단계 | 내용 | 기본 경로 |
|------|------|-----------|
| 1 | Go 1.24.5 설치 + PATH | `~/.local/go` (홈 안 → 리셋 방지) |
| 2 | OpenFHE v1.5.1 **소스 빌드** | src `/data/openfhe-src`, install `/data/openfhe-install` |
| 3 | Python venv + pandas·matplotlib | `/data/he-bench/.venv` |
| 4 | 검증(lscpu/nproc/free -g/go version/두 벤치 빌드) → `ENV_dku16c.txt` | — |

### OpenFHE cmake 옵션 (epyc4t와 동일)

```
-DCMAKE_BUILD_TYPE=Release   -DBUILD_SHARED=ON      -DBUILD_STATIC=OFF
-DBUILD_UNITTESTS=OFF        -DBUILD_EXAMPLES=OFF   -DBUILD_BENCHMARKS=OFF
-DWITH_OPENMP=ON            -DWITH_NATIVEOPT=OFF   -DWITH_INTEL_HEXL=OFF
```
(epyc4t 세션 CMakeCache 기준: Release / shared / OpenMP=ON / NATIVEOPT=OFF, MATHBACKEND=4·NATIVE_SIZE=64는 자동.)

---

## 반드시 유의할 5가지

### 1. `WITH_INTEL_HEXL`은 스크립트 기본 **OFF** — 켤 수 있지만 켜지 말 것(비교용)

- dku16c는 **AVX-512 지원**이라 Intel HEXL 가속을 켤 수 있다(`-DWITH_INTEL_HEXL=ON`).
  켜면 NTT/모듈러 연산이 AVX-512로 가속되어 OpenFHE latency가 눈에 띄게 빨라진다.
- **그러나 기본 OFF로 둔다.** 근거:
  - 기존 epyc4t 결과가 HEXL **OFF**로 빌드됐다. 켜면 두 머신 비교가 하드웨어 차이 +
    빌드 조건 차이가 뒤섞여 해석 불가.
  - heaan.io 참조 수치와의 빌드 조건도 달라진다. 공정 비교의 전제가 "같은 빌드 옵션,
    다른 하드웨어"인데, HEXL을 켜면 그 전제가 깨진다.
- HEXL 켠 별도 실험을 하고 싶다면 그건 **독립 실험**으로 분리하고 파일명에 `_hexl`을
  붙여 baseline과 절대 섞지 말 것.

### 2. devkit(HEaaN2)은 dku16c에 **없음** — 세 번째 라이브러리는 별도 확보 필요

- epyc4t에는 `~/devkit`에 HEaaN2 v0.2.0이 있었으나 **dku16c에는 없다.**
- `third-lib` 브랜치는 세 번째 라이브러리 작업을 위한 자리만 만들어 둔 상태이고,
  HEaaN2 라이브러리 자체(헤더 + `libheaan2.so` + 예제)는 Crypto Lab 제공물이라
  이 리포에 포함되지 않는다. dku16c에서 세 번째 라이브러리를 쓰려면 devkit을 **별도로
  가져와** 설치 경로(`~/devkit` 등)를 맞춰야 한다.
- GPU 실행이 `hex` 원격 CLI에 묶여 있던 점도 재확인 필요(dku16c 환경에 맞는지).

### 3. 기존 CSV는 **epyc4t 결과** — dku16c에서 전부 재측정 대상

- 기존 8-op CSV(`results_openfhe_*`, `results_lattigo_*`)는 전부 EPYC 7643 **4스레드
  (2물리코어×SMT2)** 에서 측정된 값이다. → `bootstrap-bench` 브랜치에 있음.
- dku16c는 CPU 아키텍처·코어수·SMT 유무가 완전히 달라, 절대치는 물론 스레딩 거동도
  다르다. **모든 8-op을 재측정한다.**
- 덮어쓰지 말 것. 기존 baseline = `..._epyc4t`, 신규 = `..._dku16c`로 머신 태그 유지.

### 4. 파일명 규칙 통일: `results_{lib}_{preset}_{1t|mt}[_{machine}].csv`

현재 Lattigo가 비대칭이다:
`results_lattigo.csv`(프리셋 불명·스레드 접미사 없음), `results_lattigo_medium.csv`,
`results_lattigo_large.csv`, `results_lattigo_large_gomaxprocs1.csv`.
**dku16c 재측정부터 아래 대칭 규칙으로 통일한다.**

- `lib` ∈ {`openfhe`, `lattigo`}
- `preset` ∈ {`small`, `medium`, `large`}
- `1t` = 싱글스레드, `mt` = 멀티스레드(기본)
  - OpenFHE: `1t` = `OMP_NUM_THREADS=1`, `mt` = 기본 OpenMP
  - Lattigo: `1t` = `GOMAXPROCS=1`, `mt` = 기본
- `machine` = `dku16c` (baseline은 `epyc4t`)

즉 라이브러리당 3프리셋 × {1t,mt} = **6개 파일**, 세 라이브러리(openfhe/lattigo/seal) **18개**.
검증 후 `./venv/bin/python aggregate.py`로 병합.

### 5. SMT 없음 → **코어 스윕(1/2/4/8/16)이 깨끗하다**

- dku16c는 `Thread(s) per core: 1`이라 N코어 고정 = N개의 독립 물리 스레드다.
  heaan.io에서는 SMT 때문에 "스레드 수 vs 물리코어 수" 해석이 복잡했는데, 여기선
  그 혼선이 없다.
- 기본 재측정은 `1t`/`mt` 두 지점이지만, 확장 실험으로 **1→2→4→8→16 코어 스윕**을
  깔끔하게 돌릴 수 있다(`OMP_NUM_THREADS=k` / `GOMAXPROCS=k` + 필요시 `taskset -c 0-(k-1)`).
  스케일링 그래프를 원하면 이 축을 추가할 것.

---

## 재측정 매트릭스 (step 5 — 스크립트가 자동으로 하지 않음)

`./setup_dku16c.sh` 성공 후 실행. 8-op × 3프리셋 × {1t,mt}.

```bash
cd /data/he-bench

# ── OpenFHE (C++) ─────────────────────────────────────────────────────────
BIN=build_openfhe/openfhe_bench
for p in small medium large; do
  # mt: 기본 OpenMP
  $BIN -preset $p -reps 30 -out results_openfhe_${p}_mt_dku16c.csv
  # 1t: OpenMP 1스레드
  OMP_NUM_THREADS=1 $BIN -preset $p -reps 30 -out results_openfhe_${p}_1t_dku16c.csv
done

# ── Lattigo (Go) ──────────────────────────────────────────────────────────
for p in small medium large; do
  go run lattigo_bench.go -preset $p -reps 30 -out results_lattigo_${p}_mt_dku16c.csv
  GOMAXPROCS=1 go run lattigo_bench.go -preset $p -reps 30 -out results_lattigo_${p}_1t_dku16c.csv
done

# ── 집계 + 그래프 ─────────────────────────────────────────────────────────
./.venv/bin/python aggregate.py
```

> `.gitignore`에 `results_*.csv`가 있으므로, 커밋하려면 `git add -f`로 명시 추가한다
> (기존 epyc4t CSV도 그렇게 트래킹돼 있다).

## 검증 체크리스트

- [ ] `lscpu`에 `Thread(s) per core: 1`, `avx512` 플래그, 16 cores 확인
- [ ] `nproc` = 16
- [ ] `free -g` ≈ 62 GB
- [ ] `go version` → `go1.24.5`
- [ ] `ENV_dku16c.txt` 생성됨 → **CPU 스펙을 README에 기록** (`## 측정 환경` 절 추가)
- [ ] `build_openfhe/openfhe_bench` 빌드 성공
- [ ] `go build lattigo_bench.go` 성공
- [ ] `./.venv/bin/python -c "import pandas, matplotlib"` 통과
