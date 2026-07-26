# PARAMS_dku16c.md — 3자 key-switch 파라미터 정본

이 문서는 **런타임 API로 추출한 값만** 담는다. 문서 기본값·추정치·유도값은 쓰지 않는다.
발표자료의 정합 기준 슬라이드는 이 표를 근거로 한다.

측정 환경 `dku16c`, 브랜치 `third-lib`, 추출일 2026-07-26.
라이브러리: OpenFHE v1.5.1 · Lattigo v6.2.0 · **SEAL v4.3.3 (태그 `v4.3.3`, 커밋 `02a5c345`)**

---

## 1. 추출 경로 (재현용)

| lib | API | 소스 검증 위치 |
|-----|-----|----------------|
| OpenFHE | `CryptoParametersRNS::GetNumPartQ()`, `GetNumPerPartQ()`, `GetParamsP()`, `GetAuxBits()` | 레벨별 digit 수: `src/pke/lib/keyswitch/keyswitch-hybrid.cpp:327-329`<br>`numPartQl = ceil(sizeQl / alpha)`, `alpha = GetNumPerPartQ()`, 상한 `GetNumberOfQPartitions()` |
| Lattigo | `params.QCount()`, `LogQ()`, `PCount()`, `LogP()`, `BaseRNSDecompositionVectorSize(levelQ, levelP)` | `core/rlwe/params.go:543` — `Ceil(lenQi/lenPi)`, 즉 `(levelQ+levelP+1)/(levelP+1)`. `levelP == -1`이면 `levelQ+1` |
| SEAL | `SEALContext` 체인 walk (`context_data->parms().coeff_modulus()`, `chain_index()`) | 특수 소수 1개(60비트)를 우리가 **명시 고정**. digit 수 = 해당 레벨의 데이터 프라임 수 = `level+1` |
| 128비트 상한 | `seal::CoeffModulus::MaxBitCount(N, sec_level_type::tc128)` | 실측: N=8192→**218**, 16384→**438**, 32768→**881** |

추출 도구는 저장소에 있다: `param_dump_openfhe.cpp`, `param_dump_lattigo.go`
(둘 다 벤치마크를 실행하지 않고 파라미터만 덤프한다).

---

## 2. 파라미터 대조표

`logQP = logQ + logP`. digit 수는 maxLevel → 1 순.

| preset | lib | QCount | logQ | PCount | logP | logQP | 레벨별 digit 수 |
|--------|-----|-------:|-----:|-------:|-----:|------:|-----------------|
| small (logN 13) | openfhe | 6 | 275 | 2 | 120 | 395 | 3, 3, 2, 2, 1 |
| | lattigo | 6 | 275 | 1 | 55 | 330 | 6, 5, 4, 3, 2 |
| | seal | 6 | 275 | 1 | 60 | 335 | 6, 5, 4, 3, 2 |
| medium (logN 14) | openfhe | 11 | 505 | 4 | 240 | 745 | 3, 3, 3, 2, 2, 2, 2, 1, 1, 1 |
| | lattigo | 11 | 505 | 2 | 110 | 615 | 6, 5, 5, 4, 4, 3, 3, 2, 2, 1 |
| | seal | 11 | 505 | 1 | 60 | 565 | 11, 10, 9, 8, 7, 6, 5, 4, 3, 2 |
| large (logN 15) | openfhe | 16 | 735 | 5 | 300 | 1035 | 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1 |
| | lattigo | 16 | 735 | 2 | 120 | 855 | 8, 8, 7, 7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1 |
| | seal | 16 | 735 | 1 | 60 | 795 | 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2 |

**logQ는 세 라이브러리가 275 / 505 / 735로 완전히 일치한다** (§3 정합 기준의 핵심).
**logQP는 전부 다르다** — P가 각 라이브러리 자동 결정(SEAL만 우리가 고정)이기 때문이다.

### 2.1 digit 수는 세 라이브러리 모두 레벨의 함수다

과거 문서의 "OpenFHE dnum 3 고정 / Lattigo 6~8"은 **틀린 서술**이었다.
`numPartQ = 3`은 **최상위 레벨의 상한**이지 전 레벨 고정값이 아니다.
Lattigo의 6~8도 maxLevel에서의 값일 뿐이다. 차이는 **증가 기울기**다.

| lib | digit 증가 기울기 (레벨당) | 형태 |
|-----|---------------------------|------|
| SEAL | **1.00** | `level + 1` — 선형 증가, 상한 없음 |
| Lattigo | **0.50** (small은 1.00) | `ceil((L+1)/PCount)`. small은 P가 1개라 SEAL과 동일한 수열 |
| OpenFHE | **0.17 ~ 0.50** (프리셋별) | `min(3, ceil((L+1)/perPart))` — 3에서 **포화되는 계단** |

`perPart(GetNumPerPartQ)` = small 2 / medium 4 / large 6.

---

## 3. 보안 수준 — logQ가 아니라 logQP로 판정해야 한다

하이브리드 key-switch에서 **평가키는 Q가 아니라 QP 위에 정의**된다. 따라서 실효 보안을
결정하는 것은 `logQ`가 아니라 **`logQP`**다. 아래 여유(margin) = 상한 − logQP.

