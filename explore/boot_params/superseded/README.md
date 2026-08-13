# explore/boot_params/superseded — 폐기된 2단계 후보 목록

`boot_stage2_points.csv` (21점) · `boot_stage2_candidates.csv` (816행) — **폐기**.

폐기 사유 (2026-08-12):
- **`K = 512` / EvalMod 13 / 캡슐화 off** 전제로 뽑았는데, 그 구성은 Lattigo v6.2.0 에서
  **동작하지 않는다** (`PROJECT_CONTEXT.md §10.7-17`, 캡슐화 off 9조합 전수 실패).
- 축이 **Δ 33~58** 이었으나 **Δ ≤ 50 은 OpenFHE 부트가 파탄**난다(§10.7-20, 자릿수 4~6배).

대체본은 `../boot_stage2_points2.csv` (21점, 새 축 · (마) 구성)다.
**삭제하지 않고 보존한다** — 그 목록으로 뽑은 판단 이력이 §10.7 에 남아 있다.
