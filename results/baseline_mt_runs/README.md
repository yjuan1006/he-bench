# baseline mt 반복 런 (`_off8_`) — 채택본

프리셋 A, **HEXL OFF(baseline)** 빌드를 HEXL 아암과 **같은 범위로 대등 재측정**한 mt 원자료다.
8-op × 레벨 전수. OpenFHE 5파일 + SEAL 3파일.

### 어떻게 쓰는가 — 반드시 지킬 것

- **OpenFHE 5런 / SEAL 3런의 중앙값을 쓴다.** 단일 런으로 판정하지 않는다.
  OpenFHE mt 는 런 간 산포가 커서(heavy 기준 런간 `(max−min)/median` 중앙 0.208, **최대 0.459**)
  단일 런이 우연히 어느 쪽에 떨어졌는지로 결론이 뒤집힌다.
  SEAL 은 같은 지표가 중앙 0.002 · 최대 0.008 로 사실상 재현된다.
- **Lattigo 는 반복 런이 없다.** 단일 런을 그대로 쓴다 —
  프리셋 A mt heavy 의 런 내 CV 가 사분위 0.009~0.015(중앙 **0.010**, 최대 0.024)로
  안정적이고, 내부 병렬화가 없어 mt 축에 참여하지 않기 때문이다(`PROJECT_CONTEXT.md §8.7`).
  ⚠️ 참고로 같은 조건 OpenFHE 의 CV 는 중앙 **0.242**(최대 0.513)다 — 자릿수가 다르다.
- ⚠️ **이 값들이 `explore/v3_summary_timing.csv` 의 mt 열(단일 런)을 대체한다.**
  그 요약 CSV 의 mt 는 `results/v3/A/..._timing_mt_dku16c.csv` 단일 런에서 온 것이고,
  프리셋 A 의 mt 를 인용할 때는 **여기 중앙값이 정본**이다.
  (B·C·D 의 mt 는 반복 런 자체가 없어 여전히 단일 런이다 — `PROJECT_CONTEXT.md §9.6-1`.)

분석: `scripts/v3_hexl8_plots.py` 가 HEXL 아암과 짝지어 읽는다.
