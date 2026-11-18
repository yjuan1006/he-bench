# HE Library Benchmark — OpenFHE vs Lattigo vs SEAL (CKKS)

CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++) · Lattigo(Go) · Microsoft SEAL(C++)
세 라이브러리에서 측정·비교한다.

> 파라미터 정본(logQ/logP/logQP·레벨별 digit 수·보안 여유)은 **`docs/PARAMS_dku16c.md`** 참조.

## 측정 환경

**dku16c** (현재 baseline, 파일 태그 `_dku16c`) — `docs/ENV_dku16c.txt` 참조.

| 항목 | 값 |
|------|-----|
| CPU | Intel Xeon Processor (SapphireRapids), x86_64 |
| 코어 | 16 physical (`Thread(s) per core: 1` — **SMT 없음**), 16 vCPU |
| 벡터 확장 | AVX-512 지원 (`avx512f/dq/bw/vl/vbmi2/vnni …`) |
| RAM | 62 GB |
| OS / 툴체인 | Ubuntu 24.04.3 · g++ 13.3 · cmake 3.28.3 · Go 1.24.5 |
| OpenFHE | v1.5.1 소스 빌드 (Release, shared, OpenMP=ON, **NATIVEOPT=OFF, INTEL_HEXL=OFF**) |
| Lattigo | v6.2.0 |
| SEAL | **v4.3.3 (태그 `v4.3.3`, 커밋 `02a5c345`)** 소스 빌드 (Release, shared, **SEAL_USE_INTEL_HEXL=OFF**) |

> HEXL은 공정 비교(같은 빌드 옵션·다른 하드웨어)를 위해 AVX-512 지원 머신에서도 **OFF**로 둔다.
> SEAL도 동일 — 빌드 산출물에서 확인했다(생성 `config.h`에 `SEAL_USE_INTEL_HEXL` 미정의,
> 바이너리에 hexl 심볼·문자열 0건, AVX-512(zmm) 명령 0개).
> SEAL은 `main`이 이미 v4.4.0이므로 **태그 `v4.3.3`으로 핀**해야 검증 사실이 유지된다.
> 소스/설치는 `third_party/SEAL/`(`.gitignore` 대상).
> 이전 baseline은 **epyc4t**(AMD EPYC 7643, 2물리코어×SMT2 = 4스레드), 파일 태그 `_epyc4t`.

## 저장소 구조

2026-08-01 개편. 구 프리셋(v1) 측정 결과는 전부 `archive/v1/` 로 보존했고 코드는 역할별로 나눴다.

```
src/          벤치·정밀도·파라미터 덤프 소스 (C++ / Go / C)
scripts/      측정 드라이버(run_*.sh) · 집계/분석 (aggregate.py, crossing_points.py …)
              respath.py / respath.sh — 결과 CSV 위치 규칙 (읽는 쪽 / 쓰는 쪽)
docs/         PARAMS_dku16c.md · PROJECT_CONTEXT.md · SETUP_DKU16C.md · SEAL_TASK.md · ENV_dku16c.txt
results/      측정 CSV 66 (2026-08-08 분류). 디렉터리마다 README.md 가 채택본/대체본을 밝힌다
  v3/A|B|C|D    확정 4프리셋 본측정 (1t·mt × timing·precision)   ← 채택본
  hexl/arm      HEXL 아암 8-op 전수  ↔  hexl/superseded (heavy 3종, 대체됨)
  baseline_mt_runs/   baseline mt 반복 런 (_off8_)  ↔  superseded/ (_off_, 대체됨)
  v2_discarded/ 폐기된 v2 프리셋 — 대조군으로 보존
explore/      집계 산출 요약 (v3_summary_*, hexl*_summary*) + params/ 파라미터 탐색 덤프 17
  boot_params/  부트스트래핑 1단계 격자 덤프 (OpenFHE·Lattigo 2자, keygen 없음) — README.md 참조
archive/v1/   구 프리셋 측정본 — results/ (CSV 25) · plots/ (PNG 24). **읽기 전용, 논문 근거 자료**
plots/8op/    8-op 집계 산출물(PNG·병합 CSV)  ·  plots/v3/ v3 레벨 차트
루트          README.md · CLAUDE.md · CMakeLists.txt · go.mod/go.sum · calib · build_*/ · third_party/
```

### 결과 CSV 의 위치를 스크립트가 찾는 방법

