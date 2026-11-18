# HEXL 아암 — 8-op × 레벨 전수 (채택본)

프리셋 A, HEXL ON 빌드(`build_openfhe_hexl` / `build_seal_hexl`). 14파일.
- 1t: timing·precision (OpenFHE / SEAL 각각)
- mt: timing **OpenFHE 5런 / SEAL 3런**, precision 은 별도 1런
  (mt 는 타이밍과 정밀도를 분리 실행한다 — `PROJECT_CONTEXT.md §8.6-2`)

분석·집계

| 스크립트 | 산출 |
|---|---|
| `scripts/v3_hexl8_plots.py` | `explore/hexl8_summary_timing.csv` · `explore/hexl8_speedup.csv` + PNG |
| `scripts/hexl8_unify_precision.py` | `explore/hexl8_summary_precision.csv` (`v3_summary_precision.csv` 와 같은 스키마) |

⚠️ Lattigo 는 HEXL 대응물이 없어 측정하지 않는다.
타이밍 요약은 플롯용이라 Lattigo 를 baseline 값으로 함께 싣지만,
**정밀도 요약에는 Lattigo 행이 없다** — 없는 조건을 baseline 으로 채우지 않는다.
⚠️ 두 요약 모두 `v3_summary_*.csv` 에 **병합하지 않는다**(빌드 옵션이 다른 조건).
