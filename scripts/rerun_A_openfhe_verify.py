#!/usr/bin/env python3
"""rerun_A_openfhe_verify.py — 프리셋 A/OpenFHE 독립 3회 재현성 판정.

입력: results/rerun_A_openfhe/rerun_A_openfhe_summary.csv (run 열 포함)
    + explore/v3_summary_timing.csv (기준값 대조용, 읽기 전용)

산출(콘솔):
  1) 회차별 분리 판정 (mul_cc_rlk/relin/rot1 합산, g(L)=c(L-1)/c(L))
  2) v3 기준값 대조
  3) 실행 간 변동계수(각 op,level 의 3회 mean_us 에 대한 cv)
  4) rescale 대조군 — 전이/비전이 겹침 확인
  5) (선택) Monte Carlo 95% 구간 — 표준오차 기반 20만 회 표집

물리 정합 게이트(사전 확인):
  - relin > mul_cc_rlk 인 행
  - reps>1 인데 std_us==0 인 행
  - 1t 레벨 단조성 위반(레벨이 내려가는데 mean_us 가 오히려 오르는 행) — op별로 확인
위반이 있으면 중단하지 않고 표시만 한다(자동 삭제 금지 지시).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "results", "rerun_A_openfhe")
SUMMARY = os.path.join(BASE, "rerun_A_openfhe_summary.csv")
V3REF = os.path.join(ROOT, "explore", "v3_summary_timing.csv")

KS_OPS = ["mul_cc_rlk", "relin", "rot1"]


def g_pairs(sub, ops):
    """sub: 한 run 의 DataFrame. ops 로 묶어 인접 레벨쌍 g(L)=c(L-1)/c(L) 을 낸다."""
    rows = []
    for op in ops:
        m = sub[sub.op == op].set_index("level")
        for L in sorted(m.index):
            if L - 1 in m.index:
                lo, hi = m.loc[L - 1], m.loc[L]
                rows.append(dict(op=op, level=L, g=lo.mean_us / hi.mean_us,
                                  step=int(lo.digit) != int(hi.digit)))
    return pd.DataFrame(rows)


def main():
    if not os.path.exists(SUMMARY):
        sys.exit(f"[missing] {SUMMARY} — 먼저 rerun_A_openfhe_unify.py 를 돌릴 것")
    d = pd.read_csv(SUMMARY)

    print("=" * 78)
    print("0) 물리 정합 게이트")
    print("=" * 78)
    violations = []
    for run, g in d.groupby("run"):
        m = g.set_index(["op", "level"])
        for L in g.level.unique():
            try:
                rlk = m.loc[("mul_cc_rlk", L)].mean_us
                rel = m.loc[("relin", L)].mean_us
                if rel > rlk:
                    violations.append(f"run{run} L{L}: relin({rel:.1f}) > mul_cc_rlk({rlk:.1f})")
            except KeyError:
                pass
        std0 = g[(g.reps > 1) & (g.std_us == 0)]
        for _, r in std0.iterrows():
            violations.append(f"run{run} {r.op} L{r.level}: reps={r.reps} 인데 std_us==0")
        for op, go in g.groupby("op"):
            go = go.sort_values("level", ascending=False)  # L12 -> L1
            vals = go.mean_us.values
            levels = go.level.values
            for i in range(1, len(vals)):
                if vals[i] > vals[i - 1]:  # 레벨이 내려갔는데(뒤 원소) 비용이 오히려 올랐다
                    violations.append(
                        f"run{run} {op}: L{levels[i-1]}({vals[i-1]:.1f}) -> "
                        f"L{levels[i]}({vals[i]:.1f}) 단조성 위반(내려가는데 증가)")
    if violations:
        print(f"  !! {len(violations)}건 위반 (삭제하지 않음, 아래 나열):")
        for v in violations:
            print("    -", v)
    else:
        print("  위반 없음.")
    print()

    print("=" * 78)
    print("1) 회차별 분리 판정 — mul_cc_rlk/relin/rot1 합산, g(L)=c(L-1)/c(L)")
    print("=" * 78)
    run_results = {}
    for run, g in d.groupby("run"):
        gp = g_pairs(g, KS_OPS)
        st, ns = gp[gp.step].g, gp[~gp.step].g
        sep = st.max() < ns.min() if len(st) and len(ns) else None
        run_results[run] = dict(n_step=len(st), n_nonstep=len(ns),
                                 step_lo=st.min() if len(st) else np.nan,
                                 step_hi=st.max() if len(st) else np.nan,
                                 nonstep_lo=ns.min() if len(ns) else np.nan,
                                 nonstep_hi=ns.max() if len(ns) else np.nan,
                                 gap=(ns.min() - st.max()) if len(st) and len(ns) else np.nan,
                                 separated=sep)
        exp_ok = (len(st) == 6 and len(ns) == 27)
        print(f"  run{run}: n_step={len(st)} (기대 6) n_nonstep={len(ns)} (기대 27) "
              f"{'OK' if exp_ok else '!! 개수 불일치'}")
        print(f"    전이   [{st.min():.3f}, {st.max():.3f}]")
        print(f"    비전이 [{ns.min():.3f}, {ns.max():.3f}]")
        print(f"    분리간격 = {ns.min() - st.max():+.4f}  ->  "
              f"{'분리 성공' if sep else '분리 실패'}")
    all_sep = all(v["separated"] for v in run_results.values())
    print(f"\n  3회 전부 분리 성공? {'예' if all_sep else '아니오'}")
    print()

    print("=" * 78)
    print("2) v3 기준값 대조 (explore/v3_summary_timing.csv, 읽기 전용)")
    print("=" * 78)
    if os.path.exists(V3REF):
        v3 = pd.read_csv(V3REF)
        v3a = v3[(v3.preset == "A") & (v3.library == "openfhe") & (v3["mode"] == "1t")]
        gp3 = g_pairs(v3a, KS_OPS)
        st3, ns3 = gp3[gp3.step].g, gp3[~gp3.step].g
        print(f"  v3(기준): 전이 [{st3.min():.3f}, {st3.max():.3f}]  "
              f"비전이 [{ns3.min():.3f}, {ns3.max():.3f}]  간격 {ns3.min()-st3.max():.4f}")
    else:
        print("  v3_summary_timing.csv 없음 — 대조 생략")
    print()

    print("=" * 78)
    print("3) 실행 간 변동계수 — (op,level) 조합마다 3회 mean_us 의 cv")
    print("=" * 78)
    rows = []
    for (op, level), g in d.groupby(["op", "level"]):
        if g.run.nunique() < 2:
            continue
        mu, sd = g.mean_us.mean(), g.mean_us.std(ddof=1)
        rows.append(dict(op=op, level=level, cv_across_runs=sd / mu if mu else np.nan, n=len(g)))
    cvdf = pd.DataFrame(rows)
    print(f"  중앙값 cv = {cvdf.cv_across_runs.median():.4f}   최댓값 cv = {cvdf.cv_across_runs.max():.4f}")
    worst = cvdf.sort_values("cv_across_runs", ascending=False).head(5)
    print("  최대 5건:")
    for _, r in worst.iterrows():
        print(f"    {r.op:12s} L{int(r.level):<3d} cv={r.cv_across_runs:.4f}")
    print()

    print("=" * 78)
    print("4) rescale 대조군 — 전이/비전이 표지를 적용했을 때 겹쳐야 한다")
    print("=" * 78)
    for run, g in d.groupby("run"):
        gp = g_pairs(g, ["rescale"])
        st, ns = gp[gp.step].g, gp[~gp.step].g
        overlap = (st.min() <= ns.max()) and (ns.min() <= st.max()) if len(st) and len(ns) else None
        print(f"  run{run}: 전이 [{st.min():.3f},{st.max():.3f}]  "
              f"비전이 [{ns.min():.3f},{ns.max():.3f}]  "
              f"{'겹침(정상)' if overlap else '분리됨(!! 이상)'}")
    print()

    print("=" * 78)
    print("5) Monte Carlo 95% 구간 (표준오차 기반, 20만 회 표집)")
    print("=" * 78)
    rng = np.random.default_rng(20260902)
    N = 200_000
    for run, g in d.groupby("run"):
        m = g.set_index(["op", "level"])
        step_ratios = []
        nonstep_ratios = []
        for op in KS_OPS:
            mo = g[g.op == op].set_index("level")
            for L in sorted(mo.index):
                if L - 1 not in mo.index:
                    continue
                lo, hi = mo.loc[L - 1], mo.loc[L]
                se_lo = lo.std_us / np.sqrt(lo.reps)
                se_hi = hi.std_us / np.sqrt(hi.reps)
                samp_lo = rng.normal(lo.mean_us, se_lo, N)
                samp_hi = rng.normal(hi.mean_us, se_hi, N)
                samp_hi = np.clip(samp_hi, 1e-9, None)
                gsamp = samp_lo / samp_hi
                step = int(lo.digit) != int(hi.digit)
                (step_ratios if step else nonstep_ratios).append(gsamp)
        step_pool = np.concatenate(step_ratios)
        nonstep_pool = np.concatenate(nonstep_ratios)
        step_hi95 = np.percentile(step_pool, 97.5)
        nonstep_lo95 = np.percentile(nonstep_pool, 2.5)
        print(f"  run{run}: 전이 상한(97.5%)={step_hi95:.4f}  비전이 하한(2.5%)={nonstep_lo95:.4f}  "
              f"{'분리(MC 95%)' if step_hi95 < nonstep_lo95 else '겹침(MC 95%)'}")


if __name__ == "__main__":
    main()
