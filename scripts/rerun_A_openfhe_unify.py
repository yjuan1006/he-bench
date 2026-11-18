#!/usr/bin/env python3
"""rerun_A_openfhe_unify.py — 프리셋 A/OpenFHE 독립 3회 재측정을 하나의 요약 CSV로 합친다.

v3_unify.py 와 동일한 방식(digit 추출, cv 계산)을 쓰되 run 열을 추가한다.
입력: results/rerun_A_openfhe/run{1,2,3}/openfhe_timing.csv (presetsearch_openfhe -exp 5 원본)
출력: results/rerun_A_openfhe/rerun_A_openfhe_summary.csv
  run,preset,logN,depth,delta,mode,library,dnum,PCount,logP,logQP,margin,
  level,digit,op,mean_us,std_us,cv,reps

⚠️ v3_summary_timing.csv 는 건드리지 않는다(별도 파일).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "results", "rerun_A_openfhe")


def digit_map(s):
    out = {}
    for tok in str(s).split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[int(k.lstrip("L"))] = int(v)
    return out


def main():
    frames = []
    for n in (1, 2, 3):
        path = os.path.join(BASE, f"run{n}", "openfhe_timing.csv")
        if not os.path.exists(path):
            sys.exit(f"[missing] {path}")
        t = pd.read_csv(path)
        t = t[t.ok == 1].copy()
        if t.empty:
            sys.exit(f"[empty after ok==1 filter] {path}")
        t["preset"] = "A"
        t["mode"] = "1t"
        t["run"] = n
        dm = digit_map(t.digits.iloc[0])
        t["digit"] = [dm.get(int(lv)) for lv in t.level]
        t["cv"] = np.where(t.mean_us > 0, t.std_us / t.mean_us, 0.0)
        t["library"] = "openfhe"
        frames.append(t[["run", "preset", "logN", "depth", "delta", "mode", "library",
                          "dnum", "PCount", "logP", "logQP", "margin",
                          "level", "digit", "op", "mean_us", "std_us", "cv", "reps"]])
    d = pd.concat(frames, ignore_index=True)
    out = os.path.join(BASE, "rerun_A_openfhe_summary.csv")
    d.to_csv(out, index=False)
    print(f"[summary] {out}  ({len(d)}행)")
    for n, g in d.groupby("run"):
        seq = ",".join(str(int(x)) for x in
                        g.sort_values("level", ascending=False).groupby("level", sort=False).digit.first())
        print(f"  run{n}: {len(g)}행  레벨 {g.level.nunique()}  op {g.op.nunique()}  digit열: {seq}")


if __name__ == "__main__":
    main()
