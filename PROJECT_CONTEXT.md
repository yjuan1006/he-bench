# PROJECT_CONTEXT.md — HE Library Benchmark 공유 컨텍스트

이 문서는 Claude.ai 프로젝트 지식에만 있던 큰 그림·규칙을 **저장소에 두어 Claude Code와
양쪽에서 공유**하기 위한 것이다. 측정 API 사실은 `CLAUDE.md`, 환경 구축 절차는
`SETUP_DKU16C.md`, 실행/프리셋 표는 `README.md`를 참조한다 — 여기서는 **큰 그림과 규칙**
위주로 쓰고, 세부는 중복하지 않고 참조로 넘긴다.

---

## 1. 프로젝트 개요

- **OpenFHE(C++) vs Lattigo(Go) vs Microsoft SEAL(C++)** 의 CKKS 연산
  **암호문 1개 기준 지연시간(latency)** 3자 비교.
- 측정 연산 **8종**: `add_cc`, `add_cp`, `mul_cp`, `mul_cc`, `mul_cc_rlk`, `relin`,
  `rescale`, `rot1`. (정의는 `CLAUDE.md`/`README.md`의 op 목록 참조.)
- 프리셋 3종: `small`/`medium`/`large` = **logN 13/14/15**, **maxLevel 5/10/15**,
  scale 45 bit. 각 프리셋에서 `level = maxLevel..1` 전수 스윕.
- 각 op **reps 30, warmup 3**, 두 스레드 조건(`1t`/`mt`)에서 측정.
- 산출: 라이브러리별 CSV → 병합 → 요약표 + 티어 그래프(`plots/8op/`).

## 2. 실행 환경

### 현재 = `dku16c` (파일 태그 `_dku16c`)

| 항목 | 값 |
|------|-----|
| CPU | Intel Xeon (SapphireRapids), **물리 16코어, SMT 없음** (`Thread(s) per core: 1`) |
| RAM / 벡터 | 62 GB · **AVX-512 지원** |
| 경로 / 브랜치 | `/data/yja/he-bench` · `third-lib` |
| 툴체인 | Go 1.24.5 (`~/.local/go`) · OpenFHE **v1.5.1** · Lattigo **v6.2.0** · SEAL **v4.3.3**(커밋 `02a5c345`) |
| OpenFHE 빌드 | Release/shared/OpenMP=ON, **HEXL OFF · NATIVEOPT OFF** (baseline) |
| SEAL 빌드 | Release/shared, **SEAL_USE_INTEL_HEXL=OFF** (산출물에서 확인). 설치 `third_party/SEAL/` |

> SMT가 없어 16코어 = 16 독립 물리 스레드 → 코어 스윕(1→2→4→8→16)이 깨끗하다.
> **다만 이번 측정은 `1t`/`mt` 두 조건만 수행 — 스윕은 확장 여지로 남김.**
> HEXL은 **OFF 유지** — epyc4t(Zen 3, AVX-512 없음)와 빌드 조건을 맞추기 위함
> (같은 빌드 옵션 · 다른 하드웨어). 대가로 **OpenFHE 절대 지연시간은 최적 빌드 대비 보수적**이다.
> HEXL 실험을 하려면 파일명에 `_hexl`을 붙여 분리하고 baseline과 섞지 말 것. 근거 `SETUP_DKU16C.md §1`.
> 환경 스냅샷은 `ENV_dku16c.txt`.

### 이전 = `epyc4t` (파일 태그 `_epyc4t`) — 지우지 말 것

| 항목 | 값 |
|------|-----|
| CPU | AMD EPYC 7643, **4 스레드 (물리 2 × SMT2)** |
| RAM | 31 GB |
| 빌드 조건 | OpenFHE HEXL OFF / NATIVEOPT OFF (dku16c와 동일 옵션) |

기존 8-op·부트스트래핑 결과는 이 환경 측정값이며 `bootstrap-bench` 브랜치에 보존.
**두 하드웨어 결과를 나중에 비교할 수 있어야 하므로** epyc4t 값을 덮어쓰지 않고 머신 태그로 구분한다.

## 3. 정합 기준 (세 라이브러리를 어떻게 "공정"하게 맞추는가)

> 수치 정본은 **`PARAMS_dku16c.md`** — 전부 런타임 API 추출값이다. 아래는 요약과 해석.

