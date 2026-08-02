#!/usr/bin/env python3
"""v3 4프리셋 플롯. 출력은 plots/v3/ — archive/v1/plots 는 건드리지 않는다.

스타일은 v1에서 확정된 규약을 그대로 잇는다(aggregate.py 와 동일):
  Okabe-Ito 팔레트 · 색=라이브러리 · 마커=op(○□△) · 채운 마커 · 선은 실선
  에러바는 별도 레이어로 옅게(elinewidth 0.8 / capsize 2 / alpha 0.4) —
  errorbar() 에 alpha 를 주면 선·마커까지 반투명해지므로 분리한다.

팔레트 검증(dataviz validate_palette.js, light):
  CVD 최악 인접쌍 ΔE 15.8(deutan) / 정상 시야 16.4 → PASS
  SEAL #CC79A7 만 표면 대비 2.98 (<3:1) WARN → **범례 + 직접 라벨 + op별 마커**로
  이중 인코딩해 색만으로 식별하지 않게 한다(WARN 해소 조건).

⚠️ Lattigo 경량 op(add_cc/add_cp/mul_cp/mul_cc)는 Go GC 때문에 이 프로토콜에서
  안정적으로 측정되지 않는다(PROJECT_CONTEXT §8.6). 플롯에 포함하되 **점선 + 옅은 색**
  으로 구분하고 캡션에 사유를 적는다.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

plt.rcParams.update({
    "axes.titlesize": 15, "axes.labelsize": 13,
    "xtick.labelsize": 11, "ytick.labelsize": 11,
    "legend.fontsize": 11, "figure.titlesize": 17,
})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plots", "v3")
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00", "seal": "#CC79A7"}
LIB_ORDER = ["openfhe", "lattigo", "seal"]
TIERS = {"heavy": ["mul_cc_rlk", "relin", "rot1"],
         "mid": ["mul_cc", "rescale"],
         "light": ["add_cc", "add_cp", "mul_cp"]}
MARKERS = ["o", "s", "^"]          # op 용 (티어당 최대 3개)
PMARK = {"A": "o", "B": "s", "C": "^", "D": "D"}   # 프리셋용 — 4종이라 %3 을 쓰면 A와 D가 겹친다
PCOLOR = {"A": "#D55E00", "B": "#0072B2", "C": "#009E73", "D": "#CC79A7"}
GC_OPS = {"add_cc", "add_cp", "mul_cp", "mul_cc"}   # Lattigo 한정 신뢰 불가
PRESETS = ["A", "B", "C", "D"]
PMETA = {"A": (15, 12, 42), "B": (14, 6, 42), "C": (15, 10, 48), "D": (14, 4, 42)}
GC_NOTE = ("NOTE: Lattigo add_cc/add_cp/mul_cp/mul_cc are NOT reliable under this protocol "
           "(Go GC; up to 39% run-to-run). Shown dotted+faded — do not use for judgement.")


def unreliable(lib, op):
    return lib == "lattigo" and op in GC_OPS


def load():
    p = os.path.join(ROOT, "explore", "v3_summary_timing.csv")
    if not os.path.exists(p):
        sys.exit(f"[missing] {p} — scripts/v3_unify.py 를 먼저 돌릴 것")
    return pd.read_csv(p)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, name)
    fig.savefig(f, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(f, ROOT)}")


# ---------------------------------------------------------------- 1) 레벨 곡선
def plot_levels(d):
    for preset in PRESETS:
        logN, depth, delta = PMETA[preset]
        for mode in ["1t", "mt"]:
            for tier, ops in TIERS.items():
                sub = d[(d.preset == preset) & (d["mode"] == mode) & (d.op.isin(ops))]
                if sub.empty:
                    continue
                present = [o for o in ops if not sub[sub.op == o].empty]
                om = {o: MARKERS[i % 3] for i, o in enumerate(present)}
                fig, ax = plt.subplots(figsize=(8.5, 5.6))
                for op in present:
                    for lib in LIB_ORDER:
                        g = sub[(sub.op == op) & (sub.library == lib)].sort_values("level")
                        if g.empty:
                            continue
                        bad = unreliable(lib, op)
                        ms = g.mean_us.values / 1000.0
                        sd = g.std_us.values / 1000.0
                        ax.plot(g.level, ms, color=LIB_COLOR[lib],
                                linestyle=":" if bad else "-",
                                marker=om[op], markersize=6, linewidth=2.0,
                                markeredgewidth=0, alpha=0.35 if bad else 1.0)
                        # 에러바는 별도 레이어 — 선·마커 불투명 유지
                        ax.errorbar(g.level, ms, yerr=sd, fmt="none",
                                    ecolor=LIB_COLOR[lib], elinewidth=0.8,
                                    capsize=2, capthick=0.8, alpha=0.4)
                ax.set_yscale("log")
                ax.invert_xaxis()          # 왼쪽이 고레벨
                ax.set_xlabel("level (remaining multiplicative budget) — high level on the left")
                ax.set_ylabel("mean latency (ms, log scale)")
                ax.set_title(f"{preset} · {tier} · {mode}   "
                             f"(logN {logN}, depth {depth}, Δ {delta})")
                ax.grid(True, which="both", color="0.9", linewidth=0.6)
                ax.set_axisbelow(True)
                # 직접 라벨 — 색만으로 식별하지 않게 (팔레트 대비 WARN 해소)
                xmax = sub.level.max()
                # 라벨이 겹치지 않도록 값 순서대로 위/아래로 벌린다
                ends = []
                for lib in LIB_ORDER:
                    g = sub[(sub.library == lib) & (sub.level == xmax) & (sub.op == present[0])]
                    if not g.empty:
                        ends.append((g.mean_us.iloc[0] / 1000.0, lib))
                ends.sort(reverse=True)
                for k, (yv, lib) in enumerate(ends):
                    ax.annotate(lib, (xmax, yv), textcoords="offset points",
                                xytext=(7, 8 - 11 * k), color=LIB_COLOR[lib],
                                fontsize=10, fontweight="bold")
                lh = [Line2D([0], [0], color=LIB_COLOR[l], lw=2.5, label=l) for l in LIB_ORDER]
                oh = [Line2D([0], [0], color="0.35", lw=2.0, marker=om[o], markersize=6,
                             markeredgewidth=0, label=o) for o in present]
                l1 = ax.legend(handles=lh, title="library", loc="lower left", framealpha=0.9)
                ax.add_artist(l1)
                fig.canvas.draw()
                bb = l1.get_window_extent().transformed(ax.transAxes.inverted())
                ax.legend(handles=oh, title="operation", loc="lower left",
                          bbox_to_anchor=(bb.x0, bb.y1 + 0.02), framealpha=0.9)
                if tier in ("light", "mid"):
                    fig.text(0.5, -0.03, GC_NOTE, ha="center", fontsize=9, color="0.35")
                save(fig, f"levels_{preset}_{tier}_{mode}.png")


# ------------------------------------------------------------- 2) digit 계단
def plot_digit_steps(d):
    d = d[(d["mode"] == "1t") & (d.op == "rot1")]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4))
    ax = axes[0]
    keep_all, step_all = [], []
    for preset in PRESETS:
        for lib in ["openfhe", "lattigo"]:
            g = d[(d.preset == preset) & (d.library == lib)].sort_values("level", ascending=False)
            lv = g.level.tolist(); mu = g.mean_us.tolist(); dg = g.digit.tolist()
            xs, ys, marks = [], [], []
            for k in range(len(lv) - 1):
                xs.append(lv[k] / max(lv))          # 정규화: L/Lmax (전이 위치가 프리셋마다 달라서)
                ys.append(mu[k + 1] / mu[k])
                trans = dg[k] != dg[k + 1]
                marks.append(trans)
                (step_all if trans else keep_all).append(ys[-1])
            # 좌측 패널은 OpenFHE 만 그린다 — 8선이면 스파게티가 된다.
            # Lattigo 곡선은 거의 겹치며(우측 패널 산점에는 두 라이브러리 모두 포함) 캡션에 적는다.
            if lib != "openfhe":
                continue
            ax.plot(xs, ys, color=PCOLOR[preset], marker=PMARK[preset], markersize=7,
                    markeredgewidth=0, linewidth=1.8, label=f"{preset} (depth {PMETA[preset][1]})")
            for x, y, t in zip(xs, ys, marks):
                if t:
                    ax.axvline(x, color="0.85", linewidth=1.0, zorder=0)
                    ax.plot([x], [y], marker="v", color="0.25", markersize=8, zorder=5)
    ax.set_xlabel("normalised level  L / Lmax  (high level on the left)")
    ax.set_ylabel("level-to-level ratio  v[L-1] / v[L]")
    ax.invert_xaxis()
    ax.set_title("ratio vs level", pad=10)
    ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)

    ax2 = axes[1]
    for j, (name, vals, col) in enumerate([("digit kept", keep_all, "#009E73"),
                                           ("digit transition", step_all, "#D55E00")]):
        x = np.random.default_rng(7 + j).normal(j, 0.05, len(vals))
        ax2.scatter(x, vals, color=col, s=34, alpha=0.75, edgecolors="none")
        ax2.hlines([min(vals), max(vals)], j - 0.22, j + 0.22, color=col, linewidth=2)
        ax2.annotate(f"{min(vals):.3f}~{max(vals):.3f}", (j, max(vals)),
                     textcoords="offset points", xytext=(0, 10), ha="center",
                     fontsize=11, color=col, fontweight="bold")
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(["digit kept", "digit transition"])
    ax2.set_ylabel("level-to-level ratio  v[L-1] / v[L]")
    ax2.set_title("kept vs transition", pad=10)
    ax2.grid(True, axis="y", color="0.92", linewidth=0.6); ax2.set_axisbelow(True)

    axes[0].legend(loc="lower left", framealpha=0.9, fontsize=10, title="preset (OpenFHE)")
    axes[0].plot([], [], marker="v", color="0.25", lw=0, markersize=8, label="digit transition")
    axes[0].legend(loc="lower left", framealpha=0.9, fontsize=10, title="preset (OpenFHE)")
    fig.suptitle("Steps produced by digit-count transitions (rot1, 1t)", y=1.04)
    fig.text(0.5, -0.05,
             "Left: OpenFHE only (Lattigo nearly coincides). Right: both libraries, all 4 presets. "
             "The two bands do not overlap.", ha="center", fontsize=9, color="0.35")
    save(fig, "digit_steps.png")


# ---------------------------------------------------------- 3) 곡선 분기 (of/la)
def plot_divergence(d):
    d = d[(d["mode"] == "1t") & (d.op == "rot1")]
    fig, ax = plt.subplots(figsize=(9, 5.6))
    for i, preset in enumerate(PRESETS):
        g = d[d.preset == preset]
        o = g[g.library == "openfhe"].set_index("level").mean_us
        l = g[g.library == "lattigo"].set_index("level").mean_us
        mx = max(o.index)
        norm = ((o / o[mx]) / (l / l[mx])).sort_index()   # ★ 레벨 오름차순 정렬 (안 하면 선이 뒤엉킨다)
        pO = int(g[g.library == "openfhe"].logP.iloc[0])
        pL = int(g[g.library == "lattigo"].logP.iloc[0])
        rel = "OF<LA" if pO < pL else ("OF>LA" if pO > pL else "OF=LA")
        col = PCOLOR[preset]
        ax.plot(norm.index, norm.values, marker=PMARK[preset], markersize=7,
                markeredgewidth=0, linewidth=2.0, color=col,
                label=f"{preset}  logP {pO} vs {pL}  ({rel})")
        # L1(가장 낮은 레벨) 끝점 값을 라벨 — Lmax 는 정의상 1.000 이라 붙일 필요가 없다
        ax.annotate(f"{norm.values[0]:.3f}", (norm.index[0], norm.values[0]),
                    textcoords="offset points", xytext=(-8, 0), ha="right", va="center",
                    fontsize=10, color=col, fontweight="bold")
    ax.axhline(1.0, color="0.4", linewidth=1.2, linestyle="--")
    ax.set_xlabel("level (remaining multiplicative budget) — high level on the left")
    ax.set_ylabel("normalised curve ratio  (OF/OF[Lmax]) / (LA/LA[Lmax])")
    ax.invert_xaxis()
    ax.set_title("Curve divergence — the smaller P floor falls deeper")
    ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    ax.legend(loc="best", framealpha=0.9, fontsize=10)
    fig.text(0.5, -0.04,
             "<1 : OpenFHE falls deeper   >1 : Lattigo falls deeper.\n"
             "Direction reverses between A (OF 240 < LA 300) and C (OF 300 > LA 240). "
             "A residual remains in B/D where P is equal - library-specific overhead.\n"
             "C is saw-toothed because it is the only preset where OF and LA have DIFFERENT digit "
             "sequences (OF 2,2,2,2,2,1... / LA 3,3,3,2,2,2,2,1...), so their steps fall at "
             "different levels. This is real structure, not noise.",
             ha="center", fontsize=9, color="0.35")
    save(fig, "curve_divergence.png")


# ------------------------------------------------------------- 4) mt/1t 비
def plot_mt_ratio(d):
    piv = d.pivot_table(index=["preset", "library", "op", "level"],
                        columns="mode", values="mean_us").reset_index()
    piv["r"] = piv["mt"] / piv["1t"]
    heavy = piv[piv.op.isin(TIERS["heavy"])]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4), sharey=True)
    ax = axes[0]
    ends = []
    for i, preset in enumerate(PRESETS):
        g = heavy[(heavy.preset == preset) & (heavy.library == "openfhe")]
        m = g.groupby("level").r.median()
        m = m.sort_index()
        ax.plot(m.index, m.values, marker=PMARK[preset], markersize=7, markeredgewidth=0,
                linewidth=2.2, color=PCOLOR[preset],
                label=f"{preset} (depth {PMETA[preset][1]})")
        ends.append((preset, m.values[-1]))   # maxLevel 값은 아래에 표로 모아 찍는다
    ax.axhline(1.0, color="0.4", linewidth=1.2, linestyle="--")
    ax.invert_xaxis()
    ax.set_xlabel("level — high level on the left"); ax.set_ylabel("mt / 1t   (lower = more parallel gain)")
    ax.margins(x=0.10, y=0.10)
    ax.set_title("OpenFHE — median of key-switch ops")
    ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=10)
    # maxLevel 값을 빈 영역(우상단)에 표로 — 선 위에 붙이면 범례·축과 겹친다
    txt = "at maxLevel:\n" + "\n".join(f"  {p} (d{PMETA[p][1]:>2})  {v:.3f}" for p, v in ends)
    ax.text(0.98, 0.03, txt, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10, family="monospace", color="0.2",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.8", alpha=0.92))

    ax2 = axes[1]
    for lib in ["lattigo", "seal"]:
        for i, preset in enumerate(PRESETS):
            g = heavy[(heavy.preset == preset) & (heavy.library == lib)]
            m = g.groupby("level").r.median().sort_index()
            ax2.plot(m.index, m.values, marker=PMARK[preset], markersize=6,
                     markeredgewidth=0, linewidth=1.8, color=LIB_COLOR[lib], alpha=0.85)
    ax2.axhline(1.0, color="0.4", linewidth=1.2, linestyle="--")
    ax2.invert_xaxis()
    ax2.set_xlabel("level — high level on the left")
    ax2.set_title("Lattigo / SEAL — no intra-op parallelism → near 1")
    ax2.grid(True, color="0.92", linewidth=0.6); ax2.set_axisbelow(True)
    ax2.legend(handles=[Line2D([0], [0], color=LIB_COLOR[l], lw=2.5, label=l)
                        for l in ["lattigo", "seal"]], loc="lower left", framealpha=0.9)
    fig.suptitle("mt / 1t — intra-op parallelism axis (only OpenFHE participates)")
    fig.text(0.5, -0.04,
             "OpenFHE parallel gain decreases monotonically with depth (A -> C -> B -> D). "
             "This is NOT application-level parallelism (distributing independent ciphertexts).",
             ha="center", fontsize=9, color="0.35")
    save(fig, "mt_over_1t.png")


# --------------------------------------------------------- 5) 교차점 요약
def plot_crossings(d):
    """교차 레벨을 프리셋별로. 관측 창을 회색 밴드로 그려 '창 밖'을 시각화한다."""
    DRIFT = 0.02
    pairs = [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]
    ops = TIERS["heavy"]

    def cross(A, B, sc=1.0):
        xs = sorted(A)
        r = [A[l] * sc / B[l] for l in xs]
        return ([xs[i] + (1 - r[i]) / (r[i + 1] - r[i])
                 for i in range(len(r) - 1) if (r[i] - 1) * (r[i + 1] - 1) < 0], r, xs)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), sharey=True)
    for ax, mode in zip(axes, ["1t", "mt"]):
        yl = []
        for pi, (a, b) in enumerate(pairs):
            for oi, op in enumerate(ops):
                y = pi * (len(ops) + 1) + oi
                yl.append((y, f"{a}/{b} · {op}"))
                for si, preset in enumerate(PRESETS):
                    g = d[(d.preset == preset) & (d["mode"] == mode) & (d.op == op)]
                    A = g[g.library == a].set_index("level").mean_us.to_dict()
                    B = g[g.library == b].set_index("level").mean_us.to_dict()
                    if not A or not B:
                        continue
                    depth = max(A)
                    # 관측 창
                    ax.plot([1, depth], [y - 0.30 + 0.15 * si] * 2, color="0.88",
                            linewidth=6, solid_capstyle="butt", zorder=0)
                    c, r, xs = cross(A, B)
                    lo, _, _ = cross(A, B, 1 - DRIFT)
                    hi, _, _ = cross(A, B, 1 + DRIFT)
                    yy = y - 0.30 + 0.15 * si
                    col = PCOLOR[preset]
                    if c:
                        ax.plot([lo[0], hi[0]] if lo and hi else [c[0], c[0]], [yy, yy],
                                color=col, linewidth=2.4, solid_capstyle="round", zorder=3)
                        ax.plot([c[0]], [yy], marker=PMARK[preset], color=col,
                                markersize=8, markeredgewidth=0, zorder=4)
                    elif r[-1] < 1 and r[-1] > r[0]:
                        ax.plot([depth], [yy], marker=">", color=col, markersize=9,
                                markeredgewidth=0, zorder=4)   # 창 밖 (더 깊은 쪽)
        ax.set_yticks([y for y, _ in yl]); ax.set_yticklabels([s for _, s in yl], fontsize=10)
        ax.set_xlabel("crossing level"); ax.set_title(f"{mode}")
        ax.grid(True, axis="x", color="0.92", linewidth=0.6); ax.set_axisbelow(True)
        ax.set_xlim(0, 13.5)
    handles = [Line2D([0], [0], color=PCOLOR[p], lw=0, marker=PMARK[p], markersize=8,
                      markeredgewidth=0, label=f"{p} (depth {PMETA[p][1]})") for p in PRESETS]
    handles += [Line2D([0], [0], color="0.88", lw=6, label="observation window (L1..depth)"),
                Line2D([0], [0], color="0.35", lw=0, marker=">", markersize=9,
                       markeredgewidth=0, label="crossing outside window (deeper)")]
    axes[1].legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
                   framealpha=0.9, fontsize=10)
    fig.suptitle("Crossing points — thick segment = +/-2% sensitivity band")
    fig.text(0.5, -0.04,
             "Grey band = observation window of each preset. The arrow means the crossing lies deeper "
             "than the window, NOT that there is no crossing.",
             ha="center", fontsize=9, color="0.35")
    save(fig, "crossings_summary.png")


if __name__ == "__main__":
    d = load()
    plot_levels(d)
    plot_digit_steps(d)
    plot_divergence(d)
    plot_mt_ratio(d)
    plot_crossings(d)
    print(f"\n총 {len([f for f in os.listdir(OUT) if f.endswith('.png')])}장")
