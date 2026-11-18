#!/usr/bin/env python3
"""부트스트래핑 1~3단계 플롯. **8-op 스타일 규약을 그대로 잇는다**
(`scripts/v3_plots.py` · `v3_hexl8_plots.py`): Okabe-Ito, 실선, 마커, y 선형,
에러바 alpha 0.4(선·마커는 불투명), 한글 폰트 없음 → 영문 라벨.

기존 8-op 플롯 스크립트는 건드리지 않는다 — 새 파일이다.

그림
  ① boot_delta_precision.png   Δ ↔ 정밀도. **두 라이브러리가 다른 축에 반응한다**
                               (좌: 가로 Δ / 우: 가로 q0−Δ) — 2단계
  ② boot_lb_time.png           분해깊이 ↔ 부트 시간, 1t | mt 나란히. 순서 역전 — 3단계
  ③ boot_preset_compare.png    BT1 vs BT2 확정 비교 (정밀도 · 부트 · mt/1t)
  ④ boot_dnum_tradeoff.png     dnum ↔ 부트 시간 + 보안 여유 교환비
  ⑤ boot_lb_precision.png      분해깊이 ↔ 정밀도, 세 계열(2단계 (53,52) / BT1 / BT2)
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams.update({
    "axes.titlesize": 17, "axes.labelsize": 15,
    "xtick.labelsize": 13, "ytick.labelsize": 13,
    "legend.fontsize": 13, "figure.titlesize": 20,
})

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "plots", "boot")
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00"}      # 8-op 과 같은 배정
LIB_ORDER = ["openfhe", "lattigo"]
MARK = {"openfhe": "o", "lattigo": "s"}
LBS = [(2, 2), (3, 3), (3, 4), (4, 3), (4, 4)]
LB_LABEL = [f"{{{a},{b}}}" for a, b in LBS]
ROTKEY = {(1, 1): 383, (2, 2): 61, (3, 3): 39, (3, 4): 48, (4, 3): 48, (4, 4): 33}


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[plot] {os.path.relpath(p, ROOT)}")


def load_main(lib, mode):
    d = pd.read_csv(respath.find(f"boot_main_{lib}_{mode}_dku16c.csv"))
    d["sub"] = d.scaling.astype(str).str.split("|").str[-1]
    return d[d.rep >= 0]


def agg(d, keys):
    return d.groupby(keys).agg(
        prec=("precision_bits", "mean"), pstd=("precision_bits", "std"),
        boot=("boot_us", lambda x: x.mean() / 1e6),
        bsd=("boot_us", lambda x: x.std() / 1e6)).reset_index()


# ---------------------------------------------------------------------------
def fig_delta_precision():
    """① 두 라이브러리가 **다른 축에 반응한다**.

    ⚠️ Δ 별로 평균 내면 q0−Δ 가 섞여 "평평하다" 가 보이지 않는다.
       왼쪽은 **q0−Δ = 1 로 고정**하고 Δ 를 훑고, 오른쪽은 **Δ 를 고정**한 계열들을 겹친다.
    """
    o = pd.read_csv(respath.find("boot_prec_openfhe_1t_dku16c.csv"))
    l = pd.read_csv(respath.find("boot_prec_lattigo_1t_dku16c.csv"))

    def curve(d):
        g = d[(d.rep >= 0) & (d.ok == 1) &
              (d.levelBudget_c2s == 3) & (d.levelBudget_s2c == 3)].copy()
        g["gap"] = g.q0 - g.delta
        return g

    O, L = curve(o), curve(l)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))

    # 왼쪽: q0−Δ = 1 고정, x = Δ
    ax = axes[0]
    for lib, d in (("openfhe", O), ("lattigo", L)):
        k = d[d.gap == 1].groupby("delta").precision_bits.agg(["mean", "std"]).reset_index()
        ax.errorbar(k.delta, k["mean"], yerr=k["std"].fillna(0), ecolor=LIB_COLOR[lib],
                    elinewidth=0.8, capsize=2, capthick=0.8, alpha=0.4, fmt="none", zorder=1)
        ax.plot(k.delta, k["mean"], color=LIB_COLOR[lib], marker=MARK[lib], markersize=7,
                linewidth=2.4, markeredgewidth=0, label=lib, zorder=2)
    ax.set_xlabel("Δ  (scaling modulus, bits)     [ q₀ − Δ held at 1 ]")
    ax.set_ylabel("bootstrap output precision (bits)")
    ax.set_title("Hold q₀−Δ: only OpenFHE moves", pad=10)
    ax.set_ylim(0, 21); ax.set_xlim(50.5, 60.5)
    ax.legend(frameon=False, loc="lower right")
    ax.annotate("Lattigo: 15.967 at every Δ", xy=(55, 16.4), ha="center",
                fontsize=11.5, color=LIB_COLOR["lattigo"])
    ax.annotate("OpenFHE: 5.5 → 11.2", xy=(55, 7.4), ha="center",
                fontsize=11.5, color=LIB_COLOR["openfhe"])

    # 오른쪽: Δ 고정 계열을 겹친다 (한 선 = 한 Δ)
    ax = axes[1]
    for lib, d in (("openfhe", O), ("lattigo", L)):
        for dl in sorted(d.delta.unique()):
            k = d[d.delta == dl].groupby("gap").precision_bits.mean().reset_index()
            if len(k) < 2:
                ax.plot(k.gap, k.precision_bits, color=LIB_COLOR[lib], marker=MARK[lib],
                        markersize=6, markeredgewidth=0, alpha=0.75, linestyle="none")
                continue
            ax.plot(k.gap, k.precision_bits, color=LIB_COLOR[lib], marker=MARK[lib],
                    markersize=6, linewidth=2.0, markeredgewidth=0, alpha=0.75)
    ax.set_xlabel("q₀ − Δ   ( = Lattigo LogMessageRatio )     [ one line = one Δ ]")
    ax.set_title("Hold Δ: only Lattigo moves", pad=10)
    ax.set_ylim(0, 21); ax.set_xticks([1, 2, 5, 7])
    ax.annotate("Lattigo: 14.6 → 17.9, peak at 2", xy=(4, 19.2), ha="center",
                fontsize=11.5, color=LIB_COLOR["lattigo"])
    ax.annotate("OpenFHE: flat (≤ 0.104 within each Δ)", xy=(4, 4.0), ha="center",
                fontsize=11.5, color=LIB_COLOR["openfhe"])
    for ax in axes:
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)

    fig.suptitle("Bootstrap precision — the two libraries respond to different axes", y=1.02)
    fig.text(0.5, -0.07,
             "logN 16, full slots, dense uniform ternary, {3,3}, 1t.  Δ ≤ 50 is absent "
             "because OpenFHE's bootstrap breaks there (output magnitude 4–6× off).",
             ha="center", fontsize=11.5, color="0.3")
    fig.tight_layout()
    save(fig, "boot_delta_precision.png")


def fig_lb_time():
    """② 분해깊이 ↔ 부트 시간. 1t 최속 {3,3} ↔ mt 최속 {4,3} 역전."""
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), sharey=False)
    for ax, mode in zip(axes, ("1t", "mt")):
        for lib in LIB_ORDER:
            d = load_main(lib, mode)
            if mode == "mt":
                d = d[d["sub"] == "timing"]
            for dl, pn, ls in ((59, "BT1", "-"), (58, "BT2", "--")):
                k = agg(d[d.delta == dl], ["levelBudget_c2s", "levelBudget_s2c"])
                k["ord"] = k.apply(lambda r: LBS.index((int(r.levelBudget_c2s),
                                                        int(r.levelBudget_s2c))), axis=1)
                k = k.sort_values("ord")
                ax.errorbar(k["ord"], k.boot, yerr=k.bsd, ecolor=LIB_COLOR[lib],
                            elinewidth=0.8, capsize=2, capthick=0.8, alpha=0.4,
                            fmt="none", zorder=1)
                ax.plot(k["ord"], k.boot, color=LIB_COLOR[lib], marker=MARK[lib],
                        linestyle=ls, markersize=7, linewidth=2.4, markeredgewidth=0,
                        label=f"{lib} {pn}", zorder=2)
        ax.set_xticks(range(len(LBS)))
        ax.set_xticklabels([f"{lab}\n{ROTKEY[lb]} keys" for lab, lb in zip(LB_LABEL, LBS)])
        ax.set_xlabel("(C2S, S2C) factorization depth   /   Lattigo rotation keys")
        ax.set_title(f"{mode}", pad=10)
        # 최속 지점을 명시한다 — 두 패널의 최속이 다르다는 것이 이 그림의 요지다.
        d0 = load_main("openfhe", mode)
        if mode == "mt":
            d0 = d0[d0["sub"] == "timing"]
        k0 = agg(d0[d0.delta == 59], ["levelBudget_c2s", "levelBudget_s2c"])
        k0["ord"] = k0.apply(lambda r: LBS.index((int(r.levelBudget_c2s),
                                                  int(r.levelBudget_s2c))), axis=1)
        j = k0.boot.idxmin()
        ax.annotate(f"fastest: {LB_LABEL[int(k0.loc[j, 'ord'])]}",
                    xy=(k0.loc[j, "ord"], k0.loc[j, "boot"]), xytext=(0, -34),
                    textcoords="offset points", ha="center", fontsize=12,
                    color=LIB_COLOR["openfhe"],
                    arrowprops=dict(arrowstyle="->", color=LIB_COLOR["openfhe"], lw=1.4))
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    axes[0].set_ylabel("bootstrap latency (s)")
    axes[0].legend(frameon=False, ncol=2, fontsize=11.5)
    fig.suptitle("Factorization depth vs bootstrap latency — the ordering flips 1t ↔ mt",
                 y=1.02)
    fig.text(0.5, -0.06,
             "1t fastest = {3,3} (37.1 s); mt fastest = {4,3} (13.7 s). Deeper "
             "factorization gains more from threading (mt/1t 0.35 vs 0.44–0.48 for {2,2}). "
             "Rotation-key count alone does not explain it — {4,4} has the fewest keys (33) "
             "yet is 4th in 1t, because its chain is 2 levels longer.",
             ha="center", fontsize=11.5, color="0.3")
    fig.tight_layout()
    save(fig, "boot_lb_time.png")


def fig_preset_compare():
    """③ BT1 vs BT2 — Δ 한 칸에 유불리가 뒤집힌다."""
    rows = []
    for lib in LIB_ORDER:
        d1 = load_main(lib, "1t"); dm = load_main(lib, "mt")
        for dl, pn in ((59, "BT1\nΔ=59"), (58, "BT2\nΔ=58")):
            s = lambda d: d[(d.delta == dl) & (d.levelBudget_c2s == 3) &
                            (d.levelBudget_s2c == 3)]
            a, b = s(d1), s(dm[dm["sub"] == "timing"])
            rows.append(dict(lib=lib, preset=pn, prec=a.precision_bits.mean(),
                             pstd=a.precision_bits.std(),
                             b1=a.boot_us.mean() / 1e6, b1sd=a.boot_us.std() / 1e6,
                             bm=b.boot_us.mean() / 1e6, bmsd=b.boot_us.std() / 1e6))
    r = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.0))
    x = [0, 1]; w = 0.36
    for j, (col, sd, ttl, ylab) in enumerate((
            ("prec", "pstd", "Precision (1t)", "bits"),
            ("b1", "b1sd", "Bootstrap latency — 1t", "seconds"),
            ("bm", "bmsd", "Bootstrap latency — mt", "seconds"))):
        ax = axes[j]
        for i, lib in enumerate(LIB_ORDER):
            g = r[r.lib == lib]
            ax.bar([v + (i - 0.5) * w for v in x], g[col], w,
                   yerr=g[sd].fillna(0), error_kw={"elinewidth": 1.0, "alpha": 0.4},
                   color=LIB_COLOR[lib], edgecolor="white", linewidth=0.8, label=lib)
            for xi, v in zip(x, g[col]):
                ax.annotate(f"{v:.2f}", xy=(xi + (i - 0.5) * w, v), xytext=(0, 3),
                            textcoords="offset points", ha="center", fontsize=11)
        ax.set_xticks(x); ax.set_xticklabels(list(r.preset.unique()))
        ax.set_title(ttl, pad=10); ax.set_ylabel(ylab)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
        ax.grid(True, axis="y", color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    axes[0].legend(frameon=False, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.30))
    fig.suptitle("BT1 vs BT2 — one step of Δ flips which library gains", y=1.03)
    fig.text(0.5, -0.05,
             "Both are q₀=60, residual L=4, {3,3}; only Δ differs (59 vs 58). "
             "OpenFHE loses 2.4 bits going 59→58 while Lattigo gains 1.9 — "
             "because q₀−Δ moves 1→2, Lattigo's optimum. Latency is unchanged.",
             ha="center", fontsize=11.5, color="0.3")
    fig.tight_layout()
    save(fig, "boot_preset_compare.png")


def fig_dnum():
    """④ dnum ↔ 부트 시간 + 보안 여유. 규칙 7 이 선형이 아님을 보인다."""
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    for lib in LIB_ORDER:
        d = pd.read_csv(respath.find(f"boot_dnum_{lib}_1t_dku16c.csv"))
        d = d[d.rep >= 0]
        k = d.groupby("dnum").agg(boot=("boot_us", lambda x: x.mean() / 1e6),
                                  bsd=("boot_us", lambda x: x.std() / 1e6),
                                  qp=("logQP_boot", "first")).reset_index()
        k["margin"] = 1747 - k.qp
        k["rel"] = k.boot / k.boot.iloc[0]
        axes[0].errorbar(k.dnum, k.boot, yerr=k.bsd, ecolor=LIB_COLOR[lib],
                         elinewidth=0.8, capsize=2, capthick=0.8, alpha=0.4,
                         fmt="none", zorder=1)
        axes[0].plot(k.dnum, k.boot, color=LIB_COLOR[lib], marker=MARK[lib],
                     markersize=7, linewidth=2.4, markeredgewidth=0, label=lib, zorder=2)
        axes[1].plot(k["margin"], k.boot, color=LIB_COLOR[lib], marker=MARK[lib],
                     markersize=7, linewidth=2.4, markeredgewidth=0, label=lib)
        for i, (_, r) in enumerate(k.iterrows()):
            axes[1].annotate(f"dnum {int(r.dnum)}", xy=(r["margin"], r.boot),
                             xytext=(4, 8 if i % 2 == 0 else -14),
                             textcoords="offset points", fontsize=10,
                             color=LIB_COLOR[lib])
    # 선형 기준선 — 규칙 7 이 선형이면 이 선을 따라야 한다
    base = 36.87
    axes[0].plot([7, 25], [base, base * 25 / 7], color="0.55", linestyle=":",
                 linewidth=1.8, label="linear in dnum (HK20)")
    axes[0].set_xlabel("dnum  (number of key-switch digits)")
    axes[0].set_ylabel("bootstrap latency (s)")
    axes[0].set_title("Cost is sub-linear in dnum", pad=10)
    axes[1].set_xlabel("security margin below 1747 (bits)")
    axes[1].set_ylabel("bootstrap latency (s)")
    axes[1].set_title("What margin costs", pad=10)
    for ax in axes:
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
        ax.legend(frameon=False)
    fig.suptitle("dnum sweep — rule 7 holds in direction, not in slope", y=1.02)
    fig.text(0.5, -0.06,
             "BT2, {3,3}, 1t. OpenFHE dnum 7→25 (3.6×) costs 1.93× latency; Lattigo "
             "3→19 (6.3×) costs 2.26× — exponent ≈ 0.5. Raising dnum shrinks P "
             "(logP 240→60 / 427→61), so each digit gets cheaper. HK20's linear law "
             "assumes P is fixed.",
             ha="center", fontsize=11.5, color="0.3")
    fig.tight_layout()
    save(fig, "boot_dnum_tradeoff.png")


def fig_lb_precision():
    """⑤ 분해깊이 ↔ 정밀도. 프리셋마다 순서가 다르고 방향까지 뒤집힌다.

    ⚠️ 세 계열의 절대값이 5.5 / 10~11 / 15~18 로 벌어져 한 축에 겹치면 형태가 안 보인다.
       왼쪽은 OpenFHE 절대값, 오른쪽은 **각 계열 평균을 뺀 편차**로 형태만 본다.
    """
    o2 = pd.read_csv(respath.find("boot_prec_openfhe_1t_dku16c.csv"))
    g2 = o2[(o2.rep >= 0) & (o2.q0 == 53) & (o2.delta == 52) & (o2.residual_L == 6)]
    d1 = load_main("openfhe", "1t")
    series = [
        ("Δ=52  (q₀=53, L=6, stage 2)", "0.45", ":",
         g2.groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()),
        ("BT1  Δ=59", LIB_COLOR["openfhe"], "-",
         d1[d1.delta == 59].groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()),
        ("BT2  Δ=58", LIB_COLOR["openfhe"], "--",
         d1[d1.delta == 58].groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4))
    for lab, col, ls, ser in series:
        xs = [i for i, lb in enumerate(LBS) if lb in ser.index]
        ys = [ser.loc[LBS[i]] for i in xs]
        m = sum(ys) / len(ys)
        axes[0].plot(xs, ys, color=col, linestyle=ls, marker="o", markersize=7,
                     linewidth=2.4, markeredgewidth=0, label=lab)
        axes[1].plot(xs, [y - m for y in ys], color=col, linestyle=ls, marker="o",
                     markersize=7, linewidth=2.4, markeredgewidth=0,
                     label=f"{lab}   (mean {m:.2f})")
    # Lattigo 는 세 프리셋 전부에서 완전 무관 — 편차 패널의 0 선으로 충분하다.
    dl = load_main("lattigo", "1t")
    lv = dl[dl.delta == 58].precision_bits.mean()
    axes[0].axhline(lv, color=LIB_COLOR["lattigo"], linewidth=2.4)
    axes[0].annotate(f"Lattigo BT2 — flat at {lv:.2f} (σ ≤ 0.003)", xy=(2, lv),
                     xytext=(0, 7), textcoords="offset points", ha="center",
                     color=LIB_COLOR["lattigo"], fontsize=11.5)
    axes[1].axhline(0, color="0.75", linewidth=1.0, zorder=0)
    for ax, ttl, ylab in ((axes[0], "absolute", "bootstrap output precision (bits)"),
                          (axes[1], "deviation from each series' own mean", "bits")):
        ax.set_xticks(range(len(LBS))); ax.set_xticklabels(LB_LABEL)
        ax.set_xlabel("(C2S, S2C) factorization depth")
        ax.set_ylabel(ylab); ax.set_title(ttl, pad=10)
        ax.grid(True, color="0.92", linewidth=0.6); ax.set_axisbelow(True)
    axes[0].set_ylim(3, 21)
    axes[1].legend(frameon=False, loc="lower left", fontsize=11.5)
    fig.suptitle("Factorization-depth effect depends on Δ — and reverses", y=1.02)
    fig.text(0.5, -0.07,
             "OpenFHE only. Best depth is {3,4} at Δ=52, {3,3} at Δ=59, {4,3} at Δ=58; "
             "spread grows 0.40 → 1.22 → 1.91 bits. Lattigo is unaffected throughout. "
             "We kept {3,3} for both presets so BT1↔BT2 stays a pure Δ contrast.",
             ha="center", fontsize=11.5, color="0.3")
    fig.tight_layout()
    save(fig, "boot_lb_precision.png")


if __name__ == "__main__":
    fig_delta_precision()
    fig_lb_time()
    fig_preset_compare()
    fig_dnum()
    fig_lb_precision()