- **Q 모듈러스 체인을 비트 단위로 일치**시킨다 — 이 실험의 **최대 강점**.
  실측 확인: logQ = **275 / 505 / 735** 로 세 라이브러리 완전 일치.
- **P(특수 소수)는 각 라이브러리가 자동으로 정한다**(SEAL만 우리가 60비트 1개로 명시 고정).
  따라서 이에 의존하는 `relin`/`rot1`(key-switch 계열)은 **"동일"이 아니라 "비교 가능"**이다.
- **digit(분해) 수는 세 라이브러리 모두 레벨의 함수다.** 차이는 **증가 기울기**다:
  **SEAL 1.00 / Lattigo 0.50(small은 1.00) / OpenFHE 0.17~0.50**.
  - ⚠️ 과거 문서의 "OpenFHE dnum 3 고정, Lattigo 6~8"은 **틀린 서술이었다.**
    `numPartQ=3`은 **최상위 레벨의 상한**이지 고정값이 아니다 — OpenFHE large의
    실제 digit 수열은 `3,3,3,3,2,2,2,2,2,2,1,1,1,1,1`로 3에서 포화되는 계단이다.
    Lattigo의 6~8도 maxLevel에서의 값일 뿐이다.
  - **SEAL의 digit이 OpenFHE보다 적은 레벨은 존재하지 않는다.** SEAL이 낮은 레벨에서
    빠른 것은 digit이 적어서가 아니라, **OpenFHE가 레벨과 무관하게 고정 크기 P를 항상
    운반**하여(특수소수 2/4/5개 = logP 120/240/300) 타워가 적은 낮은 레벨에서 그 고정
    비용의 비중이 지배적이 되기 때문이다. SEAL은 어느 레벨에서나 60비트 1개다.
  - **`logP=120`은 small 전용 값이다.** OpenFHE logP는 프리셋마다 다르다(120/240/300).
- **⚠️ 정합의 한계 — Q는 맞췄으나 보안 수준은 맞춰지지 않는다.**
  하이브리드 key-switch에서 평가키는 Q가 아니라 **QP 위에 정의**되므로 실효 보안을
  결정하는 것은 `logQ`가 아니라 **`logQP`**다. logQP는 세 라이브러리가 전부 다르다.
  - `large`에서 **OpenFHE만 tc128 상한을 초과**한다(logQP 1035 > 881). Lattigo 855·SEAL 795는 이내.
    `logQ`(735)만 보면 셋 다 이내로 보이므로 **logQ로 판정하면 이 사실을 놓친다.**
  - **세 프리셋 모두 OpenFHE가 상한에서 가장 멀다** — 같은 Q 위에 가장 큰 P를 얹기 때문.
  - 따라서 3자 비교는 **"동일 Q 체인 위의 비교"이지 "동일 보안 수준에서의 비교"가 아니다.**
    key-switch에서 P가 작은 쪽이 유리한데 그 유리함의 일부는 **보안 여유를 덜 확보한 대가**다.
    발표에서 이 교환관계를 함께 제시할 것.
- 링 차원은 **`HEStd_NotSet`(OpenFHE) / `sec_level_type::none`(SEAL)으로 강제**한다(logN 고정).
  **128-bit 보안 미검증**이며 상대 비교 목적의 의도된 한계다. 단 프리셋별로 비대칭이므로
  뭉뚱그리지 말 것 — small/medium은 `logQ` 자체가 이미 상한 초과(275>218, 505>438)라
  P와 무관하게 셋 다 128비트가 아니고, `large`는 **Lattigo·SEAL만** 상한 이내다.

## 4. 측정 규칙 (반드시 지킬 것)

- **타이머: C++는 `std::chrono::steady_clock`.** `high_resolution_clock`은 구현에 따라
  `system_clock`의 별칭이라 NTP 보정 시 **시계가 역행**할 수 있다 → 단조 증가 보장되는
  `steady_clock`만 사용. Go는 `time.Now()`(단조 시계 포함).
- **레벨 표기는 Lattigo 기준 "잔여 곱셈 예산"으로 통일.** OpenFHE는 `maxLevel - GetLevel()`로
  변환해 정렬을 맞춘다.
