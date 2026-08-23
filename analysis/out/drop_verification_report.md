# drop(레벨 강하) 비용 검증 — 논문 4.3용 보충 분석

생성 배경: 2026-08-23 작업 지시("drop 비용이 계단 이득에 비해 무시할 만한가")에 대한 답.
**재측정 없이 기존 `results/leveldrop/`·`analysis/out/leveldrop_report.md` 원자료를 재구성**했다
(사용자 승인) — 단 검증방법 3(Lattigo 재실행 대조)만은 원자료에 없어 Lattigo만 추가로 2회
재측정했다(§5). 이후 사용자 지시로 **정본을 `leveldrop_ip`(제자리 강하)로 통일**했다 — 배치
최적화기가 실제로 수행하는 것은 in-place 강하이지 새 암호문을 만드는 복사가 아니기 때문이다.

⚠️ 이 문서는 `docs/paper/`를 수정하지 않는다. 반영은 사용자가 한다.
관련 문서: `docs/paper/leveldrop_protocol_note.md`(측정 프로토콜 논증, 4장 근거).

---

## 0. API 확인 (직접 grep 재검증)

| library | 함수 | 파일:라인 | 확인 |
|---|---|---|---|
| openfhe | `LevelReduce`/`LevelReduceInPlace` → `LevelReduceInternalInPlace` | `openfhe-src/src/pke/lib/scheme/ckksrns/ckksrns-leveledshe.cpp:197-201` | `DropLastElements`+`SetLevel`만 있음. `SetScalingFactor` 없음 |
| seal | `mod_switch_to_next` → CKKS 분기 `mod_switch_drop_to_next` / `mod_switch_to_next_inplace` | `third_party/SEAL/src/native/src/seal/evaluator.cpp:1382-1408`(분기 1405) | BFV/BGV만 `mod_switch_scale_to_next` 탐 — CKKS는 스케일 보존 |
| lattigo | `DropLevel`/`DropLevelNew` | `~/go/pkg/mod/github.com/tuneinsight/lattigo/v6@v6.2.0/schemes/ckks/evaluator.go:459-469` | `op0.Resize(degree, level-levels)` 뿐 |

세 라이브러리 모두 대응물 있음(억지 대체 없음).

측정 원자료는 8-op 메인 하네스가 아니라 `presetsearch_{openfhe,seal,lattigo}` exp 9(`-leveldrop`)로
이미 A~D·1t·레벨전수·reps30 측정되어 있다(2026-08-19). 프로토콜(코어 고정·30초 가열·전후 프로브·
reps30)은 8-op 본측정과 동일하나 **측정 방식(단발 vs 상각)이 다르다 — 자세한 내용은
`docs/paper/leveldrop_protocol_note.md` 참조.**

---

## 1. 변종 정의와 정본 — `leveldrop_ip` 로 통일

| op | 타이머로 감싼 것 |
|---|---|
| `leveldrop_ip` (**정본**) | 제자리(파괴적) 강하. OpenFHE `LevelReduceInPlace`, Lattigo `DropLevel`, SEAL `mod_switch_to_next_inplace` |
| `leveldrop_oop` (보조) | 새 암호문 반환. OpenFHE `LevelReduce`(Clone+ip), Lattigo `DropLevelNew`(CopyNew+Drop), SEAL `mod_switch_to_next` |
| `clone_only` (보조, openfhe·seal만) | 깊은 복사만(강하 없음). `oop − clone_only` 분해용 |

### 1.1 ip/oop 비 — SEAL만 방향이 반대다

전체 32조건(A~D×전레벨) 집계, `library × preset × level` 단위:

| library | ip/oop 비 min | med | max | 방향 |
|---|---|---|---|---|
| lattigo | 0.000042 | 0.000142 | 0.000529 | **ip가 최대 24000배 싸다** |
| openfhe | 0.000985 | 0.008624 | 0.049152 | **ip가 최대 1000배 싸다** |
| seal | 2.274916 | 2.401850 | 4.264296 | **ip가 최대 4.3배 비싸다** — 역전 |

