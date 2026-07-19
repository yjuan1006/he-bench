# HE Library Benchmark — OpenFHE vs Lattigo (CKKS)

CKKS 연산의 **암호문 1개 기준** latency를 OpenFHE(C++)와 Lattigo(Go)에서 측정·비교한다.

## 실행 방법

```bash
# Lattigo (Go)
go run lattigo_bench.go -preset all -reps 30      # → results_lattigo.csv

# OpenFHE (C++, Release)
cmake . && make && ./openfhe_bench -preset all -reps 30   # → results_openfhe.csv

# 집계 + 그래프
# --suffix 와 --openfhe 는 필수 (조용한 반쪽 실행·조건 불명 산출물 방지)
# --lattigo / --openfhe 둘 다 여러 경로를 받는다 — 프리셋 3개를 모두 넘길 것.
./venv/bin/python aggregate.py --suffix _mt \
  --lattigo results_lattigo.csv results_lattigo_medium.csv results_lattigo_large.csv \
  --openfhe results_openfhe_small_mt.csv results_openfhe_medium_mt.csv results_openfhe_large_mt.csv

# 단일코어 조건은 _1t 파일 + 접미사만 바꾼다
./venv/bin/python aggregate.py --suffix _1thread \
  --lattigo results_lattigo.csv results_lattigo_medium.csv results_lattigo_large.csv \
  --openfhe results_openfhe_small_1t.csv results_openfhe_medium_1t.csv results_openfhe_large_1t.csv
#   → plots/8op/ 에 PNG 12장 + results_combined_<suffix>.csv + results_summary_std_<suffix>.csv
```

플래그: `-preset {small|medium|large|all}`, `-reps N`, `-warmup N`, `-out PATH`.

## 프리셋

| preset | logN | ring dim | maxLevel | scale bits |
|--------|------|----------|----------|------------|
| small  | 13   | 8192     | 5        | 45         |
| medium | 14   | 16384    | 10       | 45         |
| large  | 15   | 32768    | 15       | 45         |

각 프리셋에서 level = maxLevel..1 전수 스윕, 8개 op × warmup 3 + 30회 측정, μs 단위 평균/표본표준편차(n-1).

## op 목록

`add_cc`(ct+ct), `add_cp`(ct+pt), `mul_cp`(ct×pt), `mul_cc`(ct×ct relin 없음, degree-2),
`mul_cc_rlk`(ct×ct relin 포함), `relin`(= mul_cc_rlk − mul_cc, 음수 0 clamp),
`rescale`(모듈러스 1개 drop), `rot1`(+1 슬롯 회전).

## ⚠️ 측정 주의 (공정성)

- **파라미터는 벤치마크용 근사치이며 검증된 보안 파라미터가 아님.** OpenFHE는 링차원을 강제하기
  위해 `HEStd_NotSet`을 사용하므로 128-bit 보안이 보장되지 않는다. 상대 비교 목적으로만 사용.
- **스레딩 비대칭:** OpenFHE는 OpenMP로 멀티코어를 기본 사용(`user ≫ real`), Lattigo는 기본
  싱글스레드(`user ≈ real`). 즉 "out of the box" 기본값 비교이며, 코어당 성능을 보려면
  `OMP_NUM_THREADS=1`로 OpenFHE를 재측정해야 한다.
- 최적화 빌드에서만 측정 (Go 기본 / C++ `-O3 -DNDEBUG`). 타이밍은 연산 1회만 감싼다.
- **`OMP_NUM_THREADS`는 Go에 무효.** Lattigo 코어 제한은 `GOMAXPROCS`를 쓸 것.
  CSV의 `thread_mechanism` 컬럼에 실제 적용된 메커니즘과 값이 런타임 실측으로 기록된다.

---

# 부트스트래핑 벤치 (별도 실행파일)

```bash
go run lattigo_boot_bench.go -reps 10 -warmup 3            # 조밀키 boot16
GOMAXPROCS=1 go run lattigo_boot_bench.go -reps 10 -warmup 3
./openfhe_boot_bench -reps 10 -warmup 3
OMP_NUM_THREADS=1 ./openfhe_boot_bench -reps 10 -warmup 3

# key-switch 단건 (부트스트래핑 격차 원인 분해용)
go run lattigo_ks_bench.go -reps 30
./openfhe_ks_bench -reps 30
```

사양·설계 근거는 `BOOTSTRAP_TASK.md` 참조. 부트스트래핑 CSV 스키마는 8-op과 다르다:
`library,preset,logN,numSlots,in_level,out_level,op,mean_us,std_us,reps,key_bytes,peak_rss_mb,limbs_q,limbs_p,thread_mechanism`

