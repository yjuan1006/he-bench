# SEAL_TASK.md — 세 번째 라이브러리(Microsoft SEAL) 8-op 통합

대상 브랜치: `third-lib` / 작업 경로: `/data/yja/he-bench` / 머신 태그: `dku16c`

이 문서는 자체 완결적이다. 저장소의 `PROJECT_CONTEXT.md`(정합 기준 §3, 측정 규칙 §4,
검증 절차 §5), `CLAUDE.md`, `BENCHMARK_PROTOCOL.md`는 읽을 수 있으니 참조할 것.
Claude.ai 프로젝트 지식과 발표자료(`HE_benchmark_*.pptx`)는 접근 불가 — 여기 필요한 내용은 옮겨 적었다.

---

## 0. 사전 검증 완료 사항 (SEAL 4.3.3에서 실측 확인, 추측 아님)

아래는 별도 환경에서 SEAL 4.3.3(`main`, 커밋 `02a5c34`, 2026-05-29)을 빌드해
직접 확인한 결과다. 다시 조사하지 말 것.

| 항목 | 확인 결과 |
|------|-----------|
| 레벨 표기 | `context_data->chain_index()`가 **잔여 곱셈 예산과 1:1로 일치**. 신선한 암호문 = maxLevel, 바닥 = 0. OpenFHE처럼 `maxLevel - GetLevel()` 변환이 **필요 없다** |
| 체인 순서 | `coeff_modulus` 벡터의 **첫 원소 = 끝까지 살아남는 바닥 프라임**(OpenFHE `firstModSize`와 동일 역할), **마지막 원소 = 특수 소수 P**. rescale은 뒤에서부터 scale 프라임을 제거 |
| 보안 등급 | small/medium은 `sec_level_type::tc128`에서 **거부됨** → `sec_level_type::none` 필수 (OpenFHE `HEStd_NotSet`과 동일 성격). **large(logN 15)는 tc128을 통과함** — §4 비대칭 주의 |
| key-switch 구조 | 특수 소수 **1개**, 분해 digit 수 = 해당 레벨의 데이터 프라임 수. RelinKeys digit 수 실측: small 6 / medium 11 / large 16 |
| 8-op API | 전부 out-of-place 형태 존재. `multiply` → size-3, `relinearize` → size-2, `rescale_to_next` → chain_index −1. 모두 동작 확인 |
| 병렬화 | `native/src/seal/` 전체에 `#pragma omp` **0건**. 단건 연산 내부 병렬화 없음 → Lattigo와 동일하게 `1t == mt` |
| 정밀도 | scale 45에서 `mul_cp+rescale` 33.8비트, `mul_cc+relin+rescale` 33.9비트, `rot1` 34.6비트 |

**최대 함정**: `add_plain` / `multiply_plain`은 평문의 `parms_id`와 `scale`이 암호문과
정확히 일치해야 하고, 아니면 `"scale mismatch"` 예외를 던진다. 반드시
`encoder.encode(msg, ct.parms_id(), ct.scale(), pt)` 형태로 레벨별 평문을 새로 만들 것.

---

## 1. 빌드 (검증된 레시피, 외부 의존성 0개)

저장소는 `openfhe-src/` + `openfhe-install/`를 루트에 평평하게 두는 관례를 쓰고 있다.
**SEAL도 같은 관례를 따른다** — `seal-src/`, `seal-install/`.

```bash
cd /data/yja/he-bench
git clone --depth 1 https://github.com/microsoft/SEAL.git seal-src
cd seal-src
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/data/yja/he-bench/seal-install \
  -DSEAL_BUILD_DEPS=OFF -DSEAL_USE_MSGSL=OFF -DSEAL_USE_ZLIB=OFF -DSEAL_USE_ZSTD=OFF \
  -DSEAL_USE_INTEL_HEXL=OFF \
  -DSEAL_BUILD_EXAMPLES=OFF -DSEAL_BUILD_TESTS=OFF -DSEAL_BUILD_BENCH=OFF \
  -DBUILD_SHARED_LIBS=ON
cmake --build build -j"$(nproc)"
cmake --install build
```

`.gitignore`에 `openfhe-src/`·`openfhe-install/`가 어떤 형태로 들어가 있는지 확인하고
`seal-src/`·`seal-install/`도 **같은 형식으로** 추가할 것.

> **`SEAL_USE_INTEL_HEXL=OFF`는 타협 불가.** `PROJECT_CONTEXT.md §2`에서 OpenFHE를
> HEXL OFF로 맞춘 이유(epyc4t와 빌드 조건 일치)가 그대로 적용된다. dku16c는 AVX-512가
> 있어서 켜면 SEAL만 부당하게 유리해진다. HEXL 실험을 하려면 파일명에 `_hexl`을 붙여 분리.
>
> `-DBUILD_SHARED_LIBS=ON`은 OpenFHE 빌드(shared)와 맞춘 것. 정적으로 해도 무방하나
> 조건을 통일하는 편이 낫다.