SEAL만 방향이 반대다. `oop − clone_only`(=oop에서 순수 복사비용을 뺀, 강하 자체의 한계비용)로
기전을 보면:

| library | oop−clone min | med | max | 부호 |
|---|---|---|---|---|
| lattigo | −293.3 | +56.3 | +1277.9 | 부호 불안정(잡음 — Lattigo oop는 §1.2 사유로 신뢰 안 함) |
| openfhe | −2.5 | +1.6 | +5.2 | 거의 0 (강하 자체가 무의미한 한계비용) |
| seal | **−51.5** | **−29.0** | **−4.7** | **32/32 전부 음수** |

**기전**: SEAL의 `mod_switch_to_next`(oop)는 남길 RNS 성분만 목적 버퍼로 직접 복사한다 — 버릴
성분은 아예 만지지 않는다. 반면 `mod_switch_to_next_inplace`(ip)는 임시 버퍼에 결과를 만든 뒤
원본에 되씌우는 **2회 복사** 구조라 오히려 oop보다 비싸다(`evaluator.cpp` 내부 구현, SEAL 소스
주석 및 실측 32/32 전부 음수인 `oop−clone`이 방증). OpenFHE·Lattigo는 ip가 진짜 O(1)(포인터/
슬라이스 조작)이라 oop(=clone+ip)보다 압도적으로 싸고, clone 쪽이 병목이다 — 정반대 기전이다.

⚠️ **"SEAL의 drop이 본질적으로 비싸다"로 읽으면 안 된다.** 이건 SEAL 라이브러리의 근본적 열위가
아니라 **API 경로 선택의 결과**다 — SEAL도 oop 경로(`mod_switch_to_next`)를 쓰면 OpenFHE와
비슷한 수백 μs대(§2 참고)이고, 그조차 계단 이득 대비 무시 가능한 수준이다(§3). 배치 최적화기가
"제자리로 강하"를 선택하기 때문에 ip를 정본으로 쓰는 것이지, SEAL이 라이브러리로서 열등해서가
아니다.

### 1.2 Lattigo는 ip만 사용 — oop 파생값 배제

Lattigo의 `leveldrop_oop`·`clone_only`는 §1.1 표에서 보듯 부호조차 불안정하다(기존
`leveldrop_report.md` §8.4에서도 "신뢰하지 말 것"으로 명시된 값). **이 문서의 모든 표·통계에서
Lattigo는 `leveldrop_ip`만 쓰고, oop/clone 파생값(비율, 차이)은 어떤 표에도 넣지 않았다** —
§1.1의 "부호 불안정" 언급은 그 자체를 통계로 쓰지 않기 위한 반증용 서술이다.

---

## 2. 자릿수 비교 — drop_ip vs rescale·relin·rot1·mul_cc_rlk (전 프리셋·전 레벨)

전체 96행: `drop_verification_orderofmag.csv`. preset A, level=12(최댓값) 발췌:

| library | drop_ip_us | rescale_us | relin_us | rot1_us | mul_cc_rlk_us | drop/rescale | drop/relin | drop/rot1 | drop/mulccrlk |
|---|---|---|---|---|---|---|---|---|---|
| lattigo | 0.121 | 8822.7 | 49716.6 | 49675.0 | 54310.5 | 1.37e-05 | 2.43e-06 | 2.44e-06 | 2.23e-06 |
| openfhe | 2.014 | 3871.6 | 29647.7 | 31611.2 | 42267.6 | 5.20e-04 | 6.79e-05 | 6.37e-05 | 4.76e-05 |
| seal    | 867.368 | 10625.2 | 93300.2 | 93766.6 | 99516.9 | 8.16e-02 | 9.29e-03 | 9.25e-03 | 8.72e-03 |

전 96행에 대한 `drop_ip/rescale` 범위(라이브러리별 min~max):

| library | min | max |
|---|---|---|
| lattigo | 9.31e-06 | 4.02e-05 |
| openfhe | 3.74e-04 | 1.30e-03 |
| seal | 3.07e-02 | **8.17e-02** |

