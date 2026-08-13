#!/usr/bin/env python3
"""HEXL 아암 확장(8-op × 레벨 전수) 플롯 — baseline 과 **같은 형식**.

출력 plots/v3/hexl/ (기존 5장은 plots/v3/hexl/old/ 로 옮겨 둔다).
baseline 플롯 plots/v3/*.png 은 건드리지 않는다.

이 그림들이 baseline 그림과 다른 점은 딱 둘이다.
  1. OpenFHE·SEAL 값이 **HEXL 빌드**의 값이다. HEXL OFF 는 그리지 않는다.
     Lattigo 는 순수 Go 라 HEXL 대응물이 없어 baseline 빌드 값 그대로다.
     → 이 사실을 모든 캡션에 박는다(CAP_ARM). 없으면 "Lattigo 만 최적화를
       안 한 채 비교했다"는 오해를 준다.
  2. 프리셋이 A 하나뿐이라 summary 서브플롯이 1개다(baseline 은 4개).

mt 의 산포 처리 — baseline 과 다른 유일한 통계 규약.
  OpenFHE mt 는 런 간 편차가 최대 0.437 이라 한 런의 std 가 산포를 못 담는다.
  → mt 값은 **런 중앙값**, 에러바는 **런 간 min..max**.
    OpenFHE 5런 / SEAL 3런. Lattigo mt 만 단일 런이라 ±1 std 를 쓴다
    (CV 0.007~0.015 로 안정적이고, 애초에 HEXL 비교의 당사자가 아니다).
  1t 는 baseline 과 동일하게 ±1 std.

스타일 규약은 scripts/v3_plots.py 와 동일하다(Okabe-Ito, y 선형,
x 는 왼쪽 저레벨 → 오른쪽 고레벨, 한글 폰트 없음 → 영문).
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
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plots", "v3", "hexl")
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00", "seal": "#CC79A7"}
LIB_ORDER = ["lattigo", "openfhe", "seal"]
TIERS = {"heavy": ["mul_cc_rlk", "relin", "rot1"],
         "mid": ["mul_cc", "rescale", "mul_cp"],
         "light": ["add_cc", "add_cp"]}
GC_OPS = {"add_cc", "add_cp", "mul_cp", "mul_cc"}
PRESET, LOGN, DEPTH, DELTA = "A", 15, 12, 42
P = "results_v3n15d42L12"

CAP_ARM = ("OpenFHE and SEAL are HEXL-accelerated; Lattigo is pure Go and has no "
           "HEXL counterpart, so its values are the baseline build.")
GC_CAP = ("Lattigo add_cc/add_cp/mul_cp/mul_cc are NOT reliable here (Go GC, up to 39% "
          "run-to-run) — shown dotted/hatched & faded; do not judge from them.")


def unreliable(lib, op):
    return lib == "lattigo" and op in GC_OPS


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(p, ROOT)}")


def q(path):
    return pd.read_csv(respath.find(path)).query("ok == 1")


# ═══════════════════════════════════════════════ 데이터
def load():
    """긴 형식 DataFrame: mode, library, op, level, mean_ms, lo_ms, hi_ms, kind, logP."""
    rows = []

    def add(mode, lib, op, level, val, lo, hi, kind, logP):
        rows.append(dict(mode=mode, library=lib, op=op, level=int(level),
                         mean_ms=val, lo_ms=lo, hi_ms=hi, kind=kind, logP=int(logP)))

    # ---- 1t ----
    b1 = q(f"{P}_timing_1t_dku16c.csv")                       # Lattigo 는 여기서만 가져온다
    la = b1[b1.library == "lattigo"]
    for _, r in la.iterrows():
        s = r.std_us / 1000
        add("1t", "lattigo", r.op, r.level, r.mean_us / 1000,
            r.mean_us / 1000 - s, r.mean_us / 1000 + s, "std", r.logP)
    for lib, f in [("openfhe", f"{P}_hexl8_timing_1t_dku16c.csv"),
                   ("seal", f"{P}_hexl8_timing_1t_seal_dku16c.csv")]:
        for _, r in q(f).iterrows():
            s = r.std_us / 1000
            add("1t", lib, r.op, r.level, r.mean_us / 1000,
                r.mean_us / 1000 - s, r.mean_us / 1000 + s, "std", r.logP)

    # ---- mt ----
    bm = q(f"{P}_timing_mt_dku16c.csv")
    for _, r in bm[bm.library == "lattigo"].iterrows():
        s = r.std_us / 1000
        add("mt", "lattigo", r.op, r.level, r.mean_us / 1000,
            r.mean_us / 1000 - s, r.mean_us / 1000 + s, "std", r.logP)
    mt_sets = {
        "openfhe": [f"{P}_hexl8_timing_mt_run{i}_dku16c.csv" for i in range(1, 6)],
        "seal": [f"{P}_hexl8_timing_mt_seal_run{i}_dku16c.csv" for i in range(1, 4)],
    }
    for lib, files in mt_sets.items():
        ds = [q(f) for f in files]
        base = ds[0]
        for op in base.op.unique():
            for L in sorted(base.level.unique()):
                v = [d[(d.op == op) & (d.level == L)].mean_us.iloc[0] / 1000 for d in ds]
                lp = base[(base.op == op) & (base.level == L)].logP.iloc[0]
                add("mt", lib, op, L, float(np.median(v)), min(v), max(v), "range", lp)
    return pd.DataFrame(rows)


def logp_str(d, mode):
    g = d[d["mode"] == mode]
    return " / ".join(f"{l[:2].upper()} {int(g[g.library == l].logP.iloc[0])}"
                      for l in ["openfhe", "lattigo", "seal"])


def errcap(mode):
    return ("mt: bars are run-to-run min..max (OpenFHE 5 runs, SEAL 3 runs); "
            "Lattigo mt is a single run (±1 std) as it is not part of the HEXL comparison."
            if mode == "mt" else "1t: bars are ±1 std over 30 reps.")


# ═════════════════════════════════════ 1) 요약 막대 (maxLevel)
def plot_summary_bars(d):
    DEC = {"heavy": 1, "mid": 2, "light": 3}
    for mode in ["1t", "mt"]:
        for tier, ops in TIERS.items():
            sub = d[(d["mode"] == mode) & (d.level == DEPTH)]
            present = [o for o in ops if not sub[sub.op == o].empty]
            if not present:
                continue
            # 프리셋이 A 하나뿐이라 서브플롯도 하나다(baseline 은 4개 나란히).
            fig, ax = plt.subplots(figsize=(4.0 + 2.6 * len(present), 6.8))
            x = range(len(present))
            SP, W = 0.26, 0.21
            ymax = 0.0
            for i, lib in enumerate(LIB_ORDER):
                for xi, o in zip(x, present):
                    r = sub[(sub.op == o) & (sub.library == lib)]
                    if r.empty:
                        continue
                    v, lo, hi = r.mean_ms.iloc[0], r.lo_ms.iloc[0], r.hi_ms.iloc[0]
                    off = (i - 1) * SP
                    ax.bar([xi + off], [v], W, yerr=[[v - lo], [hi - v]], capsize=2.5,
                           error_kw={"elinewidth": 1.0, "alpha": 0.6},
                           color=LIB_COLOR[lib], edgecolor="white", linewidth=0.8,
                           hatch="//" if unreliable(lib, o) else "")
                    ax.annotate(f"{v:.{DEC[tier]}f}", (xi + off, hi),
                                textcoords="offset points", xytext=(0, 4),
                                ha="center", va="bottom", fontsize=11)
                    ymax = max(ymax, hi)
            ax.set_ylim(0, ymax * 1.20)
            ax.set_xticks(list(x)); ax.set_xticklabels(present, fontsize=13)
            ax.set_title(f"{PRESET} (logN={LOGN}, depth={DEPTH}, Δ={DELTA})\n"
                         f"logP  {logp_str(d, mode)}", fontsize=15)
            ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
            ax.set_ylabel("mean latency (ms)")
            # baseline 은 4패널이라 범례를 오른쪽 위 구석에 두고 suptitle 을 x=0.40 으로
            # 밀어 놨다. 여기는 패널이 1개라 그 배치를 그대로 쓰면 범례가 제목을 덮고
            # 위쪽에 빈 띠가 크게 남는다 → 제목 아래 가운데로 내리고 여백을 줄인다.
            fig.suptitle(f"CKKS op latency @ maxLevel · {tier} · {mode} · HEXL arm", y=1.0)
            fig.legend(handles=[Patch(facecolor=LIB_COLOR[l], edgecolor="black",
                                      label=l + (" (HEXL)" if l != "lattigo" else " (no HEXL)"))
                                for l in LIB_ORDER],
                       title="library", loc="upper center", bbox_to_anchor=(0.5, 0.955),
                       ncol=3, fontsize=13, title_fontsize=13)
            cap = CAP_ARM + "\n" + errcap(mode)
            if tier != "heavy":
                cap += "\n" + GC_CAP
            # 캡션 시작 위치를 -0.03 으로 두면 op 눈금 라벨(add_cc 등)과 겹친다.
            # 줄 수에 따라 더 내린다.
            fig.text(0.5, -0.075 - 0.03 * (cap.count("\n") - 1), cap,
                     ha="center", fontsize=12, color="0.3")
            fig.tight_layout(rect=[0, 0, 1, 0.87])
            save(fig, f"summary_hexl_{tier}_{mode}.png")


# ═════════════════════════════════════ 2) 레벨 곡선 — op 별 facet
def plot_levels(d):
    for mode in ["1t", "mt"]:
        for tier, ops in TIERS.items():
            sub = d[(d["mode"] == mode) & (d.op.isin(ops))]
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
                    series[lib] = dict(zip(g.level, g.mean_ms))
                    bad = unreliable(lib, op)
                    ms = g.mean_ms.values
                    lo, hi = ms - g.lo_ms.values, g.hi_ms.values - ms
                    ax.plot(g.level, ms, color=LIB_COLOR[lib],
                            linestyle=":" if bad else "-", marker="o", markersize=6,
                            linewidth=2.4, markeredgewidth=0, alpha=0.4 if bad else 1.0)
                    ax.errorbar(g.level, ms, yerr=[lo, hi], fmt="none",
                                ecolor=LIB_COLOR[lib], elinewidth=0.8, capsize=2,
                                capthick=0.8, alpha=0.4)
                # 오른쪽 여백은 선 끝 직접 라벨 자리 (baseline 과 같은 계수 0.15)
                pad = max(0.55, 0.15 * (DEPTH - 0.4))
                ax.set_xlim(0.4, DEPTH + pad)
                ax.set_xticks(range(1, DEPTH + 1))
                ax.set_ylim(bottom=0)
                ends = sorted(((series[l][DEPTH], l) for l in series), reverse=True)
                for k, (yv, lib) in enumerate(ends):
                    ax.annotate(lib, (DEPTH, yv), textcoords="offset points",
                                xytext=(9, 4 - 15 * k), color=LIB_COLOR[lib],
                                fontsize=12, fontweight="bold", annotation_clip=False)
                for a, b in [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]:
                    if a not in series or b not in series:
                        continue
                    if op in GC_OPS and "lattigo" in (a, b):
                        continue
                    l1.append(f"{op} {a[:2].upper()}/{b[:2].upper()} "
                              f"{series[a][1] / series[b][1]:.2f}")
                ax.set_title(op)
                ax.set_xlabel("level (remaining budget) →")
                ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
            axes[0].set_ylabel("mean latency (ms)")
            fig.suptitle(f"{PRESET} · {tier} · {mode} · HEXL arm   —   logN {LOGN}, "
                         f"depth {DEPTH}, Δ {DELTA}   (logP {logp_str(d, mode)})", y=1.03)
            cap = (CAP_ARM + "\nratios at L1:   " + "   ·   ".join(l1) +
                   "\nLinear y-axis — high levels dominate and the low end looks flat; "
                   "the L1 ratios above cover that range.   " + errcap(mode))
            if tier != "heavy":
                cap += "\n" + GC_CAP
            # 캡션이 각 패널의 x 축 라벨("level (remaining budget) →")과 겹쳐
            # 시작 위치를 줄 수에 맞춰 더 내린다.
            fig.text(0.5, -0.115 - 0.032 * (cap.count("\n") - 2), cap,
                     ha="center", fontsize=12, color="0.3")
            fig.tight_layout()
            save(fig, f"levels_{PRESET}_{tier}_{mode}_hexl.png")


if __name__ == "__main__":
    d = load()
    os.makedirs(os.path.join(ROOT, "explore"), exist_ok=True)
    out = os.path.join(ROOT, "explore", "hexl8_summary_timing.csv")
    d.to_csv(out, index=False)          # ⚠️ v3_summary_timing.csv 에는 병합하지 않는다
    print(f"[csv] {os.path.relpath(out, ROOT)} ({len(d)}행)")
    plot_summary_bars(d)
    plot_levels(d)
    print(f"\n총 {len([f for f in os.listdir(OUT) if f.endswith('.png')])}장 → "
          f"{os.path.relpath(OUT, ROOT)}")
