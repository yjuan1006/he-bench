#!/usr/bin/env python3
"""explore/ 의 탐색 측정 CSV → 콘솔 표. 프리셋 확정 전 단계이므로 게이트 판정은 하지 않는다.

  실험1: python3 scripts/presetsearch_table.py exp1
  실험2: python3 scripts/presetsearch_table.py exp2

정밀도는 실험 1에만 있다. KS 손실은 **같은 rep끼리 짝지어** 낸다 —
평균끼리 빼면 반복 간 상관이 사라져 SE가 과대평가된다(OpenFHE rot1은 산포가 크다).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPLORE = os.path.join(ROOT, "explore")
LIB_ORDER = {"openfhe": 0, "lattigo": 1, "seal": 2}
OPS1 = ["mul_cc", "mul_cc_rlk", "relin", "rot1"]
OPS2 = ["add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"]


def load(name):
    p = os.path.join(EXPLORE, name)
    if not os.path.exists(p):
        sys.exit(f"[missing] {p} — scripts/run_presetsearch.sh 를 먼저 돌릴 것")
    d = pd.read_csv(p)
    bad = d[d.ok != 1] if "ok" in d.columns else d.iloc[0:0]
    if len(bad):
        print(f"※ 컨텍스트 생성 실패 {len(bad)}건:")
        for _, r in bad.iterrows():
            print(f"   {r.library} Δ={r.delta} — {r.err}")
        print()
    return d[d.ok == 1].copy() if "ok" in d.columns else d


def precision_by_cfg():
    """(library, dnum, PCount) → (enc_dec, rot1, KS손실, SE)."""
    p = os.path.join(EXPLORE, "exp1_p_search_precision.csv")
    if not os.path.exists(p):
        return {}
    d = pd.read_csv(p)
    piv = d.pivot_table(index=["library", "dnum", "PCount", "rep"],
                        columns="path", values="bits").reset_index()
    piv["loss"] = piv["enc_dec"] - piv["rot1"]
    out = {}
    for (lib, dn, pc), g in piv.groupby(["library", "dnum", "PCount"]):
        out[(lib, int(dn), int(pc))] = (
            g["enc_dec"].mean(), g["rot1"].mean(), g["loss"].mean(),
            g["loss"].std(ddof=1) / np.sqrt(len(g)))
    return out


def exp1():
    d = load("exp1_p_search_timing.csv")
    prec = precision_by_cfg()
    hdr = (f"{'lib':8} {'dnum':>4} {'PCnt':>4} {'logP':>4} {'logQP':>5} {'여유':>4} "
           f"{'level':>5} {'op':11} {'mean_us':>10} {'std':>8} {'cv':>6} "
           f"{'rot1비트':>8} {'KS손실':>7}")
    print(hdr)
    print("-" * len(hdr))
    # logP 240 에 dnum 3·4 가 함께 있으므로 dnum 까지 정렬 키에 넣어야 조합이 뭉친다.
    d = d.sort_values(["library", "logP", "dnum", "level", "op"],
                      key=lambda c: (c.map(LIB_ORDER) if c.name == "library"
                                     else c.map({o: i for i, o in enumerate(OPS1)})
                                     if c.name == "op" else c))
    prev = None
    for _, r in d.iterrows():
        cur = (r.library, r.dnum, r.level)
        if prev is not None and cur[:2] != prev[:2]:
            print()
        elif prev is not None and cur != prev:
            print("  " + "·" * (len(hdr) - 4))
        prev = cur
        cv = r.std_us / r.mean_us if r.mean_us else float("nan")
        k = (r.library, int(r.dnum), int(r.PCount))
        # 정밀도는 조합당 1값 — 레벨 첫 행(maxLevel)에만 표시해 표를 어지럽히지 않는다.
        if k in prec and int(r.level) == int(r.maxLevel) and r.op == OPS1[0]:
            _, rot1b, loss, _ = prec[k]
            ptxt = f"{rot1b:>8.2f} {loss:>7.2f}"
        else:
            ptxt = f"{'':>8} {'':>7}"
        print(f"{r.library:8} {int(r.dnum):>4} {int(r.PCount):>4} {int(r.logP):>4} "
              f"{int(r.logQP):>5} {int(r.margin):>4} {int(r.level):>5} {r.op:11} "
              f"{r.mean_us:>10.1f} {r.std_us:>8.1f} {cv:>6.3f} {ptxt}")


def exp2():
    d = load("exp2_delta_sweep_timing.csv")
    hdr = (f"{'lib':8} {'Δ':>3} {'logQ':>5} {'logQP':>5} {'op':11} "
           f"{'mean_us':>10} {'std':>8} {'cv':>6}")
    print(hdr)
    print("-" * len(hdr))
    d = d.sort_values(["library", "op", "delta"],
                      key=lambda c: (c.map(LIB_ORDER) if c.name == "library"
                                     else c.map({o: i for i, o in enumerate(OPS2)})
                                     if c.name == "op" else c))
    prev = None
    for _, r in d.iterrows():
        cur = (r.library, r.op)
        if prev is not None and cur != prev:
            print()
        prev = cur
        cv = r.std_us / r.mean_us if r.mean_us else float("nan")
        print(f"{r.library:8} {int(r.delta):>3} {int(r.logQ):>5} {int(r.logQP):>5} "
              f"{r.op:11} {r.mean_us:>10.1f} {r.std_us:>8.1f} {cv:>6.3f}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "exp1"
    if which == "exp1":
        exp1()
    elif which == "exp2":
        exp2()
    else:
        sys.exit("사용법: presetsearch_table.py {exp1|exp2}")
