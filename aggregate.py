#!/usr/bin/env python3
# aggregate.py — Lattigo/OpenFHE CKKS 벤치 CSV 병합 + 요약표 + 그래프.
# 입력: results_lattigo.csv, results_openfhe.csv (동일 스키마)
# 출력: results_combined.csv, plot_<preset>.png (레벨 스케일링), plot_summary.png (라이브러리 비교 막대)
#       + 콘솔 요약표.
# --suffix로 출력 파일명에 접미사를 붙일 수 있다(예: 단일스레드 재측정본을 덮어쓰지 않고 나란히 보관).
import argparse
import glob
import os
import sys

import matplotlib

matplotlib.use("Agg")  # WSL 헤드리스: 파일로만 저장
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 발표용으로 원본보다 글씨 키움.
plt.rcParams.update({
    "axes.titlesize": 16, "axes.labelsize": 15,
    "xtick.labelsize": 13, "ytick.labelsize": 13,
    "legend.fontsize": 13, "figure.titlesize": 19,
})

# Okabe-Ito 색맹 안전 팔레트 (엔티티=색). 라이브러리 2종 + op 라인 색.
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00"}  # 파랑 / 주황
LIB_ORDER = ["lattigo", "openfhe"]
OP_COLOR = {
    "add_cc": "#000000",
    "mul_cc": "#009E73",
    "mul_cc_rlk": "#E69F00",
    "rescale": "#56B4E9",
    "rot1": "#CC79A7",
    "relin": "#0072B2",   # 추가 (heavy 층)
    "mul_cp": "#D55E00",  # 추가 (mid 층)
    "add_cp": "#E69F00",  # 추가 (light 층)
}
# 비용 층: 값이 비슷한 op끼리 묶어 층마다 별도 PNG. 층 안에서 색은 서로 구분됨.
TIERS = {
    "heavy": ["mul_cc_rlk", "relin", "rot1"],
    "mid": ["mul_cc", "rescale", "mul_cp"],
    "light": ["add_cc", "add_cp"],
}
LINE_OPS = ["add_cc", "mul_cc", "mul_cc_rlk", "rescale", "rot1"]  # (구) 통합 레벨 그래프용 — 층 분리 후 미사용
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

# 8-op 산출물 디렉터리 (PNG·CSV 공용). 부트스트래핑(plots/boot)·key-switch(plots/ks)와 분리.
# 같은 실행의 산출물은 한곳에 모은다 — PNG는 여기, CSV는 루트로 흩어지면 짝을 잃는다.
OUT_DIR = os.path.join("plots", "8op")


def out_path(name):
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


# 이 스크립트는 8-op 벤치 전용이다. 부트스트래핑(results_boot*)과 key-switch 단건(results_ks*)은
# 단위·의미가 근본적으로 다르므로(precision_bits는 μs가 아닌 비트, in_level/out_level 대 level)
# 각각 aggregate_boot.py / aggregate_ks.py를 쓸 것. 아래 게이트가 혼입을 명시적으로 거부한다.
REQUIRED_COLS = ["maxLevel", "level", "op"]


def read_bench_csv(path):
    # comment='#': 대조군 CSV는 상단에 '#' 주석을 달아두므로 헤더로 오인하지 않게 한다.
    df = pd.read_csv(path, comment="#")

    # --- 스키마 검증 게이트 ---
    # 조용한 오염이 가장 위험하다: 스키마가 안 맞는 파일이 섞여도 preset 필터에서 NaN으로
    # 빠지면 콘솔·플롯에는 안 보이는데 results_combined.csv에는 그대로 기록된다.
    # 특히 results_ks_*는 maxLevel/level 컬럼과 op 이름이 8-op과 같아 육안 식별이 어렵다.
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        sys.exit(f"[schema] {path}: 필수 컬럼 없음 {missing} — "
                 f"8-op 벤치 CSV가 아니다. 부트스트래핑은 aggregate_boot.py, "
                 f"key-switch 단건은 aggregate_ks.py를 쓸 것.")

    bad = sorted(set(df["preset"].astype(str)) - set(PRESET_ORDER))
    if bad:
        sys.exit(f"[schema] {path}: 알 수 없는 preset {bad} — "
                 f"허용값 {PRESET_ORDER}. 부트스트래핑은 aggregate_boot.py, "
                 f"key-switch 단건은 aggregate_ks.py를 쓸 것.")
    return df


