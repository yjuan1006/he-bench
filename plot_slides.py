#!/usr/bin/env python3
# plot_slides.py — 발표 슬라이드용 그래프 3종 (A 배수 / B 절대비용 / C 레벨추세).
# 로그축 하나에 다 담아 배수가 눌려 보이는 문제를 해결: 각 그래프가 "한 가지"만 보여줌.
# 색: 파랑=Lattigo(#0072B2), 주황=OpenFHE(#D55E00) — Okabe-Ito 색약 안전 쌍(명도 차 포함).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.ticker as mticker
import pandas as pd

# --- 한글 폰트 등록 (NanumGothic). 없으면 경고만. ---
for _p in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
           "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"):
    try:
        fm.fontManager.addfont(_p)
    except Exception:
        pass
# NanumGothic 우선, 없는 글리프(로그축 지수의 U+2212 마이너스 등)는 DejaVu Sans로 폴백.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["NanumGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False  # 음수 기호 깨짐 방지

# --- 발표 스타일: 멀리서도 보이게 큰 폰트/굵은 선 ---
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.titlesize": 22, "axes.labelsize": 18,
    "xtick.labelsize": 16, "ytick.labelsize": 16, "legend.fontsize": 16,
    "axes.edgecolor": "0.3", "axes.linewidth": 1.2,
    "lines.linewidth": 2.5, "font.size": 15,
})
LAT = "#0072B2"   # 파랑 = Lattigo
OF  = "#D55E00"   # 주황 = OpenFHE
VALFS = 14        # 값 표기 폰트
GRID = dict(color="0.85", linewidth=0.8)

PRESETS = [("small", 5, 13), ("medium", 10, 14), ("large", 15, 15)]
LATFILE = {"small": "results_lattigo.csv",
           "medium": "results_lattigo_medium.csv",
           "large": "results_lattigo_large.csv"}

def lvl(path, preset, L):
    d = pd.read_csv(path)
    return d[(d.preset == preset) & (d.level == L)].set_index("op")["mean_us"]

MS = 1000.0  # μs → ms

def fmt_ms(v):  # v는 ms. 1ms 이상 소수1자리, 미만은 소수3자리.
    return f"{v:.1f}" if v >= 1 else f"{v:.3f}"

# ================= 그래프 A — 배수 비교(선형축) =================
def graph_A():
    fair = ["add_cc", "mul_cc", "rescale"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6), sharey=True)
    for ax, (p, L, logN) in zip(axes, PRESETS):
        lat = lvl(LATFILE[p], p, L)
        of1 = lvl("results_openfhe.csv", p, L)
        ofm = lvl("results_openfhe_mt.csv", p, L)
        r1 = [of1[o] / lat[o] for o in fair]
        rm = [ofm[o] / lat[o] for o in fair]
        x = range(len(fair)); w = 0.38
        b1 = ax.bar([i - w/2 for i in x], r1, w, color=LAT, edgecolor="black",
                    linewidth=1.2, label="OpenFHE 1t (싱글코어)")
        bm = ax.bar([i + w/2 for i in x], rm, w, color=OF, edgecolor="black",
                    linewidth=1.2, hatch="//", label="OpenFHE mt (4 vCPU)")
        for bars, vals in ((b1, r1), (bm, rm)):
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width()/2, v + 0.08, f"{v:.2f}×",
                        ha="center", va="bottom", fontsize=VALFS, fontweight="bold")
        ax.axhline(1.0, ls="--", lw=2, color="0.35")
        if p == "small":  # 동률선 라벨은 첫 패널 왼쪽 여백에 한 번만 (막대와 겹치지 않게)
            ax.text(-0.48, 1.08, "동률(=1)", fontsize=13, color="0.35", ha="left", va="bottom")
        ax.set_title(f"{p} (logN={logN})")
        ax.set_xticks(list(x)); ax.set_xticklabels(fair, fontsize=15)
        ax.set_ylim(0, 6.2)
        ax.grid(True, axis="y", **GRID); ax.set_axisbelow(True)
    axes[0].set_ylabel("OpenFHE / Lattigo  배수")
    axes[0].legend(loc="upper right", framealpha=0.95)
    fig.suptitle("공정 비교 op의 OpenFHE/Lattigo 배수 — 1t vs mt  (배수 클수록 Lattigo 우위)",
                 fontsize=22, y=1.00)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig("plot_A_ratio.png", dpi=170)
    plt.close(fig)
    print("[plot] plot_A_ratio.png")