2026-08-08 개편 전에는 측정 CSV 68개가 전부 루트에 평평하게 쌓였고 스크립트마다 경로가
하드코딩돼 있었다. 지금은 **파일명만 주면 된다** — 탐색·목적지 규칙이 두 파일에 모여 있다.

- 읽는 쪽: `scripts/respath.py` (`find()` / `avail()`). `aggregate.py`·`crossing_points.py`·
  `v3_unify.py`·`v3_gate_table.py`·`v3_hexl*_plots.py`·`ks_precision_table.py` 가 쓴다.
- 쓰는 쪽: `scripts/respath.sh` (`res_out`). `run_main_*.sh`·`run_hexl8.sh`·탐색 드라이버가 쓴다.
- ⚠️ **같은 파일명이 두 곳에 있으면 중단한다.** 새 측정본이 루트에 떨어졌는데 분류본이
  남아 있는 상태를 조용히 통과시키지 않기 위한 것이다. 하나만 남기고 다시 돌릴 것.
- ⚠️ `.gitignore` 의 `results_*.csv` 는 `!results/**/*.csv` 로 이 트리에서만 무효화돼 있다.
  이 예외를 지우면 새 측정본이 **커밋되지 않은 채 조용히 사라진다**.

`calib`(클럭 프로브 바이너리)만 루트에 남는다 — `scripts/run_warm.sh`·`run_monitored.sh`가
`$ROOT/calib` 로 참조한다. 소스는 `src/calib.c`.

### 결과 파일 규칙

**v3 (현행)** — `results_{preset-id}_{timing|precision}_{1t|mt}_{machine}.csv`.
한 파일에 세 라이브러리가 함께 들어가고, P 메타데이터(dnum/PCount/logP/logQP/여유/레벨별 digit)와
`threads`/`nthreads`(런타임 실측)가 열로 붙는다.

| preset-id | logN | depth | Δ |
|---|---:|---:|---:|
| `v3n15d42L12` (A) | 15 | 12 | 42 |
| `v3Bn14d42L6` (B) | 14 | 6 | 42 |
| `v3Cn15d48L10` (C) | 15 | 10 | 48 |
| `v3Dn14d42L4` (D) | 14 | 4 | 42 |

측정본은 `results/v3/{A,B,C,D}/` 에 있다. Lattigo 재실행본(`_run2lattigo`)은 `A/runs/`.

`results_v2n15d40L13_*`는 **폐기된 v2**이나 대조군으로 보존한다(정밀도 20% 하한 미달,
Lattigo 보안 여유 1비트 — `docs/PROJECT_CONTEXT.md §8.1`). 위치는 `results/v2_discarded/`.

⚠️ v3 CSV는 **`aggregate.py`에 넣을 수 없다.** 스키마가 다르고 `preset` 어휘도 v1의
{small,medium,large}가 아니다. `aggregate.py`의 preset 게이트가 거부하는 것은 **의도된 동작**
(v1/v2/v3 혼입 방지)이며, v3 집계는 `scripts/v3_gate_table.py <preset-id>`를 쓴다.

**HEXL 아암 / baseline mt 반복 런** — 프리셋 A 만. `results/hexl/arm/`(8-op 전수, 채택본)와
`results/baseline_mt_runs/`(대등 재측정 `_off8_`). 각각 `superseded/` 에 구 범위판(heavy 3종)이 있다.
⚠️ **프리셋 A 의 mt 를 인용할 때는 `baseline_mt_runs/` 의 중앙값이 정본**이다
(OpenFHE 5런 / SEAL 3런). 자세한 이유는 그 폴더의 `README.md`.

**v1 (아카이브)** — `results_{lib}_{preset}_{1t|mt}_{machine}.csv`, `preset`∈{small,medium,large}.
`archive/v1/results/` 에 25개(본측정 18 + 진단 2 + 병합·요약 4 + 잔여 1).
- `mt` = 멀티스레드: OpenFHE 기본 OpenMP / Lattigo 기본
- `1t` = 싱글스레드: OpenFHE `OMP_NUM_THREADS=1` / Lattigo `GOMAXPROCS=1`
  (Go에는 `OMP_NUM_THREADS`가 무효이므로 반드시 `GOMAXPROCS=1`)
- **Lattigo·SEAL은 단건 연산 내부를 병렬화하지 않아 `mt ≈ 1t`다**(실측 mt/1t = 0.99~1.01).
  실제로 병렬화되는 것은 OpenFHE뿐(mt/1t = 0.80/0.47/0.37).

