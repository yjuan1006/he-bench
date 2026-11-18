# results/ — 측정 CSV

2026-08-08 개편. 그 전에는 68개가 전부 리포 루트에 평평하게 쌓여 있었다. **삭제 없이 `git mv` 만** 했다.

| 디렉터리 | 내용 | 상태 |
|---|---|---|
| `v3/A` `v3/B` `v3/C` `v3/D` | 확정 4프리셋 본측정 (1t·mt × timing·precision) | **채택본** |
| `hexl/arm` | HEXL 아암 — 8-op × 레벨 전수 | **채택본** |
| `hexl/superseded` | HEXL 아암 — heavy 3종 × 레벨 3점 (`arm` 이 대체) | 대체됨 |
| `baseline_mt_runs` | baseline mt 반복 런 원자료 (`_off8_`) | **채택본** |
| `baseline_mt_runs/superseded` | 같은 것의 축소 범위판 (`_off_`) | 대체됨 |
| `v2_discarded` | 폐기된 v2 프리셋 — 대조군으로 보존 | 폐기(보존) |

- 구 프리셋(v1) 측정본은 여기가 아니라 **`archive/v1/results/`** 에 있다. 읽기 전용이다.
- 파라미터 탐색 단계의 덤프는 **`explore/params/`**.
- **위치 해석은 스크립트가 알아서 한다** — 읽는 쪽은 `scripts/respath.py`,
  쓰는 쪽(`run_*.sh`)은 `scripts/respath.sh` 가 파일명만 보고 목적지를 정한다.
  같은 이름이 두 곳에 있으면 조용히 하나를 고르지 않고 **중단**한다.
- ⚠️ `.gitignore` 의 `results_*.csv` 패턴은 이 트리에서 `!results/**/*.csv` 로 무효화돼 있다.
  예외를 지우면 새 측정본이 조용히 무시된다.