def load(lattigo_csvs, openfhe_csvs):
    global LIB_ORDER
    frames = []
    # Lattigo 입력은 프리셋별로 여러 파일일 수 있다(small/medium/large). 지정된 건 반드시 존재해야 함.
    for path in lattigo_csvs:
        if not os.path.exists(path):
            sys.exit(f"missing {path} — run the benchmarks first")
        frames.append(read_bench_csv(path))
    # --- OpenFHE 입력 가드 ---
    # 예전엔 파일이 없으면 [note]만 찍고 Lattigo 단독으로 진행했다. 그 조용한 반쪽 실행이
    # 실제로 사고를 냈다: 양쪽 라이브러리가 담긴 _mt 플롯 12장이 Lattigo 단독 버전으로
    # 덮어써졌고, .gitignore 때문에 git 복구도 불가능했다(병합 CSV가 남아 있어 겨우 복원).
    # 스키마 게이트·접미사 가드와 같은 원칙으로 거부한다.
    # --lattigo와 대칭으로 여러 경로를 받는다 — OpenFHE 8-op도 프리셋별 파일이라
    # 단일 경로만 받으면 매번 병합본을 미리 만들어야 했다.
    if not openfhe_csvs:
        sys.exit("[openfhe] --openfhe 미지정. 조용히 Lattigo 단독으로 진행하지 않는다.")
    for path in openfhe_csvs:
        if not os.path.exists(path):
            avail = sorted(glob.glob("results_openfhe*.csv"))
            hint = ("\n  현재 있는 OpenFHE CSV: " + ", ".join(avail)) if avail else ""
            sys.exit(
                f"[openfhe] {path} 없음. 조용히 Lattigo 단독으로 진행하지 않는다 — "
                f"반쪽 결과가 양쪽 결과인 것처럼 같은 파일명으로 덮어써진 사고 이력이 있다.\n"
                f"  --openfhe 로 실제 경로를 지정할 것.{hint}")
        frames.append(read_bench_csv(path))
    df = pd.concat(frames, ignore_index=True)
    # 실제 존재하는 라이브러리만 남겨 팬텀 openfhe 열/범례/막대를 제거(정규 순서 유지).
    present = set(df["library"].unique())
    LIB_ORDER = [lib for lib in LIB_ORDER if lib in present]
    # 정렬용 카테고리
    df["preset"] = pd.Categorical(df["preset"], PRESET_ORDER, ordered=True)
    df["op"] = pd.Categorical(df["op"], ALL_OPS, ordered=True)

    # 카테고리 변환에서 NaN이 생겼다면 어휘 밖 값이 들어온 것이다 → 조용히 넘기지 않고 중단.
    # (preset은 위 게이트에서 걸리지만 op는 여기서만 잡힌다. 예: rescale이 없는 ks CSV 등)
    for col in ("preset", "op"):
        n_nan = int(df[col].isna().sum())
        if n_nan:
            vals = sorted(set(pd.concat(frames, ignore_index=True)[col].astype(str))
                          - set(PRESET_ORDER if col == "preset" else ALL_OPS))
            sys.exit(f"[schema] {col} 컬럼에 알 수 없는 값 {vals} — {n_nan}행. "
                     f"이 행들은 콘솔·플롯에서는 필터로 빠지지만 results_combined.csv에는 "
                     f"기록되어 조용한 오염이 된다. 입력 파일을 확인할 것.")
    return df


def write_combined(df):
    out = out_path(f"results_combined{SUFFIX}.csv")
    df.sort_values(["library", "preset", "level", "op"]).to_csv(out, index=False)
    print(f"[merged] {out}  ({len(df)} rows)")


def console_summary(df):
    # 각 프리셋의 maxLevel에서 라이브러리별 mean_us 비교 + 비율.
    both = "lattigo" in LIB_ORDER and "openfhe" in LIB_ORDER
    header = "Lattigo vs OpenFHE" if both else " / ".join(LIB_ORDER)
    print(f"\n=== op latency @ maxLevel (mean μs) — {header} ===")
    for preset in PRESET_ORDER:
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        maxL = sub["maxLevel"].iloc[0]
        top = sub[sub["level"] == maxL]
        piv = top.pivot_table(index="op", columns="library", values="mean_us", observed=True)
        piv = piv.reindex(ALL_OPS)
        cols = [lib for lib in LIB_ORDER if lib in piv.columns]
        # 두 라이브러리가 모두 있을 때만 비교 비율 열을 추가.
        if both:
            piv["OF/Lat"] = piv["openfhe"] / piv["lattigo"]
            cols = cols + ["OF/Lat"]
        print(f"\n-- preset={preset}  logN={sub['logN'].iloc[0]}  level={maxL} --")
        with pd.option_context("display.float_format", lambda v: f"{v:10.1f}"):
            print(piv[cols].to_string())


