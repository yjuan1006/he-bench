# explore/boot_params — 부트스트래핑 파라미터 1단계 (격자 탐색)

**측정본이 아니다.** 전부 파라미터 덤프(컨텍스트 생성까지)이고 **keygen·벤치를 돌리지 않았다.**
8-op 쪽 대응물은 `explore/params/` 다. 정본 서술은 `docs/PROJECT_CONTEXT.md §10`,
API 추출 경로는 `docs/PARAMS_dku16c.md §1` 의 부트 항목.

⚠️ **8-op 통합 CSV(`plots/8op/results_combined_v3_*.csv`)에 병합 금지.** 단위도 스키마도 다르다.
⚠️ **보안 상한의 출처가 A~D 와 다르다.** 여기는 Bossuat et al., IACR ePrint 2024/463,
   Table 5.2 의 **1747**(logN 16, λ=128, uniform ternary)을 쓴다. A~D 는
   `seal::CoeffModulus::MaxBitCount(tc128)` 기준(218/438/881)이다. **두 세트를 같은 표에 섞지 말 것.**

## 고정 조건 (두 라이브러리 공통, 탐색 대상 아님)

| 항목 | 값 |
|---|---|
| logN / 슬롯 | 16 / **전체 슬롯 2^15 = 32768** |
| 비밀키 | **dense uniform ternary**, sparse-secret encapsulation **끔** |
| | OpenFHE `SecretKeyDist = UNIFORM_TERNARY` · Lattigo `Xs = Ternary{P:2/3}` + `EphemeralSecretWeight = 0` |
| Lattigo K | **512 명시** (기본 16 을 두면 근사 구간을 넘어 부트가 예외 없이 깨진다) |
| OpenFHE | `FIXEDMANUAL`, `HEStd_NotSet` (링 차원 강제) |
| σ | 각 라이브러리 기본값 (OF 3.19 / LA 3.2) |

## 파일

| 파일 | 무엇인가 | 만든 것 |
|---|---|---|
| `boot_grid_openfhe.csv` | **채택본.** q0 × Δ × 잔여L(3~14) × levelBudget × dnum 격자 (23,386행) | `src/boot_param_dump_openfhe.cpp -mode grid` |
| `boot_grid_lattigo.csv` | **채택본.** q0 × Δ × 잔여L(3~14) × PCount × C2S/S2C 분해깊이 × EvalMod scale (98,496행) | `src/boot_param_dump_lattigo.go -mode grid` |
| `boot_grid_*_Lext.csv` | **보충 스윕 잔여L 15~20.** 지정 격자(3~14)의 최대 L 이 상한에 걸려 답이 잘리는지 확인하려고 별도 파일로 돌렸다 | 같은 도구 `-L-min 15 -L-max 20` |
| `boot_feasible.csv` | **채택본.** 위 넷을 조인해 **양쪽 동시 ok=1** 인 **(q0, Δ, L, levelBudget)** 마다 한 행 (1,281행) | `scripts/boot_feasible.py` |
| `boot_stage2_candidates.csv` | **채택본.** 2단계 실측 후보 (816행) — 분해깊이 2~4 · 양쪽 dnum ≤ 8 · **Δ 전 범위 유지** | 〃 |
| `boot_galois_lattigo.csv` | 분해깊이별 회전키 개수 (Lattigo). levelBudget 의 실제 비용 지표 | `-mode galois` |
| `boot_cf_openfhe.csv` | correctionFactor 규칙 실측 (q0=60, Δ 5점) | `-mode cf` |
| `boot_dnumrule_openfhe.csv` | §8.5 규칙 4·5 가 부트 체인에서도 성립하는지 — **실패하는 dnum 까지 일부러 시도한** 표본 | `-mode dnum` |
| `boot_diag_openfhe.csv` | Set II 재현 격차의 **성분 분해** (단건 7케이스. FLEXIBLEAUTO 대조 1회 포함) | `-mode diag` |
| `boot_diag_lattigo.csv` | Set I 재현 격차의 **성분 분해** (logQ 를 잔여/S2C/EvalMod/C2S 로 쪼갬) | `-mode diag` |
| `boot_repro_openfhe.csv` | 논문 Table 5.8 **Set II** 재현 (도구 검증용) | `-mode repro` |
| `boot_repro_lattigo.csv` | 논문 Table 5.8 **Set I** 재현 (도구 검증용) | `-mode repro` |
| `boot_kcheck_lattigo.csv` | Lattigo K=16 vs K=512 의 EvalMod 레벨 수 대조 | `-mode kcheck` |
| `boot_sanity.txt` · `boot_feasible.txt` · `boot_ceiling.txt` | 콘솔 사본 (boot↔residual 혼동 검사 / 가능 영역 / 상한 걸린 셀) | `boot_sanity.py` · `boot_feasible.py` |

