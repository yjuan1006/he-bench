# 작업 지시: CKKS 부트스트래핑 벤치마크 추가

## 배경

이 저장소는 OpenFHE vs Lattigo의 CKKS 연산 지연시간을 비교하는 벤치마크다.
기존 코드(`lattigo_bench.go`, `openfhe_bench.cpp`)는 8종 연산(add_cc, add_cp, mul_cp,
mul_cc, mul_cc_rlk, relin, rescale, rot1)을 프리셋(small/medium/large) × 레벨 전수로
측정한다. 저장소의 `CLAUDE.md`와 기존 두 벤치 소스를 먼저 읽을 것.

### 실행 환경

| 항목 | 값 |
|---|---|
| CPU | AMD EPYC 7643 — **4 vCPU 할당** (물리 2코어×2스레드) |
| 메모리 | **31 GiB** |
| Lattigo | v6.2.0 (Go 1.24.5) |
| OpenFHE | v1.5.1 (소스 빌드, Release + OpenMP) |

### 기존 실험에서 이미 확인된 사실 (배경 지식)

- 연산 비용 계층: 덧셈 < 곱셈 < **key-switch(relin·회전)**, 최대 100~150배 차이
- 모든 연산이 레벨↑일수록 느려짐 (limb/tower 개수 = 처리량)
- OpenFHE는 OpenMP 멀티코어, Lattigo는 단건 연산 내부 병렬이 설계상 없음
  → 두 조건(기본 mt / `OMP_NUM_THREADS=1`)으로 각각 측정해왔음
- 보안 미검증: 링 차원을 맞추려 `HEStd_NotSet`으로 보안 자동조정을 끔 (의도된 한계)

이번에 부트스트래핑 측정을 추가한다. 기존 루프에 op를 하나 더 넣는 방식이 **아니라**,
별도 프리셋 + 별도 실행파일 + 별도 CSV로 분리한다. 이유:

- 부트스트래핑은 연산 자체가 곱셈 깊이 15 내외를 소모 → 기존 프리셋(depth 5~15)으로 불가
- 측정 1회가 초 단위 → reps=30이 비현실적
- 입력이 항상 최하위 레벨 → 레벨 스윕이 무의미

---

## 이미 확정된 설계 결정 (바꾸지 말 것)

이 세 가지는 검토를 거쳐 확정됐다. 구현 중 편의를 이유로 변경하지 말고,
기술적으로 불가능하다면 진행 대신 보고할 것.

1. **비밀키 분포는 조밀(dense) 정합**
   OpenFHE `UNIFORM_TERNARY` ↔ Lattigo `ring.Ternary{H: 32768}` (= N/2).
   각자 기본값을 쓰면 Lattigo가 희소키(H=192)라 부당하게 유리해진다.

2. **Lattigo 검증 프리셋을 기준선으로 삼고 OpenFHE를 맞춘다**
   기준: Lattigo 공식 `N16QP1788H32768H32` (정밀도·실패확률이 문서화된 검증 파라미터).

3. **측정 범위**: 부트스트래핑 총 지연시간 / 키 생성 시간·크기·피크 메모리 /
   레벨당 정규화 지표. 단계별 분해(C2S·EvalMod·S2C)는 이번 범위에서 **제외**.

---

## 프리셋 `boot16` 사양

> **갱신 이력**: 아래 표는 구현·실측 후 확정된 *실제* 설정이다.
> 최초 사양에서 두 곳이 바뀌었고, 근거는 각각 아래 「사양에서 바뀐 것」에 적었다.

| 항목 | Lattigo | OpenFHE | 비고 |
|---|---|---|---|
| logN | 16 (ringDim 65536) | 16 (ringDim 65536) | 일치 |
| numSlots | 32768 (= ringDim/2) | 32768 (= ringDim/2) | 일치 |
| in_level → out_level | 1 → 9 | 1 → 9 | 일치 (실측) |
| levelBudget {C2S, S2C} | {4, 3} | {4, 3} | 일치 |
| 비밀키 | `ring.Ternary{H: 32768}` | `UNIFORM_TERNARY` | **엄밀히는 불일치** (아래 주 참조) |
| **scale** | **2^45** | **2^59** | **비대칭 — 아래 참조** |
| firstMod | 60 (LogQ[0]) | 60 | 일치 |
| 스케일링 기법 | (내부 자동) | `FLEXIBLEAUTO` | 대응 모드 |
| `-levels` (OpenFHE) | — | 8 | out_level 정합용 |

### 두 지표를 구분할 것