**ip 정본으로 바뀐 뒤에도 모든 프리셋·레벨·라이브러리에서 drop_ip는 rescale·relin·rot1·
mul_cc_rlk보다 최소 1자릿수(SEAL 최악 8.2%) 작고, OpenFHE·Lattigo는 3~5자릿수 작다.**
(ip 반영 전 SEAL 최악치는 3.46%였다 — ip가 oop보다 비싸므로 여유폭이 줄었지만 결론은 그대로다.)

---

## 3. 검증방법 1 — 전이점(계단) pass/fail

**판정 기준(단순화)**: `drop_ip(L) < c(L) − c(L−1)` — `c`는 해당 KS-op(relin/rot1/mul_cc_rlk)의
레벨별 평균비용. 좌변이 우변보다 작으면 pass.

- 전이점(계단) 분류는 **OpenFHE·Lattigo에만 적용**한다(OpenFHE=`digit` 교차, Lattigo=g밴드추정
  중점). **SEAL은 digit이 매 레벨 1씩 줄어 전이/비전이 구분 자체가 성립하지 않는다** — 참고 표로
  분리했다.
- 파일: `drop_verification_passfail_transitions.csv`(전이점만 45행, OpenFHE+Lattigo) ·
  `drop_verification_passfail_all.csv`(전 252행, SEAL 포함 — 참고용).

| library | 전이점 n | pass | fail |
|---|---|---|---|
| openfhe | 21 | **21** | 0 |
| lattigo | 24 | **24** | 0 |
| **합계** | **45** | **45** | **0** |

SEAL(전이점 미분류, 참고 84쌍): pass 84 / fail 0 (ip 반영 후에도 유지).

**최악 여유폭(전이점 45쌍 중 drop/gain 비율이 가장 큰 5건)**:

| preset | library | op | level | step_gain(μs) | drop_ip(μs) | drop/gain |
|---|---|---|---|---|---|---|
| D | openfhe | rot1 | 2 | 4292.29 | 1.302 | 0.0303% |
| B | openfhe | relin | 3 | 4721.53 | 1.408 | 0.0298% |
| B | openfhe | rot1 | 3 | 4732.24 | 1.408 | 0.0298% |
| D | openfhe | mul_cc_rlk | 2 | 4436.98 | 1.302 | 0.0293% |
| D | openfhe | relin | 2 | 4492.95 | 1.302 | 0.0290% |

가장 타이트한 경우도 0.03% — 3300배 이상 여유가 있다. 전이점 45쌍의 `step_gain` 자체도
lattigo 최소 2012μs, openfhe 최소 3716μs로, drop_ip 최댓값(SEAL 867μs, 그러나 SEAL은 전이점
미분류이므로 사실상 openfhe 최댓값 2.02μs·lattigo 최댓값 0.121μs)과 비교해도 3~4자릿수 차이다.

### 3.1 모집단 차이 — "252쌍 중 nets≠0 1쌍"과 "45쌍 중 0건"의 관계

- **252쌍** = 인접 레벨쌍 전부 × KS-op 3종(relin/rot1/mul_cc_rlk) × 라이브러리 3 (openfhe 84 +
  lattigo 84 + seal 84). 계단·비계단 구분 없이 전수.
- **45쌍** = 252쌍 중 **전이점(계단)으로 분류된 것만** — openfhe 21 + lattigo 24. SEAL 84는
  애초에 전이점 분류가 없어 45에 포함되지 않는다(위 3. 서두 참조).
- **nets≠0 1건**(A·lattigo·mul_cc_rlk·L11→L10)은 **비계단(step=False)** 쌍이다
  (`leveldrop_net.csv` 원자료 직접 확인: `step` 컬럼 값 `False`). 즉 애초에 45쌍 인구에
  들어갈 자격이 없었다 — "어디로 갔다"가 아니라 **처음부터 다른 모집단 소속**이다. 미규명 아님.
- 이 쌍의 `net<0` 원인도 drop 비용이 아니라 `step_gain` 자체가 음수(−527μs)이기 때문이다
  — 기존 v3 8-op 자료의 이상치(`level_cost_report.md` §5에서 별도 확인됨, g=1.010로
  "레벨을 내렸는데 오히려 느려진" 케이스). ip 재산출 후에도 이 쌍의 `drop_ip=0.081μs`로
  drop 자체는 여전히 무시 가능한 크기이고, pass/fail 판정에도 영향 없다(비계단 인구라 45쌍
  판정 밖).

