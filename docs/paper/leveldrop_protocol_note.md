# leveldrop 측정 프로토콜 노트 — 8-op 단발계측과의 차이, 그리고 4장 pass/fail이 유효한 이유

이 문서는 `analysis/out/drop_verification_report.md`(§3의 pass/fail 판정)의 방법론적 근거다.
논문 4장에 drop 비용을 인용할 때 이 문서의 논증을 함께 참조할 것.

---

## 1. 두 프로토콜이 재는 것은 다른 양이다

- **8-op 본측정** (`src/{openfhe,seal}_bench.cpp`, `src/lattigo_bench.go`): 연산 1회를 감싸고
  `reps=30`번 반복 — **단발 계측**. 한 번의 측정값 = `op_cost + Δ_clock`, 여기서 `Δ_clock`은
  타이머 시작·종료 호출 자체의 오버헤드(호출당 1쌍).
- **leveldrop** (`presetsearch_{openfhe,seal,lattigo}` exp 9, `-leveldrop`): 제자리(ip) 강하는
  **파괴적**이라 같은 암호문에 반복 적용할 수 없다. 그래서 타이머 밖에서 `K`개 사본을 만들고
  (`reset()`), 타이머 안에서 `K`회 연속 수행한 뒤(`runK()`) `K`로 나눈다 — **상각 계측**.
  한 번의 측정값 = `mean(op_cost) + Δ_clock / K`.

즉 단발 계측은 매 반복마다 `Δ_clock` 전체를 포함하고, 상각 계측은 `Δ_clock`을 `K`로 희석한다.
`op_cost ≫ Δ_clock`인 연산(add, mul, rescale, relin, rot1 등 모두 수백 ns~수백 μs)에서는 이
차이가 무시 가능해 두 프로토콜의 값이 사실상 같다. 하지만 **`op_cost`가 `Δ_clock`과 같은
자릿수인 연산(Lattigo의 leveldrop_ip)에서는 단발 계측 자체가 원리적으로 불가능하다** — §3.

## 2. K 값과 선정 근거

Lattigo 소스(`src/presetsearch_lattigo.go:133-142`, `batchKFor`):

```go
func batchKFor(logN, level int, budgetBytes int64, kmax int) int {
    ctBytes := 2.0 * float64(level+1) * float64(int64(1)<<uint(logN)) * 8.0
    k := int(float64(budgetBytes) / ctBytes)
    if k < 4    { k = 4 }
    if k > kmax { k = kmax }
    return k
}
```

- `ctBytes` = 암호문 1개 크기 = `2 polys × (level+1) RNS한계 × 2^logN 계수 × 8바이트`.
- 기본 예산 `batchbudget=64MiB`, 상한 `batchkmax=2048`, 하한 `4`.
- 사본 `K`개를 미리 만들 메모리 예산으로 `K`를 역산한다 — 레벨이 높을수록(암호문이 클수록) `K`는
  작아진다.
- 실측 범위(op=`leveldrop_ip`, 전 프리셋 공통): A `K=9~64`, B `K=36~128`, C `K=11~64`,
  D `K=51~128`. 세 라이브러리 모두 같은 `K` 스케줄을 썼다(암호문 바이트 수 산식이 라이브러리
  무관하게 동일 로직으로 계산됨).
- `runK()` 안에서 `reset()`으로 만든 사본 각각에 `DropLevel`을 1회씩 호출 — 즉 `K`회 모두
  **완전한 함수 호출**(파괴적 연산 1회분)이지, 같은 사본을 재사용하는 것이 아니다.

## 3. rep_mode / batch_k 컬럼 — 스키마 확장

`results/leveldrop/results_leveldrop_{A,B,C,D}_timing_1t_dku16c.csv` 헤더는 8-op 원자료의
`library,...,level,op,mean_us,std_us,reps` 뼈대에 프리셋 탐색용 진단열(`exp,q0,delta,depth,
dnum,PCount,logP,logQ,logQP,bound,margin,digits,threads,nthreads,ok,err`)과 함께 **`batch_k`,
`rep_mode` 2열이 끝에 추가**된다.

