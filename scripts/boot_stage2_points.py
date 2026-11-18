#!/usr/bin/env python3
"""2단계 정밀도 곡선의 **측정 대상점**을 뽑는다. 측정은 하지 않는다.

입력  explore/boot_params/boot_stage2_candidates.csv (816행)
출력  explore/boot_params/boot_stage2_points.csv

816행 전수는 시간이 안 되므로 다음 규칙으로 줄인다:
  · 분해깊이 **{3,3} 하나로 고정** — 중간값이고 회전키 39개로 합리적이다
  · 각 (q0, Δ) 마다 **최대 L 한 점만**
  · q0 ∈ {40, 45, 50, 55, 60}  (42는 40·45와 사실상 같은 대역이라 뺀다)
  · Δ 는 **자르지 않는다** — Δ 하한을 찾는 것이 2단계의 목적이다
  · 양쪽 dnum ≤ 8 (입력 CSV 에서 이미 걸러져 있다)

여기에 **L 무관성 확인용 보조점**을 덧붙인다. 8-op 에서는 정밀도가 레벨에 무관했는데
(`PARAMS_dku16c.md §8.4`) 부트에서도 그런지 한 (q0, Δ) 에서 L 을 3~4개 바꿔 본다.

`role` 열로 두 묶음을 구분한다: `curve`(Δ 곡선) / `Lsweep`(L 무관성 확인).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "explore", "boot_params")

LB = (3, 3)
Q0S = [40, 45, 50, 55, 60]
# ⚠️ 곡선 왼쪽 끝 보강. Δ=35 는 `0 < q0 − Δ ≤ 7` 로 q0 ∈ {40, 42} 만 가능하고,
#    Δ=33 은 q0=40 **하나뿐**이다(구조적 제약. dnum 상한을 8→12 로 풀어도 늘지 않는다).
#    그래서 42 를 Δ=35 에 한해 되살린다.
Q0_EXTRA = [(42, 35)]
LSWEEP_AT = (45, 40)          # L 무관성 확인 지점
LSWEEP_N = 4

COLS = ["role", "q0", "delta", "residual_L", "levelBudget_c2s", "levelBudget_s2c",
        "evalmod_scale_la",
        "boot_depth_of", "dnum_of", "PCount_boot_of", "logP_boot_of", "logQP_boot_of",
        "margin_1747_of", "boot_depth_la", "dnum_la", "PCount_boot_la", "logP_boot_la",
        "logQP_boot_la", "margin_1747_la", "rotkeys_la"]


def main():
    c = pd.read_csv(respath.find("boot_stage2_candidates.csv"))
    g = c[(c.levelBudget_c2s == LB[0]) & (c.levelBudget_s2c == LB[1]) & (c.q0.isin(Q0S))]
    if g.empty:
        sys.exit("[비었다] 분해깊이/q0 조건에 맞는 후보가 없다")

    mask = pd.Series([(int(q), int(d)) in Q0_EXTRA for q, d in zip(c.q0, c.delta)],
                     index=c.index)
    extra = c[(c.levelBudget_c2s == LB[0]) & (c.levelBudget_s2c == LB[1]) & mask]
    g = pd.concat([g, extra], ignore_index=True).drop_duplicates()

    curve = g.loc[g.groupby(["q0", "delta"]).residual_L.idxmax()].copy()
    curve["role"] = "curve"

    ls = g[(g.q0 == LSWEEP_AT[0]) & (g.delta == LSWEEP_AT[1])].sort_values("residual_L")
    if ls.empty:
        sys.exit(f"[비었다] L 스윕 지점 {LSWEEP_AT} 이 후보에 없다")
    # 최대 L 은 curve 에 이미 있으므로 그 아래에서 고르게 3점을 더 뽑는다
    lo, hi = int(ls.residual_L.min()), int(ls.residual_L.max())
    want = sorted({int(round(lo + (hi - lo) * i / LSWEEP_N)) for i in range(LSWEEP_N)} - {hi})
    lsw = ls[ls.residual_L.isin(want)].copy()
    lsw["role"] = "Lsweep"

    # ⚠️ Lattigo 의 EvalMod scale 은 격자 축인데 격자 CSV 스키마에 열이 없다(지시된 스키마).
    # 체인 구성식으로 **역산**해 되살린다 — 이걸 하네스에 넘기지 않으면 기본값 60 으로 돌아
    # 격자가 고른 조합과 **다른 체인**을 재게 된다(2026-08-12 보정에서 실제로 발생: 1704 → 1834).
    #   logQ_boot = q0 + Δ·L + 39·s2c + scale·evalmod + 56·c2s
    for d in (curve, lsw):
        d["evalmod_scale_la"] = (
            (d.logQ_boot_la - (d.q0 + d.delta * d.residual_L
                               + 39 * d.levelBudget_s2c + 56 * d.levelBudget_c2s))
            / d.evalmod_levels_la).round().astype(int)

    out = pd.concat([curve, lsw], ignore_index=True)
    out = out.sort_values(["role", "q0", "delta", "residual_L"]).reset_index(drop=True)

    os.makedirs(OUTDIR, exist_ok=True)
    f = os.path.join(OUTDIR, "boot_stage2_points.csv")
    out[COLS].to_csv(f, index=False)

    print(f"[points] {os.path.relpath(f, ROOT)}  ({len(out)}점)")
    print(f"  curve  {len(curve)}점 — (q0, Δ)별 최대 L, 분해깊이 {LB}")
    print(f"  Lsweep {len(lsw)}점 — (q0={LSWEEP_AT[0]}, Δ={LSWEEP_AT[1]}) 에서 L "
          f"{sorted(lsw.residual_L.astype(int).tolist())} (곡선점 L={hi} 와 합쳐 {len(lsw)+1}점)")
    print(f"  Δ 커버리지: {sorted(out.delta.unique().astype(int).tolist())}")
    print()
    print(f"{'role':>7}{'q0':>4}{'Δ':>5}{'L':>4}{'OF dnum':>9}{'OF logQP':>10}{'여유':>6}"
          f"{'LA dnum':>9}{'LA logQP':>10}{'여유':>6}")
    for _, r in out.iterrows():
        print(f"{r.role:>7}{int(r.q0):>4}{int(r.delta):>5}{int(r.residual_L):>4}"
              f"{int(r.dnum_of):>9}{int(r.logQP_boot_of):>10}{int(r.margin_1747_of):>6}"
              f"{int(r.dnum_la):>9}{int(r.logQP_boot_la):>10}{int(r.margin_1747_la):>6}")


if __name__ == "__main__":
    main()
