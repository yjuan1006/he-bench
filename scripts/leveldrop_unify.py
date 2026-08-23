#!/usr/bin/env python3
"""leveldrop_unify.py — 프리셋 A~D × 3 라이브러리 leveldrop 원자료를 요약 CSV 로 합친다.

`v3_unify.py` 를 건드리지 않고 **같은 스키마 규약**을 따른다(그 파일은 8-op 전용이다).
출력 스키마 = v3_summary_timing.csv 와 동일 + 배치 계측 구분 2열:

  preset,logN,depth,delta,mode,library,dnum,PCount,logP,logQP,margin,
  level,digit,op,mean_us,std_us,cv,reps,batch_k,rep_mode

`digit` 은 원본 CSV 의 `digits` 문자열("L12=3;L11=3;…")에서 레벨별로 편 값이다.
⚠️ digit 의 **정의가 라이브러리마다 다르다**(OpenFHE 만 런타임 실측, SEAL 은 level+1 하드코딩,
   Lattigo 는 외부 재구성). 계단 판정에 쓸 때는 OpenFHE 에만 쓸 것 —
   `analysis/out/level_cost_report.md` §1 참조.

`rep_mode` 는 mean_us 가 어떻게 나온 값인지 구분한다:
  single = 연산 1회를 30번 재서 평균 (기존 8-op 와 동일)
  batch  = 타이머 밖에서 K개 사본을 만들고 K회를 한 번에 재서 K로 나눈 값을 30번 반복.
           파괴적(in-place) 연산이라 같은 암호문에 반복할 수 없고, Go 의 time.Now 호출
           오버헤드(~86ns)보다 연산이 싸서 단발 계측이 불가능하기 때문이다.
           ⚠️ 이때 std_us 는 "K개 평균"의 rep 간 산포라 single 의 std 와 의미가 다르다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "explore")
IN = os.path.join(ROOT, "results", "leveldrop")
PRESETS = ["A", "B", "C", "D"]

COLS = ["preset", "logN", "depth", "delta", "mode", "library", "dnum", "PCount", "logP",
        "logQP", "margin", "level", "digit", "op", "mean_us", "std_us", "cv", "reps",
        "batch_k", "rep_mode"]


def digit_map(s):
    out = {}
    for tok in str(s).split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[int(k.lstrip("L"))] = int(v)
    return out


def main():
    tim, ver = [], []
    for lb in PRESETS:
        tname = f"results_leveldrop_{lb}_timing_1t_dku16c.csv"
        vname = f"results_leveldrop_{lb}_verify_1t_dku16c.csv"
        tp = os.path.join(IN, tname)
        vp = os.path.join(IN, vname)
        if not os.path.exists(tp):
            sys.exit(f"[missing] {tp}")
        t = pd.read_csv(tp)
        t = t[t.ok == 1].copy()
        t["preset"], t["mode"] = lb, "1t"
        dm = {lib: digit_map(g.digits.iloc[0]) for lib, g in t.groupby("library")}
        t["digit"] = [dm[r.library].get(int(r.level)) for _, r in t.iterrows()]
        t["cv"] = np.where(t.mean_us > 0, t.std_us / t.mean_us, 0.0)
        tim.append(t[COLS])
        v = pd.read_csv(vp)
        v["preset"] = lb
        ver.append(v)

    os.makedirs(OUT, exist_ok=True)
    dt = pd.concat(tim, ignore_index=True)
    dv = pd.concat(ver, ignore_index=True)
    ft = os.path.join(OUT, "leveldrop_summary_timing.csv")
    fv = os.path.join(OUT, "leveldrop_verify.csv")
    dt.to_csv(ft, index=False)
    dv.to_csv(fv, index=False)
    print(f"[timing] {ft}  ({len(dt)}행)")
    print(f"[verify] {fv}  ({len(dv)}행)")

    print("\n=== 구성 확인 ===")
    print(f"{'preset':7}{'lib':9}{'행':>5}{'레벨':>5}{'op':>4}  ops")
    for (pl, lib), g in dt.groupby(["preset", "library"], sort=False):
        print(f"{pl:7}{lib:9}{len(g):>5}{g.level.nunique():>5}{g.op.nunique():>4}  "
              + ",".join(sorted(g.op.unique())))

    print("\n=== 검증 요약 (레벨 -1 / 스케일 보존 / 복호값 불변) ===")
    dv["scale_ok"] = np.isclose(dv.scale_ratio, 1.0, rtol=0, atol=1e-12)
    dv["lvl_ok"] = dv.ok == 1
    s = dv.groupby(["preset", "library"]).agg(
        n=("ok", "size"), lvl_ok=("lvl_ok", "sum"), scale_ok=("scale_ok", "sum"),
        maxdiff_max=("max_abs_diff", "max"),
        dbits_max=("bits_after", lambda x: 0.0)).reset_index()
    dv["dbits"] = (dv.bits_after - dv.bits_before).abs()
    s["dbits_max"] = dv.groupby(["preset", "library"])["dbits"].max().values
    print(s.to_string(index=False))
    bad = dv[(~dv.lvl_ok) | (~dv.scale_ok)]
    print(f"\n검증 실패 행: {len(bad)}")
    if len(bad):
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