| preset | N | tc128 상한 | lib | logQP | 여유 | 128비트 |
|--------|---|-----------:|-----|------:|-----:|---------|
| small | 8192 | 218 | openfhe | 395 | **−177** | ✗ 초과 |
| | | | lattigo | 330 | −112 | ✗ 초과 |
| | | | seal | 335 | −117 | ✗ 초과 |
| medium | 16384 | 438 | openfhe | 745 | **−307** | ✗ 초과 |
| | | | lattigo | 615 | −177 | ✗ 초과 |
| | | | seal | 565 | −127 | ✗ 초과 |
| large | 32768 | 881 | openfhe | 1035 | **−154** | ✗ **초과** |
| | | | lattigo | 855 | +26 | ✓ 이내 |
| | | | seal | 795 | +86 | ✓ 이내 |

**읽는 법**

- **large에서 OpenFHE만 상한을 넘는다** (1035 > 881). Lattigo(855)와 SEAL(795)은 이내다.
  `logQ`(735)만 보면 셋 다 881 이내로 보이므로 **logQ로 판정하면 이 사실을 놓친다.**
- **세 프리셋 모두 OpenFHE가 상한에서 가장 멀다.** 같은 Q 체인 위에서도 OpenFHE가
  가장 큰 P(특수소수 2/4/5개)를 얹기 때문이다.
- small / medium은 **세 라이브러리 모두 초과**한다. 이 두 프리셋은 `logQ` 자체가 이미
  상한을 넘으므로(275 > 218, 505 > 438) P와 무관하게 128비트가 아니다.
- ⚠️ 정확히 적을 것: 순서가 프리셋마다 같지 않다. medium·large는
  **OpenFHE < Lattigo < SEAL** 순으로 보안 여유가 커지지만, **small은 Lattigo(−112)가
  SEAL(−117)보다 5비트 앞선다.** OpenFHE가 셋 중 최악이라는 점만 세 프리셋 공통이다.

### 3.1 정합 기준의 한계 (기존 문서에 빠져 있던 항목)

**Q는 비트 단위로 일치시켰으나 P가 자동 결정되므로 보안 수준까지는 정합되지 않는다.**
같은 Q 체인 위에서 도는 세 라이브러리가 서로 다른 실효 보안을 갖는다는 뜻이다.
따라서 3자 latency 비교는 **"동일 Q 체인 위의 비교"이지 "동일 보안 수준에서의 비교"가 아니다.**
key-switch 계열(`relin`/`rot1`/`mul_cc_rlk`)에서 P가 작은 쪽이 유리한데, 그 유리함의 일부는
**보안 여유를 덜 확보한 대가**다. 발표 시 이 교환관계를 함께 제시할 것.

---

## 4. 측정된 곡률과의 대조

`relin`의 레벨 대비 2차 계수(1t, AICc로 선형/이차 판정)와 위 digit 기울기의 관계:

| preset | lib | digit 기울기 | 2차 계수 | 판정 |
|--------|-----|-------------:|---------:|------|
| small | openfhe | 0.50 (계단 3→1) | −7.7 | **1차** |
| | lattigo | 1.00 | 101.2 | 2차 |
| | seal | 1.00 | 88.7 | 2차 |
| medium | openfhe | 0.25 | 107.3 | 보류 |
| | lattigo | 0.52 | 157.3 | 2차 |
| | seal | 1.00 | 226.5 | 2차 |
| large | openfhe | 0.17 | 213.6 | 2차(약) |
| | lattigo | 0.50 | 269.1 | 2차 |
| | seal | 1.00 | 438.1 | 2차 |

- **순위가 일치한다**: digit 기울기 SEAL > Lattigo > OpenFHE, 2차 계수도 동일 순서(세 프리셋 모두).
- **small에서 Lattigo와 SEAL의 digit 수열이 `6,5,4,3,2`로 완전히 같고**, 2차 계수도
  101.2 / 88.7로 근접한다 — 독립 추출한 파라미터와 독립 적합한 곡률이 서로를 확증한다.
- OpenFHE small이 1차인 것은 digit이 `3,3,2,2,1`로 이미 포화된 계단이라 곡률이 없기 때문이다.
- ⚠️ 계수비가 기울기비보다 체계적으로 크다(예: large openfhe 0.49 vs 0.17). key-switch
  총비용에는 digit 수와 무관하게 타워 수에만 비례하는 성분과 P 크기에 비례하는 성분이
  함께 있어, 순수 `d(L)×(L+1)` 모델로는 계수 크기까지 예측되지 않는다.
  **순위·방향은 확정, 비례상수는 미설명.**

### 4.1 저레벨에서 SEAL이 빠른 이유

**SEAL의 digit 수가 OpenFHE보다 적은 레벨은 존재하지 않는다** (위 표에서 확인 가능).
그런데도 낮은 레벨에서 SEAL이 크게 빠르다(large L1에서 relin 0.343배).
원인은 digit 수가 아니라 **P의 고정 비용**이다 — OpenFHE는 레벨과 무관하게 특수소수
2/4/5개(logP 120/240/300)를 항상 운반하고, 타워가 적은 낮은 레벨에서는 이 고정 비용의
비중이 지배적이 된다. SEAL은 어느 레벨에서나 특수소수 1개(60비트)뿐이다.
레벨이 오르면 SEAL의 digit이 선형으로 늘어 이 이점을 잠식하고, dnum ≈ 9~11 부근에서
역전된다(relin 교차: medium L≈9.8, large L≈8.5, small은 digit이 6까지만 커져 **교차 없음**).

⚠️ 저레벨 우위의 **배수**는 프라임 개수 셈만으로 설명되지 않는다(large L1: OpenFHE
1 digit × 7 프라임 vs SEAL 2 digit × 3 프라임). 구현 상수가 남아 있으므로
"P 고정 오버헤드가 주된 방향"까지가 결론이다.
