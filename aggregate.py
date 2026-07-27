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
LIB_COLOR = {"lattigo": "#0072B2", "openfhe": "#D55E00", "seal": "#CC79A7"}  # 파랑 / 주황 / 보라
LIB_ORDER = ["lattigo", "openfhe", "seal"]
LIB_LABEL = {"lattigo": "Lattigo", "openfhe": "OpenFHE", "seal": "SEAL"}
LIB_LS = {"lattigo": "-", "openfhe": "--", "seal": ":"}      # (구) 레벨 차트 선스타일 인코딩 — 폐지됨
LIB_MARKER = {"lattigo": "o", "openfhe": "s", "seal": "^"}   # (구) 동상
# 레벨 차트 신 스타일(2026-07-27): 색=라이브러리(요약 막대와 동일), 마커=연산, 선은 전부 실선.
# 예전엔 색=연산 / 선스타일=라이브러리라 선 하나를 짚으려면 범례 둘을 교차 참조해야 했고,
# 요약 막대 차트(색=라이브러리)와 같은 발표 안에서 색의 의미가 뒤바뀌었다.
# 마커는 티어마다 재사용한다 — 한 차트 안에서만 구분되면 되고, 종류가 적을수록 읽기 쉽다.
TIER_MARKERS = ["o", "s", "^"]

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
THREAD_MODE = "1t"  # --suffix에서 유도. 물리 게이트가 1t/mt를 다르게 검사한다.

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


def load(lattigo_csvs, openfhe_csvs, seal_csvs):
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
    # --- SEAL 입력 가드 --- (OpenFHE 가드와 동일 원칙: 조용한 반쪽 실행 금지)
    if not seal_csvs:
        sys.exit("[seal] --seal 미지정. 조용히 2자 비교로 진행하지 않는다.")
    for path in seal_csvs:
        if not os.path.exists(path):
            avail = sorted(glob.glob("results_seal*.csv"))
            hint = ("\n  현재 있는 SEAL CSV: " + ", ".join(avail)) if avail else ""
            sys.exit(f"[seal] {path} 없음. 3자 비교인데 조용히 2자로 진행하지 않는다.{hint}")
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
    physics_gate(df)
    return df


# --- 물리 정합 게이트 (2026-07-27 추가) ---
# 왜 필요한가: lattigo large 1t L15에서 relin > mul_cc_rlk 위반이 나왔는데 사람이 플롯을
# 눈으로 보고서야 잡았다. 자동화하지 않으면 다음 재측정·라이브러리 추가에서 조용히 지나간다.
# 임계값은 전부 실측 분포에서 정했다(근거를 주석에 남긴다).
#
# 세 라이브러리 18 CSV 기준 관측값:
#   relin/mul_cc_rlk : 1t 최대 0.982 (90행) / mt 최대 2.28 (CV가 1.8까지 가서 평균이 무의미)
#   1t 인접레벨 비    : 최대 0.975
#   1t CV            : 중앙 0.014, 최대 0.315 (작은 op) → CV는 판별자로 쓸 수 없다
FUSE_RATIO_TOL_1T = 1.02   # relin/mul_cc_rlk 상한. 정상 최대 0.982, 실제 위반 1.095 → 사이에 둔다
MONO_RATIO_TOL_1T = 1.02   # v[L]/v[L+1] 상한. 정상 최대 0.975
SIGMA_K = 3.0              # mt는 비율이 무의미하므로 자체 분산으로 설명 안 되는 것만 위반