**결론**: 45/45 전부 pass, 252쌍 전체 인구의 유일한 실패(비계단 1건)는 drop 비용 문제가 아니다.
두 표는 서로 다른 모집단이며 충돌하지 않는다.

---

## 4. 검증방법 2 — 라이브러리별 레벨-비용 선형적합 (leveldrop_ip 기준)

파일: `drop_verification_linearfit.csv` (library × preset, 12행)

| library | preset | slope(μs/level) | R² | mean(μs) | 기울기(%/level) | 판정(±2% 기준) |
|---|---|---|---|---|---|---|
| lattigo | A | +0.00690 | 0.933 | 0.0667 | +10.4% | 레벨비례 |
| lattigo | B | +0.00340 | 0.780 | 0.0375 | +9.1% | 레벨비례 |
| lattigo | C | +0.00388 | 0.513 | 0.0562 | +6.9% | 레벨비례 |
| lattigo | D | +0.00440 | 0.774 | 0.0325 | +13.5% | 레벨비례 |
| openfhe | A | +0.0766 | 0.880 | 1.653 | +4.6% | 레벨비례 |
| openfhe | B | +0.0689 | 0.527 | 1.262 | +5.5% | 레벨비례 |
| openfhe | C | +0.0969 | 0.933 | 1.626 | +6.0% | 레벨비례 |
| openfhe | D | +0.1052 | 0.405 | 1.243 | +8.5% | 레벨비례 |
| seal | A | +75.11 | 0.999 | 456.2 | +16.5% | 레벨비례 |
| seal | B | +38.27 | 0.976 | 101.7 | +37.6% | 레벨비례 |
| seal | C | +75.81 | 1.000 | 383.0 | +19.8% | 레벨비례 |
| seal | D | +29.41 | 0.977 | 61.2 | +48.0% | 레벨비례 |

(ip 정본 반영 후 SEAL 기울기가 rescale과 유사한 방향으로 더 뚜렷해졌다 — R² 0.976~1.000로
oop 기준보다 오히려 더 깨끗하다. 임시버퍼+2회복사 구조가 레벨 크기에 정직하게 비례하기 때문.)

**지시된 ±2%/level 문턱을 문자 그대로 적용하면 세 라이브러리 전부 "레벨비례"다.** 다만 성격은
질적으로 다르다:

- **SEAL**: 기울기 17~48%, R² 0.976~1.000 — **강하고 확실한 비례**. §1.1 기전(임시버퍼+2회복사)과
  정확히 일치.
- **OpenFHE**: 기울기 4.6~8.5%, R² 0.41~0.93 — **약하지만 재현되는 비례**(4개 프리셋 전부 같은
  방향). 메커니즘상 `DropLastElements`는 O(1)이어야 하나, 레벨이 클수록 건드리는 메모리(벡터
  크기)가 커져 캐시/할당 비용이 완만히 늘어나는 것으로 보인다. 절대 크기 0.9~2.0μs는 여전히
  무의미한 수준(§2).
- **Lattigo**: 기울기 6.9~13.5%, R² 0.51~0.93 — **회귀상 유의해 보이지만 신뢰하지 않는다.**
  절대값이 23~121ns로 Go 시계 호출 오버헤드(86ns)와 같은 자릿수이고, 32개 값 전부가 기존
  cv>0.05 게이트에 걸렸다(cv_med 0.18, cv_max 1.99). 메커니즘(슬라이스 절단, 산술 없음)은 O(1)을
  가리킨다. **점추정 대신 자릿수 대역(10¹~10² ns)으로만 서술한다** — 근거는
  `docs/paper/leveldrop_protocol_note.md` §5.

**요약 판정**: SEAL만 "레벨비례"를 확신 있게 쓸 수 있다. OpenFHE는 "레벨비례(약함, 실측 재현됨,
절대량 무의미)"로, Lattigo는 회귀 결과를 인용하지 말고 "측정 하한 근방, 메커니즘상 O(1), 자릿수
대역만 보고"로 서술한다.