| 지표 | Lattigo | OpenFHE | 성격 |
|---|---|---|---|
| **logQP** | 1788 (bootstrapping)<br>770 (residual) | 2371 | **보안 지표.** 링차원 대비 모듈러스 크기가 보안 수준을 결정한다. 양쪽을 맞출 수 없고 맞춰서도 안 된다(함정 5). |
| **limb(tower) 개수** | Q=28 P=5 **QP=33**<br>(residual Q=10 P=5) | Q=30 P=10 **QP=40** | **작업량 지표.** NTT 호출 횟수가 limb 수에 비례하므로 실제 계산량은 이 값이 대변한다. logQP 격차(583비트)보다 limb 격차(33 vs 40, 21%)가 지연시간 차이를 훨씬 잘 설명한다. |

logQP만 보면 OpenFHE가 33% 더 큰 모듈러스를 쓰는 것처럼 보이지만, 작업량 관점에서는 limb 21% 차이가 실제 부담이다. **발표·각주에서 두 지표를 섞어 쓰지 말 것.**

### 사양에서 바뀐 것 (실측 근거)

**1. OpenFHE scale 2^45 → 2^59** (Lattigo는 2^45 유지)

45비트 스케일에서는 OpenFHE 부트스트래핑이 성립하지 않는다. 공식 예제 설정에서 출발해
한 번에 하나씩만 바꾸는 이등분 격리로 확인했다 (다른 조건 전부 고정, `scaleMod`만 변경):

| 단계 | 바꾼 것 | 평균 정밀도 |
|---|---|---|
| 0 | 공식 예제 그대로 (ringDim 4096) | 16.98비트 ✅ |
| 1 | 입력을 full packing으로 | 17.35비트 ✅ |
| 2 | ringDim 4096 → 65536 | 12.34비트 ✅ |
| 3 | levelBudget {4,4} → {4,3} | 12.34비트 ✅ |
| 4 | levelsAfterBoot 10 → 8 | 12.35비트 ✅ |
| **5** | **scaleMod 59 → 45** | **EXCEPTION** ❌ |
| 6 | firstMod 60 → 52 | **−1.61비트 (쓰레기 값)** ❌ |

`ringDim`·`levelBudget`·`levelsAfterBoot`·full packing·`HEStd_NotSet`은 모두 무관함이 실측으로 배제됐다.
단계 5·6은 같은 원인의 두 얼굴이다 — `deg = firstMod − scaleMod ≤ correctionFactor`(=8) 가드에
`firstMod 60`은 걸려서 예외를 던지고, `firstMod 52`는 통과하지만 **조용히 틀린 값**을 낸다.

채택값 `scaleMod 59 / firstMod 60 / FLEXIBLEAUTO`는 임의 선택이 아니라
공식 `advanced-ckks-bootstrapping.cpp`의 **64비트 빌드(`NATIVEINT != 128`) 처방값 전체**다.
본 빌드의 `NATIVEINT`는 `config_core.h:20`에서 64로 확인했다.
`FLEXIBLEAUTO`를 함께 채택한 이유: 처방이 세 값을 한 묶음으로 제시하고,
Lattigo 부트스트래핑이 스케일을 내부 자동 관리하므로 `FLEXIBLEAUTO`가 대응 모드다
(`FIXEDMANUAL`은 Lattigo 쪽에 짝이 없다).

**이 비대칭은 정밀도 격차로 직결된다: OpenFHE 12.34비트 vs Lattigo 29.74비트.**
지연시간만 비교하면 OpenFHE가 낮은 정밀도로 얻은 이득이 감춰진다.
**반드시 `precision_bits` 행을 함께 인용할 것.**

**2. OpenFHE `-levels` 9 → 8**

`-levels 9`면 `out_level=10`이 되어 Lattigo(1→9)보다 1레벨 더 복원한다.
bootstrap 비용은 복원 레벨에 비례하지 않으므로 `us_per_level` 정규화가 OpenFHE에 유리하게 편향된다.
`-levels 8` → `in_level=1, out_level=9`로 Lattigo와 정확히 일치(gain 8) → 절대값 비교가 성립한다.

### 결정 1에 대한 정정

「비밀키 분포는 조밀(dense) 정합」의 전제가 정확하지 않다.
`UNIFORM_TERNARY`는 각 계수가 {−1,0,1} 균등이므로 기대 해밍무게가 **2N/3 ≈ 43,690**이고,
Lattigo `ring.Ternary{H: 32768}`은 정확히 **N/2 = 32,768**이다. 둘 다 "조밀" 범주지만 **33% 차이**가 난다.
결정 사항이므로 임의로 바꾸지 않았다 — 엄밀한 정합을 원하면 Lattigo를 `H: 43690`으로 맞추거나
이 차이를 각주로 남길 것.

