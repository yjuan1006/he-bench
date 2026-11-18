# results/hexl/ — HEXL 아암

Intel HEXL(AVX-512)을 켠 빌드의 별도 실험. **프리셋 A 만** 있다(B·C·D 없음 — 미정리 항목).

| 디렉터리 | 범위 | 상태 |
|---|---|---|
| `arm/` | 8-op × 레벨 전수 (`_hexl8_`) | **채택본** |
| `superseded/` | heavy 3종 × 레벨 3점 (`_hexl_`) | 대체됨 |

⚠️ **baseline 과 같은 표에 섞지 말 것.** 빌드 옵션이 다르다(`PROJECT_CONTEXT.md §2`).
비교 상대는 루트 baseline 이 아니라 **같은 범위로 대등 재측정한 `../baseline_mt_runs/`** 다.
