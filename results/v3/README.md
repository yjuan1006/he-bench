# results/v3/ — 확정 4프리셋 본측정 (채택본)

`PROJECT_CONTEXT.md §8.3` 의 v3 4프리셋. 공통 `q0 60`, FIXEDMANUAL, 링 차원 강제.
각 폴더에 `{timing,precision} × {1t,mt}` 4개가 들어 있다(한 파일에 세 라이브러리가 함께).

| | logN | depth | Δ | logQ | 파일 식별자 |
|---|---:|---:|---:|---:|---|
| **A** | 15 | 12 | 42 | 564 | `v3n15d42L12` |
| **B** | 14 | 6 | 42 | 312 | `v3Bn14d42L6` |
| **C** | 15 | 10 | 48 | 540 | `v3Cn15d48L10` |
| **D** | 14 | 4 | 42 | 228 | `v3Dn14d42L4` |

- 집계: `scripts/v3_gate_table.py <식별자>` · `scripts/v3_unify.py` · `scripts/crossing_points.py v3 {1t|mt}`
- ⚠️ **v1·v2 와 같은 표에 섞지 말 것** — 보안 수준이 다른 조건이다.
- ⚠️ **mt 는 A 를 뺀 B·C·D 가 단일 런이다.** A 의 반복 런은 `../baseline_mt_runs/` 에 있다.