v1 집계는 스레드 모드별로 분리한다(v1 스키마에는 스레드 컬럼이 없어 한 파일에 합치면 충돌):
`python3 scripts/aggregate.py --lattigo <...> --openfhe <...> --seal <...> --suffix _MODE_dku16c`.
출력은 `plots/8op/` 에 쌓인다. `--seal`도 `--openfhe`와 같은 입력 가드가 걸려 있다.
**v3에는 쓰지 않는다** — 위의 preset 게이트 참조.

## 실행 방법 (v3)

프리셋별 드라이버로 돌린다. 각 실행은 `run_warm.sh`(코어 고정 + 30초 가열 + 전후 프로브)를 거친다.

```bash
./scripts/run_main_v3.sh    # A: 1t (타이밍+정밀도)
./scripts/run_main_bc.sh    # B·C: 1t
./scripts/run_main_D.sh     # D: 1t + mt
./scripts/run_main_mt.sh    # A·B·C: mt
```

임의 프리셋은 `-mainrun "logN:depth:delta:x"`로 돌린다(x = OpenFHE dnum / Lattigo PCount, SEAL은 생략):

```bash
# 1t — 코어 12 단일 고정
OMP_NUM_THREADS=1 PROBE_CORE=12 ./scripts/run_warm.sh 12 1 30 /tmp/pr/of \
  ./build_openfhe/presetsearch_openfhe -mainrun "15:12:42:3" -threads 1t \
  -reps 30 -warmup 3 -precreps 12 -out OUT.csv -precout PREC.csv

# mt — OpenFHE 만 전 코어 + 전 코어 가열. ⚠️ 타이밍과 정밀도를 분리 실행할 것
OMP_NUM_THREADS=16 PROBE_CORE=12 ./scripts/run_warm.sh 0-15 16 30 /tmp/pr/of_mt \
  ./build_openfhe/presetsearch_openfhe -mainrun "15:12:42:3" -threads mt \
  -reps 30 -warmup 3 -precreps 0 -out OUT_mt.csv -precout /dev/null

# mt — Lattigo·SEAL 은 내부 병렬화가 없어 코어 12 단일 고정 유지
GOMAXPROCS=16 PROBE_CORE=12 ./scripts/run_warm.sh 12 1 30 /tmp/pr/la_mt \
  ./presetsearch_lattigo -mainrun "15:12:42:5" -threads mt -reps 30 -warmup 3 -precreps 0 -out OUT_mt.csv

python3 scripts/probe_check.py /tmp/pr/of   # 측정 전/후 클럭이 fast 밴드였는지 확인
```

집계·게이트:

```bash
python3 scripts/v3_gate_table.py v3n15d42L12    # physics_gate + op×level 표 + 교차점 + 정밀도
```

파라미터만 확인할 때는 벤치 없이 격자 덤프를 쓴다(초 단위):

```bash
./build_openfhe/param_dump_openfhe -mode grid -logN 15 -q0 60 \
  -depth-min 9 -depth-max 13 -delta-min 40 -delta-max 60 -logq-min 540 -logq-max 610 -out G.csv
go run src/param_dump_lattigo_grid.go -logN 15 -q0 60 -depth-min 8 -depth-max 11 -pcount-max 5 -out GL.csv
./build_seal/param_dump_seal_grid -logN 15 -q0 60 -depth-min 8 -depth-max 11 -out GS.csv
```

### v1 실행 방법 (이력 — `archive/v1/` 재현용)

구 프리셋(small/medium/large) 측정에 쓰던 절차다. 드라이버·스크립트 모두 그대로 보존한다.

```bash
./scripts/run_all_dku16c.sh   # 3 lib × 3 preset × {1t,mt} = 18 CSV (프리셋마다 자동 커밋)

# 개별 실행 — <고정코어> <가열스레드> <가열초> <프로브경로> -- 실행할 명령
./scripts/run_warm.sh 12 1 30 traces/of ./build_openfhe/openfhe_bench -preset large -reps 30 -out OUT.csv
./scripts/run_warm.sh 12 1 30 traces/la go run src/lattigo_bench.go   -preset large -reps 30 -out OUT.csv
./scripts/run_warm.sh 12 1 30 traces/se ./build_seal/seal_bench -preset large -reps 30 -warmup 3 -warmsec 0 \
                                -machine dku16c -threads 1t -sweep desc -out OUT.csv
python3 scripts/probe_check.py traces/of
```