def physics_gate(df):
    """물리적으로 불가능한 값과 계측 실패 흔적을 잡는다. 위반 시 중단한다."""
    viol = []

    # G1. std_us == 0 — reps>1에서 0은 측정값이 아니다(파생값·일괄계측의 흔적).
    #     relin이 실제로 이 상태였다(lattigo·openfhe, 각 60행).
    z = df[(df["std_us"] == 0) & (df["reps"] > 1)]
    for _, r in z.iterrows():
        viol.append(f"[std=0] {r.library} {r.preset} L{int(r.level)} {r.op} "
                    f"(reps={int(r.reps)}) — 파생값이거나 반복별 계측이 아님")

    piv_m = df.pivot_table(index=["library", "preset", "level"], columns="op", values="mean_us")
    piv_s = df.pivot_table(index=["library", "preset", "level"], columns="op", values="std_us")
    has = {"relin", "mul_cc_rlk"} <= set(piv_m.columns)

    # G2. relin <= mul_cc_rlk — relin 단독이 '곱셈+relin'보다 비쌀 수 없다.
    #     융합(fusion)이 있어도 이 부등식은 유지된다.
    if has:
        for idx in piv_m.index:
            rel, rlk = piv_m.loc[idx, "relin"], piv_m.loc[idx, "mul_cc_rlk"]
            if pd.isna(rel) or pd.isna(rlk) or rlk <= 0:
                continue
            if THREAD_MODE == "1t":
                if rel / rlk > FUSE_RATIO_TOL_1T:
                    viol.append(f"[relin>mul_cc_rlk] {idx} — {rel:.1f} / {rlk:.1f} = "
                                f"{rel/rlk:.4f} > {FUSE_RATIO_TOL_1T}")
            else:
                sig = SIGMA_K * (piv_s.loc[idx, "relin"] + piv_s.loc[idx, "mul_cc_rlk"])
                if rel - rlk > sig:
                    viol.append(f"[relin>mul_cc_rlk] {idx} — 차 {rel-rlk:.1f} > "
                                f"{SIGMA_K}σ {sig:.1f} (분산으로 설명 안 됨)")

    # G3. 1t 레벨 단조성 — 레벨이 낮을수록 빨라야 한다.
    #     작은 op는 CV가 0.3까지 가므로 σ 조건을 함께 걸어 오탐을 막는다.
    if THREAD_MODE == "1t":
        for (lib, preset, op), g in df.groupby(["library", "preset", "op"], observed=True):
            g = g.sort_values("level")
            v, sd, lv = g.mean_us.tolist(), g.std_us.tolist(), g.level.tolist()
            for i in range(len(v) - 1):
                if v[i] > v[i + 1] * MONO_RATIO_TOL_1T and (v[i] - v[i + 1]) > 2 * (sd[i] + sd[i + 1]):
                    viol.append(f"[단조성] {lib} {preset} {op} L{int(lv[i])}({v[i]:.1f}) > "
                                f"L{int(lv[i+1])}({v[i+1]:.1f})")

    if viol:
        sys.exit("[physics] 물리 정합 게이트 위반 — 통과시키지 않는다.\n  "
                 + "\n  ".join(viol)
                 + "\n\n  위반 행을 조사할 것. 재측정이 필요할 수 있다."
                 + "\n  (임계 근거는 aggregate.py 상단 FUSE_RATIO_TOL_1T 주석 참조)")
    print(f"[physics] 게이트 통과 ({len(df)}행, mode={THREAD_MODE})")


def write_combined(df):
    out = out_path(f"results_combined{SUFFIX}.csv")
    df.sort_values(["library", "preset", "level", "op"]).to_csv(out, index=False)
    print(f"[merged] {out}  ({len(df)} rows)")


def console_summary(df):
    # 각 프리셋의 maxLevel에서 라이브러리별 mean_us 비교 + 비율.
    # LIB_ORDER는 실제 데이터에 존재하는 라이브러리만 담고 있다(load에서 필터).
    # 하드코딩하면 3자 비교인데 제목이 2자로 남는 사고가 난다.
    header = " vs ".join(LIB_LABEL[l] for l in LIB_ORDER)
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
        # 3자 비교이므로 Lattigo를 기준(=1)으로 한 상대비 열을 붙인다.
        # 예전 2자 시절의 OF/Lat 단일 열은 SEAL이 빠져 조용히 반쪽 표가 된다.
        if "lattigo" in piv.columns:
            for lib in LIB_ORDER:
                if lib != "lattigo" and lib in piv.columns:
                    name = f"{lib[:2].upper()}/Lat"
                    piv[name] = piv[lib] / piv["lattigo"]
                    cols = cols + [name]
        print(f"\n-- preset={preset}  logN={sub['logN'].iloc[0]}  level={maxL} --")
        with pd.option_context("display.float_format", lambda v: f"{v:10.1f}"):
            print(piv[cols].to_string())