참고로 희소키의 이득 크기도 실측했다 (step 4 설정, `SecretKeyDist`만 변경):

| secretKeyDist | GetBootstrapDepth | 평균 정밀도 | bootstrap 지연시간 |
|---|---|---|---|
| `UNIFORM_TERNARY` (조밀) | 21 | 12.35비트 | 38.10 s ± 0.26 (reps 10) |
| `SPARSE_TERNARY` (희소) | **17** | **18.71비트** | **24.48 s ± 0.14** (reps 5) |

희소키는 정밀도 +6.4비트, 깊이 −4단계, 지연시간 −36%(1.56배 빠름)로 세 지표 모두 유리하다.
이것이 결정 1이 존재하는 이유이며, **정밀도가 낮다는 이유로 희소키로 전환해선 안 된다** —
정밀도를 산 게 아니라 보안 가정을 판 것이 된다.

> **지연시간 열 주의.** 깊이·정밀도는 이등분 진단 프로그램(`boot_bisect`)에서 나온 값이고,
> 지연시간은 본 벤치(`openfhe_boot_bench`)에서 측정했다. 두 설정은 동일하다
> (ringDim 65536, full packing, levelBudget {4,3}, levelsAfterBoot 8, scaleMod 59,
> firstMod 60, FLEXIBLEAUTO). 조밀 값은 `results_boot2_openfhe_mt.csv`,
> 희소 값은 `results_boot_openfhe_sparse_robustness.csv`에서 온 것이다.
>
> **희소 24.48 s는 `-warmup 3` 재측정값이다.** 이전에 기록했던 25.17 s는 `-warmup 1`이라
> 첫 반복(23.14 s)이 덜 워밍업된 채 평균에 섞인 오염된 값이었다.
> 첫 반복만 제외한 추정치(25.67 s)도 부정확했다 — 실제로는 전 반복이 덜 워밍업된 상태였고,
> 제대로 워밍업하니 두 추정치보다 모두 낮은 24.48 s로 수렴했다.
> 부트스트래핑 측정에 `-warmup 3` 이상을 요구하는 근거가 이 사례다(`CLAUDE.md` 참조).

### Lattigo 쪽 (residual 파라미터)

```
LogN            16
LogQ            {60, 45×9}        → residual MaxLevel = 9
LogP            {61×5}
Xs              ring.Ternary{H: 32768}
LogDefaultScale 45
```

부트스트래핑 회로 리터럴:
```
SlotsToCoeffsFactorizationDepthAndLogScales  {{42},{42},{42}}
CoeffsToSlotsFactorizationDepthAndLogScales  {{58},{58},{58},{58}}
LogMessageRatio  2      (utils.Pointy)
Mod1InvDegree    7      (utils.Pointy)
```

### OpenFHE 쪽 (위에 맞춰 유도)

```
SetRingDim(1 << 16)
SetSecurityLevel(HEStd_NotSet)      // 기존 실험과 동일한 한계
SetSecretKeyDist(UNIFORM_TERNARY)
SetScalingModSize(45)
SetFirstModSize(60)
SetScalingTechnique(FIXEDMANUAL)    // CLI 플래그로 교체 가능하게 (아래 함정 2)
SetMultiplicativeDepth(9 + FHECKKSRNS::GetBootstrapDepth({4,3}, UNIFORM_TERNARY))
```

---

## 산출물

### 1. `lattigo_boot_bench.go`

- 패키지: `github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping`
- 호출 순서: `NewParametersFromLiteral(residual, btpLit)` → `GenEvaluationKeys(sk)`
  → `NewEvaluator(btpParams, keys)` → `eval.Bootstrap(ct)`
- 플래그: `-reps`(기본 10) `-warmup`(기본 1) `-out`
- 키 크기는 `EvaluationKeys.BinarySize()`로 정확히 측정

### 2. `openfhe_boot_bench.cpp` + CMakeLists 타겟 추가

- `cc->Enable(FHE)` 필수
- 호출 순서 고정: `EvalBootstrapSetup(levelBudget, bsgsDim, numSlots)`
  → `KeyGen` / `EvalMultKeyGen` / `EvalBootstrapKeyGen(sk, numSlots)`
  → `EvalBootstrap(ct)`
