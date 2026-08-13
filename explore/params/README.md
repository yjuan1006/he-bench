# explore/params/ — 파라미터 탐색 덤프

v3 프리셋을 고르는 과정에서 나온 격자 탐색·정밀도 덤프다. **본측정이 아니다** —
본측정은 `results/` 에 있다. 확정 파라미터의 정본은 `docs/PARAMS_dku16c.md`.

| 접두 | 내용 |
|---|---|
| `params_bc_*` `params_D_*` | 프리셋 B·C·D 후보 격자 (`_grid_` 라이브러리별 / `_optp_` 최적 P / `_precision_` 정밀도) |
| `params_alt_*` | 대안 (depth, Δ) 쌍 15개 탐색 |
| `params_A_dnum_confirm` `params_pconfirm_d12d42` | A 의 dnum·P 선택 확인 |
| `params_openfhe_dnum_sweep` | OpenFHE dnum 유효 조건 전수 대조 (237조합) |
| `params_ks_precision` | key-switch 정밀도 스윕 → `scripts/ks_precision_table.py` 요약표 입력 |

생성 드라이버: `scripts/run_{bc_optp,bc_precision,D_search,alt_precision}.sh` (전부 여기로 떨어진다).