def plot_level_scaling(df):
    # 프리셋 × 비용층별 별도 PNG: x=level, y=mean(ms, log), 색=op, 선스타일=library.
    # 층으로 나눠 op끼리 안 눌리고 Lattigo vs OpenFHE 간격이 잘 보인다.
    from matplotlib.lines import Line2D
    for preset in PRESET_ORDER:
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        for tier, ops in TIERS.items():
            present = [o for o in ops if not sub[sub["op"] == o].empty]
            if not present:
                continue
            fig, ax = plt.subplots(figsize=(9, 6))
            ymax = 0.0
            for op in present:
                for lib in LIB_ORDER:
                    d = sub[(sub["op"] == op) & (sub["library"] == lib)].sort_values("level")
                    if d.empty:
                        continue
                    # mean_us/std_us를 ms(÷1000)로 그린다. 원본 데이터는 μs 유지.
                    mean_ms = d["mean_us"].values / 1000.0
                    std_ms = d["std_us"].values / 1000.0
                    # 선형축이라 대칭 에러바(yerr=std). log_safe_yerr는 로그축 전용이라 미사용.
                    container = ax.errorbar(
                        d["level"], mean_ms,
                        yerr=std_ms,
                        color=OP_COLOR[op],
                        linestyle="-" if lib == "lattigo" else "--",
                        marker="o" if lib == "lattigo" else "s",
                        markersize=6, linewidth=2.2,
                        capsize=2, elinewidth=0.8, ecolor=OP_COLOR[op],
                    )
                    for bar in container[2]:  # barlinecols
                        bar.set_alpha(0.4)
                    for cap in container[1]:  # caplines
                        cap.set_alpha(0.6)
                    ymax = max(ymax, float((mean_ms + std_ms).max()))
            # 선형축, 층 데이터에 타이트하게 0부터 시작 → 배수 차이를 정직하게 표시.
            ax.set_ylim(0, ymax * 1.08)
            ax.set_xlabel("level (remaining multiplicative budget)")
            ax.set_ylabel("mean latency (ms)")
            ax.set_title(f"CKKS op latency vs level — {preset} · {tier} "
                         f"(logN={sub['logN'].iloc[0]})")
            ax.grid(True, which="both", axis="both", color="0.9", linewidth=0.6)
            ax.set_axisbelow(True)
            # 범례 2개: op=색, library=선스타일 (원본 그대로).
            op_handles = [Line2D([0], [0], color=OP_COLOR[o], lw=2.5, label=o) for o in present]
            lib_handles = [
                Line2D([0], [0], color="0.3", lw=2.5, linestyle="-", marker="o", label="lattigo"),
                Line2D([0], [0], color="0.3", lw=2.5, linestyle="--", marker="s", label="openfhe"),
            ]
            leg1 = ax.legend(handles=op_handles, title="operation", loc="upper left")
            ax.add_artist(leg1)
            ax.legend(handles=lib_handles, title="library", loc="lower right")
            fig.tight_layout()
            out = out_path(f"plot_{preset}_{tier}{SUFFIX}.png")
            fig.savefig(out, dpi=140)
            plt.close(fig)
            print(f"[plot] {out}")