- `rep_mode=single` — `measure()` 경로. 8-op와 동일한 단발 계측(연산 1회 × reps 30).
  `leveldrop_oop`, `clone_only`가 이 경로다(비파괴적이라 재사용 가능하므로 굳이 배치할 필요
  없음 — 단 Lattigo는 이 두 값 자체를 신뢰하지 않는다, `drop_verification_report.md` §1.2).
- `rep_mode=batch` — `measureBatch()` 경로(§2). `leveldrop_ip`(=정본 `leveldrop`)가 이 경로다.
  **세 라이브러리 전부** `leveldrop_ip`는 `batch`로 쟀다 — OpenFHE·SEAL은 시계 분해능 때문이
  아니라 **파괴적 연산이라 반복 재사용이 안 되기 때문**이다(§1). Lattigo만 시계 분해능 문제까지
  겹친다(§4).
- `batch_k` — 그 행에서 실제 쓰인 `K` 값. `rep_mode=single`이면 `K=1`(사실상 미사용, 형식상 채움).

⚠️ `rep_mode=batch`인 행의 `std_us`는 **"K개 평균"의 rep(30회) 간 산포**이지 단발 계측의 산포와
의미가 다르다 — 참값 산포보다 대략 `1/√K`만큼 작게 보인다. 8-op의 `std_us`와 직접 비교하지 말 것.

## 4. Go `time.Now()` 오버헤드(86ns)와 Lattigo 실측(23~121ns)의 관계

이 저장소(dku16c)에서 사전 실측한 시계 호출 쌍의 최소 간격:

| 시계 | 최소 간격 | 중앙값 |
|---|---|---|
| C++ `std::chrono::steady_clock` | 40 ns | 44 ns |
| Go `time.Now()` | 86 ns | 90 ns |

Lattigo `leveldrop_ip`(=`DropLevel`, 슬라이스 절단, 산술 없음)의 상각 실측값은 **23~121 ns**
(전 A~D·전 레벨, `analysis/out/leveldrop_cost_by_level.csv` 전수 확인) — **Go 시계 호출
오버헤드(86ns)와 같은 자릿수**다. 만약 상각 없이 8-op 방식(단발 계측)으로 쟀다면 매 반복마다
`op_cost(23~121ns) + Δ_clock(~86ns)` 전체를 더한 값이 나와, 참값의 최대 4~5배까지 부풀려진
숫자를 참값인 것처럼 보고했을 것이다 — 단발 계측이 **원리적으로 이 연산에는 적용 불가**하다.

**`batch_k` 상각이 이 문제를 어떻게 처리했는가**: `Δ_clock`은 `reset()`(사본 K개 생성) 이후,
`runK()`(K회 연산) 전체를 감싸는 **단 한 쌍**의 `time.Now()`/`time.Since()`만 부담한다. 즉 실측값
= `mean(op_cost) + Δ_clock/K`이고, 최소 `K=4`(코드 하한)에서도 `Δ_clock/K ≤ 86/4 = 21.5ns`,
실제 관측된 `K`(9~128)에서는 `Δ_clock/K`가 0.7~9.6ns로 더 작아진다. 시계 오버헤드를 op_cost
자체보다 한 자릿수 이상 작게 눌러 순수 연산비용에 근접시킨 것이 상각의 존재 이유다.

## 5. 그럼에도 pass/fail(§3, `drop_verification_report.md`)이 유효한 이유 — 수치 논증

프로토콜 차이가 만들어낼 수 있는 **최악의 편향 상한**은 `Δ_clock` 전체(상각을 걷어냈다고 가정한
가장 비관적인 경우) — Lattigo 86ns, OpenFHE/SEAL(C++) 40ns다. 이 상한을 각 라이브러리의
`leveldrop_ip` 실측 최댓값에 **더해도** 4장 결론(§3의 pass/fail, §2의 자릿수 비교)이 흔들리는지
확인한다.

