#!/usr/bin/env python3
"""2단계 측정 후보 (새 축, 2026-08-12). **기존 21점 목록은 폐기됐다.**

폐기 사유: 그 목록은 `K = 512` / EvalMod 13 / 캡슐화 off 전제로 뽑은 것인데, 그 구성은
Lattigo v6.2.0 에서 동작하지 않는다(`PROJECT_CONTEXT.md §10.7-17`). 축도 Δ 33~58 이었으나
Δ ≤ 50 은 OpenFHE 부트가 파탄난다(§10.7-20).

입력  explore/boot_params/boot_grid2_{openfhe,lattigo}.csv   (새 축 · (마) 구성)
출력  explore/boot_params/boot_stage2_points2.csv
      explore/boot_params/boot_feasible2.csv

새 축: Δ ∈ {52,53,55,58,59} · q0 ∈ Δ+1..min(Δ+7,60) · 잔여 L 3..30 · (마) 고정값.

후보 구성 (17점 내외 — 축 형태에 따라 곡선이 9~10점)
  · **곡선 10점** — Δ 5종 × q0−Δ {최소, 최대} 2점, 각 (q0,Δ) 에서 최대 L, 분해깊이 {3,3}
  · **L 무관성 4점** — 한 (q0,Δ) 에서 L 을 4개 (8-op 에서는 레벨 무관이었다, `PARAMS §8.4`)
  · **분해깊이 무관성 4점** — L 고정, {2,2}/{3,4}/{4,3}/{4,4}
공통: 양쪽 `dnum ≤ 8` (keygen 시간 통제, §9.5 의 dnum 15 → 9분 초과 이력).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "explore", "boot_params")
BOUND, DNUM_CAP, LMAX_AXIS = 1747, 8, 30
KEY = ["q0", "delta", "residual_L", "levelBudget_c2s", "levelBudget_s2c"]

_buf = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _buf.append(s)


def main():
    of = pd.read_csv(respath.find("boot_grid2_openfhe.csv"))
    la = pd.read_csv(respath.find("boot_grid2_lattigo.csv"))
    for n, d in (("openfhe", of), ("lattigo", la)):
        ok = d[d.ok == 1]
        if len(ok) and ok.logQP_boot.max() > BOUND:
            sys.exit(f"[모순] {n}: ok=1 인데 logQP_boot {ok.logQP_boot.max()} > {BOUND}")
        p(f"[{n}] 행 {len(d)} / ok=1 {len(ok)} / Δ {sorted(ok.delta.unique().astype(int))} "
          f"/ 잔여L {int(ok.residual_L.min())}~{int(ok.residual_L.max())}")

    # levelBudget 을 고정한 안에서만 dnum/PCount 최소화 (§10.7-2)
    ofb = of[of.ok == 1].sort_values(["dnum", "logQP_boot"]).groupby(KEY, as_index=False).first()
    lab = la[la.ok == 1].sort_values(["dnum", "PCount_boot", "logQP_boot"]).groupby(KEY, as_index=False).first()
    # ⚠️ `evalmod_scale` 은 Lattigo 에만 있다 — OpenFHE 는 FIXEDMANUAL 에서 부트 회로
    # 전체가 Δ 크기 프라임이라 대응 개념이 없다(§10.5-2). 공통 열에서 빼고 LA 쪽만 붙인다.
    cols = ["boot_depth", "evalmod_levels", "QCount_boot", "logQ_boot",
            "PCount_boot", "logP_boot", "logQP_boot", "margin_1747", "dnum",
            "log_message_ratio"]
    m = ofb[KEY + cols].merge(lab[KEY + cols + ["evalmod_scale"]], on=KEY, suffixes=("_of", "_la"))
    m = m.rename(columns={"evalmod_scale": "evalmod_scale_la"})
    m = m.sort_values(KEY).reset_index(drop=True)
    m.to_csv(os.path.join(OUTDIR, "boot_feasible2.csv"), index=False)
    p(f"\n[feasible2] {len(m)}행 (양쪽 동시 ok=1)")

    # ---- L 천장 확인 --------------------------------------------------------
    hit = m[m.residual_L >= LMAX_AXIS]
    p(f"\n=== 잔여 L 천장({LMAX_AXIS}) 확인 ===")
    if hit.empty:
        p(f"  걸린 셀 없음 — 격자 안에서 확정됐다. 전역 최대 L = {int(m.residual_L.max())}")
    else:
        g = hit.groupby(["levelBudget_c2s", "levelBudget_s2c"]).apply(
            lambda x: sorted(set(zip(x.q0.astype(int), x.delta.astype(int)))), include_groups=False)
        p(f"  ⚠️ 걸린 셀 {len(hit)}개 / {hit.groupby(['q0','delta']).ngroups}개 (q0,Δ) 쌍")
        for k, v in g.items():
            p(f"    levelBudget {k}: {v}")
        p("  ⚠️ 범위를 임의로 늘리지 않았다 — 실용성 판단(부트 빈도 vs dnum·keygen)이 필요하다.")

    c = m[(m.dnum_of <= DNUM_CAP) & (m.dnum_la <= DNUM_CAP) &
          (m.levelBudget_c2s == 3) & (m.levelBudget_s2c == 3)]

    # ---- 곡선 10점 ----------------------------------------------------------
    rows = []
    for d in sorted(c.delta.unique()):
        g = c[c.delta == d]
        gaps = sorted((g.q0 - g.delta).unique())
        for gap in ({gaps[0], gaps[-1]} if len(gaps) > 1 else {gaps[0]}):
            gg = g[(g.q0 - g.delta) == gap]
            r = gg.loc[gg.residual_L.idxmax()].copy()
            r["role"] = "curve"
            rows.append(r)
    curve = pd.DataFrame(rows)
    # (a) Δ=59 는 q0 ≤ 60 제약으로 q0−Δ 대조가 불가능하다(q0=60 하나뿐).
    #     대신 **잔여 L 을 축으로** 한 점 더 잡아 곡선 오른쪽 끝의 해상도를 확보한다.
    g59 = c[(c.delta == 59)]
    if not g59.empty:
        mx = int(g59.residual_L.max())
        alt = g59[g59.residual_L < mx]
        if not alt.empty:
            r = alt.loc[alt.residual_L.idxmax()].copy()
            r["role"] = "curve"
            curve = pd.concat([curve, pd.DataFrame([r])], ignore_index=True)

    # ---- L 무관성 4점 (곡선 점 중 L 폭이 가장 넓은 (q0,Δ)) -------------------
    span = c.groupby(["q0", "delta"]).residual_L.agg(["min", "max", "count"])
    span["w"] = span["max"] - span["min"]
    q0s, ds = span.w.idxmax()
    ls = c[(c.q0 == q0s) & (c.delta == ds)].sort_values("residual_L")
    lo, hi = int(ls.residual_L.min()), int(ls.residual_L.max())
    want = sorted({int(round(lo + (hi - lo) * i / 4)) for i in range(4)} - {hi})
    lsw = ls[ls.residual_L.isin(want)].copy()
    lsw["role"] = "Lsweep"

    # ---- 분해깊이 무관성 4점 -------------------------------------------------
    # ⚠️ 깊은 분해깊이는 boot_depth 를 키워 체인이 길어지므로 큰 L 에서는 상한을 넘긴다.
    #    그래서 **가용 levelBudget 종류가 가장 많은 (q0, Δ, L)** 을 고른다 — L 최대가 아니다.
    lbpool = m[(m.dnum_of <= DNUM_CAP) & (m.dnum_la <= DNUM_CAP)]
    cnt = (lbpool.groupby(["q0", "delta", "residual_L"])
                 .apply(lambda x: len(set(zip(x.levelBudget_c2s, x.levelBudget_s2c))),
                        include_groups=False))
    (lq0, ld, lL) = cnt.idxmax()
    p(f"\n분해깊이 무관성 기준점: (q0={int(lq0)}, Δ={int(ld)}, L={int(lL)}) "
      f"— 가용 levelBudget {int(cnt.max())}종")
    lbs = lbpool[(lbpool.q0 == lq0) & (lbpool.delta == ld) & (lbpool.residual_L == lL) &
                 (~((lbpool.levelBudget_c2s == 3) & (lbpool.levelBudget_s2c == 3)))].copy()
    lbs["role"] = "LBsweep"

    # (b) 곡선점 근처(L 이 큰 쪽)에서도 분해깊이 무관성을 본다. L=3 하나만으로는
    #     곡선점(L 6~7)에서 같은 경향이 나온다는 보장이 없다. 되는 것만 잡는다.
    span2 = lbpool[(lbpool.q0 == q0s) & (lbpool.delta == ds)]
    Lhi = int(span2[(span2.levelBudget_c2s == 3) & (span2.levelBudget_s2c == 3)].residual_L.max()) - 1
    lbs2 = span2[(span2.residual_L == Lhi) &
                 (~((span2.levelBudget_c2s == 3) & (span2.levelBudget_s2c == 3)))].copy()
    lbs2["role"] = "LBsweep"
    p(f"분해깊이 무관성 보조점: (q0={int(q0s)}, Δ={int(ds)}, L={Lhi}) — {len(lbs2)}종")
    lbs = pd.concat([lbs, lbs2], ignore_index=True)

    out = pd.concat([curve, lsw, lbs], ignore_index=True)
    out["q0_minus_delta"] = out.q0 - out.delta
    f = os.path.join(OUTDIR, "boot_stage2_points2.csv")
    out.to_csv(f, index=False)

    p(f"\n[후보] {os.path.relpath(f, ROOT)}  총 {len(out)}점 "
      f"(곡선 {len(curve)} / L무관성 {len(lsw)} / 분해깊이무관성 {len(lbs)})")
    p(f"{'role':>9}{'q0':>4}{'Δ':>4}{'q0-Δ':>6}{'L':>4}{'lb':>7}"
      f"{'OF dnum':>8}{'OF logQP':>9}{'LA dnum':>8}{'LA logQP':>9}{'최소여유':>9}")
    for _, r in out.iterrows():
        p(f"{r.role:>9}{int(r.q0):>4}{int(r.delta):>4}{int(r.q0-r.delta):>6}{int(r.residual_L):>4}"
          f"{f'{{{int(r.levelBudget_c2s)},{int(r.levelBudget_s2c)}}}':>7}"
          f"{int(r.dnum_of):>8}{int(r.logQP_boot_of):>9}{int(r.dnum_la):>8}{int(r.logQP_boot_la):>9}"
          f"{int(min(r.margin_1747_of, r.margin_1747_la)):>9}")

    with open(os.path.join(OUTDIR, "boot_stage2_points2.txt"), "w") as fh:
        fh.write("\n".join(_buf) + "\n")
    p("\n※ 프리셋을 고르지 않는다 — Δ 곡선을 그리는 것이 2단계의 결과물이다.")


if __name__ == "__main__":
    main()