- **통계: 평균 + 표본표준편차(n-1), 단위 μs(float).** ns로 재서 μs로 환산.
- 타이밍은 **연산 1회만** 감싼다(키 생성·인코딩·출력 할당은 밖으로).
  입력 암호문 재사용은 **해당 연산이 out-of-place인 경우에만** 허용 —
  **새 라이브러리 추가 시 in-place 여부를 먼저 확인할 것.**
  in-place 연산에 재사용을 적용하면 입력이 오염된 채로 반복되며,
  에러 없이 조용히 틀린 값을 측정하게 된다.
- **스레드 제어:** OpenFHE = `OMP_NUM_THREADS`, Lattigo = `GOMAXPROCS`, SEAL = 해당 없음.
  ⚠️ **`OMP_NUM_THREADS`는 Go에 무효**(실측 확인). Lattigo `1t`는 반드시 `GOMAXPROCS=1`.
  **Lattigo·SEAL은 단건 연산 내부를 병렬화하지 않아 `mt ≈ 1t`**(실측 mt/1t = 0.99~1.01).
  실제로 병렬화되는 것은 OpenFHE뿐(mt/1t = 0.80/0.47/0.37).
  ⚠️ mt에서 OpenFHE만 분산이 크다(key-switch CV 중앙값 1t 0.004~0.008 vs **mt 0.18~0.52**).
  에러바 크기가 다른 계열을 같은 근거로 쓰지 말 것 — 레벨 기울기 분석은 1t로만 한다.
- **모든 op는 직접 계측한다. 파생값(다른 op의 차)으로 비용을 산출하지 마라** —
  분산 정보가 사라지고(std=0), 융합 구현이 있는 라이브러리에서는 평균 자체가
  독립 연산의 비용과 다른 양이 된다. **`relin`에서 실제로 발생했고 라이브러리 간
  계측 방식 불일치를 낳았다(2026-07-26 발견·수정).** lattigo·openfhe는
  `relin = mul_cc_rlk − mul_cc`, std=0으로 기록하고 있었고 SEAL만 직접 계측이었다.
  ⚠️ 반복별 개별 계측이 원칙이다. 총시간÷반복수나 파생값은 모두 std_us=0으로
  나타나므로, **새 하네스를 추가하면 전 op의 std_us>0을 먼저 확인할 것.**
- **파일명:** `results_{lib}_{preset}_{1t|mt}_{machine}.csv`.
- **⚠️ dku16c는 코어 고정 + 사전 가열이 필수다.** 코어 단위 DVFS(base 2.2GHz ↔ turbo 3.7GHz,
  비 1.675, 유휴 ~1초면 base 복귀)로 콜드 시작 시 높은 레벨만 부풀려진다.
  반드시 `run_warm.sh`(핀한 셸에서 가열 후 `exec` 전환)를 거칠 것. 절차·근거는 README 「측정 프로토콜」.

## 5. 검증 절차 (이전 작업에서 얻은 교훈)

1. **정확성 검증 필수** — 지연시간만 재면 *틀린 계산의 소요 시간*을 재고도 모른다.
   OpenFHE가 예외 없이 무의미한 값(정밀도 음수)을 반환하면서 정상적인 지연시간과
   정상적인 정성 패턴을 보인 이력이 있다.
   - **정성 검증**: 소규모(`-reps 5`)로 레벨↓ 빨라짐, relin/rot ≫ mul ≫ add 확인
   - **정밀도 검증**: 알려진 값 암호화 → 연산 → 복호화 → 원본과 오차 비교.
     `-log2(mean|err|)`로 비트 수 산출.
   - ⚠️ **정성 검증만으로는 파탄을 못 잡는다** — 둘 다 해야 한다.
   - 라이브러리 문서에 기준 정밀도가 있으면 재현 확인
     (Lattigo는 문서값 29.8비트를 실측 29.75비트로 재현하여 하네스 정상 확인)
2. **파라미터 파탄 시 이등분 격리(bisection)** 로 원인 특정 — 프리셋/레벨/op/스레드/빌드옵션 중
   무엇이 원인인지 반씩 잘라 좁힌다. 추측 대신 실제 메시지·수치.
3. **aggregate 게이트** — 스키마 게이트(필수 컬럼·허용 preset/op)·**접미사 가드**·증분 CSV 기록.
   스키마 안 맞는 파일이 섞이면 필터에서 NaN으로 빠져도 combined CSV엔 남는 "조용한 오염"을 막는다.