| library | leveldrop_ip 실측 최댓값(전 A~D) | +Δ_clock 상한 적용 시 | 전이점 최소 step_gain(45쌍 중) | 여유배수 |
|---|---|---|---|---|
| lattigo | 0.121 μs | 0.121+0.086 = 0.207 μs | 2012.49 μs (B, 계단) | **9720배** |
| openfhe | 2.020 μs | 2.020+0.040 = 2.060 μs | 3715.57 μs (B, 계단) | **1803배** |
| seal | 867.368 μs | 867.368+0.040 ≈ 867.4 μs | (SEAL은 전이점 미분류 — §3 참고 84쌍 최소 step_gain으로 대체) | 아래 참고 |

(SEAL 참고: `drop_verification_passfail_all.csv`에서 SEAL 84쌍 중 최소 `step_gain`으로도 §3
표에서 84/84 전부 pass 확인됨 — 자릿수 비교 §2에서 rescale 대비 최악 8.2%이므로 40ns 가산은
비율에 영향 없음.)

**결론: 프로토콜(단발 vs 상각) 차이로 발생 가능한 최대 편향(40~86ns)을 가장 비관적으로 더해도,
가장 타이트한 전이점 쌍조차 최소 1800배 이상 여유가 있다.** §3에서 실측된 최악 여유폭(OpenFHE
D·rot1·L2, drop/gain=0.030%)에 40ns를 더해도 0.033% 수준으로 결론에 영향 없다. **자릿수 차이가
프로토콜 차이를 압도한다.**

## 6. 원자료 불일치 1건 — 처리 명시

`leveldrop_net.csv`(A·lattigo·mul_cc_rlk·L10)의 `drop_leveldrop=0.097μs`과
`leveldrop_cost_by_level.csv`의 동일 지점 `leveldrop_ip=0.081μs`이 다르다(둘 다 2026-08-19
동일 측정 배치에서 나온 서로 다른 집계 산출물).

- **`leveldrop_cost_by_level.csv`를 정본으로 채택**했다 — 원시 `presetsearch_lattigo` 출력에
  가장 가까운 조인이고(`drop_verification_report.md`가 참조하는 모든 표가 이 파일을 소스로
  쓴다), `leveldrop_net.csv`는 이 위에 8-op `mean_hi/mean_lo`를 추가로 조인한 2차 가공물이라
  조인 과정에서 반올림·재계산 차이가 들어갔을 가능성이 있다.
- 두 값 모두 이 지점의 `cv=0.2346`(23.5%) 대역 안에 있다 — `0.081`과 `0.097`의 차이(약 20%)는
  측정 잡음으로 충분히 설명된다. 어느 쪽도 "틀렸다"고 단정할 근거는 없다.
- ⚠️ **이 지점은 어차피 Lattigo `leveldrop_ip`이므로 §4~§5의 규정("점추정 인용 금지, 자릿수
  대역만 서술")이 그대로 적용된다.** 즉 이 불일치를 "어느 값이 맞는가"로 풀 필요 자체가 없다 —
  두 값 다 인용 대상이 아니기 때문이다. **두 판정(원자료 불일치 처리 vs Lattigo 재측정불가
  규정)은 충돌하지 않는다** — 후자가 전자를 포함한다.

## 7. Lattigo 서술 형식 — 점추정 대신 자릿수 대역

**형식**: "Lattigo의 `leveldrop_ip` 비용은 **10¹~10² ns 대역**(실측 23~121ns, 전 A~D·전 레벨)이며,
개별 재실행 간 최대 89% 편차가 있어 점추정치는 인용하지 않는다."

이 형식으로도 §3·§5의 pass/fail 논증은 그대로 성립한다 — 자릿수 대역의 **상한을 사용해도**
결론이 안 바뀌기 때문이다. 대역 상한을 하이퍼-보수적으로 한 자릿수 더 올려 `10³ ns = 1μs`를
가정해도:

```
1 μs (하이퍼보수 상한) vs 최소 step_gain 2012.49 μs (B, 계단)
→ 여유배수 2012배 — 여전히 pass
```

즉 "정확히 몇 ns인가"를 모르는 채로도(대역·심지어 그 대역보다 10배 큰 값을 가정해도) "계단
이득보다 무시할 만큼 작다"는 결론은 무너지지 않는다. 이것이 §5의 여유배수 논증과 결합되는
지점이다 — Lattigo는 정밀 수치 없이도 정성적 결론(무시 가능)을 안전하게 유지한다.
