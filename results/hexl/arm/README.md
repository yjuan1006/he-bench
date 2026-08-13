# HEXL 아암 — 8-op × 레벨 전수 (채택본)

프리셋 A, HEXL ON 빌드(`build_openfhe_hexl` / `build_seal_hexl`). 14파일.
- 1t: timing·precision (OpenFHE / SEAL 각각)
- mt: timing **OpenFHE 5런 / SEAL 3런**, precision 은 별도 1런
  (mt 는 타이밍과 정밀도를 분리 실행한다 — `PROJECT_CONTEXT.md §8.6-2`)

분석: `scripts/v3_hexl8_plots.py` → `explore/hexl8_summary_timing.csv` · `explore/hexl8_speedup.csv`.
⚠️ Lattigo 는 HEXL 대응물이 없어 측정하지 않는다 — baseline 값을 그대로 쓴다.
