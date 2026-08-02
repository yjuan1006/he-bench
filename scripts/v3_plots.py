#!/usr/bin/env python3
"""v3 4프리셋 플롯. 출력 plots/v3/ — archive/v1/plots 는 건드리지 않는다.

설계 원칙 (2026-08-02 재설계)
  · 그림 하나 = 주장 하나. 제목이 그 주장을 문장으로 말한다.
  · 한 패널에 선 3~4개까지. 그 이상이면 facet 으로 나눈다.
  · 범례보다 선 끝 직접 라벨을 우선한다.
  · 교차점·digit 전이는 그림 안에 직접 주석한다.

축 규약 (변경)
  · y 는 **선형**. 로그를 쓰지 않는다.
    ⚠️ 선형이면 고레벨이 축을 지배해 저레벨이 눌린다 → 각 그림에 **L1 배율 표**를 붙여
      저레벨에서의 상대 관계를 숫자로 읽을 수 있게 한다.
  · x 는 **왼쪽이 저레벨(L1), 오른쪽이 고레벨** — v1 플롯과 같은 방향이다.

스타일은 v1 규약 유지: Okabe-Ito, 색=라이브러리, 채운 마커, 에러바는 별도 레이어로 옅게
(errorbar 에 alpha 를 주면 선·마커까지 반투명해지므로 분리한다).
팔레트 검증(validate_palette.js, light): CVD 최악 인접쌍 ΔE 15.8 / 정상 16.4 → PASS.
SEAL #CC79A7 만 표면 대비 2.98 (<3:1) WARN → 범례 + 선 끝 직접 라벨로 이중 인코딩.

⚠️ Lattigo 경량 op(add_cc/add_cp/mul_cp/mul_cc)는 Go GC 때문에 이 프로토콜에서
  안정적으로 측정되지 않는다(PROJECT_CONTEXT §8.6). 점선 + alpha(막대는 해칭)로 구분하고
  캡션에 사유를 적는다.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# 랩미팅 슬라이드에서도 읽히도록 크게
plt.rcParams.update({
    "axes.titlesize": 17, "axes.labelsize": 15,
    "xtick.labelsize": 13, "ytick.labelsize": 13,
    "legend.fontsize": 13, "figure.titlesize": 20,
})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plots", "v3")
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00", "seal": "#CC79A7"}
LIB_ORDER = ["lattigo", "openfhe", "seal"]
TIERS = {"heavy": ["mul_cc_rlk", "relin", "rot1"],
         "mid": ["mul_cc", "rescale", "mul_cp"],
         "light": ["add_cc", "add_cp"]}
GC_OPS = {"add_cc", "add_cp", "mul_cp", "mul_cc"}      # Lattigo 한정 신뢰 불가
PRESETS = ["A", "B", "C", "D"]
PMETA = {"A": (15, 12, 42), "B": (14, 6, 42), "C": (15, 10, 48), "D": (14, 4, 42)}
PCOLOR = {"A": "#D55E00", "B": "#0072B2", "C": "#009E73", "D": "#CC79A7"}
PMARK = {"A": "o", "B": "s", "C": "^", "D": "D"}
DRIFT = 0.02
GC_CAP = ("Lattigo add_cc/add_cp/mul_cp/mul_cc are NOT reliable here (Go GC, up to 39% "
          "run-to-run) — shown dotted/hatched & faded; do not judge from them.")


def unreliable(lib, op):
    return lib == "lattigo" and op in GC_OPS


def load():
    p = os.path.join(ROOT, "explore", "v3_summary_timing.csv")
    if not os.path.exists(p):
        sys.exit(f"[missing] {p} — scripts/v3_unify.py 를 먼저 돌릴 것")
    return pd.read_csv(p)


def logp_str(d, preset, mode):
    g = d[(d.preset == preset) & (d["mode"] == mode)]
    return " / ".join(f"{l[:2].upper()} {int(g[g.library == l].logP.iloc[0])}"
                      for l in ["openfhe", "lattigo", "seal"])


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, name)
    fig.savefig(f, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(f, ROOT)}")


def crossings(A, B, scale=1.0):
    xs = sorted(A)
    r = [A[l] * scale / B[l] for l in xs]
    return ([xs[i] + (1 - r[i]) / (r[i + 1] - r[i])
             for i in range(len(r) - 1) if (r[i] - 1) * (r[i + 1] - 1) < 0], r, xs)


# ═════════════════════════════════════ 1) 요약 막대 (v1 스타일 복원)
def plot_summary_bars(d):
    DEC = {"heavy": 1, "mid": 2, "light": 3}
    for mode in ["1t", "mt"]:
        for tier, ops in TIERS.items():
            fig, axes = plt.subplots(1, 4, figsize=(21, 6.4))
            for ax, preset in zip(axes, PRESETS):
                logN, depth, delta = PMETA[preset]
                sub = d[(d.preset == preset) & (d["mode"] == mode) & (d.level == depth)]
                present = [o for o in ops if not sub[sub.op == o].empty]
                x = range(len(present))
                SP, W = 0.26, 0.21
                ymax = 0.0
                for i, lib in enumerate(LIB_ORDER):
                    for xi, o in zip(x, present):
                        r = sub[(sub.op == o) & (sub.library == lib)]
                        if r.empty:
                            continue
                        v, e = r.mean_us.iloc[0] / 1000, r.std_us.iloc[0] / 1000
                        off = (i - 1) * SP
                        # 막대에는 점선을 쓸 수 없어 GC 영향군은 해칭으로 표시한다
                        ax.bar([xi + off], [v], W, yerr=[e], capsize=2.5,
                               error_kw={"elinewidth": 1.0, "alpha": 0.6},
                               color=LIB_COLOR[lib], edgecolor="white", linewidth=0.8,
                               hatch="//" if unreliable(lib, o) else "")
                        ax.annotate(f"{v:.{DEC[tier]}f}", (xi + off, v + e),
                                    textcoords="offset points", xytext=(0, 4),
                                    ha="center", va="bottom", fontsize=11)
                        ymax = max(ymax, v + e)
                ax.set_ylim(0, ymax * 1.20)
                ax.set_xticks(list(x)); ax.set_xticklabels(present, fontsize=13)
                ax.set_title(f"{preset} (logN={logN}, depth={depth}, Δ={delta})\n"
                             f"logP  {logp_str(d, preset, mode)}", fontsize=15)
                ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
            axes[0].set_ylabel("mean latency (ms)")
            fig.legend(handles=[Patch(facecolor=LIB_COLOR[l], edgecolor="black", label=l)
                                for l in LIB_ORDER],
                       title="library", loc="upper right", bbox_to_anchor=(0.998, 1.0),
                       ncol=3, fontsize=14, title_fontsize=14)
            fig.suptitle(f"CKKS op latency @ maxLevel · {tier} · {mode}", x=0.40)
            cap = ("Each preset uses a DIFFERENT P (logP in each subtitle) — bars are "
                   "'each library at its own optimum', NOT an equal-P comparison. "
                   "y-axes are per-panel.")
            if tier != "heavy":
                cap += "\n" + GC_CAP
            fig.text(0.5, -0.03, cap, ha="center", fontsize=12, color="0.3")
            fig.tight_layout(rect=[0, 0, 1, 0.86])
            save(fig, f"summary_{tier}_{mode}.png")


# ═════════════════════════════════════ 2) 레벨 곡선 — op 별 facet
def plot_levels(d):
    for preset in PRESETS:
        logN, depth, delta = PMETA[preset]
        for mode in ["1t", "mt"]:
            for tier, ops in TIERS.items():
                sub = d[(d.preset == preset) & (d["mode"] == mode) & (d.op.isin(ops))]
                present = [o for o in ops if not sub[sub.op == o].empty]
                if not present:
                    continue
                n = len(present)
                fig, axes = plt.subplots(1, n, figsize=(6.6 * n, 6.2))
                axes = np.atleast_1d(axes)
                l1 = []
                for ax, op in zip(axes, present):
                    series = {}
                    for lib in LIB_ORDER:
                        g = sub[(sub.op == op) & (sub.library == lib)].sort_values("level")
                        if g.empty:
                            continue
                        series[lib] = dict(zip(g.level, g.mean_us))
                        bad = unreliable(lib, op)
                        ms, sd = g.mean_us.values / 1000, g.std_us.values / 1000
                        ax.plot(g.level, ms, color=LIB_COLOR[lib],
                                linestyle=":" if bad else "-", marker="o", markersize=6,
                                linewidth=2.4, markeredgewidth=0, alpha=0.4 if bad else 1.0)
                        ax.errorbar(g.level, ms, yerr=sd, fmt="none", ecolor=LIB_COLOR[lib],
                                    elinewidth=0.8, capsize=2, capthick=0.8, alpha=0.4)
                    # 오른쪽 여백은 선 끝 직접 라벨("openfhe" 등) 자리다.
                    # 패널 폭(픽셀)이 depth 와 무관하게 일정하므로 라벨이 차지하는 데이터 단위는
                    # 데이터 범위에 비례한다 — 고정값(+1.9)을 쓰면 depth 4 에서 축 절반이 빈다.
                    # "openfhe"(bold 12pt) + 오프셋 ≈ 105px, 축 폭 ≈ 810px → 축 폭의 약 13%.
                    #   m/(depth-0.4+m) = 0.13  →  m ≈ 0.15*(depth-0.4)
                    # (계수를 0.095 로 잡았더니 라벨이 패널 밖으로 삐져나가 잘렸다)
                    pad = max(0.55, 0.15 * (depth - 0.4))
                    ax.set_xlim(0.4, depth + pad)
                    ax.set_xticks(range(1, depth + 1))
                    ax.set_ylim(bottom=0)
                    # 선 끝(고레벨=오른쪽) 직접 라벨
                    ends = sorted(((series[l][depth] / 1000, l) for l in series), reverse=True)
                    for k, (yv, lib) in enumerate(ends):
                        ax.annotate(lib, (depth, yv), textcoords="offset points",
                                    xytext=(9, 4 - 15 * k), color=LIB_COLOR[lib],
                                    fontsize=12, fontweight="bold", annotation_clip=False)
                    # L1 배율 수집 (선형 y 축에서 눌리는 저레벨 구간의 보완 지표)
                    # ⚠️ 교차점은 여기 그리지 않는다 — 전용 그림 crossings_{op}.png 가 담당한다.
                    #   레벨 곡선에 세로선을 겹치면 곡선 자체를 읽는 데 방해가 됐다.
                    for a, b in [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]:
                        if a not in series or b not in series:
                            continue
                        if op in GC_OPS and "lattigo" in (a, b):
                            continue          # GC 영향군은 판정하지 않는다
                        l1.append(f"{op} {a[:2].upper()}/{b[:2].upper()} "
                                  f"{series[a][1] / series[b][1]:.2f}")
                    ax.set_title(op)
                    ax.set_xlabel("level (remaining budget) →")
                    ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
                axes[0].set_ylabel("mean latency (ms)")
                fig.suptitle(f"{preset} · {tier} · {mode}   —   logN {logN}, depth {depth}, "
                             f"Δ {delta}   (logP {logp_str(d, preset, mode)})", y=1.03)
                cap = ("ratios at L1:   " + "   ·   ".join(l1) +
                       "\nLinear y-axis — high levels dominate and the low end looks flat; "
                       "the L1 ratios above cover that range.")
                if tier != "heavy":
                    cap += "\n" + GC_CAP
                fig.text(0.5, -0.06, cap, ha="center", fontsize=12, color="0.3")
                fig.tight_layout()
                save(fig, f"levels_{preset}_{tier}_{mode}.png")


# ═════════════════════════════════════ 3) digit 계단 — 프리셋별 facet
def plot_digit_steps(d):
    dd = d[(d["mode"] == "1t") & (d.op == "rot1")]
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.5))
    for ax, preset in zip(axes.ravel(), PRESETS):
        logN, depth, delta = PMETA[preset]
        trans = {}
        for lib in ["openfhe", "lattigo"]:
            g = dd[(dd.preset == preset) & (dd.library == lib)].sort_values("level")
            lv, mu, dg = g.level.tolist(), g.mean_us.tolist(), g.digit.tolist()
            xs = [lv[k] + 0.5 for k in range(len(lv) - 1)]
            ys = [mu[k] / mu[k + 1] for k in range(len(lv) - 1)]   # 낮은 레벨 / 한 단계 높은 레벨
            ax.plot(xs, ys, color=LIB_COLOR[lib], marker="o", markersize=8,
                    markeredgewidth=0, linewidth=2.6, label=lib)
            trans[lib] = {lv[k] + 0.5: f"{dg[k+1]}→{dg[k]}"
                          for k in range(len(lv) - 1) if dg[k] != dg[k + 1]}
        # 두 라이브러리가 같은 자리에서 전이하면 회색 한 줄, 다르면 각자 색으로 표시한다.
        # (C 만 digit 수열이 달라 전이 위치가 어긋난다 — 표시하지 않으면 파란 급락이 설명되지 않는다)
        common = set(trans["openfhe"]) & set(trans["lattigo"])
        for lib in ["openfhe", "lattigo"]:
            for x, lab in trans[lib].items():
                if x in common and lib != "openfhe":
                    continue
                shared = x in common
                ax.axvline(x, color="0.45" if shared else LIB_COLOR[lib],
                           linestyle="--", linewidth=1.8, zorder=0,
                           alpha=1.0 if shared else 0.75)
                ytxt = 0.995 if (shared or lib == "openfhe") else 0.93
                ax.annotate(("digit " if shared else f"{lib[:2].upper()} ") + lab, (x, ytxt),
                            ha="center", va="top", fontsize=11,
                            color="0.2" if shared else LIB_COLOR[lib],
                            bbox=dict(boxstyle="round,pad=0.22", fc="white",
                                      ec="0.75" if shared else LIB_COLOR[lib], alpha=0.92))
        ax.axhspan(0.81, 0.93, color="#009E73", alpha=0.10, zorder=0)
        ax.set_ylim(0.50, 1.02); ax.set_xlim(0.9, depth + 0.1)
        ax.set_xticks(range(1, depth + 1))
        ax.set_title(f"{preset} (depth {depth}, Δ {delta})")
        ax.set_xlabel("level (remaining budget) →")
        ax.set_ylabel("v[L] / v[L+1]")
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
        ax.legend(loc="lower right", framealpha=0.9, fontsize=12)
    fig.suptitle("The performance curve steps exactly where the digit count drops", y=1.00)
    fig.text(0.5, -0.02,
             "Green band = the 'digit kept' range (0.81–0.93) measured across all four presets; "
             "every dashed line (a digit transition) sits below it (0.54–0.73).\n"
             "rot1, 1t. OpenFHE and Lattigo share the digit sequence in A/B/D; only in C do they differ.",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout()
    save(fig, "digit_steps.png")


# ═════════════════════════════════════ 4) 교차점 (op 별 파일)
def plot_crossings(d, op, fname):
    pairs = [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]
    fig, axes = plt.subplots(1, 2, figsize=(17, 6.4), sharey=True)
    for ax, mode in zip(axes, ["1t", "mt"]):
        yticks, ylabels, row = [], [], 0
        for a, b in pairs:
            for preset in PRESETS:
                depth = PMETA[preset][1]
                g = d[(d.preset == preset) & (d["mode"] == mode) & (d.op == op)]
                A = g[g.library == a].set_index("level").mean_us.to_dict()
                B = g[g.library == b].set_index("level").mean_us.to_dict()
                yticks.append(row); ylabels.append(f"{a[:2].upper()}/{b[:2].upper()}  {preset}")
                ax.plot([1, depth], [row, row], color="0.86", linewidth=11,
                        solid_capstyle="butt", zorder=0)
                c, r, xs = crossings(A, B)
                lo, _, _ = crossings(A, B, 1 - DRIFT)
                hi, _, _ = crossings(A, B, 1 + DRIFT)
                col = PCOLOR[preset]
                if c and lo and hi:
                    ax.plot([min(lo[0], hi[0]), max(lo[0], hi[0])], [row, row],
                            color=col, linewidth=4.5, solid_capstyle="round", zorder=3)
                    ax.plot([c[0]], [row], marker=PMARK[preset], color=col, markersize=11,
                            markeredgewidth=0, zorder=4)
                    ax.annotate(f"{c[0]:.1f}", (c[0], row), textcoords="offset points",
                                xytext=(0, 10), ha="center", fontsize=11,
                                color=col, fontweight="bold")
                elif r[-1] < 1 and r[-1] > r[0]:
                    k = max(2, len(r) // 2)
                    xx, yy = xs[-k:], r[-k:]
                    mx, my = sum(xx) / k, sum(yy) / k
                    den = sum((x - mx) ** 2 for x in xx)
                    sl = sum((x - mx) * (v - my) for x, v in zip(xx, yy)) / den if den else 0
                    est = xs[-1] + (1 - r[-1]) / sl if sl > 0 else None
                    ax.annotate("", xy=(depth + 1.5, row), xytext=(depth, row),
                                arrowprops=dict(arrowstyle="-|>", color=col, lw=2.6))
                    if est and est <= 14:
                        ax.plot([est], [row], marker=PMARK[preset], color=col, markersize=10,
                                markeredgewidth=0, alpha=0.28, zorder=3)
                        ax.annotate(f"~{est:.0f}", (est, row), textcoords="offset points",
                                    xytext=(0, 10), ha="center", fontsize=11,
                                    color=col, alpha=0.6)
                row += 1
            row += 0.8
        ax.set_yticks(yticks); ax.set_yticklabels(ylabels, fontsize=12)
        ax.invert_yaxis()
        ax.set_xlim(0, 15); ax.set_xlabel("crossing level →")
        ax.set_title(mode)
        ax.grid(True, axis="x", color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    h = [Line2D([0], [0], color="0.86", lw=11, label="levels actually observed (L1..depth)"),
         Line2D([0], [0], color="0.35", lw=4.5, label="±2% sensitivity band"),
         Line2D([0], [0], color="0.35", lw=2.6, marker=">", markersize=9,
                label="crossing lies beyond the range"),
         Line2D([0], [0], color="0.55", lw=0, marker="o", markersize=10, alpha=0.3,
                label="extrapolated (indicative)")]
    axes[1].legend(handles=h, loc="center left", bbox_to_anchor=(1.02, 0.5),
                   framealpha=0.9, fontsize=12)
    fig.suptitle(f"B and D show no SEAL↔OpenFHE crossing only because their depth is "
                 f"shorter than the crossing level   ({op})", y=1.02)
    fig.text(0.5, -0.05,
             "Grey bar = the levels each preset actually observes. An arrow means the crossing "
             "exists but sits deeper than that range — not that it is absent.\n"
             "Faint marker = linear extrapolation from the upper half of the curve (indicative only).",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout()
    save(fig, fname)


# ═════════════════════════════════════ 5) 곡선 분기
def plot_divergence(d):
    dd = d[(d["mode"] == "1t") & (d.op == "rot1")]
    fig, ax = plt.subplots(figsize=(12.5, 7.0))
    info = {}
    for preset in PRESETS:
        g = dd[dd.preset == preset]
        o = g[g.library == "openfhe"].set_index("level").mean_us.sort_index()
        l = g[g.library == "lattigo"].set_index("level").mean_us.sort_index()
        mx = max(o.index)
        norm = (o / o[mx]) / (l / l[mx])
        key = preset in ("A", "C")
        ax.plot(norm.index, norm.values, marker=PMARK[preset], markersize=10 if key else 6,
                markeredgewidth=0, linewidth=3.4 if key else 1.8, color=PCOLOR[preset],
                alpha=1.0 if key else 0.28, zorder=4 if key else 2)
        info[preset] = (norm.index[0], norm.values[0])
    ax.axhline(1.0, color="0.2", linewidth=3.0, zorder=1)
    ax.annotate("1.0 — identical shape", (12.4, 1.0), textcoords="offset points",
                xytext=(0, 9), ha="right", fontsize=13, color="0.3")
    ann = {"A": "A   logP: OF 240 < LA 300\n→ OpenFHE falls deeper",
           "C": "C   logP: OF 300 > LA 240\n→ Lattigo falls deeper",
           "B": "B   logP equal (120)",
           "D": "D   logP equal (180)"}
    # 주석은 데이터 영역이 아니라 **왼쪽 여백**에 둔다 — 곡선 위에 놓으면 선을 가린다.
    for p, (x, y) in info.items():
        key = p in ("A", "C")
        ax.annotate(f"{ann[p]}\nL1 = {y:.3f}", (x, y), textcoords="offset points",
                    xytext=(-16, 0), ha="right", va="center",
                    fontsize=13 if key else 11, fontweight="bold" if key else "normal",
                    color=PCOLOR[p], annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=PCOLOR[p],
                              alpha=0.95 if key else 0.5, lw=2.0 if key else 1.0),
                    arrowprops=dict(arrowstyle="-", color=PCOLOR[p],
                                    alpha=0.9 if key else 0.4, lw=1.4))
    ax.set_xlim(-4.6, 12.6); ax.set_xticks(range(1, 13))
    ax.set_xlabel("level (remaining budget) →")
    ax.set_ylabel("shape ratio   (OF / OF[max]) ÷ (LA / LA[max])")
    ax.set_title("Swapping which library carries the smaller P\nreverses which curve falls deeper")
    ax.grid(True, color="0.93", linewidth=0.6); ax.set_axisbelow(True)
    fig.text(0.5, -0.05,
             "A and C (bold) are the test — they swap which library has the smaller P and the "
             "divergence flips sign (0.792 vs 1.184).\n"
             "B and D (faint) have EQUAL logP yet still diverge: a residual library overhead that "
             "the P-floor account does not explain.\n"
             "C is saw-toothed because it is the only preset where the two libraries have DIFFERENT "
             "digit sequences, so their steps land on different levels.   rot1, 1t.",
             ha="center", fontsize=12, color="0.3")
    save(fig, "curve_divergence.png")


# ═════════════════════════════════════ 6) mt / 1t
def plot_mt_ratio(d):
    piv = d.pivot_table(index=["preset", "library", "op", "level"],
                        columns="mode", values="mean_us").reset_index()
    piv["r"] = piv["mt"] / piv["1t"]
    heavy = piv[piv.op.isin(TIERS["heavy"])]
    fig, axes = plt.subplots(1, 2, figsize=(16.5, 6.6), sharey=True)
    ax, ends = axes[0], []
    for preset in PRESETS:
        m = heavy[(heavy.preset == preset) & (heavy.library == "openfhe")] \
            .groupby("level").r.median().sort_index()
        ax.plot(m.index, m.values, marker=PMARK[preset], markersize=9, markeredgewidth=0,
                linewidth=2.8, color=PCOLOR[preset], label=f"{preset} (depth {PMETA[preset][1]})")
        ends.append((preset, m.values[-1]))
    ax.axhline(1.0, color="0.2", linewidth=3.0, zorder=1)
    ax.annotate("1.0 — no gain", (5.0, 1.0), textcoords="offset points", xytext=(0, 8),
                ha="center", fontsize=13, color="0.3")
    ax.annotate("↓  below 1 = parallel gain", (0.03, 0.97), xycoords="axes fraction",
                ha="left", va="top", fontsize=14, color="0.2", fontweight="bold")
    ax.set_ylabel("mt / 1t"); ax.set_xlabel("level (remaining budget) →")
    ax.set_title("OpenFHE — the only library that gains")
    ax.set_xticks(range(1, 13)); ax.set_xlim(0.4, 12.6)
    ax.grid(True, color="0.93", linewidth=0.6); ax.set_axisbelow(True)
    ax.legend(loc="lower left", framealpha=0.9, fontsize=12)
    tt = "at maxLevel:\n" + "\n".join(f"  {p} (d{PMETA[p][1]:>2})  {v:.3f}" for p, v in ends)
    ax.text(0.97, 0.90, tt, transform=ax.transAxes, ha="right", va="top", fontsize=12,
            family="monospace", color="0.2",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.8", alpha=0.92))

    ax2 = axes[1]
    for lib in ["lattigo", "seal"]:
        for preset in PRESETS:
            m = heavy[(heavy.preset == preset) & (heavy.library == lib)] \
                .groupby("level").r.median().sort_index()
            ax2.plot(m.index, m.values, marker=PMARK[preset], markersize=6, markeredgewidth=0,
                     linewidth=1.8, color=LIB_COLOR[lib], alpha=0.85)
    ax2.axhline(1.0, color="0.2", linewidth=3.0, zorder=1)
    ax2.set_title("Lattigo · SEAL — no intra-op parallelism, so ≈ 1")
    ax2.set_xlabel("level (remaining budget) →")
    ax2.set_xticks(range(1, 13)); ax2.set_xlim(0.4, 12.6)
    ax2.grid(True, color="0.93", linewidth=0.6); ax2.set_axisbelow(True)
    ax2.legend(handles=[Line2D([0], [0], color=LIB_COLOR[l], lw=2.8, label=l)
                        for l in ["lattigo", "seal"]], loc="lower left", framealpha=0.9)
    fig.suptitle("Parallel gain shrinks as the preset gets shallower   (key-switch ops, median)",
                 y=1.02)
    fig.text(0.5, -0.05,
             "Only OpenFHE parallelises inside a single operation; Lattigo/SEAL ≈ 1 means they sit "
             "outside this axis, not that they are slower.\n"
             "This is NOT application-level parallelism (distributing independent ciphertexts).",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout()
    save(fig, "mt_over_1t.png")


if __name__ == "__main__":
    d = load()
    plot_summary_bars(d)
    plot_levels(d)
    plot_digit_steps(d)
    for op in ["rot1", "relin", "mul_cc_rlk"]:
        plot_crossings(d, op, f"crossings_{op}.png")
    plot_divergence(d)
    plot_mt_ratio(d)
    print(f"\n총 {len([f for f in os.listdir(OUT) if f.endswith('.png')])}장")