def plot_level_scaling(df):
    # 프리셋 × 비용층별 별도 PNG: x=level, y=mean(ms), **색=library, 마커=operation, 선은 전부 실선**.
    # 마커는 채우고 테두리를 없애(mew=0, mec=선색) 마커와 선이 한 획으로 이어져 보이게 한다.
    from matplotlib.lines import Line2D
    for preset in PRESET_ORDER:
        sub = df[df["preset"] == preset]
        if sub.empty:
            continue
        for tier, ops in TIERS.items():
            present = [o for o in ops if not sub[sub["op"] == o].empty]
            if not present:
                continue
            # 마커는 티어 내 연산 순서대로 o, s, ^ (light는 연산이 2개라 o, s만 쓰인다).
            op_marker = {o: TIER_MARKERS[i % len(TIER_MARKERS)] for i, o in enumerate(present)}
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
                    # 선·마커와 에러바를 나눠 그린다.
                    # errorbar()에 alpha를 주면 선·마커까지 반투명해지므로,
                    # 선·마커는 plot()으로 불투명하게 그리고 에러바만 fmt="none"으로 얹는다.
                    ax.plot(
                        d["level"], mean_ms,
                        color=LIB_COLOR[lib],
                        linestyle="-",
                        marker=op_marker[op],
                        markersize=6, linewidth=2.0,
                        markeredgewidth=0, markeredgecolor=LIB_COLOR[lib],
                    )
                    # 에러바 = 표준편차 1배. 색은 해당 라이브러리 색, 반투명으로 얹는다.
                    ax.errorbar(
                        d["level"], mean_ms, yerr=std_ms, fmt="none",
                        ecolor=LIB_COLOR[lib],
                        elinewidth=0.8, capsize=2, capthick=0.8,
                        alpha=0.4,
                    )
                    ymax = max(ymax, float((mean_ms + std_ms).max()))
            # 선형축, 층 데이터에 타이트하게 0부터 시작 → 배수 차이를 정직하게 표시.
            # mt에서 OpenFHE 에러바가 축을 늘리더라도 그대로 둔다 — 분산이 큰 것 자체가 결과다.
            ax.set_ylim(0, ymax * 1.08)
            ax.set_xlabel("level (remaining multiplicative budget)")
            ax.set_ylabel("mean latency (ms)")
            ax.set_title(f"CKKS op latency vs level — {preset} · {tier} "
                         f"(logN={sub['logN'].iloc[0]})")
            ax.grid(True, which="both", axis="both", color="0.9", linewidth=0.6)
            ax.set_axisbelow(True)

            # 범례 2개를 좌상단에 세로로 쌓는다. library(색) 위, operation(마커) 아래.
            lib_handles = [Line2D([0], [0], color=LIB_COLOR[l], lw=2.5, label=l)
                           for l in LIB_ORDER]
            op_handles = [Line2D([0], [0], color="0.35", lw=2.0, marker=op_marker[o],
                                 markersize=6, markeredgewidth=0, label=o) for o in present]
            leg1 = ax.legend(handles=lib_handles, title="library", loc="upper left",
                             framealpha=0.9)
            ax.add_artist(leg1)
            # leg1의 실제 높이를 재서 그 아래에 붙인다(연산 개수와 무관하게 안정적).
            fig.canvas.draw()
            bb = leg1.get_window_extent().transformed(ax.transAxes.inverted())
            ax.legend(handles=op_handles, title="operation", loc="upper left",
                      bbox_to_anchor=(bb.x0, bb.y0 - 0.02), framealpha=0.9)

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
            # 3자 레이아웃: 막대 중심 간격과 막대 폭을 따로 잡는다.
            # 예전 공식 offset=(i-0.5)*width 는 2자 전용이라 3자에서 그룹이 눈금 중심에서
            # 벗어나고(오프셋 -0.19/+0.19/+0.57) 간격==폭이라 막대가 맞닿아 한 덩어리로 보였다.
            SPACING = 0.26      # 막대 중심 간 간격
            width = 0.21        # 막대 폭 (SPACING과 달라야 사이가 벌어진다)
            n_lib = len(LIB_ORDER)
            ymax = 0.0
            for i, lib in enumerate(LIB_ORDER):
                # mean_us/std_us를 ms(÷1000)로 표시. 원본 데이터는 μs 유지.
                vals = [top[(top["op"] == op) & (top["library"] == lib)]["mean_us"].mean() / 1000.0
                        for op in present]
                errs = [top[(top["op"] == op) & (top["library"] == lib)]["std_us"].mean() / 1000.0
                        for op in present]
                offset = (i - (n_lib - 1) / 2.0) * SPACING   # 그룹을 눈금 중심에 정렬
                # 선형축 → 대칭 에러바(yerr=std). relin은 std=0이라 에러바 없음(정상).
                # 흰색 edge: 막대끼리 붙어 보이는 것을 끊어준다.
                ax.bar([xi + offset for xi in x], vals, width,
                       yerr=errs, capsize=2.5,
                       error_kw={"elinewidth": 1.0, "alpha": 0.6},
                       color=LIB_COLOR[lib], label=lib, edgecolor="white", linewidth=0.6)
                # 값 라벨은 막대 상단이 아니라 **에러바 캡 위**에 둔다(캡과 겹치지 않게).
                for xi, v, e in zip(x, vals, errs):
                    if np.isnan(v):
                        continue
                    ax.annotate(f"{v:.{dec}f}", (xi + offset, v + e),
                                textcoords="offset points", xytext=(0, 3.5),
                                ha="center", va="bottom", fontsize=8.5)
                    ymax = max(ymax, v + e)
            ax.set_ylim(0, ymax * 1.18)  # 값 라벨 공간 확보
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
                   bbox_to_anchor=(0.998, 1.0), ncol=3, fontsize=13, title_fontsize=13)
        libs_txt = " vs ".join(LIB_LABEL[l] for l in LIB_ORDER)
        fig.suptitle(f"CKKS op latency @ maxLevel · {tier} — {libs_txt}",
                     fontsize=19, x=0.4)
        # 범례를 축 영역 위로 완전히 빼서 서브플롯 제목을 가리지 않게 한다
        # (3자가 되며 범례가 커져 "large" 제목을 덮었다).
        fig.tight_layout(rect=[0, 0, 1, 0.88])
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
    # SEAL도 동일 원칙: 기본값을 존재하지 않는 경로로 두어 사용자가 조건을 명시하게 한다.
    ap.add_argument("--seal", nargs="+", default=["results_seal.csv"])
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
    global THREAD_MODE
    THREAD_MODE = "mt" if "_mt" in args.suffix else "1t"

    df = load(args.lattigo, args.openfhe, args.seal)
    write_combined(df)
    console_summary(df)
    std_summary(df)
    plot_level_scaling(df)
    plot_summary_bars(df)
    print("\n[done] combined CSV + plots written.")


if __name__ == "__main__":
    main()