⚠️ v1 절차에는 `PROBE_CORE`가 없다(1t 전용이라 필요 없었다). mt 재현에는 v3 절차를 쓸 것.

빌드: `cmake -S . -B build_openfhe -DCMAKE_PREFIX_PATH=/data/yja/openfhe-install`,
`cmake -S . -B build_seal -DBENCH_OPENFHE=OFF -DBENCH_SEAL=ON -DCMAKE_PREFIX_PATH=$PWD/third_party/SEAL/install`.

플래그 — **v3** (`presetsearch_*`): `-mainrun "logN:depth:delta:x"`, `-reps N`, `-warmup N`,
`-precreps N`(0이면 정밀도 생략), `-threads {1t|mt}`(기록용 라벨), `-out`, `-precout`.
`-combos "logN:depth:delta:x,..."`는 maxLevel 한 점만 heavy 3종으로 재는 최적 P 탐색 모드다.

**v1** (`openfhe_bench` 등): `-preset {small|medium|large|all}`, `-reps N`, `-warmup N`, `-out PATH`.
`seal_bench`는 추가로 `-sweep {asc|desc}`, `-warmsec N`(래퍼로 가열하므로 본측정은 **0**),
`-machine`, `-threads`를 받는다.

## 프리셋

### v1 프리셋 (아카이브 — `archive/v1/`)

⚠️ **logQP를 통제하지 않아 `large`에서 OpenFHE가 128비트에 미달한다**(logQP 1035 > 상한 881).
v3로 대체됐으며 근거는 `docs/PROJECT_CONTEXT.md §8.1`.

| preset | logN | ring dim | maxLevel | scale bits |
|--------|------|----------|----------|------------|
| small  | 13   | 8192     | 5        | 45         |
| medium | 14   | 16384    | 10       | 45         |
| large  | 15   | 32768    | 15       | 45         |

### v3 프리셋 (현행) — `q0 = 60` 공통

| preset | logN | ring dim | maxLevel | Δ | logQ | tc128 상한 | OpenFHE logP/여유 | Lattigo logP/여유 | SEAL logP/여유 |
|--------|-----:|---------:|---------:|---:|-----:|-----:|---:|---:|---:|
| **A** | 15 | 32768 | 12 | 42 | 564 | 881 | 240 / +77 | 300 / +17 | 60 / +257 |
| **B** | 14 | 16384 | 6 | 42 | 312 | 438 | 120 / **+6** | 120 / **+6** | 60 / +66 |
| **C** | 15 | 32768 | 10 | 48 | 540 | 881 | 300 / +41 | 240 / +101 | 60 / +281 |
| **D** | 14 | 16384 | 4 | 42 | 228 | 438 | 180 / +30 | 180 / +30 | 60 / +150 |

축: **A↔B** 링 차원(Δ 42 동일), **B↔D** 깊이(Δ 42 동일), **A↔C** 깊이(⚠️ Δ 42 vs 48 교란).
Q 체인만 통일하고 **P는 라이브러리별 최적을 쓴다** — "동일 P 비교"가 아니라
"각자 최적 조건에서의 비교"다. 파라미터 정본은 `docs/PARAMS_dku16c.md §8`.

각 프리셋에서 level = maxLevel..1 전수 스윕, 8개 op × warmup 3 + 30회 측정, μs 단위 평균/표본표준편차(n-1).
정밀도(rot1, 비밀키)는 레벨 전수 12회. **판정은 평균이 아니라 최소값 ≥25비트**다.

## op 목록

`add_cc`(ct+ct), `add_cp`(ct+pt), `mul_cp`(ct×pt), `mul_cc`(ct×ct relin 없음, degree-2),
`mul_cc_rlk`(ct×ct relin 포함), `relin`(재선형화 단독 — **직접 계측**),
`rescale`(모듈러스 1개 drop), `rot1`(+1 슬롯 회전).

`relin`은 size-3(degree-2) 암호문을 타이머 밖에서 1회 만들어 두고 out-of-place
relinearize를 반복 측정한다 — 세 라이브러리 모두 같은 방식이다.

