# results/leveldrop — 순수 레벨 강하(level drop) 측정 원자료 · **채택본**

논문 5절(레벨 하강 배치 규칙의 정지 조건)용. 프리셋 A~D × 3 라이브러리 × **1t 전용**.
대체본 없음 — 이 디렉터리가 유일본이다.

## 무엇을 쟀나

기존 8-op 의 `rescale` 이 **아니다**. rescale 은 모듈러스를 버리면서 **스케일까지 나누므로**
곱셈 뒤 스케일 관리 연산이고 회로상 위치를 옮길 수 없다. 여기서 재는 것은
**모듈러스만 버리고 스케일은 보존하는** 연산 — 예산만 소모하는 대신 자유롭게 삽입 가능하다.

| library | 함수 | 인자 | 형태 |
|---|---|---|---|
| openfhe | `LevelReduce` / `LevelReduceInPlace` | `levels`(기본 1) | 새 암호문 / 제자리 |
| lattigo | `DropLevelNew` / `DropLevel` | `levels` | 새 암호문 / 제자리 |
| seal | `mod_switch_to_next` / `_inplace` | **없음(1단계 고정)** | 새 암호문 / 제자리 |

스케일 보존 근거(소스)는 `analysis/out/leveldrop_report.md` §1.1 에 인용해 두었다.

## op 4종 — ⚠️ 세 라이브러리의 작업량은 대응하지 않는다

- `leveldrop` — 그 라이브러리가 레벨을 내리는 **가장 싼 정당한 방법**.
  openfhe·lattigo = in-place, **seal = out-of-place**(SEAL 은 O(1) 강하가 없고 제자리 쪽이 더 비싸다).
  → 라이브러리 간 **절대 비용 비교에 쓰지 말 것.** 작업량이 다르다.
- `leveldrop_ip` — 제자리 형태
- `leveldrop_oop` — 새 암호문 반환 형태. **세 라이브러리에서 대응**하므로 작업량 비교는 이쪽으로.
- `clone_only` — 암호문 깊은 복사만. 분해 확인용(`oop ≈ clone_only + ip` 인가).

## 측정 프로토콜

기존 8-op 본측정(`run_main_v3.sh`)과 **완전히 동일**하다: 코어 12 고정 · 30초 사전 가열
(`run_warm.sh`, 유휴 틈 없이 exec) · 전후 DVFS 프로브 · reps 30 / warmup 3 · 레벨 전수.
다른 것은 op 목록뿐이다(`presetsearch_*` 의 새 경로 **exp 9**, `-leveldrop` 플래그).
기존 exp 5/7/8 경로와 CSV 헤더는 **바이트 단위로 그대로**다.

⚠️ **`rep_mode` 열을 반드시 볼 것.**
- `single` — 연산 1회를 30번 재서 평균(기존 8-op 와 동일)
- `batch`  — 타이머 밖에서 K개 사본을 만들고 K회를 한 번에 재서 K로 나눈 값을 30번 반복.
  제자리 강하는 **파괴적**이라 같은 암호문에 반복할 수 없고, Lattigo 는 연산(~30ns)이
  **Go `time.Now()` 호출 오버헤드(86ns)보다 싸서** 단발 계측이 원리적으로 불가능하다.
  이때 `std_us` 는 "K개 평균"의 rep 간 산포라 single 의 std 와 **의미가 다르다**(약 1/√K).
  `batch_k` 열에 K 가 들어 있다.

## 파일

- `results_leveldrop_{A,B,C,D}_timing_1t_dku16c.csv` — 타이밍. 스키마는 8-op 원자료와 같고
  끝에 `batch_k,rep_mode` 2열이 추가된다.
- `results_leveldrop_{A,B,C,D}_verify_1t_dku16c.csv` — 매 레벨의 정확성 검증:
  강하 전후 레벨 · 스케일 · 복호값 최대차 · 복호 정밀도(비트).

## 쓰는 쪽

- `scripts/leveldrop_unify.py` → `explore/leveldrop_summary_timing.csv` · `explore/leveldrop_verify.csv`
- `analysis/leveldrop_net.py` → `analysis/out/leveldrop_report.md`
- ⚠️ `scripts/aggregate.py` 에 **넣지 말 것.** 그쪽 `ALL_OPS` 어휘 게이트는 8-op 전용이고,
  leveldrop op 는 그 어휘 밖이라 정당하게 거부된다. 게이트를 우회하지 말고 위 두 스크립트를 쓴다.
