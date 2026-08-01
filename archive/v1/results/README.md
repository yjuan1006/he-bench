# archive/v1/results — 구 프리셋(v1) 측정 결과 · 읽기 전용

논문 근거 자료다. 내용을 고치거나 지우지 않는다. 재처리할 때 **디렉터리를 통째로 글롭하지 말 것** —
아래 4개는 8-op 집계(`scripts/aggregate.py`)의 입력이 아니다.

| 파일 | 왜 입력이 아닌가 |
|------|------------------|
| `results_openfhe.csv` | **0바이트 실패 산출물.** 초기 실행 잔여물로 헤더조차 없어 `pd.read_csv`가 `EmptyDataError`로 죽는다. 보존용일 뿐 **입력으로 쓰지 말 것** |
| `results_combined_{1t,mt}_dku16c.csv` | 집계 **출력**(720행 병합본). 다시 넣으면 같은 측정이 이중 계상된다 |
| `results_summary_std_{1t,mt}_dku16c.csv` | 집계 **출력**(cv 요약). `maxLevel` 컬럼이 없어 스키마 게이트가 거부한다 |

집계 입력은 `results_{lib}_{preset}_{1t|mt}_dku16c.csv` **18개**뿐이다
(lib ∈ {lattigo, openfhe, seal} × preset ∈ {small, medium, large} × {1t, mt}).

`results_{lattigo,openfhe}_medium_1t_dku16c_diag.csv` 2개는 스키마도 행 키도 본측정본과
같은 medium 1t 진단본이라 **함께 넣으면 행이 중복된다.** 둘 중 하나만 쓸 것.

측정 조건과 재설계 사유(logQP 미통제 → `large`에서 OpenFHE가 128비트 미달)는
`docs/PROJECT_CONTEXT.md §7` 참조.