---

## 5. 검증방법 3 — Lattigo drop 동일조건 재실행 2회 대조

`run_leveldrop.sh`와 동일 프로토콜로 Lattigo만 A~D 2회 재실행(코어 12 고정, 30초 가열, 전후 DVFS
프로브 — 8회 실행 전부 pre/post FAST band, 이탈 0건). 원자료:
`results/leveldrop/lattigo_rerun_1t_dku16c/{run1,run2}_{A,B,C,D}.csv`. 비교표:
`drop_verification_lattigo_rerun.csv`.

| op | n | median\|Δ\| | max\|Δ\| | 0.05 초과 |
|---|---|---|---|---|
| leveldrop_ip | 32 | 0.050 | 0.352 | 16/32 |
| leveldrop_oop | 32 | 0.096 | 0.753 | 22/32 |
| clone_only | 32 | 0.086 | 0.890 | 26/32 |

**판정: leveldrop_ip 32쌍 중 16쌍이 0.05 문턱을 넘는다.** 지시대로 이 값들은 논문에 정밀
인용하지 않는다 — **"Lattigo의 drop_ip 비용은 Go GC/시계 분해능 영향으로 안정적으로
재측정되지 않는다"**로만 서술한다. 절대 크기 자체(run1/run2 모두 23~121ns 대역, §1.1)는 두 번
다 다른 op 대비 무의미하게 작다는 결론(§2, §3)에는 영향이 없다 — 재현성이 없는 것은 "정확히
몇 ns인가"이지 "무시할 만큼 작은가"가 아니다.

이 값(0.097 vs 0.081, A·lattigo·mul_cc_rlk·L10 지점의 원자료 간 불일치)은 §3.1에서 다룬 것과
같은 지점이며, 애초에 Lattigo·저수준 μs 미만 값이라 재실행 안정성 대상 밖(둘 다 인용 금지)이다
— 자세한 처리는 `docs/paper/leveldrop_protocol_note.md` §6.

---

## 6. 결론 (숫자만 — 문장화는 사용자가 논문에 반영)

1. `leveldrop_ip`가 정본이다. SEAL만 ip가 oop보다 비싸다(최대 4.3배) — API 경로 차이이지
   라이브러리 우열이 아니다. §1.
2. drop_ip는 rescale·relin·rot1·mul_cc_rlk보다 전 조건에서 최소 1자릿수(SEAL 최악 8.2%) ~
   5자릿수(Lattigo) 작다. §2.
3. drop_ip 비용이 전이점 계단 이득보다 작지 않은 경우는 0건(45/45, 최악 여유도 0.03%). 252쌍
   전체의 유일한 예외(비계단 1건)는 drop 비용과 무관. §3.
4. 라이브러리별 레벨 의존성: SEAL=확실한 비례(R²≥0.976), OpenFHE=약한 비례(재현되나 절대량
   무의미), Lattigo=측정 하한이라 판정 불가(메커니즘상 O(1), 자릿수 대역만 서술). §4.
5. Lattigo의 drop_ip 정밀값은 재실행 간 최대 35%(중앙값)~89%(최대) 튄다 — 정밀 인용 금지,
   정성적 서술만. §5.

## 파일 목록

- `analysis/out/drop_verification_orderofmag.csv` — §2 전체(96행, ip 기준)
- `analysis/out/drop_verification_passfail_transitions.csv` — §3 전이점만(45행, ip 기준)
- `analysis/out/drop_verification_passfail_all.csv` — §3 전체(252행, ip 기준)
- `analysis/out/drop_verification_linearfit.csv` — §4(12행, ip 기준)
- `analysis/out/drop_verification_lattigo_rerun.csv` — §5(128행)
- `analysis/out/drop_variant_comparison_presetA_wide.csv` — §1 프리셋A 4종 비교(36행)
- `results/leveldrop/lattigo_rerun_1t_dku16c/` — §5 원자료(run1/run2 8쌍 + probe)
- `docs/paper/leveldrop_protocol_note.md` — 측정 프로토콜 논증(4장 근거, 신규)
