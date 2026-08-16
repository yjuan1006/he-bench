#!/usr/bin/env python3
"""부트 **속도** 플롯 4장. 발표 주제 "정합된 조건에서 두 라이브러리의 부트 성능 차이".

⚠️ `scripts/boot_plots.py`(기존 5장)를 대체하지 않는다 — 새 파일이고 기존 PNG 는 남는다.
스타일은 **8-op 규약을 그대로 복제**한다(`scripts/v3_plots.py`):
  · rcParams(17/15/13/13/13/20), Okabe-Ito, 색 = 라이브러리, y 선형·패널별 독립
  · 막대(summary_*) = 값 라벨 소수점, 검정 얇은 에러바 + cap, y 그리드만
  · 선(levels_*) = 선 끝 직접 라벨, 작은 원 마커, 실선, 에러바는 옅게
  · 범례 우상단 바깥 박스 + 제목, 소제목 2줄(조건 / 파라미터), 하단 회색 각주

부트 고유 조정 2건
  · 라이브러리 2개 — 색은 8-op 그대로 두고 막대 폭·간격만 조정
  · **1t / mt 축이 새로 생겼다** — 색을 새로 만들지 않고 **해칭 + 채도**로 구분한다

그림
  ① boot_speed_main.png       부트 1회 속도. BT1 | BT2 × (1t, mt) — 발표의 핵심
  ② boot_speed_breakdown.png  3.30배의 분해: 설명되는 것(상한) vs 미규명
  ③ boot_speed_mt.png         병렬 이득 — Lattigo 는 이 축 밖이다
  ④ boot_speed_lb.png         분해깊이 ↔ 속도 (기존 boot_lb_time 을 8-op 선 규약으로)

⚠️ mt 의 부트 시간은 **timing 런**만 쓴다(§8.6 — mt 는 타이밍/정밀도 실행을 분리했다).
  keygen 은 두 런이 모두 수행하므로 mt 전량을 쓴다.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

plt.rcParams.update({
    "axes.titlesize": 17, "axes.labelsize": 15,
    "xtick.labelsize": 13, "ytick.labelsize": 13,
    "legend.fontsize": 13, "figure.titlesize": 20,
})

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plots", "boot")
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00"}     # 8-op 배정 그대로
LIB_ORDER = ["openfhe", "lattigo"]
LBS = [(2, 2), (3, 3), (3, 4), (4, 3), (4, 4)]
LB_LABEL = [f"{{{a},{b}}}" for a, b in LBS]
# ⚠️ 회전키 수는 **Lattigo 실측**이다. OpenFHE 것은 §10.7-4 에서 얻지 못했다(미규명 7).
ROTKEY_LA = {(2, 2): 61, (3, 3): 39, (3, 4): 48, (4, 3): 48, (4, 4): 33}
PRESET = {"BT1": 59, "BT2": 58}          # 프리셋 → Δ (q0=60, L=4 공통)
MT_BAND_8OP = (0.51, 0.76)               # §8.7 OpenFHE heavy mt/1t


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(p, ROOT)}")


def load(lib, mode):
    d = pd.read_csv(respath.find(f"boot_main_{lib}_{mode}_dku16c.csv"))
    d = d[d.rep >= 0]
    d["run"] = d.scaling.astype(str).str.split("|").str[-1]
    return d


def pick(d, preset, lb, timing_only=False):
    """(프리셋, 분해깊이) 한 점. mt 의 부트 시간은 timing 런만 본다."""
    g = d[(d.delta == PRESET[preset]) &
          (d.levelBudget_c2s == lb[0]) & (d.levelBudget_s2c == lb[1])]
    return g[g["run"] == "timing"] if (timing_only and (g["run"] == "timing").any()) else g


D = {(lib, mode): load(lib, mode) for lib in LIB_ORDER for mode in ["1t", "mt"]}


def boot_s(lib, mode, preset, lb=(3, 3)):
    g = pick(D[(lib, mode)], preset, lb, timing_only=True)
    return g.boot_us.mean() / 1e6, g.boot_us.std() / 1e6


def keygen_s(lib, mode, preset, lb=(3, 3)):
    return pick(D[(lib, mode)], preset, lb).keygen_us.mean() / 1e6


def qp(lib, preset, lb=(3, 3)):
    v = int(pick(D[(lib, "1t")], preset, lb).logQP_boot.iloc[0])
    return v, 1747 - v


# ══════════════════════════════════ ① 핵심 — 부트 1회 속도
def plot_speed_main():
    fig, axes = plt.subplots(1, 2, figsize=(15.0, 6.8))
    for ax, preset in zip(axes, ["BT1", "BT2"]):
        SP, W, ymax = 0.40, 0.36, 0.0
        for i, lib in enumerate(LIB_ORDER):
            for xi, mode in enumerate(["1t", "mt"]):
                v, e = boot_s(lib, mode, preset)
                off = (i - 0.5) * SP
                ax.bar([xi + off], [v], W, yerr=[e], capsize=3.5,
                       error_kw={"elinewidth": 1.1, "ecolor": "black"},
                       color=LIB_COLOR[lib], edgecolor="white", linewidth=0.8,
                       alpha=1.0 if mode == "1t" else 0.55,
                       hatch="" if mode == "1t" else "//")
                ax.annotate(f"{v:.2f}", (xi + off, v + e), textcoords="offset points",
                            xytext=(0, 4), ha="center", va="bottom", fontsize=12)
                ymax = max(ymax, v + e)
        # 배수 주석 — 이 그림이 말하려는 수 자체다
        for xi, mode in enumerate(["1t", "mt"]):
            r = boot_s("openfhe", mode, preset)[0] / boot_s("lattigo", mode, preset)[0]
            ax.annotate(f"{r:.2f}×", (xi, ymax * 1.12), ha="center", va="center",
                        fontsize=17, fontweight="bold", color="0.15",
                        bbox=dict(boxstyle="round,pad=0.32", fc="white", ec="0.6", lw=1.4))
        ax.set_ylim(0, ymax * 1.26); ax.set_xlim(-0.58, 1.58)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["1t", "mt (16 threads)"], fontsize=14)
        o, lat = qp("openfhe", preset), qp("lattigo", preset)
        ax.set_title(f"{preset} (logN=16, Δ={PRESET[preset]}, L=4, {{3,3}})\n"
                     f"logQP  OP {o[0]}({o[1]}) / LA {lat[0]}({lat[1]})", fontsize=15)
        ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
    axes[0].set_ylabel("bootstrap latency (s)")
    fig.legend(handles=[Patch(facecolor=LIB_COLOR[l], edgecolor="black",
                              alpha=1.0 if m == "1t" else 0.55,
                              hatch="" if m == "1t" else "//", label=f"{l} {m}")
                        for l in LIB_ORDER for m in ["1t", "mt"]],
               title="library · threads", loc="upper right", bbox_to_anchor=(1.0, 1.02),
               ncol=2, fontsize=13, title_fontsize=14)
    fig.suptitle("CKKS bootstrap latency · BT1 / BT2 · 1t vs mt", x=0.38, y=1.02)
    fig.text(0.5, -0.09,
             "NOT the same amount of work: EvalMod depth 14 (OpenFHE, dense key, K=512) "
             "vs 8 (Lattigo, sparse ephemeral key, K=16).\n"
             "Lattigo is also ~9 bits MORE precise at BT2 (17.90 vs 8.85) — quoting latency alone "
             "hides a gain bought with lower precision.\n"
             "reps 10, warmup 3, error bars = sample std. y-axes are per-panel.",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    save(fig, "boot_speed_main.png")


# ══════════════════════════════════ ② 3.30배의 분해
def plot_speed_breakdown():
    uni = boot_s("openfhe", "1t", "BT2")[0]
    lat = boot_s("lattigo", "1t", "BT2")[0]
    dg = pd.read_csv(respath.find("boot_prec_openfhe_diag_skdist_1t_dku16c.csv"))
    dg = dg[dg.rep >= 0]
    spa, spa_sd = dg.boot_us.mean() / 1e6, dg.boot_us.std() / 1e6
    expl, unex, tot = uni - spa, spa - lat, uni - lat

    fig, ax = plt.subplots(figsize=(14.5, 6.2))
    OC = LIB_COLOR["openfhe"]
    # 위→아래로 UNIFORM / SPARSE / Lattigo. 맨 위 막대만 3구간으로 쪼갠다.
    ax.barh([2], [lat], 0.52, color=LIB_COLOR["lattigo"], alpha=0.30,
            edgecolor="white", linewidth=1.0)
    ax.barh([2], [unex], 0.52, left=lat, color=OC, alpha=1.00,
            edgecolor="white", linewidth=1.0)
    ax.barh([2], [expl], 0.52, left=spa, color=OC, alpha=0.38,
            edgecolor="white", linewidth=1.0, hatch="//")
    ax.barh([1], [spa], 0.52, xerr=[spa_sd], capsize=3.5,
            error_kw={"elinewidth": 1.1, "ecolor": "black"},
            color=OC, alpha=0.38, edgecolor=OC, linewidth=1.6, hatch="//")
    ax.barh([0], [lat], 0.52, color=LIB_COLOR["lattigo"], edgecolor="white", linewidth=1.0)

    for y, v in [(2, uni), (1, spa), (0, lat)]:
        ax.annotate(f"{v:.2f} s", (v, y), textcoords="offset points", xytext=(9, 0),
                    va="center", fontsize=15, fontweight="bold", color="0.15")
    for x, y, txt, col in [
        (lat + unex / 2, 2, f"unexplained\n{unex:.2f} s  ({unex / tot * 100:.0f}%)", "white"),
        (spa + expl / 2, 2, f"explained (upper bound)\n{expl:.2f} s  ({expl / tot * 100:.0f}%)", "0.15"),
        (lat / 2, 2, "Lattigo level", "0.25"),
    ]:
        ax.annotate(txt, (x, y), ha="center", va="center", fontsize=12.5,
                    color=col, fontweight="bold")
    for xv in (lat, spa):
        ax.axvline(xv, color="0.45", linestyle="--", linewidth=1.3, zorder=0)
    # sparse 로 내려도 남는 배수 — 이 그림의 결론
    ax.annotate(f"still {spa / lat:.2f}× slower", ((lat + spa) / 2, 0.55), ha="center",
                fontsize=14, fontweight="bold", color="0.15",
                bbox=dict(boxstyle="round,pad=0.30", fc="white", ec="0.6", lw=1.4))
    ax.set_yticks([2, 1, 0])
    ax.set_yticklabels(["OpenFHE\nUNIFORM_TERNARY\n(main)",
                        "OpenFHE\nSPARSE_TERNARY\n(diagnostic)",
                        "Lattigo\n(main)"], fontsize=13)
    ax.set_xlim(0, uni * 1.16); ax.set_xlabel("bootstrap latency (s)")
    ax.grid(True, axis="x", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
    ax.set_title(f"Where the {uni / lat:.2f}× goes — over half of it is unexplained\n"
                 f"BT2 (Δ=58, L=4, {{3,3}}), 1t, dnum held at 7", fontsize=16)
    fig.text(0.5, -0.10,
             "SPARSE_TERNARY is a DIAGNOSTIC point, NOT a preset candidate — it makes the MAIN "
             "key sparse (H=192), so the Table 5.2 (uniform ternary) bound no longer applies.\n"
             "The 11.44 s drop is an UPPER BOUND: three confounders moved with it and all three "
             "point the same (faster) way — boot_depth 20→16, sizeQ 25→21, logP 240→180.\n"
             "dnum was held at 7 to remove a fourth. Do NOT read the residual as 'implementation "
             "quality' — that was never measured.   reps 10, warmup 3.",
             ha="center", fontsize=12, color="0.3")
    save(fig, "boot_speed_breakdown.png")


# ══════════════════════════════════ ③ 병렬 이득
def plot_speed_mt():
    fig, axes = plt.subplots(1, 2, figsize=(16.0, 6.6))

    ax = axes[0]
    ax.axhspan(*MT_BAND_8OP, color="0.55", alpha=0.16, zorder=0)
    ax.annotate("8-op heavy ops (OpenFHE, §8.7):  0.51 – 0.76",
                (0.02, sum(MT_BAND_8OP) / 2), xycoords=("axes fraction", "data"),
                ha="left", va="center", fontsize=12, color="0.3",
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="0.8", alpha=0.92))
    SP, W = 0.24, 0.20
    for i, lib in enumerate(LIB_ORDER):
        for xi, lb in enumerate(LBS):
            rs = [boot_s(lib, "mt", p, lb)[0] / boot_s(lib, "1t", p, lb)[0]
                  for p in ["BT1", "BT2"]]
            v, off = float(np.mean(rs)), (i - 0.5) * SP
            ax.bar([xi + off], [v], W,
                   yerr=[[v - min(rs)], [max(rs) - v]], capsize=3.5,
                   error_kw={"elinewidth": 1.1, "ecolor": "black"},
                   color=LIB_COLOR[lib], edgecolor="white", linewidth=0.8)
            ax.annotate(f"{v:.3f}", (xi + off, max(rs)), textcoords="offset points",
                        xytext=(0, 4), ha="center", va="bottom", fontsize=11)
    ax.axhline(1.0, color="0.2", linewidth=2.6, zorder=2)
    ax.annotate("solid line at 1.0 = no gain", (0.02, 0.97), xycoords="axes fraction",
                ha="left", va="top", fontsize=12, color="0.3")
    ax.annotate("↓  below 1 = parallel gain", (0.02, 0.03), xycoords="axes fraction",
                ha="left", va="bottom", fontsize=13, color="0.2", fontweight="bold")
    ax.set_xticks(range(5)); ax.set_xticklabels(LB_LABEL, fontsize=13)
    ax.set_xlabel("levelBudget {c2s, s2c}")
    ax.set_ylabel("mt / 1t")
    ax.set_ylim(0, 1.22)
    ax.set_title("Bootstrap  —  only OpenFHE is on this axis\n"
                 "bars = mean of BT1/BT2, whiskers = the two presets", fontsize=15)
    ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)

    ax2 = axes[1]
    SP, W, ymax = 0.40, 0.36, 0.0
    for i, lib in enumerate(LIB_ORDER):
        for xi, mode in enumerate(["1t", "mt"]):
            v = keygen_s(lib, mode, "BT1")
            off = (i - 0.5) * SP
            ax2.bar([xi + off], [v], W, color=LIB_COLOR[lib], edgecolor="white",
                    linewidth=0.8, alpha=1.0 if mode == "1t" else 0.55,
                    hatch="" if mode == "1t" else "//")
            ax2.annotate(f"{v:.1f}", (xi + off, v), textcoords="offset points",
                         xytext=(0, 4), ha="center", va="bottom", fontsize=12)
            ymax = max(ymax, v)
    for i, lib in enumerate(LIB_ORDER):
        r = keygen_s(lib, "1t", "BT1") / keygen_s(lib, "mt", "BT1")
        ax2.annotate(f"{lib}  {r:.2f}×", (0.5, ymax * (0.94 - 0.10 * i)), ha="center",
                     fontsize=14, fontweight="bold", color=LIB_COLOR[lib])
    ax2.set_ylim(0, ymax * 1.16); ax2.set_xlim(-0.58, 1.58)
    ax2.set_xticks([0, 1]); ax2.set_xticklabels(["1t", "mt (16 threads)"], fontsize=14)
    ax2.set_ylabel("keygen (s)")
    ax2.set_title("Key generation  —  the same split, much larger\n"
                  "BT1 (Δ=59, L=4, {3,3})", fontsize=15)
    ax2.grid(True, axis="y", color="0.9", linewidth=0.6); ax2.set_axisbelow(True)

    fig.legend(handles=[Patch(facecolor=LIB_COLOR[l], edgecolor="black", label=l)
                        for l in LIB_ORDER] +
                       [Patch(facecolor="0.75", edgecolor="black", label="1t"),
                        Patch(facecolor="0.88", edgecolor="black", hatch="//", label="mt")],
               title="library                threads (keygen panel)",
               loc="upper right", bbox_to_anchor=(1.0, 1.02),
               ncol=2, fontsize=13, title_fontsize=13)
    fig.suptitle("Parallel gain · bootstrap and keygen · mt = 16 threads", x=0.40)
    fig.text(0.5, -0.10,
             "Lattigo has no intra-operation parallelism, so ≈ 1 means it sits OUTSIDE this axis — "
             "not that it is slower. It is still the faster library in both modes.\n"
             "Bootstrap gain (0.34–0.48) is LARGER than the 8-op heavy band (0.51–0.76): a "
             "10–60 s circuit amortises OMP team/barrier cost that a µs-scale op cannot.\n"
             "Bootstrap timings use the mt TIMING runs only (§8.6 separates timing and precision "
             "runs); keygen pools BOTH mt runs (20 samples), since both perform it.   reps 10, warmup 3.",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    save(fig, "boot_speed_mt.png")


# ══════════════════════════════════ ④ 분해깊이 ↔ 속도 (levels_* 선 규약)
def plot_speed_lb():
    fig, axes = plt.subplots(1, 2, figsize=(16.5, 6.8))
    for ax, mode in zip(axes, ["1t", "mt"]):
        ends = []
        for lib in LIB_ORDER:
            for preset, ls in [("BT1", "--"), ("BT2", "-")]:
                ys = [boot_s(lib, mode, preset, lb) for lb in LBS]
                mu, sd = [a for a, _ in ys], [b for _, b in ys]
                ax.plot(range(5), mu, color=LIB_COLOR[lib], linestyle=ls, marker="o",
                        markersize=6, linewidth=2.4, markeredgewidth=0)
                ax.errorbar(range(5), mu, yerr=sd, fmt="none", ecolor=LIB_COLOR[lib],
                            elinewidth=0.8, capsize=2, capthick=0.8, alpha=0.4)
                ends.append((mu[-1], f"{lib} {preset}", LIB_COLOR[lib]))
        # 선 끝 직접 라벨 (범례 대신) — 겹치면 위에서부터 밀어 내린다
        for k, (yv, lab, col) in enumerate(sorted(ends, reverse=True)):
            ax.annotate(lab, (4, yv), textcoords="offset points",
                        xytext=(10, 4 - 15 * k), color=col, fontsize=12,
                        fontweight="bold", annotation_clip=False)
        # OpenFHE 최속점 강조 — 모드에 따라 자리가 바뀐다는 것이 이 그림의 주장이다
        best = int(np.argmin([boot_s("openfhe", mode, "BT2", lb)[0] for lb in LBS]))
        bv = boot_s("openfhe", mode, "BT2", LBS[best])[0]
        lbest = int(np.argmin([boot_s("lattigo", mode, "BT2", lb)[0] for lb in LBS]))
        lv = boot_s("lattigo", mode, "BT2", LBS[lbest])[0]
        if best == lbest:
            # 같은 자리면 콜아웃 두 개가 서로(그리고 상대 선을) 겹친다 — 하나로 합친다
            ax.annotate(f"both fastest: {LB_LABEL[best]}", (lbest, lv),
                        textcoords="offset points", xytext=(0, -52), ha="center",
                        fontsize=13, fontweight="bold", color="0.15",
                        arrowprops=dict(arrowstyle="-|>", color="0.35", lw=2.2),
                        bbox=dict(boxstyle="round,pad=0.30", fc="white", ec="0.45", lw=1.6))
        else:
            ax.annotate(f"OpenFHE fastest: {LB_LABEL[best]}", (best, bv),
                        textcoords="offset points", xytext=(0, -58), ha="center",
                        fontsize=13, fontweight="bold", color=LIB_COLOR["openfhe"],
                        arrowprops=dict(arrowstyle="-|>", color=LIB_COLOR["openfhe"], lw=2.2),
                        bbox=dict(boxstyle="round,pad=0.30", fc="white",
                                  ec=LIB_COLOR["openfhe"], lw=1.6))
            ax.annotate(f"Lattigo fastest: {LB_LABEL[lbest]}", (lbest, lv),
                        textcoords="offset points", xytext=(0, 34), ha="center",
                        fontsize=13, fontweight="bold", color=LIB_COLOR["lattigo"],
                        arrowprops=dict(arrowstyle="-|>", color=LIB_COLOR["lattigo"], lw=2.2),
                        bbox=dict(boxstyle="round,pad=0.30", fc="white",
                                  ec=LIB_COLOR["lattigo"], lw=1.6))
        ax.set_xlim(-0.35, 4.72)
        ax.set_xticks(range(5))
        ax.set_xticklabels([f"{lab}\n{ROTKEY_LA[lb]} keys (LA)"
                            for lab, lb in zip(LB_LABEL, LBS)], fontsize=12.5)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("levelBudget {c2s, s2c}   (rotation keys below)")
        ax.set_title(mode if mode == "1t" else "mt (16 threads)")
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    axes[0].set_ylabel("bootstrap latency (s)")
    fig.suptitle("CKKS bootstrap latency vs factorisation depth · BT1 / BT2 · 1t | mt", y=1.02)
    fig.text(0.5, -0.10,
             "The fastest factorisation MOVES with the thread mode for OpenFHE ({3,3} at 1t → "
             "{4,3} at mt) but NOT for Lattigo ({4,3} in both) — 'the optimal depth' is a "
             "function of (library, thread mode), not a single value.\n"
             "Rotation-key counts alone do not explain the order: {4,4} has the FEWEST keys (33) "
             "yet is 4th of 5 at 1t — the 2-level-longer chain cancels the saving. "
             "The counts shown are LATTIGO-measured; OpenFHE's were never obtained (§10.7-4).\n"
             "Solid = BT2 (Δ=58), dashed = BT1 (Δ=59). Latency is almost identical between the two "
             "presets — the Δ step moves precision, not speed.   reps 10, warmup 3.",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout()
    save(fig, "boot_speed_lb.png")


if __name__ == "__main__":
    plot_speed_main()
    plot_speed_breakdown()
    plot_speed_mt()
    plot_speed_lb()
