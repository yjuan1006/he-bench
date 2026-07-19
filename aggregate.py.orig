#!/usr/bin/env python3
# aggregate.py — Lattigo/OpenFHE CKKS 벤치 CSV 병합 + 요약표 + 그래프.
# 입력: results_lattigo.csv, results_openfhe.csv (동일 스키마)
# 출력: results_combined.csv, plot_<preset>.png (레벨 스케일링), plot_summary.png (라이브러리 비교 막대)
#       + 콘솔 요약표.
# --suffix로 출력 파일명에 접미사를 붙일 수 있다(예: 단일스레드 재측정본을 덮어쓰지 않고 나란히 보관).
import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")  # WSL 헤드리스: 파일로만 저장
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Okabe-Ito 색맹 안전 팔레트 (엔티티=색). 라이브러리 2종 + op 라인 색.
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00"}  # 파랑 / 주황
LIB_ORDER = ["lattigo", "openfhe"]
OP_COLOR = {
    "add_cc": "#000000",
    "mul_cc": "#009E73",
    "mul_cc_rlk": "#E69F00",
    "rescale": "#56B4E9",
    "rot1": "#CC79A7",
}
LINE_OPS = ["add_cc", "mul_cc", "mul_cc_rlk", "rescale", "rot1"]  # 레벨 그래프에 그릴 대표 op
KEY_OPS = ["add_cc", "mul_cc", "mul_cc_rlk", "rot1", "rescale"]   # std 요약 대상 핵심 연산
ALL_OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"]
PRESET_ORDER = ["small", "medium", "large"]


def log_safe_yerr(mean, std):
    # 로그 y축에서 아래쪽 에러바가 0/음수로 내려가 깨지지 않도록 하한 클리핑.
    # 비대칭 yerr [lower, upper] 반환: mean-lower >= mean*0.001 보장.
    mean = np.asarray(mean, dtype=float)
    std = np.asarray(std, dtype=float)
    lower = np.minimum(std, mean * 0.999)
    return np.vstack([lower, std])


SUFFIX = ""  # 출력 파일명 접미사 (main에서 --suffix로 설정)


def load(lattigo_csv, openfhe_csv):
    frames = []
    for path in (lattigo_csv, openfhe_csv):
        if not os.path.exists(path):
            sys.exit(f"missing {path} — run the benchmarks first")
        frames.append(pd.read_csv(path))
    df = pd.concat(frames, ignore_index=True)
    # 정렬용 카테고리
    df["preset"] = pd.Categorical(df["preset"], PRESET_ORDER, ordered=True)
    df["op"] = pd.Categorical(df["op"], ALL_OPS, ordered=True)
    return df


def write_combined(df):
    out = f"results_combined{SUFFIX}.csv"
    df.sort_values(["library", "preset", "level", "op"]).to_csv(out, index=False)
    print(f"[merged] {out}  ({len(df)} rows)")


def console_summary(df):
    # 각 프리셋의 maxLevel에서 라이브러리별 mean_us 비교 + 비율.
    print("\n=== op latency @ maxLevel (mean μs) — Lattigo vs OpenFHE ===")
    for preset in PRESET_ORDER:
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        maxL = sub["maxLevel"].iloc[0]
        top = sub[sub["level"] == maxL]
        piv = top.pivot_table(index="op", columns="library", values="mean_us", observed=True)
        piv = piv.reindex(ALL_OPS)
        for lib in LIB_ORDER:
            if lib not in piv.columns:
                piv[lib] = float("nan")
        piv["OF/Lat"] = piv["openfhe"] / piv["lattigo"]
        print(f"\n-- preset={preset}  logN={sub['logN'].iloc[0]}  level={maxL} --")
        with pd.option_context("display.float_format", lambda v: f"{v:10.1f}"):
            print(piv[["lattigo", "openfhe", "OF/Lat"]].to_string())


def plot_level_scaling(df):
    # 프리셋별: x=level(오름차순), y=mean_us(log), 색=op, 선스타일=library.
    for preset in PRESET_ORDER:
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        fig, ax = plt.subplots(figsize=(8, 5))
        for op in LINE_OPS:
            for lib in LIB_ORDER:
                d = sub[(sub["op"] == op) & (sub["library"] == lib)].sort_values("level")
                if d.empty:
                    continue
                # 각 점에 std_us를 에러바로 표시 (로그축 하한 클리핑).
                container = ax.errorbar(
                    d["level"], d["mean_us"],
                    yerr=log_safe_yerr(d["mean_us"].values, d["std_us"].values),
                    color=OP_COLOR[op],
                    linestyle="-" if lib == "lattigo" else "--",
                    marker="o" if lib == "lattigo" else "s",
                    markersize=4, linewidth=2,
                    capsize=2, elinewidth=0.8, ecolor=OP_COLOR[op],
                )
                # 선/마커는 선명하게, 에러바만 alpha 낮춰 지저분하지 않게.
                for bar in container[2]:  # barlinecols
                    bar.set_alpha(0.4)
                for cap in container[1]:  # caplines
                    cap.set_alpha(0.6)
        ax.set_yscale("log")
        ax.set_xlabel("level (remaining multiplicative budget)")
        ax.set_ylabel("mean latency (μs, log scale)")
        ax.set_title(f"CKKS op latency vs level — preset={preset} "
                     f"(logN={sub['logN'].iloc[0]})")
        ax.grid(True, which="both", axis="both", color="0.9", linewidth=0.6)
        ax.set_axisbelow(True)
        # 범례 2개: op=색, library=선스타일.
        from matplotlib.lines import Line2D
        op_handles = [Line2D([0], [0], color=OP_COLOR[o], lw=2, label=o) for o in LINE_OPS]
        lib_handles = [
            Line2D([0], [0], color="0.3", lw=2, linestyle="-", marker="o", label="lattigo"),
            Line2D([0], [0], color="0.3", lw=2, linestyle="--", marker="s", label="openfhe"),
        ]
        leg1 = ax.legend(handles=op_handles, title="operation", loc="upper left", fontsize=8)
        ax.add_artist(leg1)
        ax.legend(handles=lib_handles, title="library", loc="lower right", fontsize=8)
        fig.tight_layout()
        out = f"plot_{preset}{SUFFIX}.png"
        fig.savefig(out, dpi=130)
        plt.close(fig)
        print(f"[plot] {out}")


