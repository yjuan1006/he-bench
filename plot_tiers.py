#!/usr/bin/env python3
# plot_tiers.py — 방식1: 비용 층(tier)별 그래프. op를 heavy/mid/light 3층으로 나눠
# 층×프리셋마다 별도 이미지로 저장 → 층 안 값 스케일이 비슷해 배수 눌림 방지.
# 입력은 원측정 CSV만. 결과는 plots/ 에 저장. 단위 전부 ms.
# 색=라이브러리(파랑=Lattigo, 주황=OpenFHE), 마커=op, 선스타일=라이브러리(실선/점선), 에러바 유지.
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
import pandas as pd

for _p in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",):
    try: fm.fontManager.addfont(_p)
    except Exception: pass
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.titlesize": 24, "axes.labelsize": 20,
    "xtick.labelsize": 18, "ytick.labelsize": 18, "legend.fontsize": 18,
    "axes.edgecolor": "0.3", "axes.linewidth": 1.2, "lines.linewidth": 3, "font.size": 16,
})
LAT, OF = "#0072B2", "#D55E00"          # 파랑=Lattigo, 주황=OpenFHE
MS = 1000.0
GRID = dict(color="0.85", linewidth=0.8)

LATFILE = {"small": "results_lattigo.csv", "medium": "results_lattigo_medium.csv",
           "large": "results_lattigo_large.csv"}
OFFILE = {"small": "results_openfhe_small_1t.csv", "medium": "results_openfhe_medium_1t.csv",
          "large": "results_openfhe_large_1t.csv"}
PRESETS = [("small", 13), ("medium", 14), ("large", 15)]

# 3층 정의 + 층별 y스케일/소수자리. heavy는 레벨 스윕 범위가 넓어 로그 허용.
TIERS = {
    "heavy": dict(ops=["mul_cc_rlk", "relin", "rot1"], scale="log", dec=1),
    "mid":   dict(ops=["mul_cc", "rescale", "mul_cp"], scale="linear", dec=2),
    "light": dict(ops=["add_cc", "add_cp"],            scale="linear", dec=3),
}
OP_MARKER = {"mul_cc_rlk": "P", "relin": "o", "rot1": "s",
             "mul_cc": "s", "rescale": "D", "mul_cp": "^",
             "add_cc": "o", "add_cp": "D"}

def load(preset):
    lat = pd.read_csv(LATFILE[preset]); lat = lat[lat.preset == preset]
    of = pd.read_csv(OFFILE[preset]);  of = of[of.preset == preset]
    return lat, of

def make(preset, logN, tier, cfg):
    ops = cfg["ops"]
    lat, of = load(preset)
    fig, ax = plt.subplots(figsize=(11, 7))
    lo, hi = float("inf"), 0.0
    for op in ops:
        for df, color, ls, lib in ((lat, LAT, "-", "Lattigo"), (of, OF, "--", "OpenFHE")):
            d = df[df.op == op].sort_values("level")
            if d.empty:
                continue
            x = d["level"].values
            y = d["mean_us"].values / MS
            e = d["std_us"].values / MS
            cont = ax.errorbar(x, y, yerr=e, color=color, linestyle=ls,
                               marker=OP_MARKER[op], markersize=11, linewidth=3,
                               markeredgecolor="white", markeredgewidth=1.2,
                               capsize=3, elinewidth=1.0, ecolor=color)
            for bar in cont[2]:
                bar.set_alpha(0.35)
            lo = min(lo, (y - e).min()); hi = max(hi, (y + e).max())

    # y축 스케일/범위: 층 데이터에 타이트하게.
    if cfg["scale"] == "log":
        ax.set_yscale("log")
        ax.set_ylim(lo * 0.82, hi * 1.22)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.{cfg['dec']}f}"))
        ax.yaxis.set_minor_formatter(mticker.NullFormatter())
    else:
        span = hi - lo
        ax.set_ylim(max(0.0, lo - 0.10 * span), hi + 0.12 * span)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.{cfg['dec']}f}"))

    maxL = int(lat["level"].max())  # small=5, medium=10, large=15 (logN 아님)
    ax.set_xlim(0.5, maxL + 0.5)
    ax.set_xlabel("level (remaining budget)")
    ax.set_ylabel("Latency (ms)")
    tiername = {"heavy": "무거운 층", "mid": "중간 층", "light": "가벼운 층"}[tier]
    ax.set_title(f"{preset} (logN={logN}) · {tiername}\n{', '.join(ops)}", fontsize=24)
    ax.grid(True, which="both", **GRID); ax.set_axisbelow(True)

    # 이중 범례: 라이브러리(색+선) / op(마커).
    lib_h = [Line2D([0], [0], color=LAT, lw=3, ls="-", marker="o", ms=9, label="Lattigo"),
             Line2D([0], [0], color=OF, lw=3, ls="--", marker="s", ms=9, label="OpenFHE (1t)")]
    op_h = [Line2D([0], [0], color="0.35", lw=0, marker=OP_MARKER[o], ms=12, label=o) for o in ops]
    leg1 = ax.legend(handles=lib_h, loc="upper left", framealpha=0.95)
    ax.add_artist(leg1)
    ax.legend(handles=op_h, loc="lower right", framealpha=0.95, title="marker = op")

    fig.tight_layout()
    out = f"plots/plot_{preset}_{tier}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out

if __name__ == "__main__":
    os.makedirs("plots", exist_ok=True)
    n = 0
    for preset, logN in PRESETS:
        for tier, cfg in TIERS.items():
            print("[plot]", make(preset, logN, tier, cfg)); n += 1
    print(f"[done] {n} tier plots → plots/")
