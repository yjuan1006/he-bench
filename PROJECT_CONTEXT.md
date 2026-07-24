# PROJECT_CONTEXT.md — HE Library Benchmark 공유 컨텍스트

이 문서는 Claude.ai 프로젝트 지식에만 있던 큰 그림·규칙을 **저장소에 두어 Claude Code와
양쪽에서 공유**하기 위한 것이다. 측정 API 사실은 `CLAUDE.md`, 환경 구축 절차는
`SETUP_DKU16C.md`, 실행/프리셋 표는 `README.md`를 참조한다 — 여기서는 **큰 그림과 규칙**
위주로 쓰고, 세부는 중복하지 않고 참조로 넘긴다.

---

## 1. 프로젝트 개요

- **OpenFHE(C++) vs Lattigo(Go)** 의 CKKS 연산 **암호문 1개 기준 지연시간(latency)** 비교.
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
| 툴체인 | Go 1.24.5 (`~/.local/go`) · OpenFHE **v1.5.1** · Lattigo **v6.2.0** |
| OpenFHE 빌드 | Release/shared/OpenMP=ON, **HEXL OFF · NATIVEOPT OFF** (baseline) |

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

## 3. 정합 기준 (두 라이브러리를 어떻게 "공정"하게 맞추는가)

- **Q 모듈러스 체인을 비트 단위로 일치**시킨다 — 이 실험의 **최대 강점**. 두 라이브러리가 같은
  Q 체인 위에서 도는지가 비교의 전제다.
- **P(특수 소수)·dnum은 각 라이브러리가 자동으로 정한다.** 따라서 이에 의존하는
  `relin`/`rot1`(key-switch 계열)은 **"동일"이 아니라 "비교 가능"**으로 표현한다 —
  키스위칭 내부 분해 방식이 달라 완전 동일 조건이 아님을 명시.
- 링 차원은 **`HEStd_NotSet`으로 강제**한다(logN 고정). 이 때문에 **128-bit 보안은 보장되지
  않으며(보안 미검증), 상대 비교 목적의 의도된 한계**다. README/코드에 명시.

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
- **스레드 제어:** OpenFHE = `OMP_NUM_THREADS`, Lattigo = `GOMAXPROCS`.
  ⚠️ **`OMP_NUM_THREADS`는 Go에 무효**(실측 확인). Lattigo `1t`는 반드시 `GOMAXPROCS=1`.
  Lattigo는 단건 연산 내부를 병렬화하지 않아 `mt ≈ 1t`.
- **파일명:** `results_{lib}_{preset}_{1t|mt}_{machine}.csv`.

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

- [x] **8-op dku16c 재측정 완료** — 12 CSV(3프리셋 × {1t,mt} × 2 lib) + `plots/8op/` 24 PNG + 병합 CSV 4.
- [x] 티어 그룹핑(light/mid/heavy) `aggregate.py` 복원(이식) 및 커밋.
- [ ] **세 번째 라이브러리 추가 후 8-op 3자 비교.**
  - 부트스트래핑 확장은 `bootstrap-bench` 브랜치에 보존(단위·의미가 8-op과 달라 별도 집계).
  - **세 번째 라이브러리 선정 기준: Q 모듈러스 체인을 비트 단위로 지정 가능한가**
    (§3 정합 기준을 만족해야 3자 비교가 성립).

### 후보 조사 결과

다음 세션에서 다시 조사하지 않도록 남긴다.

- **HEaaN2 v0.2.0**: `paramsUtils::LevelsBuilder`로 비트 단위 지정 가능
  (`initMod(bits)` + `buildAbove(num_mults, bits)`). 우리 체인 매핑:
  - small: `initMod(50); buildAbove(5,45)`
  - medium: `initMod(55); buildAbove(10,45)`
  - large: `initMod(60); buildAbove(15,45)`
  - ⚠️ 미확인: `setRing(log_degree)`가 13/14/15를 받는지 (기본 프리셋은 전부 logN 16).
  - ⚠️ devkit이 dku16c에 **없음** — 별도 확보 필요, 라이선스 확인 필요.
- **SEAL**: `CoeffModulus::Create`로 비트 크기 직접 지정 확실히 가능. 소스 빌드 필요.