**선정 규칙 (2026-08-11 수정).** `levelBudget`(분해깊이)은 **선정 규칙에서 제외한다** —
계산으로 우열을 정할 근거가 없어 2단계 실측 대상으로 넘긴다. dnum/PCount 최소화는
**levelBudget 을 고정한 안에서만** 적용한다. 그대로 접어서 적용하면 OpenFHE 최적이 전부
`{1,1}` 로 몰리는데, 그 지점은 회전키가 **383개**(분해깊이 4 는 33개)로 최악이다.
자세한 근거는 `PROJECT_CONTEXT.md §10.7-2`.

**재현 격차는 규명됐다** (`PROJECT_CONTEXT.md §10.7-5`). Set II 의 logP +360 은 논문의
"dnum 3" 을 `numPerPartQ` 로 읽어야 맞는 **표기 해석 차이**이고, logQ 격차는 EvalMod 1레벨이다.
해석을 고치면 논문과 **1비트 차이**로 재현된다. Set I 은 `logP`(305)와 잔여 체인(395)이
정확히 일치하고 EvalMod 1레벨이 주 성분이며, S2C·C2S 배분 8~25비트만 미규명이다.
**도구 결함의 근거는 없다.**
⚠️ `boot_diag_openfhe.csv` 의 FLEXIBLEAUTO 두 행은 **원인 규명용 대조 1회**다.
프로젝트 기본은 FIXEDMANUAL 이며, 이 대조는 격차를 설명하지 못했다(logQ·logP 동일).

⚠️ `boot_repro_*.csv` 의 두 세트는 **프리셋 후보가 아니다.** 논문 §5.2 가 "라이브러리 간 비교
목적이 아니다"라고 명시하며 실제로 L 도 Δ 도 서로 다르다. **도구가 맞는지 보는 정답지**로만 쓴다.

## 격자 CSV 스키마

```
library,logN,numSlots,q0,delta,residual_L,
boot_depth,levelBudget_c2s,levelBudget_s2c,evalmod_levels,K,
QCount_boot,logQ_boot,PCount_boot,logP_boot,logQP_boot,
QCount_residual,logQ_residual,logP_residual,logQP_residual,
dnum,maxDigitBits,margin_1747,ok,fail_reason
```

- **`logQP_boot` 이 판정 대상이다. residual 이 아니다.** 폐기된 구 측정(§9.5)의
  OpenFHE 2371 / Lattigo 1788 이 모두 이 값이고 모두 1747 초과였다 — residual 만 보면 못 잡는다.
- 게이트: `ok = 1` ⟺ `q0 − Δ ≤ 7` **그리고** `logQP_boot ≤ 1747`.
- `ok=0` 행은 **버리지 않고 사유를 `fail_reason` 에 남긴다.** 컨텍스트를 아예 만들지 않은
  행(사전 가지치기)도 그 사실을 사유에 적는다 — 조용한 누락을 만들지 않기 위해서다.