> **2026-07-26 변경.** 그 전에는 `relin = mul_cc_rlk − mul_cc`(음수 0 clamp) 파생값이었고
> OpenFHE·Lattigo만 그랬다(SEAL은 처음부터 직접 계측). 파생 방식은 두 가지가 문제였다 —
> ⑴ `EvalMult`가 곱셈+relin을 실제로 융합하는 OpenFHE에서 relin을 **4.4% 과소평가**했고
> (같은 실행에서 직접/파생 = OpenFHE **1.044**, Lattigo 1.001, SEAL 1.006),
> ⑵ 두 평균의 차라서 분산이 없어 **전 행 `std_us=0`** 이었다.
> 근거와 상세는 `docs/PARAMS_dku16c.md §6`. `archive/v1/` 의 CSV는 전환 후 재측정본이다.

## 측정 프로토콜 (dku16c 필수)

이 머신은 **코어 단위 DVFS**가 있다 — 유휴 코어는 base(2.2 GHz)로 떨어지고 부하 후 약 6.7초에
turbo(3.7 GHz)에 도달하며 유휴 약 1초면 base로 되돌아간다(**비 1.675**). 스윕이 maxLevel에서
시작하므로 콜드 상태로 시작하면 **높은 레벨만 선택적으로 부풀려져 레벨-지연 기울기가 가짜로
가팔라진다.** 실제로 이 편향이 이전 12개 CSV를 오염시켰다(최대 3.02배, 파일마다 오염 구간이 달랐다).

- **대책: 코어 고정 + 사전 가열.** `scripts/run_warm.sh`가 `taskset`으로 핀한 셸 안에서 30초 가열한 뒤
  **`exec`으로 벤치 바이너리로 전환**한다. 새 프로세스를 띄우면 그 틈에 base로 떨어지므로 exec이 필수다.
- **채택/기각 장치는 쓰지 않는다.** 전용 코어의 모니터는 측정 프로세스가 올라간 코어의 상태를
  원리적으로 알 수 없고(오염된 실행을 통과시킨 사례 확인), mt에서는 코어를 뺏어 OpenFHE의 OMP
  조건을 깨뜨린다(rot1/relin 4.3~5.2배 왜곡). 대신 측정 **직전/직후에만** 캘리브레이션 프로브를
  1회씩 재어 기록한다(`scripts/probe_check.py`). 18개 실행 × 전후 36개 프로브 전부 fast 밴드(82.5~82.9 ms)였다.
- 고정 코어: 단일스레드 실행은 **코어 12**, OpenFHE mt만 **전 코어(0–15) 고정 + 전 코어 가열**.
- 수용 검사 통과 기준(asc/desc 방향 편향): small 0.62% · medium 0.55%, 상/하 비 1.00±0.01.

### mt 측정 프로토콜 (v3)

이 축은 **"단건 연산 내부 병렬화가 있는 라이브러리가 얼마나 이득을 보는가"** 이며,
실질적으로 **OpenFHE만 참여한다**. Lattigo·SEAL의 `mt/1t ≈ 1`은 성능 열위가 아니라
**설계상 이 축 밖**이라는 뜻이다. 독립 암호문을 코어에 분배하는 애플리케이션 수준
병렬화는 별개 축이며 여기서 측정하지 않는다.

| lib | 스레드 설정 | 코어 고정 | op 내부 병렬화 |
|---|---|---|---|
| OpenFHE | `OMP_NUM_THREADS=16` | **0–15 전체 + 16스레드 가열** | 있음 |
| Lattigo | `GOMAXPROCS=16` | 코어 12 단일 | 없음 |
| SEAL | — | 코어 12 단일 | 없음 |

- **프로브는 `PROBE_CORE=12`로 고정한다.** 전 코어 집합에 풀어두면 `calib`이 유휴 코어로
  이주해 base 클럭(138ms)을 기록한다 — 측정 오염이 아니라 프로브의 아티팩트다.
- **타이밍과 정밀도를 분리 실행한다.** 한 프로세스에서 정밀도가 뒤에 오면 그 구간이
  대부분 직렬이라 post 프로브가 식은 구간을 잰다.
- **mt physics_gate는 `relin − mul_cc_rlk > 3σ`** 기준이다(1t의 비 1.02가 아니다).
  레벨 단조성은 mt에서 게이트로 쓰지 않고 건수만 보고한다.
- ⚠️ **Lattigo 경량 op(`add_cc`/`add_cp`/`mul_cp`/`mul_cc`)는 Go GC 때문에 이 프로토콜에서
  안정적으로 측정되지 않는다** — 재현성 편차가 안정군의 10배다. 단조성 판정에서 제외한다.