**`precision_bits` 행은 μs가 아니라 비트를 담는다** (`mean_us`=평균 정밀도, `std_us`=최악 슬롯 정밀도).

---

## 집계 스크립트와 출력 위치

세 벤치는 단위·의미가 달라(`precision_bits`는 비트, `in_level`/`out_level` 대 `level`)
집계 스크립트를 분리했다. `aggregate.py`에는 스키마 게이트가 있어 다른 벤치 CSV를 넣으면
명시적 에러로 거부한다(조용한 오염 방지).

| 스크립트 | 입력 | CSV 출력 | PNG 출력 |
|---|---|---|---|
| `aggregate.py` | 8-op | `plots/8op/results_combined*.csv` | `plots/8op/` |
| `aggregate_boot.py` | 부트스트래핑 | `results_boot_combined.csv` | `plots/boot/` |
| `aggregate_ks.py` | key-switch 단건 | `results_ks_combined.csv` | `plots/ks/` |

### 발표용 차트

| 파일 | 무엇을 보여주나 |
|---|---|
| `plots/ks/plot_ks_reversal.png` | **핵심 그림.** 단건 rot1 vs 전체 부트스트래핑을 Lattigo=1.0으로 정규화. mt에서 OpenFHE가 기준선 *아래*(0.82x, 더 빠름)였다가 부트스트래핑에서 *위*(1.59x, 더 느림)로 넘어가는 역전이 한눈에 보인다 |
| `plots/boot/plot_boot_summary.png` | 4조건 지연시간(초), 에러바=표본표준편차. 정밀도는 축이 아니라 막대 위 회색 라벨 |
| `plots/boot/plot_boot_density.png` | 조밀/희소 2×2. 희소 대조군이 단일 변수 실험이 아니라는 경고 배너 포함 |

차트 규칙:
- 색은 **엔티티 고정**(lattigo=파랑 `#0072B2`, openfhe=주황 `#D55E00`), 순위에 따라 바뀌지 않는다.
  Okabe-Ito 색맹 안전 조합이며 6검사 통과(CVD ΔE=21.9 / 일반시야 ΔE=31.2 / 대비 ≥3:1).
- **정밀도를 지연시간과 같은 축에 놓지 않는다.** 단위가 다른 두 측정을 한 축에 올리면
  두 스케일의 정렬이 임의라 없는 상관을 만들어낸다. 반드시 텍스트 라벨로만 병기한다.
- 차트 텍스트는 **영문** — 이 환경에 한글 폰트가 없어 한글은 두부박스로 렌더된다.

`aggregate.py`는 세 가지를 **거부(sys.exit)** 한다. 셋 다 "조용한 통과를 막는다"는 같은 원칙이다:

| 가드 | 거부 조건 | 이유 |
|---|---|---|
| 스키마 게이트 | 필수 컬럼 없음 / preset이 small·medium·large 밖 | 부트스트래핑·ks CSV가 섞이면 콘솔엔 안 보이는데 병합 CSV엔 남는다 |
| 접미사 가드 | `--suffix` 미지정 | 조건이 지워진 파일명은 나중에 mt인지 1core인지 판별 불가 |
| OpenFHE 가드 | `--openfhe` 경로 없음 | 예전엔 조용히 Lattigo 단독 진행 → 양쪽 담긴 `_mt` PNG 12장이 반쪽 버전으로 덮어써진 사고 발생 |

`plots/8op/` 안의 24장은 `--suffix _mt`(12장) + `--suffix _1thread`(12장)로 각각 돌린 산출물이다.
접미사 없이 돌리면 `plot_<preset>_<tier>.png` / `plot_summary_<tier>.png` 12장이 나온다.

> 측정 산출물(CSV·PNG)은 **버전 관리 대상**이다. 예전엔 `.gitignore`로 제외했으나
> 잘못된 입력으로 덮어쓴 PNG를 복구하지 못한 사고가 있어 추적으로 전환했다.
> `archive/`의 무효 CSV도 포함한다 — 무엇이 왜 폐기됐는지가 곧 실험 기록이다.

## CSV 파일 목록

### 본 결과 — 8-op (기존)

| 파일 | 역할 |
|---|---|
| `results_lattigo.csv` | Lattigo 8-op, 전 프리셋 (small/medium/large) |
| `results_lattigo_medium.csv` / `results_lattigo_large.csv` | Lattigo 8-op, 프리셋별 분할 |
| `results_openfhe_{small,medium,large}_mt.csv` | OpenFHE 8-op, 멀티코어 |
| `results_openfhe_{small,medium,large}_1t.csv` | OpenFHE 8-op, `OMP_NUM_THREADS=1` |
| `results_lattigo_large_gomaxprocs1.csv` | Lattigo large를 `GOMAXPROCS=1`로 점검. 전 op 2~4% *빨라짐* → 단건 연산 내부 병렬 없음 확인 |