컴파일은 **루트 `CMakeLists.txt`에 타깃을 추가하는 방식**으로 한다.
`openfhe_bench.cpp` 타깃이 어떻게 정의돼 있는지 먼저 읽고 같은 패턴으로 `seal_bench`를 추가할 것
(빌드 디렉터리 관례도 `build_openfhe/`를 따라 `build_seal/` 등으로 맞춘다).

SEAL은 `find_package(SEAL 4.3 REQUIRED)` + `target_link_libraries(seal_bench SEAL::seal)`로 붙는다.
`CMAKE_PREFIX_PATH`에 `/data/yja/he-bench/seal-install`을 넣어주면 찾는다.

참고 — 아래 단일 명령으로도 빌드는 되지만, 저장소 관례에서 벗어나므로 검증용으로만 쓸 것:
```bash
g++ -O2 -std=c++17 seal_bench.cpp \
  -I seal-install/include/SEAL-4.3 -L seal-install/lib -lseal-4.3 -o seal_bench
```

---

## 2. 체인 매핑 (§3 정합 기준의 핵심)

`coeff_modulus = { firstMod, scale × maxLevel, P }` — 순서 중요.

| preset | logN | N | coeff_modulus 비트 리스트 | Q(=firstMod+L·45) | 데이터 프라임 수 |
|--------|------|---|---------------------------|-------------------|------------------|
| small  | 13 | 8192  | `{50, 45×5,  60}` | 275 bit | 6 |
| medium | 14 | 16384 | `{55, 45×10, 60}` | 505 bit | 11 |
| large  | 15 | 32768 | `{60, 45×15, 60}` | 735 bit | 16 |

- Q 체인은 OpenFHE/Lattigo와 **비트 단위로 일치**한다 → §3 최대 강점 유지.
- **P는 SEAL에서 자동 결정되지 않으므로 60비트 단일 특수소수로 명시 고정했다.**
  §3은 "P/dnum은 각 라이브러리가 자동 결정"이라고 적혀 있는데 SEAL은 예외다.
  이 선택(SEAL 관례상 최대 프라임 크기 = 60비트)을 README와 발표자료 각주에 **반드시 명시**할 것.
- 따라서 logQP는 세 라이브러리가 서로 다르다. Q만 일치, QP는 불일치 — 기존
  "동일이 아니라 비교 가능" 표현을 SEAL에도 그대로 적용한다.

---

## 3. 해야 할 일

### 3.1 하네스
`seal_bench.cpp` 참조 구현이 함께 제공된다. 컴파일·실행 확인까지 끝난 상태다. 할 일:

1. **CSV 스키마를 기존 파일에 맞출 것.** 참조 구현의 헤더는 임시다.
   `results_openfhe_small_1t_dku16c.csv` 같은 기존 파일을 **먼저 읽어서** 컬럼명·순서·
   단위를 그대로 복제할 것. 추측하지 말 것.
2. 파일명 규칙 준수: `results_seal_{preset}_{1t|mt}_dku16c.csv` (§4).
3. `aggregate.py`의 스키마 게이트와 접미사 가드에 `seal`을 허용 라이브러리로 추가.
   **게이트를 느슨하게 만들지 말고 `seal`만 추가할 것** — §5.3의 조용한 오염 방지가 목적이다.

참조 구현이 이미 지키고 있는 것 (변경 시 깨뜨리지 말 것):
- `std::chrono::steady_clock`만 사용 (§4)
- **반복마다 개별 계측** 후 평균·표본표준편차(n−1) 산출 → 기존 `relin std_us=0` 문제 재발 방지
- 전 연산 out-of-place → 입력 암호문 무오염 (§4). `relin` 단독 측정용 size-3 암호문은
  타이머 **밖에서** 생성
- 레벨 진입은 `mod_switch_to_inplace`로 (rescale 반복이 아니라) — scale 드리프트 회피
- Galois 키는 step 1만 생성 (large에서 전체 생성하면 메모리·시간 낭비)

### 3.2 실행
`run_openfhe_dku16c.sh` / `run_lattigo_dku16c.sh`를 읽고 같은 형식으로
**`run_seal_dku16c.sh`를 만들 것** (로그 처리, 출력 경로, 에러 처리 관례를 그대로 따른다).

