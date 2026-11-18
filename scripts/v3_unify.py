#!/usr/bin/env python3
"""v3 4프리셋 × 1t/mt 를 하나의 요약 CSV 로 합친다.

타이밍과 정밀도는 **단위·의미가 달라 별도 파일**로 낸다
(μs 대 비트, op 대 path — 한 파일에 섞으면 v1 §5 의 '조용한 오염'과 같은 사고가 난다).

출력:
  explore/v3_summary_timing.csv     preset,logN,depth,delta,mode,library,dnum,PCount,logP,
                                    logQP,margin,level,digit,op,mean_us,std_us,cv,reps
  explore/v3_summary_precision.csv  preset,logN,depth,delta,mode,library,dnum,PCount,logP,
                                    level,rep,enc_dec,rot1,ks_loss

`digit` 은 해당 레벨의 digit 수 — 원본 CSV 의 `digits` 문자열("L12=3;L11=3;…")에서 뽑아
레벨별 스칼라로 편다. 이 열이 있어야 성능 곡선과 digit 계단을 한 파일에서 대조할 수 있다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "explore")
PRESETS = [("A", "v3n15d42L12"), ("B", "v3Bn14d42L6"),
           ("C", "v3Cn15d48L10"), ("D", "v3Dn14d42L4")]
MODES = ["1t", "mt"]


def digit_map(s):
    """'L12=3;L11=3;…' → {12: 3, 11: 3, …}"""
    out = {}
    for tok in str(s).split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[int(k.lstrip("L"))] = int(v)
    return out


def main():
    tim, prec = [], []
    for label, pid in PRESETS:
        for mode in MODES:
            tname = f"results_{pid}_timing_{mode}_dku16c.csv"
            pname = f"results_{pid}_precision_{mode}_dku16c.csv"
            if not respath.exists(tname):
                sys.exit(f"[missing] {tname}")
            tp = respath.find(tname)
            pp = pname if not respath.exists(pname) else respath.find(pname)
            t = pd.read_csv(tp)
            t = t[t.ok == 1].copy()
            t["preset"], t["mode"] = label, mode
            dm = {lib: digit_map(g.digits.iloc[0]) for lib, g in t.groupby("library")}
            t["digit"] = [dm[r.library].get(int(r.level)) for _, r in t.iterrows()]
            t["cv"] = np.where(t.mean_us > 0, t.std_us / t.mean_us, 0.0)
            tim.append(t[["preset", "logN", "depth", "delta", "mode", "library",
                          "dnum", "PCount", "logP", "logQP", "margin",
                          "level", "digit", "op", "mean_us", "std_us", "cv", "reps"]])

            if not respath.exists(pname):
                print(f"[note] 정밀도 없음: {pname}")
                continue
            p = pd.read_csv(pp)
            pv = p.pivot_table(index=["library", "dnum", "PCount", "logP", "level", "rep"],
                               columns="path", values="bits").reset_index()
            pv["ks_loss"] = pv["enc_dec"] - pv["rot1"]
            meta = t.groupby("library").first()[["logN", "depth", "delta"]]
            pv = pv.join(meta, on="library")
            pv["preset"], pv["mode"] = label, mode
            prec.append(pv[["preset", "logN", "depth", "delta", "mode", "library",
                            "dnum", "PCount", "logP", "level", "rep",
                            "enc_dec", "rot1", "ks_loss"]])

    os.makedirs(OUT, exist_ok=True)
    dt = pd.concat(tim, ignore_index=True)
    dp = pd.concat(prec, ignore_index=True)
    ft = os.path.join(OUT, "v3_summary_timing.csv")
    fp = os.path.join(OUT, "v3_summary_precision.csv")
    dt.to_csv(ft, index=False)
    dp.to_csv(fp, index=False)
    print(f"[timing]    {ft}  ({len(dt)}행)")
    print(f"[precision] {fp}  ({len(dp)}행)")

    print("\n=== 구성 확인 ===")
    print(f"{'preset':7}{'mode':5}{'lib':9}{'행':>5}{'레벨':>5}{'op':>4}  digit 수열")
    for (pl, md, lib), g in dt.groupby(["preset", "mode", "library"], sort=False):
        seq = ",".join(str(int(x)) for x in
                       g.sort_values("level", ascending=False).groupby("level", sort=False).digit.first())
        print(f"{pl:7}{md:5}{lib:9}{len(g):>5}{g.level.nunique():>5}{g.op.nunique():>4}  {seq}")


if __name__ == "__main__":
    main()