상세는 `docs/PROJECT_CONTEXT.md §8.6`.

## ⚠️ 측정 주의 (공정성)

- **파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아니다.** 링차원을 강제하기 위해
  OpenFHE는 `HEStd_NotSet`, SEAL은 `sec_level_type::none`을 쓴다.
  **⚠️ 프리셋마다 비대칭이므로 뭉뚱그리지 말 것** — 실효 보안은 `logQ`가 아니라 **`logQP`**로
  판정해야 한다(하이브리드 key-switch의 평가키는 QP 위에 정의된다):

  | preset | N | tc128 상한 | OpenFHE | Lattigo | SEAL |
  |--------|---|-----------:|--------:|--------:|-----:|
  | small  | 8192  | 218 | 395 ✗ | 330 ✗ | 335 ✗ |
  | medium | 16384 | 438 | 745 ✗ | 615 ✗ | 565 ✗ |
  | large  | 32768 | 881 | **1035 ✗** | 855 ✓ | 795 ✓ |

  - small·medium은 `logQ` 자체가 상한을 넘어(275>218, 505>438) **세 라이브러리 모두 128비트가 아니다.**
  - **large는 Lattigo·SEAL만 상한 이내이고 OpenFHE는 초과한다.** `logQ`(735)만 보면 셋 다
    이내로 보이므로 logQ로 판정하면 놓친다.
  - **세 프리셋 모두 OpenFHE가 상한에서 가장 멀다** — 같은 Q 위에 가장 큰 P를 얹기 때문이다.
    (여유 순서는 medium·large가 OpenFHE < Lattigo < SEAL, small은 Lattigo가 SEAL보다 5비트 앞선다.)
  - 즉 **Q는 비트 단위로 맞췄으나 보안 수준까지 정합되지는 않았다.** 3자 비교는 "동일 Q 체인
    위의 비교"이지 "동일 보안 수준에서의 비교"가 아니다. 자세한 근거는 `docs/PARAMS_dku16c.md`.
- **SEAL의 특수소수는 자동 결정되지 않아 60비트 1개로 명시 고정**했다(SEAL 관례상 최대 프라임 크기).
  위 logQP 차이의 직접 원인이므로 발표 각주에 반드시 명시할 것.
- **key-switch 계열은 "동일 조건"이 아니라 "비교 가능"이다.** P와 digit 분해 구조가 셋 다 다르다.
  digit 수는 세 라이브러리 모두 레벨의 함수이며 증가 기울기가 다르다(SEAL 1.00 / Lattigo 0.50 /
  OpenFHE 0.17~0.50, 3에서 포화). `docs/PARAMS_dku16c.md` 참조.
- **스레딩 비대칭:** 실제로 단건 연산을 병렬화하는 것은 **OpenFHE뿐**이다(mt/1t = 0.80/0.47/0.37).
  Lattigo·SEAL은 내부 병렬화가 없어 `mt ≈ 1t`(0.99~1.01).
  ⚠️ mt에서 OpenFHE만 분산이 크다 — key-switch 계열 CV 중앙값이 1t 0.004~0.008 대비
  **mt 0.18~0.52(최대 1.23)**. OMP 스케줄링 지터이므로 **에러바 크기가 다른 계열을 같은 근거로
  쓰지 말 것.** 레벨 대비 기울기 분석은 전부 1t로만 수행했다.
- 최적화 빌드에서만 측정 (Go 기본 / C++ `-O3 -DNDEBUG`). 타이밍은 연산 1회만 감싼다.
- 측정 전 반드시 `scripts/run_warm.sh`를 거칠 것 — 위 "측정 프로토콜" 참조.

<sup>주) SEAL `large`의 최상위 레벨 `add_cc`/`add_cp`는 추세 대비 1.3~1.5배 높다. 세 피연산자
작업 세트가 약 23~24 MB를 넘는 지점과 일치하며, 버퍼 정렬·2의 거듭제곱 크기와는 무관함을
확인했다(비2^n 크기에서도 동일, 정렬 교란으로 회수되지 않음). 다만 이 게스트에는 가상 PMU가
없어 `perf`로 LLC-miss를 확인하지 못했으므로 **기제는 단정하지 않는다.** 무거운 op에는 영향이
미미하여 3자 비교 결론에는 영향이 없다.</sup>