내용의 골자:
```bash
for p in small medium large; do
  ./seal_bench -preset $p -reps 30 -warmup 3 -machine dku16c -threads 1t \
    -out results_seal_${p}_1t_dku16c.csv
  ./seal_bench -preset $p -reps 30 -warmup 3 -machine dku16c -threads mt \
    -out results_seal_${p}_mt_dku16c.csv
done
```
> SEAL은 내부 병렬화가 없으므로 `1t`/`mt`는 동일한 조건이다. 스키마 정합을 위해 두 파일을
> 모두 만들되, **두 파일이 통계적으로 같은지 확인하고** 그 사실을 결과 해석에 명시할 것.
> 다르게 나오면 그건 머신 노이즈이므로 원인을 조사할 것.

### 3.3 검증 게이트 (§5 — 건너뛰지 말 것)
1. **정성 검증**: `-reps 5`로 레벨↓ 시 단조 감소, `relin/rot1 ≫ mul_cc ≫ add` 확인.
2. **정밀도 검증**: 알려진 값 암호화 → 연산 → 복호 → `-log2(mean|err|)`.
   위 표의 33~34비트 근처가 나와야 한다. 크게 벗어나면 체인 매핑이 틀린 것이다.
   **지연시간만 재고 넘어가면 안 된다** — OpenFHE에서 조용한 파탄을 겪은 이력이 있다.
3. **PNG 육안 확인**: 3자 비교로 범례·색상·티어 그룹핑이 깨질 가능성이 높다.
   정상 종료 ≠ 그림 정상 (§5.4).
4. **커밋**: 산출물은 `.gitignore` 대상이므로 `git add -f`. 측정 직후 즉시 커밋 (§5.5).

---

## 4. 결과 해석 시 주의할 점

> ⚠️ 아래는 **실측 완료 후 갱신된 서술**이다. 수치 정본은 `PARAMS_dku16c.md`.

- **`sec_level` 비대칭**: SEAL 기준 large만 tc128을 통과한다(logQP 795 ≤ 881).
  세 프리셋 모두 `none`으로 통일해 측정하되, "보안 미검증" 단서가 SEAL에서는
  small/medium에만 실질적으로 해당한다는 점을 README에 정확히 적을 것.
  ⚠️ **이 비대칭은 라이브러리마다 다르다** — 같은 large에서 Lattigo(855)도 상한 이내지만
  **OpenFHE는 1035로 초과**한다. 실효 보안은 `logQ`가 아니라 **`logQP`**로 판정해야 한다
  (하이브리드 key-switch의 평가키는 QP 위에 정의된다). `PROJECT_CONTEXT.md §3` 참조.
- **digit 수는 세 라이브러리 모두 레벨의 함수다** — 차이는 증가 기울기다
  (**SEAL 1.00 / Lattigo 0.50(small은 1.00) / OpenFHE 0.17~0.50**).
  - ⚠️ 이 문서의 이전 판에 있던 "OpenFHE는 dnum 3 고정, Lattigo는 6~8, SEAL만 dnum이
    레벨의 함수"는 **틀린 서술이었다.** `numPartQ=3`은 최상위 레벨의 상한이지 고정값이
    아니다(large 실제 수열 `3,3,3,3,2,2,2,2,2,2,1,1,1,1,1`). Lattigo의 6~8도 maxLevel 값이다.
  - **SEAL의 digit이 OpenFHE보다 적은 레벨은 없다.** 저레벨에서 SEAL이 빠른 이유는
    digit이 적어서가 아니라 **OpenFHE가 레벨과 무관하게 고정 크기 P(특수소수 2/4/5개,
    logP 120/240/300)를 항상 운반**하기 때문이다. SEAL은 어느 레벨에서나 60비트 1개.
  - **실측 결과**: relin의 레벨 대비 곡률은 AICc 기준 **SEAL 세 프리셋 모두 2차**,
    **Lattigo 2차(계수는 SEAL의 약 0.6~0.7배)**, **OpenFHE는 small에서 1차·medium 보류·
    large 약한 2차**. 사전 프로브의 "명확한 초선형 미관측"은 노이즈 때문이었고,
    코어 고정 + 사전 가열 조건에서 재측정하니 SEAL의 2차가 명확히 나온다(R² 0.9995~1.0000).
  - SEAL↔OpenFHE 교차(정정본, 정본은 `PARAMS_dku16c.md §4.1`):
    **small·medium은 교차 없음**(최근접 0.611·0.908), **large만 교차**하며
    relin **L≈9.1**(±2%: 8.92~9.35) / rot1 **L≈8.6**(±2%: 8.47~8.78).
    ⚠️ 이 문서 이전 판의 `medium L≈9.8, large L≈8.5`는 두 가지가 겹친 오류다 —
    ⑴ relin이 파생값이었고 ⑵ 교차 산출이 '마지막 교차'를 집었다. 둘 다 수정됐다.
- **부트스트래핑**: SEAL CKKS에는 없다. `bootstrap-bench`는 2자 비교로 유지.