- `bsgsDim = {0, 0}` (자동)
- 플래그: `-reps` `-warmup` `-out` `-levels` `-scaling`
- CMakeLists.txt 끝에 타겟 2줄 추가 (기존 `openfhe_bench` 타겟은 건드리지 말 것)

### 3. 공통 CSV 스키마 (기존 `results_combined_*.csv`와 별개 파일)

```
library,preset,logN,numSlots,in_level,out_level,op,mean_us,std_us,reps,key_bytes,peak_rss_mb,limbs_q,limbs_p
```

기록할 op 행:
| op | 내용 | reps |
|---|---|---|
| `bootstrap` | 전체 갱신 (평균 ± 표준편차) | reps |
| `btp_setup` | 사전계산 (OpenFHE만) | 1 |
| `btp_keygen` | 키 생성 | 1 |
| `us_per_level` | `bootstrap / (out_level - in_level)` | reps |
| `precision_bits` | 정밀도 검증 (아래 주의) | 1 |

**`precision_bits` 행은 μs가 아니라 *비트*를 담는다** (스키마 고정이라 컬럼 재사용):
- `mean_us` = 평균 정밀도 = `-log2(mean|err|)`
- `std_us` = 최악 슬롯 정밀도 = `-log2(max|err|)`

측정 방식: 알려진 값(시드 고정 [−1,1) 균등 난수) 암호화 → 부트스트래핑 → 복호화 → 슬롯별 비교.
타이밍 구간 밖에서 1회. **타이밍용 입력 0.5는 그대로 유지**하고 정밀도 측정에만 난수를 쓴다
(상수 벡터는 슬롯별 오차 분포를 볼 수 없고 DFT 단계에서 비대표적으로 유리하다).

`limbs_q` / `limbs_p`는 작업량 지표다 (위 「두 지표를 구분할 것」 참조).
Lattigo는 bootstrapping 파라미터 기준으로 기록한다 — 부트스트래핑 회로가 실제로 도는 쪽이다.

> **정밀도 검증은 선택이 아니다.** 구현 초기에 OpenFHE가 예외 없이 −1.6비트(= 신호보다 오차가 큰
> 쓰레기 값)를 반환하면서도 정상적인 지연시간을 내놓아, 측정 4회분이 통째로 무효가 된 이력이 있다.
> 지연시간만 보면 파탄을 알아챌 수 없다.

---

## 기존 코드와 반드시 맞출 규칙

기존 벤치를 만들며 이미 겪고 해결한 이슈들이다. 재발시키지 말 것.
기존 소스에 같은 처리가 들어가 있으니 확인하고 동일하게 따를 것.

- **타이머**: C++는 `std::steady_clock` (`high_resolution_clock`은 `system_clock`
  별칭이라 시계 역행 → 음수 latency 발생 이력 있음). Go의 `time.Now()`는 이미 monotonic.
- **레벨 방향**: OpenFHE `GetLevel()`은 소모량(0→max), Lattigo는 잔량(max→0).
  CSV에는 **Lattigo 기준 잔량**으로 통일 — `level = maxLevel - GetLevel()`.
- **통계**: 평균 + 표본표준편차(n−1), 단위 μs.
- **입력값**: 모든 슬롯 `0.5` (기존 8-op 벤치와 동일).
- **타이밍 범위**: 부트스트래핑 호출 1회만. 입력 암호문 재생성은 타이밍 밖에서.
  Lattigo `Bootstrap`은 입력을 in-place로 건드릴 수 있으므로 **매 반복 새 ct를 만들 것**
  (재사용 금지).
- **피크 메모리**: `/proc/self/status`의 `VmHWM`을 읽을 것. Go의 `runtime.MemStats`는
  힙만 봐서 키 메모리를 놓친다.

---

## 예상되는 함정 (미리 방어할 것)

1. **깊이 하드코딩 금지** — `GetBootstrapDepth` 반환값은 OpenFHE 버전에 따라 다르다.
   반드시 런타임 호출하고 stderr에 찍을 것.

2. **OpenFHE `FIXEDMANUAL`** — 기존 8-op 벤치는 rescale을 명시적으로 측정하려고
   FIXEDMANUAL을 쓴다. 부트스트래핑은 64비트 CKKS에서 전 모드를 지원하지만
   공식 예제 기본은 `FLEXIBLEAUTO`이고, 스케일 관리 실패가 가장 흔한 초기 에러다.
   → `-scaling` 플래그로 FIXEDMANUAL / FIXEDAUTO / FLEXIBLEAUTO 전환 가능하게 만들 것.

