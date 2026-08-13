#!/usr/bin/env python3
"""v2 본측정 physics_gate + 표.

⚠️ 이 CSV는 aggregate.py 에 넣을 수 없다 — 스키마가 다르고(P 메타데이터 열이 붙는다)
preset 어휘도 v1의 {small,medium,large}가 아니다. aggregate.py 의 preset 게이트가
이 파일을 거부하는 것은 **의도된 동작**이다(v1/v2 혼입 방지).
그래서 게이트 세 가지를 여기에 옮겨 왔다. 임계값 근거는 aggregate.py 상단 주석 그대로:

  G1 std_us == 0 and reps > 1  → 측정값이 아니라 파생값·일괄계측의 흔적
  G2 relin / mul_cc_rlk > 1.02 → relin 단독이 '곱셈+relin'보다 비쌀 수 없다 (1t)
  G3 v[L] / v[L+1] > 1.02 이고 차가 2σ 밖 → 1t 레벨 단조성 위반
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET = "v2n15d40L13"
LIB_ORDER = {"openfhe": 0, "lattigo": 1, "seal": 2}
OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"]
FUSE_RATIO_TOL_1T = 1.02
MONO_RATIO_TOL_1T = 1.02

# ⚠️ 게이트는 **key-switch 계열 한정**으로 적용한다 (2026-08-02 판정).
# Lattigo 경량 op는 Go GC 때문에 이 프로토콜에서 안정적으로 측정되지 않는다:
# 1차 실행은 L4·L12에서 단조성 위반 4건, 2차 실행은 위반 0건인데 두 실행의 경량 op
# 값이 최대 38.6% 어긋난다(중앙 5.4%). 위반 레벨의 교집합이 비어 있어 계통이 아니다.
# 반면 heavy는 두 실행 중앙 0.6% / 최대 4.4%로 재현된다.
# ★ 2차가 전 op 게이트를 통과한 것은 우연이다 — 단조성 검사는 인접 레벨 역전만 보므로
#   전 구간이 함께 밀린 GC 오염은 통과시킨다. 통과했다고 경량 op를 신뢰하면 안 된다.
HEAVY_OPS = ["mul_cc_rlk", "relin", "rot1"]


def physics_gate(df):
    viol = []
    z = df[(df.std_us == 0) & (df.reps > 1)]
    for _, r in z.iterrows():
        viol.append(f"[std=0] {r.library} L{int(r.level)} {r.op} (reps={int(r.reps)})")

    pm = df.pivot_table(index=["library", "level"], columns="op", values="mean_us")
    ps = df.pivot_table(index=["library", "level"], columns="op", values="std_us")
    if {"relin", "mul_cc_rlk"} <= set(pm.columns):
        for idx in pm.index:
            rel, rlk = pm.loc[idx, "relin"], pm.loc[idx, "mul_cc_rlk"]
            if pd.isna(rel) or pd.isna(rlk) or rlk <= 0:
                continue
            if rel / rlk > FUSE_RATIO_TOL_1T:
                viol.append(f"[relin>mul_cc_rlk] {idx} — {rel:.1f}/{rlk:.1f} = {rel/rlk:.4f}")

    for (lib, op), g in df.groupby(["library", "op"]):
        g = g.sort_values("level")
        v, sd, lv = g.mean_us.tolist(), g.std_us.tolist(), g.level.tolist()
        for i in range(len(v) - 1):
            if v[i] > v[i + 1] * MONO_RATIO_TOL_1T and (v[i] - v[i + 1]) > 2 * (sd[i] + sd[i + 1]):
                viol.append(f"[단조성] {lib} {op} L{int(lv[i])}({v[i]:.1f}) > L{int(lv[i+1])}({v[i+1]:.1f})")

    if viol:
        print(f"[physics] ✗ 게이트 위반 {len(viol)}건:")
        for v in viol:
            print("   " + v)
        return False
    print(f"[physics] ✓ 게이트 통과 ({len(df)}행, 1t)")
    return True


def main():
    t = pd.read_csv(respath.find(f"results_{PRESET}_timing_1t_dku16c.csv"))
    bad = t[t.ok != 1]
    if len(bad):
        print(f"※ 컨텍스트 생성 실패 {len(bad)}건")
    t = t[t.ok == 1].copy()

    print("=== 구성 (런타임 API 추출) ===")
    cfg = t.groupby("library").first()[["dnum", "PCount", "logP", "logQ", "logQP",
                                        "bound", "margin", "digits"]]
    for lib in sorted(cfg.index, key=lambda x: LIB_ORDER[x]):
        r = cfg.loc[lib]
        print(f"  {lib:8} dnum={int(r.dnum):>2} PCount={int(r.PCount)} logP={int(r.logP):>3} "
              f"logQ={int(r.logQ)} logQP={int(r.logQP)} 상한={int(r.bound)} 여유={int(r.margin):>3}")
        print(f"           레벨별 digit: {r.digits}")
    print()
    print("--- key-switch 계열 한정 (판정 기준) ---")
    ok = physics_gate(t[t.op.isin(HEAVY_OPS)])
    print("--- 경량 op (참고: 판정에 쓰지 않는다) ---")
    physics_gate(t[~t.op.isin(HEAVY_OPS)])
    print()

    print("=== op × level (mean_us, 1t) ===")
    for op in OPS:
        g = t[t.op == op]
        piv = g.pivot_table(index="level", columns="library", values="mean_us")
        piv = piv[[c for c in ["openfhe", "lattigo", "seal"] if c in piv.columns]]
        print(f"\n-- {op} --")
        print(f"{'L':>3} " + "".join(f"{c:>12}" for c in piv.columns) + "   최속")
        for L in sorted(piv.index, reverse=True):
            row = piv.loc[L]
            win = row.idxmin()
            print(f"{int(L):>3} " + "".join(f"{row[c]:>12.1f}" for c in piv.columns)
                  + f"   {win}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