# ================= 그래프 B — 절대 비용 서열(가로 로그) =================
def graph_B():
    order = ["add_cc", "mul_cc", "rescale", "mul_cc_rlk", "relin", "rot1"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 7), sharey=True)
    for ax, (p, L, logN) in zip(axes, PRESETS):
        lat = lvl(LATFILE[p], p, L)
        of1 = lvl("results_openfhe.csv", p, L)
        y = range(len(order)); h = 0.38
        latv = [lat[o] / MS for o in order]; ofv = [of1[o] / MS for o in order]
        bl = ax.barh([i + h/2 for i in y], latv, h, color=LAT, edgecolor="black",
                     linewidth=1.2, label="Lattigo")
        bo = ax.barh([i - h/2 for i in y], ofv, h, color=OF, edgecolor="black",
                     linewidth=1.2, hatch="//", label="OpenFHE (1t)")
        for bars, vals in ((bl, latv), (bo, ofv)):
            for b, v in zip(bars, vals):
                ax.text(v * 1.15, b.get_y() + b.get_height()/2, fmt_ms(v),
                        va="center", ha="left", fontsize=VALFS)
        ax.set_xscale("log")
        # 로그축 지수 표기(10^-1)의 mathtext 마이너스 글리프 문제를 피해 일반 십진(0.1,1,10)으로.
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
        ax.xaxis.set_minor_formatter(mticker.NullFormatter())
        ax.set_yticks(list(y)); ax.set_yticklabels(order, fontsize=15)
        ax.invert_yaxis()  # add_cc 를 맨 위로
        ax.set_xlim(right=max(ofv + latv) * 4)
        ax.set_title(f"{p} (logN={logN}, level={L})")
        ax.set_xlabel("Time (ms, log)")
        ax.grid(True, axis="x", which="both", **GRID); ax.set_axisbelow(True)
    # 범례는 첫 패널 우상단(짧은 add_cc/mul_cc 막대 옆 빈 공간) — 긴 rot1 값과 겹치지 않게.
    axes[0].legend(loc="upper right", framealpha=0.95)
    fig.suptitle("대표 레벨(maxLevel)의 op별 절대 비용 — Lattigo vs OpenFHE(1t)", fontsize=22, y=1.00)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig("plot_B_absolute.png", dpi=170)
    plt.close(fig)
    print("[plot] plot_B_absolute.png")

# ================= 그래프 C — 레벨 추세(패널 분리, large) =================
def graph_C():
    p, L, logN = "large", 15, 15
    lat_all = pd.read_csv(LATFILE[p]); of_all = pd.read_csv("results_openfhe.csv")
    def series(df, op):
        d = df[(df.preset == p) & (df.op == op)].sort_values("level")
        return d["level"].values, d["mean_us"].values / MS  # ms 단위
    heavy = [("relin", "o"), ("rot1", "s"), ("mul_cc_rlk", "^")]
    light = [("add_cc", "o"), ("mul_cc", "s"), ("rescale", "^")]
    fig, (axh, axl) = plt.subplots(1, 2, figsize=(15, 6.5))
    from matplotlib.lines import Line2D
    for ax, group, title, labels in ((axh, heavy, "무거운 op (key-switch)", False),
                                     (axl, light, "가벼운 op (산술)", True)):
        ymax = 0
        for op, mk in group:
            for df, col, lib in ((lat_all, LAT, "Lattigo"), (of_all, OF, "OpenFHE")):
                xs, ys = series(df, op)
                ax.plot(xs, ys, marker=mk, color=col, markersize=9,
                        markeredgecolor="white", markeredgewidth=1.0)
                ymax = max(ymax, ys.max())
                if labels:  # 가벼운 op는 최대 레벨 끝점에 값(ms)을 크게 표기 → 숫자로 읽히게
                    dy = 7 if col == OF else -7  # 같은 op의 두 선 라벨을 위/아래로 분리
                    ax.annotate(fmt_ms(ys[-1]), (xs[-1], ys[-1]),
                                textcoords="offset points", xytext=(8, dy),
                                fontsize=VALFS, color=col, va="center", fontweight="bold")
        ax.set_title(title)
        ax.set_xlabel("level (remaining budget)")
        ax.set_ylabel("Time (ms)")
        ax.grid(True, **GRID); ax.set_axisbelow(True)
        ax.set_xlim(1, L + (2.0 if labels else 0.5))  # 라벨 공간 확보
        ax.set_ylim(0, ymax * 1.10)  # 데이터에 맞게 확대
        lib_h = [Line2D([0], [0], color=LAT, lw=3, label="Lattigo"),
                 Line2D([0], [0], color=OF, lw=3, label="OpenFHE (1t)")]
        leg1 = ax.legend(handles=lib_h, loc="upper left", framealpha=0.95)
        ax.add_artist(leg1)
        mk_h = [Line2D([0], [0], color="0.3", marker=m, lw=0, markersize=10, label=o)
                for o, m in group]
        ax.legend(handles=mk_h, loc="lower right", framealpha=0.95, title="marker = op")
    fig.suptitle(f"CKKS op latency vs level — {p} (logN={logN})  [선형 y축, 패널 분리]",
                 fontsize=22, y=1.00)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig("plot_C_level_trend.png", dpi=170)
    plt.close(fig)
    print("[plot] plot_C_level_trend.png")

if __name__ == "__main__":
    graph_A(); graph_B(); graph_C()
    print("[done] 3 slides written.")