def plot_summary_bars(df):
    # 비용층별 별도 PNG. 각 층: maxLevel에서 프리셋 3개 가로 서브플롯, 선형 y(0부터),
    # 파랑=lattigo/주황=openfhe 막대 높이 차이를 정직하게 표시. 막대 위 값(ms) 표기.
    DEC = {"heavy": 1, "mid": 2, "light": 3}  # 층별 값 라벨 소수자리
    for tier, ops in TIERS.items():
        dec = DEC[tier]
        fig, axes = plt.subplots(1, 3, figsize=(16, 6))  # 프리셋 스케일이 달라 sharey 안 함
        for ax, preset in zip(axes, PRESET_ORDER):
            sub = df[df["preset"] == preset]
            if sub.empty:
                continue
            maxL = sub["maxLevel"].iloc[0]
            top = sub[sub["level"] == maxL]
            present = [o for o in ops if not top[top["op"] == o].empty]
            x = range(len(present))
            width = 0.38
            ymax = 0.0
            for i, lib in enumerate(LIB_ORDER):
                # mean_us/std_us를 ms(÷1000)로 표시. 원본 데이터는 μs 유지.
                vals = [top[(top["op"] == op) & (top["library"] == lib)]["mean_us"].mean() / 1000.0
                        for op in present]
                errs = [top[(top["op"] == op) & (top["library"] == lib)]["std_us"].mean() / 1000.0
                        for op in present]
                offset = (i - 0.5) * width
                # 선형축 → 대칭 에러바(yerr=std). relin은 std=0이라 에러바 없음(정상).
                ax.bar([xi + offset for xi in x], vals, width,
                       yerr=errs, capsize=3,
                       error_kw={"elinewidth": 0.8, "alpha": 0.6},
                       color=LIB_COLOR[lib], label=lib, edgecolor="black", linewidth=0.8)
                # 막대 위 값 표기.
                for xi, v, e in zip(x, vals, errs):
                    if np.isnan(v):
                        continue
                    ax.annotate(f"{v:.{dec}f}", (xi + offset, v + e),
                                textcoords="offset points", xytext=(0, 3),
                                ha="center", va="bottom", fontsize=12)
                    ymax = max(ymax, v + e)
            ax.set_ylim(0, ymax * 1.20)  # 값 라벨 공간 확보
            ax.set_title(f"{preset} (logN={sub['logN'].iloc[0]}, level={maxL})")
            ax.set_xticks(list(x))
            ax.set_xticklabels(present, fontsize=13)
            ax.grid(True, axis="y", color="0.9", linewidth=0.6)
            ax.set_axisbelow(True)
        axes[0].set_ylabel("mean latency (ms)")
        # 범례는 그림 상단 우측 여백에 (막대·값라벨과 안 겹치게). 막대 높이가 균일해 축 안에 두면 가려짐.
        from matplotlib.patches import Patch
        lib_handles = [Patch(facecolor=LIB_COLOR[lib], edgecolor="black", label=lib)
                       for lib in LIB_ORDER]
        fig.legend(handles=lib_handles, title="library", loc="upper right",
                   bbox_to_anchor=(0.998, 0.99), ncol=2, fontsize=13, title_fontsize=13)
        fig.suptitle(f"CKKS op latency @ maxLevel · {tier} — Lattigo vs OpenFHE",
                     fontsize=19, x=0.4)
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        out = out_path(f"plot_summary_{tier}{SUFFIX}.png")
        fig.savefig(out, dpi=140)
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
    outcsv = out_path(f"results_summary_std{SUFFIX}.csv")
    cols = ["preset", "level", "op", "library", "mean_us", "std_us", "cv"]
    d.sort_values(["preset", "level", "op", "library"])[cols].to_csv(outcsv, index=False)
    print(f"\n[summary] {outcsv}  ({len(d)} rows)")


def main():
    global SUFFIX
    ap = argparse.ArgumentParser(description="CKKS 벤치 CSV 병합 + 요약표 + 그래프")
    # Lattigo는 프리셋별 파일이 여러 개일 수 있어 여러 경로를 받는다(기본=small/medium/large).
    ap.add_argument("--lattigo", nargs="+",
                    default=["results_lattigo.csv",
                             "results_lattigo_medium.csv",
                             "results_lattigo_large.csv"])
    # OpenFHE도 프리셋별 파일이 여러 개다(small/medium/large × mt/1t) → --lattigo와 대칭으로 다중 경로.
    # 기본값은 일부러 존재하지 않는 단일 경로로 둔다: 조건(mt/1t)을 스크립트가 임의로 고르지 않고
    # 사용자가 명시하게 하기 위함이다(가드가 걸려 실행이 멈춘다).
    ap.add_argument("--openfhe", nargs="+", default=["results_openfhe.csv"])
    ap.add_argument("--suffix", default="",
                    help="출력 파일명 접미사 (필수, 예: _mt / _1thread). "
                         "측정 조건을 파일명에 남기기 위한 것으로 생략할 수 없다.")
    args = ap.parse_args()

    # --- 접미사 가드 ---
    # 스키마 게이트와 같은 원칙: 조용한 통과를 막는다.
    # 접미사 없이 돌리면 plot_large_heavy.png / results_combined.csv 처럼 조건이 지워진
    # 파일명이 나온다. 나중에 보면 mt인지 1core인지 알 수 없고, 같은 이름으로 다른 조건이
    # 덮어써도 눈치챌 수 없다. 경고로는 부족해서 거부한다.
    if not args.suffix:
        sys.exit(
            "[suffix] --suffix 가 필요하다. 접미사 없이 만든 산출물은 측정 조건을 "
            "파일명으로 알 수 없어(mt인지 1core인지) 나중에 판별이 불가능하고, "
            "다른 조건 실행이 같은 이름을 조용히 덮어쓴다.\n"
            "  예: --suffix _mt        (기본 멀티코어)\n"
            "      --suffix _1thread   (OMP_NUM_THREADS=1)")
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