3. **입력 레벨 1 차이** — Lattigo는 level 0(`MinimumInputLevel()`)에서 입력.
   OpenFHE 공식 예제는 `MakeCKKSPackedPlaintext(x, 1, depth-1, nullptr, numSlots)`로
   마지막 프라임 1개를 예약한다. 억지로 맞추지 말고 **실측 `in_level`/`out_level`을
   CSV에 그대로 기록**하고, `us_per_level`로 정규화해 비교할 수 있게 할 것.

4. **키 크기 지표 비대칭** — Lattigo는 `BinarySize()`로 정확한 값이 나오지만
   OpenFHE에는 대응 API가 없다. RSS 증가분을 근사로 쓰고, 코드 주석과 stderr 출력에
   "근사"임을 명시할 것. 없는 API를 만들어내지 말 것.

5. **Q 체인 정합 시도 금지** — Lattigo는 residual/bootstrapping 파라미터를 2겹으로
   분리하고 OpenFHE는 단일 체인에 합산한다. 기존 실험의 "Q 체인 완벽 일치"는 여기서
   성립하지 않는다. 강제로 맞추면 한쪽이 자기 최적점을 벗어나 비최적화되고,
   logQP가 따라 움직여 보안 수준까지 바뀐다 — 변수 하나 잡으려다 다른 변수를 푸는 꼴이라
   오히려 공정성을 해친다. 기존 실험에서 P/dnum을 맞추지 않기로 한 것과 동일한 판단이다.
   대신 **양쪽 체인을 stderr에 덤프**해 각주용 수치를 남길 것:
   - Lattigo: residual `LogQP()`, bootstrapping params `LogQP()`, `Depth()`,
     `DepthCoeffsToSlots()` / `DepthEvalMod()` / `DepthSlotsToCoeffs()`
   - OpenFHE: `log2 Q`, `log2 QP`, `GetNumPartQ()`, `GetAuxBits()`, 산출된 depth
   (기존 `openfhe_bench.cpp`의 `dumpChain` 함수를 참고할 것)

---

## 저자 벤치 조사 — 왜 직접 비교하지 않았나

"우리가 OpenFHE 설정을 불리하게 잡은 것 아닌가"라는 의문을 확인하려고 **양쪽 라이브러리의
공식 벤치마크를 모두 조사**했다. 결론: 직접 비교 대상이 아니며, 저자 설정 계열이 오히려 더
느리고 부정확했다.

### 무엇이 있었나

| | Lattigo | OpenFHE |
|---|---|---|
| 위치 | `circuits/ckks/bootstrapping/evaluator_benchmarks_test.go` | `benchmark/src/ckks-bootstrapping.cpp` |
| 형태 | 검증 프리셋 8종 (`DefaultParametersDense/Sparse`) | 설정 테이블 17행 |
| 정밀도 보증 | **프리셋마다 문서화** (15.4~32.1비트, 실패확률 2^-138.7) | **문서화 없음** |
| 측정 대상 | `RunParallel` 동시 처리량 | `Iterations(4)`, 초 단위 |

### Lattigo 벤치를 쓰지 않은 이유

1. **프리셋이 다르다.** `BenchmarkConcurrentBootstrap`은 `DefaultParametersDense[0]`
   = `N16QP1767H32768H32`를 쓴다. 우리 `boot16`은 `[1]` = `N16QP1788H32768H32`다.
   잔여 레벨 13 대 9, scale 2^40 대 2^45, 문서상 정밀도 23.8 대 29.8비트로 전부 다르다.
2. **지표가 다르다.** `RunParallel` 동시 처리량이지 단건 지연시간이 아니다.
   우리는 단건을 재고, `GOMAXPROCS` 실험으로 단건에 내부 병렬이 없음을 이미 확인했다.
3. **코드에 의심스러운 점이 있다** (코드 리딩 기준, 미검증):
   `eval`과 `ct1`을 `RunParallel` 밖에서 1개씩 만들어 모든 고루틴이 공유한다.
   이 패키지에 `ShallowCopy`가 없고 `Evaluator`는 `xPow2N1` 등 가변 버퍼를 들고 있어
   데이터 경합 소지가 있다. 또 `NewCiphertext(params,1,0)`은 암호화되지 않은 0이라
   정밀도 검증도 없다.
   → `-race`로 3회 확인을 시도했으나 **전부 세션 종료로 중단**되어 검증하지 못했다.
   재현 프로브는 `racecheck/`에 남겨 두었다(작은 프리셋으로 패턴만 복제).
   **경합 여부는 여전히 추정이며 사실로 기록하지 말 것.**

