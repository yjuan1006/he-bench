#!/usr/bin/env python3
"""HEXL 아암 플롯. 출력 plots/v3/hexl/ — baseline 플롯(plots/v3/*.png)은 건드리지 않는다.

⚠️ 이 아암은 baseline 과 **다른 질문**에 답한다.
  Lattigo 는 순수 Go 라 HEXL 대응물이 없다 → 가속 대상이 아니다.
  그래서 이 그림들은 "AVX-512 로 가속된 둘 vs 안 된 하나"의 비교다.
  모든 그림 캡션에 그 문장을 박아 둔다(CAP_HEXL). 색만으로는 그 조건 차이가
  읽히지 않으므로 **해칭(OFF) / 실채움(HEXL)** 과 x 라벨로 이중 인코딩한다.

데이터 범위: 프리셋 A, 레벨 3점(12/6/1), heavy 3종, 1t·mt.
  baseline 처럼 레벨 전수가 아니므로 **곡선이 아니라 점·막대**로 그린다.

mt 의 불확실성 처리 — 이게 이 아암의 핵심 주의점이다.
  OpenFHE mt 는 런 간 편차가 최대 0.437 이라 한 런의 std 로는 산포를 못 담는다.
  → mt 는 **여러 런의 중앙값**을 값으로, **런 간 min~max** 를 에러바로 쓴다.
    OpenFHE OFF/HEXL 5런, SEAL OFF/HEXL 3런.
  Lattigo mt 만 단일 런이라 std 를 쓴다(CV 0.007~0.015 로 안정적이고,
  애초에 HEXL 비교의 당사자가 아니다). 그림에서 이 차이를 명시한다.

축·스타일 규약은 baseline(scripts/v3_plots.py)과 동일하다.
  Okabe-Ito, 색=라이브러리, y 선형, x 는 왼쪽이 저레벨(L1) → 오른쪽이 고레벨.
  한글 폰트가 없으므로 그림 안 문자열은 전부 영어.
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
OPS = ["mul_cc_rlk", "relin", "rot1"]
LEVELS = [1, 6, 12]          # 왼쪽이 저레벨 — baseline 과 같은 방향
MAXLEVEL = 12

CAP_HEXL = ("Lattigo has no HEXL counterpart (pure Go) — this arm compares "
            "two AVX-512-accelerated libraries against one that is not.")


def light(hex_color, f=0.55):
    """흰색과 섞어 옅은 판을 만든다. OFF 조건용."""
    c = np.array(matplotlib.colors.to_rgb(hex_color))
    return tuple(c + (1.0 - c) * f)


def dark(hex_color, f=0.72):
    """라벨 글자용으로 어둡게. SEAL #CC79A7 은 흰 바탕 대비 2.98 로 낮아
    그대로 쓰면 작은 글씨가 안 읽힌다(dataviz 팔레트 검증 WARN)."""
    c = np.array(matplotlib.colors.to_rgb(hex_color)) * f
    return tuple(c)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(p, ROOT)}")


# ═══════════════════════════════════════════════ 데이터
def q(path):
    return pd.read_csv(respath.find(path)).query("ok == 1")


def load():
    """{(mode, lib, cond, op, level): (value, lo, hi, kind)} 를 만든다.

    kind 는 에러바의 정체다 — 'std'(단일 런) 인지 'range'(런 간 min~max) 인지.
    두 종류를 한 그림에 쓰므로 무엇이 무엇인지 데이터에 달고 다닌다.
    """
    d = {}

    # ---- 1t : 전부 단일 런 → std ----
    b1 = q("results_v3n15d42L12_timing_1t_dku16c.csv")
    h1 = pd.concat([q("results_v3n15d42L12_hexl_timing_1t_dku16c.csv"),
                    q("results_v3n15d42L12_hexl_timing_1t_seal_dku16c.csv")])
    for lib in ["lattigo", "openfhe", "seal"]:
        for op in OPS:
            for L in LEVELS:
                r = b1[(b1.library == lib) & (b1.op == op) & (b1.level == L)]
                m, s = r.mean_us.iloc[0] / 1000, r.std_us.iloc[0] / 1000
                d[("1t", lib, "off", op, L)] = (m, m - s, m + s, "std")
    for lib in ["openfhe", "seal"]:
        for op in OPS:
            for L in LEVELS:
                r = h1[(h1.library == lib) & (h1.op == op) & (h1.level == L)]
                m, s = r.mean_us.iloc[0] / 1000, r.std_us.iloc[0] / 1000
                d[("1t", lib, "hexl", op, L)] = (m, m - s, m + s, "std")

    # ---- mt : 복수 런 → 중앙값 + 런 간 범위 ----
    sets = {
        ("openfhe", "off"): [f"results_v3n15d42L12_off_timing_mt_run{i}_dku16c.csv" for i in range(1, 6)],
        ("openfhe", "hexl"): (["results_v3n15d42L12_hexl_timing_mt_dku16c.csv"] +
                              [f"results_v3n15d42L12_hexl_timing_mt_run{i}_dku16c.csv" for i in [2, 3, 4, 5]]),
        ("seal", "off"): [f"results_v3n15d42L12_off_timing_mt_seal_run{i}_dku16c.csv" for i in [1, 2, 3]],
        ("seal", "hexl"): (["results_v3n15d42L12_hexl_timing_mt_seal_dku16c.csv"] +
                           [f"results_v3n15d42L12_hexl_timing_mt_seal_run{i}_dku16c.csv" for i in [2, 3]]),
    }
    for (lib, cond), files in sets.items():
        ds = [q(f) for f in files]
        for op in OPS:
            for L in LEVELS:
                v = [x[(x.op == op) & (x.level == L)].mean_us.iloc[0] / 1000 for x in ds]
                d[("mt", lib, cond, op, L)] = (float(np.median(v)), min(v), max(v), "range")

    # Lattigo mt 는 단일 런뿐 — std 로 둔다. HEXL 비교의 당사자가 아니고 CV 도 작다.
    bm = q("results_v3n15d42L12_timing_mt_dku16c.csv")
    for op in OPS:
        for L in LEVELS:
            r = bm[(bm.library == "lattigo") & (bm.op == op) & (bm.level == L)]
            m, s = r.mean_us.iloc[0] / 1000, r.std_us.iloc[0] / 1000
            d[("mt", "lattigo", "off", op, L)] = (m, m - s, m + s, "std")
    return d


D = load()
NRUNS = {("1t", "openfhe"): 1, ("1t", "seal"): 1,
         ("mt", "openfhe"): 5, ("mt", "seal"): 3}


# ═════════════════════════════ 1) 조건별 막대 (maxLevel)
def plot_summary(mode):
    # 막대 5개: lattigo / OF-OFF / OF-HEXL / SE-OFF / SE-HEXL
    #   같은 라이브러리는 같은 색, OFF 는 옅은 채움 + 해칭 → 색각/흑백에서도 갈린다.
    bars = [("lattigo", "off",  "Lattigo\n(no HEXL)"),
            ("openfhe", "off",  "OpenFHE\nOFF"),
            ("openfhe", "hexl", "OpenFHE\nHEXL"),
            ("seal",    "off",  "SEAL\nOFF"),
            ("seal",    "hexl", "SEAL\nHEXL")]
    fig, ax = plt.subplots(figsize=(15.5, 8.0))
    W, SP = 0.155, 0.17
    ymax = 0.0
    for gi, op in enumerate(OPS):
        for bi, (lib, cond, _) in enumerate(bars):
            v, lo, hi, kind = D[(mode, lib, cond, op, MAXLEVEL)]
            x = gi + (bi - 2) * SP
            solid = (cond == "hexl")
            ax.bar([x], [v], W,
                   color=LIB_COLOR[lib] if solid else light(LIB_COLOR[lib]),
                   edgecolor=LIB_COLOR[lib], linewidth=1.6,
                   # Lattigo 는 'OFF 상태'가 아니라 '해당 없음'이다 → 해칭을 달리해
                   # OFF(///) 와 혼동되지 않게 한다.
                   hatch=("xxx" if lib == "lattigo" else ("" if solid else "///")),
                   # Lattigo 는 OFF/HEXL 구분 자체가 없다 → 점선 테두리로 "대상 아님"을 표시
                   linestyle="--" if lib == "lattigo" else "-", zorder=3)
            ax.errorbar([x], [v], yerr=[[v - lo], [hi - v]], fmt="none",
                        ecolor="0.25", elinewidth=1.4, capsize=4, capthick=1.4, zorder=4)
            ax.annotate(f"{v:.1f}", (x, hi), textcoords="offset points", xytext=(0, 5),
                        ha="center", va="bottom", fontsize=12,
                        fontweight="bold" if solid else "normal")
            ymax = max(ymax, hi)
    ax.set_xticks(range(len(OPS)))
    ax.set_xticklabels(OPS, fontsize=15)
    ax.set_ylim(0, ymax * 1.22)
    ax.set_ylabel("mean latency at maxLevel (ms)")
    ax.grid(True, axis="y", color="0.9", linewidth=0.6)
    ax.set_axisbelow(True)

    # 막대 아래에 조건 라벨 — 색 없이도 어느 막대가 무엇인지 읽히게 한다
    for gi in range(len(OPS)):
        for bi, (lib, cond, lab) in enumerate(bars):
            ax.annotate(lab, (gi + (bi - 2) * SP, 0), xycoords=("data", "axes fraction"),
                        textcoords="offset points", xytext=(0, -34),
                        ha="center", va="top", fontsize=9.5,
                        color=dark(LIB_COLOR[lib]),
                        fontweight="bold" if cond == "hexl" else "normal")

    handles = [Patch(facecolor=light(LIB_COLOR["openfhe"]), edgecolor="0.3", hatch="///",
                     label="HEXL OFF (hatched, pale)"),
               Patch(facecolor=LIB_COLOR["openfhe"], edgecolor="0.3", label="HEXL ON (solid)"),
               Patch(facecolor=light(LIB_COLOR["lattigo"]), edgecolor=LIB_COLOR["lattigo"],
                     linestyle="--", hatch="xxx",
                     label="Lattigo: N/A, not an OFF state (x-hatch, dashed edge)")]
    ax.legend(handles=handles, loc="upper right", framealpha=0.95)

    err = ("error bars = run-to-run min..max (OpenFHE 5 runs, SEAL 3 runs); Lattigo = ±1 std (single run)"
           if mode == "mt" else "error bars = ±1 std over 30 reps")
    ax.set_title(f"Preset A · maxLevel (L12) · {mode} — what Intel HEXL buys, per library", pad=14)
    fig.text(0.5, -0.055,
             f"{CAP_HEXL}\n{err}. Same colour = same library; pale+hatched is HEXL OFF.",
             ha="center", fontsize=12, color="0.3")
    save(fig, f"summary_hexl_{mode}.png")


# ═════════════════════════════ 2) 배수
def plot_speedup():
    """OFF→HEXL 배수. 점이 3개뿐이라 **띠(fill_between)가 아니라 캡 달린 에러바**를 쓴다 —
    띠로 그렸더니 OpenFHE mt 의 넓은 구간이 1t 선을 삼켜 둘이 구분되지 않았다."""
    fig, ax = plt.subplots(figsize=(12.5, 7.6))
    series = [("openfhe", "1t", "-", "o"), ("openfhe", "mt", "--", "s"),
              ("seal", "1t", "-", "^"), ("seal", "mt", "--", "D")]
    x = np.arange(len(LEVELS), dtype=float)
    OFFX = {("openfhe", "1t"): -0.045, ("openfhe", "mt"): 0.045,
            ("seal", "1t"): -0.045, ("seal", "mt"): 0.045}   # 에러바 겹침 방지
    vals = {}
    for lib, mode, ls, mk in series:
        v, lo, hi = [], [], []
        for L in LEVELS:
            o = D[(mode, lib, "off", "relin", L)]
            h = D[(mode, lib, "hexl", "relin", L)]
            v.append(o[0] / h[0])
            # 배수의 불확실 구간 — 분자·분모 양끝을 반대로 조합한 최악/최선
            lo.append(o[1] / h[2]); hi.append(o[2] / h[1])
        vals[(lib, mode)] = v
        col = LIB_COLOR[lib]
        xs = x + OFFX[(lib, mode)]
        ax.plot(x, v, ls, color=col, marker=mk, markersize=11, linewidth=2.6,
                markeredgecolor="white", markeredgewidth=1.2,
                label=f"{lib} · {mode}", zorder=4)
        ax.errorbar(xs, v, yerr=[np.array(v) - np.array(lo), np.array(hi) - np.array(v)],
                    fmt="none", ecolor=col, elinewidth=1.7, capsize=6, capthick=1.7,
                    alpha=0.75, zorder=3)
    # 값 라벨. 세로 오프셋만으로는 두 종류의 충돌이 났다 —
    #   (a) L1 에서 openfhe 1t(1.81) 라벨과 seal 1t(1.93) 라벨이 겹쳤고,
    #   (b) L12 에서 openfhe mt(1.12) 라벨이 y=1 기준선 위에 얹혔다.
    # → 라이브러리별로 **가로 방향을 갈라** 놓고(openfhe 왼쪽 / seal 오른쪽),
    #   같은 라이브러리 안에서만 위·아래로 나눈다. SEAL 은 1t·mt 간격이 0.04 밖에
    #   안 되므로 세로 간격을 넉넉히 준다.
    for lib in ["openfhe", "seal"]:
        dx, ha = (-13, "right") if lib == "openfhe" else (13, "left")
        for i in range(len(LEVELS)):
            a, b = vals[(lib, "1t")][i], vals[(lib, "mt")][i]
            for val in [a, b]:
                up = (val >= max(a, b))
                dy = (16 if up else -26) if lib == "seal" else (0 if abs(a - b) > 0.2 else (14 if up else -22))
                ax.annotate(f"{val:.2f}", (x[i], val), textcoords="offset points",
                            xytext=(dx, dy), ha=ha, va="center", fontsize=12,
                            color=dark(LIB_COLOR[lib]), fontweight="bold", zorder=6,
                            # 선이 글자를 뚫고 지나가 읽기 나빴다 → 흰 헤일로
                            bbox=dict(boxstyle="round,pad=0.12", fc="white",
                                      ec="none", alpha=0.82))
    ax.axhline(1.0, color="0.15", linewidth=2.4, zorder=2)
    ax.annotate("no speed-up", (0.015, 1.0), xycoords=("axes fraction", "data"),
                textcoords="offset points", xytext=(0, 7), fontsize=11, color="0.25")

    # OpenFHE mt maxLevel — 에러바가 1 을 품는다 = 유의하지 않다.
    # 화살표를 라이브러리 색·직선으로 그렸더니 데이터 계열처럼 보였다 → 회색 곡선으로.
    iL12 = LEVELS.index(12)
    ax.annotate("error bar spans 1.0\n→ not significant",
                (iL12 + 0.045, 1.0), xytext=(iL12 - 0.5, 1.45),
                fontsize=12, color="0.15", fontweight="bold", ha="center",
                bbox=dict(boxstyle="round,pad=0.35", fc="#FFF3E0",
                          ec=LIB_COLOR["openfhe"], lw=1.4),
                arrowprops=dict(arrowstyle="->", color="0.35", linewidth=1.6,
                                connectionstyle="arc3,rad=-0.25"))
    ax.set_xticks(x); ax.set_xticklabels([f"L{L}" for L in LEVELS], fontsize=14)
    ax.set_xlim(-0.35, len(LEVELS) - 0.55)
    ax.set_xlabel("level  (left = low, right = maxLevel)")
    ax.set_ylabel("speed-up  =  HEXL OFF  ÷  HEXL ON")
    ax.set_ylim(0.82, 2.95)
    ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
    ax.legend(loc="upper left", framealpha=0.95)
    ax.set_title("HEXL pays off for SEAL in both modes,\nbut OpenFHE loses most of it once OMP is on", pad=14)
    fig.text(0.5, -0.06,
             f"{CAP_HEXL}\nop = relin. Error bars: 1t = ±1 std; mt = run-to-run min..max "
             f"(OpenFHE 5 runs, SEAL 3 runs), propagated through the ratio.",
             ha="center", fontsize=12, color="0.3")
    save(fig, "hexl_speedup.png")


# ═════════════════════════════ 3) 중첩 이득 달성률
def plot_stacking():
    """OMP 단독 × HEXL 단독 = 예측. 실측이 그에 못 미치는 정도가 이 아암의 핵심 발견."""
    b1 = q("results_v3n15d42L12_timing_1t_dku16c.csv")
    fig, axes = plt.subplots(1, 3, figsize=(19, 7.2), sharey=True)
    W = 0.33
    for ax, op in zip(axes, OPS):
        x = np.arange(len(LEVELS))
        pred, act, att = [], [], []
        for L in LEVELS:
            base1t = b1[(b1.library == "openfhe") & (b1.op == op) & (b1.level == L)].mean_us.iloc[0] / 1000
            omp = base1t / D[("mt", "openfhe", "off", op, L)][0]      # OMP 단독
            hx = base1t / D[("1t", "openfhe", "hexl", op, L)][0]      # HEXL 단독
            a = base1t / D[("mt", "openfhe", "hexl", op, L)][0]       # 둘 다
            pred.append(omp * hx); act.append(a); att.append(a / (omp * hx))
        ax.bar(x - W / 2, pred, W, color=light(LIB_COLOR["openfhe"], 0.55),
               edgecolor=LIB_COLOR["openfhe"], linewidth=1.6, hatch="///",
               label="predicted  (OMP alone × HEXL alone)", zorder=3)
        ax.bar(x + W / 2, act, W, color=LIB_COLOR["openfhe"], edgecolor=LIB_COLOR["openfhe"],
               linewidth=1.6, label="measured  (OMP + HEXL together)", zorder=3)
        for xi, (p, a, t) in enumerate(zip(pred, act, att)):
            ax.annotate(f"{p:.2f}", (xi - W / 2, p), textcoords="offset points", xytext=(0, 5),
                        ha="center", fontsize=11.5, color="0.3")
            ax.annotate(f"{a:.2f}", (xi + W / 2, a), textcoords="offset points", xytext=(0, 5),
                        ha="center", fontsize=11.5, fontweight="bold", color=LIB_COLOR["openfhe"])
            # 달성률 — 축 아래에 둔다. 막대 안에 넣었더니 해칭과 겹쳐 안 읽혔다.
            ax.annotate(f"{t:.0%}", (xi, 0), xycoords=("data", "axes fraction"),
                        textcoords="offset points", xytext=(0, -44),
                        ha="center", va="top", fontsize=17, fontweight="bold", color="0.15")
        ax.set_xticks(x); ax.set_xticklabels([f"L{L}" for L in LEVELS], fontsize=14)
        ax.annotate("attained:", (0, 0), xycoords="axes fraction",
                    textcoords="offset points", xytext=(-8, -44),
                    ha="right", va="top", fontsize=11.5, color="0.4")
        ax.set_title(op, fontsize=16)
        ax.grid(True, axis="y", color="0.9", linewidth=0.6); ax.set_axisbelow(True)
        ax.set_ylim(0, 4.45)
    axes[0].set_ylabel("speed-up vs OpenFHE 1t / HEXL OFF")
    # x 축 라벨을 축에 걸면 달성률 행과 같은 높이에서 겹친다 → 캡션으로 내린다.
    axes[0].legend(loc="upper left", fontsize=12, framealpha=0.95)
    fig.suptitle("OMP and HEXL do not multiply — they compete for the same memory bandwidth", y=1.0)
    fig.text(0.5, -0.045,
             f"{CAP_HEXL}\nLevels run low (L1) on the left to maxLevel (L12) on the right. "
             f"OpenFHE only (Lattigo cannot be accelerated; SEAL has no internal "
             f"parallelism, so it has no OMP factor to stack). Attainment recovers at low levels, "
             f"where fewer RNS towers leave bandwidth to spare.",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    save(fig, "hexl_stacking.png")


# ═════════════════════════════ 4) 순위 역전
def plot_ranking():
    """각 (mode, level) 칸에서 세 라이브러리를 점으로. OFF→HEXL 이동을 화살표로 잇는다."""
    fig, axes = plt.subplots(2, 3, figsize=(18.5, 10.4))
    for ri, mode in enumerate(["1t", "mt"]):
        for ci, L in enumerate(LEVELS):
            ax = axes[ri][ci]
            ypos = {op: len(OPS) - 1 - i for i, op in enumerate(OPS)}
            xmax = 0
            for op in OPS:
                y = ypos[op]
                arm, base = {}, {}
                for lib in ["lattigo", "openfhe", "seal"]:
                    off = D[(mode, lib, "off", op, L)]
                    base[lib] = off[0]
                    hx = D[(mode, lib, "hexl", op, L)] if lib != "lattigo" else off
                    arm[lib] = hx[0]
                    col = LIB_COLOR[lib]
                    if lib != "lattigo":
                        ax.annotate("", xy=(hx[0], y), xytext=(off[0], y),
                                    arrowprops=dict(arrowstyle="->", color=col,
                                                    linewidth=1.5, alpha=0.55))
                        ax.plot([off[0]], [y], "o", mfc="white", mec=col, mew=1.8,
                                markersize=9, zorder=3)      # OFF = 빈 마커
                    ax.errorbar([hx[0]], [y], xerr=[[hx[0] - hx[1]], [hx[2] - hx[0]]],
                                fmt="o", color=col, markersize=11, capsize=4,
                                elinewidth=1.6, capthick=1.6, zorder=4)
                    xmax = max(xmax, hx[2], off[2])
                w_base = min(base, key=base.get)
                w_arm = min(arm, key=arm.get)
                # 아암 1위에 링
                ax.plot([arm[w_arm]], [y], "o", mfc="none", mec="0.1", mew=2.2,
                        markersize=21, zorder=5)
                if w_base != w_arm:
                    ax.annotate("flips", (arm[w_arm], y), textcoords="offset points",
                                xytext=(0, 15), ha="center", fontsize=10.5,
                                fontweight="bold", color="0.1")
            ax.set_yticks(list(ypos.values()))
            ax.set_yticklabels(list(ypos.keys()), fontsize=12)
            # 아래 여백은 mt·L12 의 주석 상자 자리만 남긴다(나머지는 비어 보였다).
            ax.set_ylim(-0.75 if (mode == "mt" and L == 12) else -0.42, len(OPS) - 0.4)
            ax.set_xlim(0, xmax * 1.14)
            ax.grid(True, axis="x", color="0.92", linewidth=0.6); ax.set_axisbelow(True)
            ax.set_title(f"{mode} · L{L}", fontsize=15)
            if ri == 1:
                ax.set_xlabel("mean latency (ms)")
    # maxLevel mt 의 OpenFHE 우위는 SEAL 과 구간이 겹친다 → 그림 안에 직접 적는다
    axes[1][LEVELS.index(12)].annotate(
        "OpenFHE leads on the median, but its\nrun-to-run range overlaps SEAL — not significant",
        (0.5, 0.045), xycoords="axes fraction", ha="center", fontsize=11,
        color="0.1", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", fc="#FFF3E0", ec=LIB_COLOR["openfhe"], lw=1.4))
    handles = [Line2D([], [], marker="o", ls="", mfc="white", mec="0.35", mew=1.8,
                      markersize=9, label="HEXL OFF (hollow)"),
               Line2D([], [], marker="o", ls="", color="0.35", markersize=11,
                      label="HEXL ON (filled)"),
               Line2D([], [], marker="o", ls="", mfc="none", mec="0.1", mew=2.2,
                      markersize=18, label="fastest in this arm"),
               Line2D([], [], marker="o", ls="", color=LIB_COLOR["lattigo"], markersize=11,
                      label="Lattigo — one marker only (not accelerable)")]
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.045),
               fontsize=12.5, framealpha=0.95)
    fig.suptitle("Where the ranking flips once HEXL is on", y=1.085)
    fig.text(0.5, -0.035,
             f"{CAP_HEXL}\nArrows run from HEXL OFF to HEXL ON; Lattigo has a single marker "
             f"because it cannot move. Error bars: 1t = ±1 std, mt = run-to-run min..max "
             f"(OpenFHE 5 runs, SEAL 3 runs; Lattigo mt is a single run, ±1 std).",
             ha="center", fontsize=12, color="0.3")
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    save(fig, "hexl_ranking.png")


if __name__ == "__main__":
    plot_summary("1t")
    plot_summary("mt")
    plot_speedup()
    plot_stacking()
    plot_ranking()
    print(f"\n총 {len([f for f in os.listdir(OUT) if f.endswith('.png')])}장 → {os.path.relpath(OUT, ROOT)}")