### 본 결과 — 부트스트래핑 (인용은 여기서)

`boot2_` 접두사가 최종본이다. OpenFHE는 scaleMod 59 / FLEXIBLEAUTO 확정 후 재측정한 것.

| 파일 | 조건 | bootstrap | 정밀도 |
|---|---|---|---|
| `results_boot2_lattigo_mt.csv` | `GOMAXPROCS=4` | 23.910 s | 29.74비트 |
| `results_boot2_lattigo_1core.csv` | `GOMAXPROCS=1` | 23.872 s | 29.74비트 |
| `results_boot2_openfhe_mt.csv` | `OMP_NUM_THREADS=4` | 38.098 s | 12.34비트 |
| `results_boot2_openfhe_1core.csv` | `OMP_NUM_THREADS=1` | 60.373 s | 12.33비트 |

> **지연시간만 인용하지 말 것.** 정밀도가 17.4비트 벌어져 있다(scale 2^45 vs 2^59 비대칭).
> Lattigo는 더 빠르면서 동시에 더 정밀하다 — 동일 정밀도 지점의 비교가 아니다.

### 본 결과 — key-switch 단건 (logN 16 / boot16 체인)

| 파일 | 조건 |
|---|---|
| `results_ks_lattigo_{mt,1core}.csv` | Lattigo, `GOMAXPROCS` 4 / 1 |
| `results_ks_openfhe_{mt,1core}.csv` | OpenFHE, `OMP_NUM_THREADS` 4 / 1 |

목적: 부트스트래핑 격차가 단건 key-switch 성능 차이인지 조합 최적화 차이인지 구분.
결과 — mt에서 OpenFHE 단건이 **오히려 18% 빠름**(rot1 323.9 vs 393.5 ms)에도 부트스트래핑은
59% 느림. 부트스트래핑 1회를 rot1 등가로 환산하면 Lattigo 60.8회 vs OpenFHE 117.6회.
→ **조합 최적화(hoisting / lazy reduction) 차이**로 결론.

### 검증·대조군 (본 결과와 섞지 말 것)

| 파일 | 역할 |
|---|---|
| `results_boot_lattigo_sparse_robustness.csv` | Lattigo 희소 프리셋 `N16QP1546H192H32`. 18.240 s / 27.33비트 |
| `results_boot_openfhe_sparse_robustness.csv` | OpenFHE `SPARSE_TERNARY`. 깊이 21→17. 24.48 s / 18.70비트 (warmup 3 재측정) |
| `results_boot_openfhe_fixedmanual_footnote.csv` | FIXEDMANUAL 단일 샘플 각주용. 27.53 s / 10.08비트 |

희소 대 희소로 짝을 맞추면 격차 1.34배로, 조밀 조건의 1.59배와 큰 차이 없다
→ Lattigo 우위는 비밀키 분포에서 오는 것이 아니다.
정밀도는 두 라이브러리에서 **반대 방향**으로 움직인다 (OpenFHE +6.4비트, Lattigo −2.4비트).
단 Lattigo 희소는 프리셋 전체 교체(scale 2^40 등)라 OpenFHE의 단일 변수 실험과 성격이 다르다.

### 초기 파일럿 / 중간 산출 (인용 비권장)

| 파일 | 비고 |
|---|---|
| `results_lattigo_boot.csv` | 최초 Lattigo 파일럿 (reps 1). `boot2_`로 대체됨 |
| `results_boot_lattigo_mt.csv` | 라운드1 Lattigo mt. `boot2_`로 대체됨 |
| `results_boot_lattigo_1core.csv` | 라운드1 `GOMAXPROCS=1` |
| `results_boot_lattigo_omp1_noop.csv` | **`OMP_NUM_THREADS=1`로 돌렸으나 Go에 무효 → 실질 mt 재측정.** 이름이 `_1core`가 아닌 이유 |

### 폐기 — `archive/invalid_scale45/`

`results_openfhe_boot.csv`, `results_boot_openfhe_mt.csv`, `results_boot_openfhe_1thread.csv`.
scaleMod 45 파탄 설정으로 측정됨. 정밀도 음수(신호보다 오차가 큼). **사용 금지.**
예외 없이 정상적인 지연시간을 내놓았기 때문에 시간만 봐서는 파탄을 알 수 없다.