### OpenFHE 벤치를 쓰지 않은 이유

저자 테이블의 2^16/2^15 조밀 행 5개는 우리와 여섯 항목 중 다섯이 다르다
(`dcrtBits` 50~54, `firstMod` 57~60, `levelBudget {3,3}`, `iters` 대부분 2,
`numDigits` 10~16 명시, `HEStd_128_classic`).

그중 가장 가까운 A행
(`dcrtBits 54 / firstMod 60 / {3,3} / lvlsAfter 9 / iters 1 / FLEXIBLEAUTO`)을
우리 하네스로 실측했다 → `results_boot_openfhe_authorbench_A.csv`

| | 본 결과 boot16 | 저자 A행 변형 | Lattigo boot16 |
|---|---|---|---|
| bootstrap | 38.098 s | **41.605 s ± 0.128** | 23.910 s |
| 정밀도 | 12.34비트 | **7.42비트** (최악 4.40) | 29.74비트 |
| out_level | 9 | **10** | 9 |
| limb QP | 40 | 40 | 33 |
| logQP | 2371 | 2226 | 1788 |
| btp_keygen | 31.1 s | 18.1 s | 57.9 s |

**저자 설정 계열이 더 느리고 정밀도도 더 낮았다.** 즉 "OpenFHE 설정을 불리하게 잡아서
결과가 나빴다"는 가설은 이 측정으로는 지지되지 않는다.

다만 이 값은 **저자 A행의 변형**이지 원본이 아니다. 두 가지가 다르다:

- `numDigits` 미지정(자동 dnum=3). 원본은 15. → 아래 dnum 교환 관계 참조.
  `numDigits=15`로 2회 시도했으나 keygen이 9분을 넘겨 완주 실패
  (부분 결과 `archive/authorbench_A_dnum15_partial.csv`).
- `SecurityLevel = HEStd_NotSet`. 원본은 `HEStd_128_classic`.
  **링 차원을 65536으로 강제해 Lattigo와 맞추려면 불가피하다.**

**이 두 번째 항목 때문에 `numDigits`를 넣더라도 원본 온전 재현은 애초에 불가능하다.**
게다가 `out_level`이 10이라 본 실험(1→9)과 복원 레벨이 달라 나란히 놓을 수도 없다.
그래서 B행(`iters 2`)은 진행하지 않았다 — 같은 한계가 그대로 남기 때문이다.

### dnum(`numDigits`) 교환 관계

조사 중 드러난 별개 사실. 공짜로 좋아지는 쪽이 없는 손잡이다:

| | dnum ↑ (15) | dnum ↓ (자동 3) |
|---|---|---|
| towersPerPart | 2 | 10 |
| limb P / QP | 2 / **32** | 10 / **40** |
| 연산 체인 | 가벼움 | 무거움 |
| key-switch 오차 | 작음 (정밀도 유리) | 큼 |
| **keygen** | **9분 초과** | **18.1 s** |

실측 근거(둘 다 `dcrtBits 54 / firstMod 60 / {3,3} / lvlsAfter 9 / iters 1`):
dnum 3은 완주해 bootstrap 41.6 s / 정밀도 7.42비트를 얻었고,
dnum 15는 체인 구조만 확인되고 **지연시간·정밀도는 미측정**이다.
"dnum이 크면 정밀도에 유리"는 key-switch 오차가 digit 크기에 비례한다는 구조적 근거에
따른 추정이며 실측이 아니다.

## 완료 조건

1. 두 실행파일이 `-reps 1`로 정상 종료하고 CSV를 남긴다.
2. 양쪽 stderr에 체인 덤프(위 5번 항목)가 출력된다.
3. 빌드 경고가 에러로 승격되지 않는다 (`CMakeLists.txt`는 이미 `-Werror`를 제거함).
4. 기존 `lattigo_bench.go` / `openfhe_bench.cpp` / 기존 CSV는 **수정하지 않는다.**

구현 완료 후 `-reps 1` 파일럿을 직접 실행하고, 다음을 보고할 것:

- 1회 소요 시간 (reps 확정용 — 60초 초과면 reps를 10에서 5로 낮출 것)
- 피크 RSS (워크스페이스는 31 GiB. 25 GiB 근접이면 `-levels`를 9→5로 낮춰야 함)
- `GetBootstrapDepth` 실제 반환값
- 양쪽 logQP 격차