def plot_summary_bars(df):
    # 프리셋별 subplot: maxLevel에서 op별 라이브러리 비교 막대 (log y).
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    x = range(len(ALL_OPS))
    width = 0.38
    for ax, preset in zip(axes, PRESET_ORDER):
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        maxL = sub["maxLevel"].iloc[0]
        top = sub[sub["level"] == maxL]
        for i, lib in enumerate(LIB_ORDER):
            vals = [
                top[(top["op"] == op) & (top["library"] == lib)]["mean_us"].mean()
                for op in ALL_OPS
            ]
            errs = [
                top[(top["op"] == op) & (top["library"] == lib)]["std_us"].mean()
                for op in ALL_OPS
            ]
            offset = (i - 0.5) * width
            # yerr=std_us, log축 하한 클리핑. relin은 std=0이라 에러바가 안 그려짐(정상).
            ax.bar([xi + offset for xi in x], vals, width,
                   yerr=log_safe_yerr(vals, errs), capsize=3,
                   error_kw={"elinewidth": 0.8, "alpha": 0.6},
                   color=LIB_COLOR[lib], label=lib)
        ax.set_yscale("log")
        ax.set_title(f"{preset} (logN={sub['logN'].iloc[0]}, level={maxL})")
        ax.set_xticks(list(x))
        ax.set_xticklabels(ALL_OPS, rotation=45, ha="right", fontsize=8)
        ax.grid(True, which="both", axis="y", color="0.9", linewidth=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("mean latency (μs, log scale)")
    axes[0].legend(title="library", loc="upper left", fontsize=9)
    fig.suptitle("CKKS op latency @ maxLevel — Lattigo vs OpenFHE", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = f"plot_summary{SUFFIX}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"[plot] {out}")


def std_summary(df):
    # 변동계수 cv = std/mean (mean=0이면 0). relin은 std=0으로 기록돼 cv=0.
    d = df.copy()
    d["cv"] = np.where(d["mean_us"] > 0, d["std_us"] / d["mean_us"], 0.0)

    # (1) 프리셋 maxLevel에서 핵심 연산의 "mean ± std" 표 (라이브러리별).
    print("\n=== op latency @ maxLevel (mean ± std, μs) — 핵심 연산 ===")
    for preset in PRESET_ORDER:
        sub = d[d["preset"] == preset]
        if sub.empty:
            continue
        maxL = sub["maxLevel"].iloc[0]
        top = sub[sub["level"] == maxL]
        table = {}
        for lib in LIB_ORDER:
            col = {}
            for op in KEY_OPS:
                r = top[(top["op"] == op) & (top["library"] == lib)]
                if r.empty:
                    col[op] = "—"
                else:
                    col[op] = f"{r['mean_us'].iloc[0]:9.1f} ± {r['std_us'].iloc[0]:7.1f}"
            table[lib] = col
        out = pd.DataFrame(table).reindex(KEY_OPS)
        print(f"\n-- preset={preset}  logN={sub['logN'].iloc[0]}  level={maxL} --")
        print(out.to_string())

    # (2) 변동계수 큰 상위 10개 측정 (어느 연산이 측정 불안정한지).
    print("\n=== 변동성 상위 10개 측정 (cv = std/mean 내림차순) ===")
    top10 = d.sort_values("cv", ascending=False).head(10)
    show = top10[["preset", "level", "op", "library", "mean_us", "std_us", "cv"]].copy()
    with pd.option_context("display.float_format", lambda v: f"{v:8.3f}"):
        print(show.to_string(index=False))

    # (3) 전체 요약 CSV 저장 (cv 포함).
    outcsv = f"results_summary_std{SUFFIX}.csv"
    cols = ["preset", "level", "op", "library", "mean_us", "std_us", "cv"]
    d.sort_values(["preset", "level", "op", "library"])[cols].to_csv(outcsv, index=False)
    print(f"\n[summary] {outcsv}  ({len(d)} rows)")


def main():
    global SUFFIX
    ap = argparse.ArgumentParser(description="CKKS 벤치 CSV 병합 + 요약표 + 그래프")
    ap.add_argument("--lattigo", default="results_lattigo.csv")
    ap.add_argument("--openfhe", default="results_openfhe.csv")
    ap.add_argument("--suffix", default="", help="출력 파일명 접미사 (예: _1thread)")
    args = ap.parse_args()
    SUFFIX = args.suffix

    df = load(args.lattigo, args.openfhe)
    write_combined(df)
    console_summary(df)
    std_summary(df)
    plot_level_scaling(df)
    plot_summary_bars(df)
    print("\n[done] combined CSV + plots written.")


if __name__ == "__main__":
    main()