4. **렌더 결과는 반드시 직접 열어볼 것** — **정상 종료 ≠ 그림 정상.** 축·범례·티어 그룹핑을
   눈으로 확인하고, 하드웨어 비교 시 이전 PNG와 나란히 대조.
5. **긴 측정은 커밋 후 진행** — 산출물(`results_*.csv`, `plot_*.png`)은 `.gitignore` 대상이라
   `git add -f`로 명시 추가. **커밋 누락으로 PNG 12장을 소실한 이력**이 있으니 재측정 후 즉시 커밋.

## 6. 현재 상태와 다음 단계

- [x] ~~8-op dku16c 2자 측정(12 CSV)~~ — **폐기.** 코어 단위 DVFS 오염이 확인되어
  (최대 3.02배, 파일마다 오염 구간 상이) 아래 3자 재측정본으로 대체했다. 근거는 README 측정 프로토콜.
- [x] 티어 그룹핑(light/mid/heavy) `aggregate.py` 복원(이식) 및 커밋.
- [x] **세 번째 라이브러리(Microsoft SEAL) 추가 완료 — 8-op 3자 비교 성립.**
  - **18 CSV**(3프리셋 × {1t,mt} × 3 lib) + `plots/8op/` 24 PNG + 병합/요약 CSV 4.
  - 파라미터 정본: **`PARAMS_dku16c.md`**(런타임 추출).
  - 부트스트래핑 확장은 `bootstrap-bench` 브랜치에 2자로 보존(단위·의미가 8-op과 달라 별도 집계).
    **SEAL CKKS에는 부트스트래핑이 없다** — 3자로 확장 불가.

### 세 번째 라이브러리 선정 근거와 SEAL 확정 사항

- **선정 기준: Q 모듈러스 체인을 비트 단위로 지정 가능한가**(§3 정합 기준을 만족해야 3자 비교가 성립).
  SEAL은 `CoeffModulus::Create(N, {비트 리스트})`로 직접 지정 가능 → 기준 충족, logQ 275/505/735 일치 확인.
- **버전 고정: SEAL v4.3.3 (태그 `v4.3.3`, 커밋 `02a5c345`).**
  `main` HEAD는 이미 v4.4.0이라 그대로 clone하면 사전 검증 사실이 무효가 된다 → 태그로 핀할 것.
- **빌드: `SEAL_USE_INTEL_HEXL=OFF` 필수**(§2와 동일 근거). 산출물에서 확인 — 생성된
  `config.h`에 `SEAL_USE_INTEL_HEXL` 미정의, 바이너리에 hexl 심볼·문자열 0건, AVX-512(zmm) 명령 0개.
  설치 경로는 `third_party/SEAL/`(`.gitignore` 대상).
- **`sec_level_type::none` 사용**(OpenFHE `HEStd_NotSet`과 동일 성격). small/medium은 `tc128`에서
  거부되고, `large`는 SEAL 기준 `tc128`을 통과한다(logQP 795 ≤ 881). §3의 보안 비대칭 참조.
- **특수소수는 자동 결정되지 않아 60비트 1개로 명시 고정**했다 — SEAL 관례상 최대 프라임 크기.
  이 선택은 README와 발표자료 각주에 반드시 명시할 것(§3의 logQP 불일치 원인).
- 레벨 표기: SEAL `chain_index()`가 잔여 곱셈 예산과 1:1이라 OpenFHE식 `maxLevel - GetLevel()`
  변환이 **불필요**하다.

### 미채택 후보 (재조사 방지용 보존)

- **HEaaN2 v0.2.0**: `paramsUtils::LevelsBuilder`로 비트 단위 지정 가능
  (`initMod(bits)` + `buildAbove(num_mults, bits)`). 우리 체인 매핑:
  - small: `initMod(50); buildAbove(5,45)` / medium: `initMod(55); buildAbove(10,45)` /
    large: `initMod(60); buildAbove(15,45)`
  - ⚠️ 미확인: `setRing(log_degree)`가 13/14/15를 받는지 (기본 프리셋은 전부 logN 16).
  - ⚠️ devkit이 dku16c에 **없음** — 별도 확보 필요, 라이선스 확인 필요. 이 때문에 SEAL을 우선했다.