- 비트는 **명목(round(log2))** 로 통일한다 (`PARAMS_dku16c.md §8` 과 같은 관례).

## 두 라이브러리의 구조 차이 (제거 대상이 아니라 보고 대상)

- **P 의 개수가 다른 뜻을 갖는다.** OpenFHE 는 컨텍스트 하나에 P 가 하나뿐이라 잔여 구간도
  같은 P 를 쓴다 → `logP_residual == logP_boot`. Lattigo 는 잔여/부트 파라미터가 분리된
  두 객체라 P 도 따로다.
- **P 프라임 크기.** OpenFHE `auxBits = 60` (NATIVEINT=64 상수), Lattigo 기본 **61**.
  각자 최적 조건에 세우는 것이 §8.2 방침이라 그대로 둔다.
- **부트 회로 프라임 크기.** OpenFHE 는 FIXEDMANUAL 에서 부트 회로 전체가 **Δ 크기 프라임**이고,
  Lattigo 는 단계별로 독립이다(C2S 56 / EvalMod scale / S2C 39).
  → Δ 를 낮추면 Lattigo 는 잔여 L 만 늘고 **OpenFHE 는 부트 회로까지 얇아진다.**

## 재현

```bash
cmake -S . -B build_openfhe && cmake --build build_openfhe --target boot_param_dump_openfhe
./build_openfhe/boot_param_dump_openfhe -mode grid  -out explore/boot_params/boot_grid_openfhe.csv
./build_openfhe/boot_param_dump_openfhe -mode cf    -out explore/boot_params/boot_cf_openfhe.csv
./build_openfhe/boot_param_dump_openfhe -mode dnum  -out explore/boot_params/boot_dnumrule_openfhe.csv
./build_openfhe/boot_param_dump_openfhe -mode repro -out explore/boot_params/boot_repro_openfhe.csv

go run src/boot_param_dump_lattigo.go -mode grid   -out explore/boot_params/boot_grid_lattigo.csv -workers 5
go run src/boot_param_dump_lattigo.go -mode kcheck -out explore/boot_params/boot_kcheck_lattigo.csv
go run src/boot_param_dump_lattigo.go -mode galois -out explore/boot_params/boot_galois_lattigo.csv
go run src/boot_param_dump_lattigo.go -mode repro  -out explore/boot_params/boot_repro_lattigo.csv

# 재현 격차 성분 분해 (단건. 격자 아님)
./build_openfhe/boot_param_dump_openfhe -mode diag -out explore/boot_params/boot_diag_openfhe.csv
go run src/boot_param_dump_lattigo.go   -mode diag -out explore/boot_params/boot_diag_lattigo.csv

# 보충 스윕 (잔여 L 15~20) — 지정 격자와 섞지 않는다
./build_openfhe/boot_param_dump_openfhe -mode grid -L-min 15 -L-max 20 \
    -out explore/boot_params/boot_grid_openfhe_Lext.csv
go run src/boot_param_dump_lattigo.go -mode grid -L-min 15 -L-max 20 -workers 5 \
    -out explore/boot_params/boot_grid_lattigo_Lext.csv

.venv/bin/python scripts/boot_verify.py       # (a)~(d) 손계산 대조. 불일치면 exit 1
.venv/bin/python scripts/boot_sanity.py       # boot↔residual 혼동 검사. 이상이면 exit 1
.venv/bin/python scripts/boot_feasible.py     # 공통 가능 영역 + (a)(b)(c) + 2단계 후보
```

소요(dku16c): OpenFHE 격자 약 17분(컨텍스트당 ~1.1초 × 3,956) · Lattigo 격자 약 17분(5워커).
보충 스윕은 각각 6~13분. **keygen 은 없다** — 분 단위인 것은 logN 16 × 최대 43타워
컨텍스트 생성 비용이다.

경로는 `scripts/respath.py`(읽기) · `scripts/respath.sh`(쓰기)의 `boot_*` 규칙이 해석한다.
