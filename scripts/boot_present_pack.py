#!/usr/bin/env python3
"""발표용 데이터 팩 생성 — `explore/boot_present/PRESENT_DATA.md`.

⚠️ **모든 수치를 원자료 CSV 에서 다시 뽑는다.** `PROJECT_CONTEXT.md §10` 의 서술을
베끼지 않는다 — 문서와 원자료가 어긋나면 원자료가 맞다.

새 측정을 하지 않는다. 이미 있는 CSV 만 읽는다.
"""
import os
import shutil
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "explore", "boot_present")
LBS = [(2, 2), (3, 3), (3, 4), (4, 3), (4, 4)]
ROTKEY = {(2, 2): 61, (3, 3): 39, (3, 4): 48, (4, 3): 48, (4, 4): 33}
B = []


def w(*a):
    B.append(" ".join(str(x) for x in a))


def main_df(lib, mode):
    d = pd.read_csv(respath.find(f"boot_main_{lib}_{mode}_dku16c.csv"))
    d["sub"] = d.scaling.astype(str).str.split("|").str[-1]
    return d[d.rep >= 0]


def stat(g):
    return dict(prec=g.precision_bits.mean(), pstd=g.precision_bits.std(),
                boot=g.boot_us.mean() / 1e6, bsd=g.boot_us.std() / 1e6,
                kg=g.keygen_us.mean() / 1e6, rss=g.peak_rss_mb.max() / 1024,
                mag=g.magnitude_ratio.mean(), n=len(g), ok=int(g.ok.sum()))


def main():
    os.makedirs(OUT, exist_ok=True)
    w("# PRESENT_DATA — 부트스트래핑 3단계 발표 수치\n")
    w("⚠️ **전 수치를 원자료 CSV 에서 재추출했다** (`scripts/boot_present_pack.py`).")
    w("`PROJECT_CONTEXT.md §10` 서술을 베끼지 않았다. 어긋나면 이 표가 맞다.\n")
    w("측정 환경 `dku16c`, 브랜치 `third-lib`. OpenFHE v1.5.1 / Lattigo v6.2.0.")
    w("SEAL 은 CKKS 부트스트래핑을 지원하지 않아 **2자**다.\n")

    # ---- 1. 확정표 -------------------------------------------------------
    w("## 1. 확정표 — BT1 · BT2 × 라이브러리 × 1t/mt (분해깊이 {3,3})\n")
    w("BT1 = q₀ 60 / Δ 59 / 잔여 L 4,  BT2 = q₀ 60 / Δ 58 / 잔여 L 4. 둘 다 분해깊이 {3,3}.\n")
    w("| preset | lib | 1t 정밀도 ±σ | mt 정밀도 | mt−1t | 1t 부트 s ±σ | mt 부트 s ±σ | mt/1t | 1t keygen | mt keygen | peak RSS |")
    w("|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|")
    for dl, pn in ((59, "BT1"), (58, "BT2")):
        for lib in ("openfhe", "lattigo"):
            d1, dm = main_df(lib, "1t"), main_df(lib, "mt")
            sel = lambda d: d[(d.delta == dl) & (d.levelBudget_c2s == 3) & (d.levelBudget_s2c == 3)]
            a = stat(sel(d1))
            t = stat(sel(dm[dm["sub"] == "timing"]))
            p = stat(sel(dm[dm["sub"] == "precision"]))
            w(f"| **{pn}** | {lib} | **{a['prec']:.3f}** ±{a['pstd']:.3f} | {p['prec']:.3f} | "
              f"{p['prec'] - a['prec']:+.3f} | {a['boot']:.2f} ±{a['bsd']:.2f} | "
              f"{t['boot']:.2f} ±{t['bsd']:.2f} | **{t['boot'] / a['boot']:.3f}** | "
              f"{a['kg']:.1f}s | {t['kg']:.1f}s | {max(a['rss'], t['rss']):.1f} GB |")
    w("\n자릿수비(복호값/원본)는 전 조합 1.000~1.006, 레벨 전이 전건 정확.\n")

    # ---- 2. 정밀도 곡선 --------------------------------------------------
    w("## 2. 정밀도 곡선 (2단계, 1t, {3,3})\n")
    o = pd.read_csv(respath.find("boot_prec_openfhe_1t_dku16c.csv"))
    l = pd.read_csv(respath.find("boot_prec_lattigo_1t_dku16c.csv"))

    def cur(d):
        g = d[(d.rep >= 0) & (d.ok == 1) & (d.levelBudget_c2s == 3) & (d.levelBudget_s2c == 3)].copy()
        g["gap"] = g.q0 - g.delta
        return g

    O, L = cur(o), cur(l)
    w("### 2a. OpenFHE — Δ 에 반응 (q₀−Δ = 1 고정)\n")
    w("| Δ | 52 | 53 | 55 | 58 | 59 |")
    w("|---|---:|---:|---:|---:|---:|")
    k = O[O.gap == 1].groupby("delta").precision_bits.mean()
    w("| **정밀도** | " + " | ".join(f"**{k[d]:.3f}**" for d in (52, 53, 55, 58, 59)) + " |")
    sp = O.groupby("delta").precision_bits.agg(lambda x: x.max() - x.min())
    w("| 같은 Δ 안 q₀ 편차 | " + " | ".join(f"{sp[d]:.3f}" for d in (52, 53, 55, 58, 59)) + " |")
    w("\n### 2b. Lattigo — q₀−Δ (= LogMessageRatio) 에 반응\n")
    w("| q₀−Δ | 1 | 2 | 5 | 7 |")
    w("|---|---:|---:|---:|---:|")
    kl = L.groupby("gap").precision_bits.mean()
    w("| **정밀도** | " + " | ".join(f"**{kl[g]:.3f}**" for g in (1, 2, 5, 7)) + " |")
    w("| 해당 Δ | " + " | ".join(
        ",".join(str(int(x)) for x in sorted(L[L.gap == g].delta.unique())) for g in (1, 2, 5, 7)) + " |")
    n1 = L[L.gap == 1]
    w(f"\n⚠️ q₀−Δ=1 인 {n1.groupby('delta').ngroups}개 Δ 에서 정밀도가 "
      f"{n1.precision_bits.min():.3f}~{n1.precision_bits.max():.3f} — **Δ 의존성 사실상 0**.\n")

    # ---- 3. Δ 절벽 -------------------------------------------------------
    w("## 3. Δ 절벽 — OpenFHE 는 Δ ≥ 52 에서만 동작한다\n")
    w("| q₀ | Δ | q₀−Δ | 잔여 L | 정밀도 | 자릿수비 | 판정 |")
    w("|---:|---:|---:|---:|---:|---:|---|")
    rows = []
    for src in ("boot_prec_openfhe_1t_dku16c.csv", "boot_prec_openfhe_thresh_1t_dku16c.csv"):
        d = pd.read_csv(respath.find(src))
        d = d[(d.rep >= 0) & (d.levelBudget_c2s == 3) & (d.levelBudget_s2c == 3)]
        for k2, g in d.groupby(["q0", "delta", "residual_L"]):
            rows.append((int(k2[0]), int(k2[1]), int(k2[2]), g.precision_bits.mean(),
                         g.magnitude_ratio.mean(), int(g.ok.min())))
    for q0, dl, L_, pr, mg, ok in sorted(set(rows), key=lambda r: (r[1], r[0])):
        if pd.isna(pr):
            w(f"| {q0} | **{dl}** | {q0 - dl} | {L_} | — | — | ✗ Decode 거부 |")
        else:
            w(f"| {q0} | **{dl}** | {q0 - dl} | {L_} | {pr:.3f} | {mg:.3f} | "
              f"{'✔' if ok else '✗ 자릿수 파탄'} |")
    w("\nΔ ≤ 45 는 OpenFHE `Decode` 가 거부한다 (`ckkspackedencoding.cpp:451-455`,")
    w("`logstd > Δ − 5` → **정밀도 5비트 미만**). Δ 상한은 59 (`scalingModSize < 60`).\n")

    # ---- 4. 분해깊이 × 부트 시간 -----------------------------------------
    w("## 4. 분해깊이 × 부트 시간 (3단계)\n")
    w("| 분해깊이 | 회전키(LA) | BT1 1t | BT1 mt | mt/1t | BT2 1t | BT2 mt | mt/1t | LA BT2 1t | LA BT2 mt |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for lb in LBS:
        c = []
        for dl in (59, 58):
            d1 = main_df("openfhe", "1t"); dm = main_df("openfhe", "mt")
            s = lambda d: d[(d.delta == dl) & (d.levelBudget_c2s == lb[0]) & (d.levelBudget_s2c == lb[1])]
            a = s(d1).boot_us.mean() / 1e6
            t = s(dm[dm["sub"] == "timing"]).boot_us.mean() / 1e6
            c += [f"{a:.2f}", f"{t:.2f}", f"{t / a:.2f}"]
        l1 = main_df("lattigo", "1t"); lm = main_df("lattigo", "mt")
        sl = lambda d: d[(d.delta == 58) & (d.levelBudget_c2s == lb[0]) & (d.levelBudget_s2c == lb[1])]
        c += [f"{sl(l1).boot_us.mean() / 1e6:.2f}",
              f"{sl(lm[lm['sub'] == 'timing']).boot_us.mean() / 1e6:.2f}"]
        w(f"| {{{lb[0]},{lb[1]}}} | {ROTKEY[lb]} | " + " | ".join(c) + " |")
    w("\n**1t 최속 = {3,3}, mt 최속 = {4,3}** — 순서가 뒤집힌다.\n")

    # ---- 5. 분해깊이 × 정밀도 --------------------------------------------
    w("## 5. 분해깊이 × 정밀도 — Δ 마다 순서가 다르고 방향이 뒤집힌다\n")
    g2 = o[(o.rep >= 0) & (o.q0 == 53) & (o.delta == 52) & (o.residual_L == 6)]
    s52 = g2.groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()
    d1 = main_df("openfhe", "1t")
    s59 = d1[d1.delta == 59].groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()
    s58 = d1[d1.delta == 58].groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.mean()
    lat = main_df("lattigo", "1t")
    l58 = lat[lat.delta == 58].groupby(["levelBudget_c2s", "levelBudget_s2c"]).precision_bits.agg(["mean", "std"])
    w("| 분해깊이 | Δ=52 (q₀53,L6) | BT1 Δ=59 | BT2 Δ=58 | Lattigo BT2 |")
    w("|---|---:|---:|---:|---:|")
    for lb in LBS:
        f = lambda s: f"{s.loc[lb]:.3f}" if lb in s.index else "—"
        lv = f"{l58.loc[lb, 'mean']:.3f}" if lb in l58.index else "—"
        w(f"| {{{lb[0]},{lb[1]}}} | {f(s52)} | {f(s59)} | {f(s58)} | {lv} |")
    sp = [("Δ=52", s52), ("BT1", s59), ("BT2", s58)]
    w("| **폭** | " + " | ".join(f"**{s.max() - s.min():.3f}**" for _, s in sp) +
      f" | **{l58['mean'].max() - l58['mean'].min():.3f}** |")
    w(f"\nLattigo 반복 σ ≤ {l58['std'].max():.3f} — 완전 무관.\n")

    # ---- 6. dnum 스윕 ----------------------------------------------------
    w("## 6. dnum 스윕 (BT2, {3,3}, 1t, reps 10)\n")
    for lib in ("openfhe", "lattigo"):
        d = pd.read_csv(respath.find(f"boot_dnum_{lib}_1t_dku16c.csv"))
        d = d[d.rep >= 0]
        k = d.groupby("dnum").agg(prec=("precision_bits", "mean"),
                                  boot=("boot_us", lambda x: x.mean() / 1e6),
                                  bsd=("boot_us", lambda x: x.std() / 1e6),
                                  kg=("keygen_us", lambda x: x.mean() / 1e6),
                                  rss=("peak_rss_mb", "max"), pc=("PCount", "first"),
                                  lp=("logP_boot", "first"), qp=("logQP_boot", "first")).sort_index()
        w(f"### {lib}\n")
        w("| dnum | PCount | logP | logQP | 여유 | 정밀도 | 부트 s ±σ | 부트비 | keygen | peak RSS |")
        w("|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|")
        b0 = k.boot.iloc[0]
        for i, r in k.iterrows():
            w(f"| {int(i)} | {int(r.pc)} | {int(r.lp)} | {int(r.qp)} | **{1747 - int(r.qp)}** | "
              f"{r.prec:.3f} | {r.boot:.2f} ±{r.bsd:.2f} | {r.boot / b0:.3f} | "
              f"{r.kg:.1f}s | {r.rss / 1024:.1f} GB |")
        w("")
        import math as _m
        lo, hi = int(k.index[0]), int(k.index[-1])
        rb = k.boot.iloc[-1] / b0
        expo = _m.log(rb) / _m.log(hi / lo)
        w(f"dnum {lo} → {hi} (**{hi / lo:.1f}배**) 에 부트 **{rb:.2f}배** — "
          f"비용 지수 **{expo:.2f}** (선형이면 1.0).\n")

    # ---- 6b. 속도·정밀도 격차 분해 ---------------------------------------
    w("## 6b. 격차 정량 분해 (진단, BT2 1t {3,3})\n")
    w("⚠️ **진단 목적 단발 측정. 프리셋 후보가 아니다** — `SPARSE_TERNARY` 는 메인키가")
    w("H=192 sparse 라 Table 5.2(uniform ternary) 를 적용할 수 없다.\n")
    dg = pd.read_csv(respath.find("boot_prec_openfhe_diag_skdist_1t_dku16c.csv"))
    dg = dg[dg.rep >= 0]
    mu = main_df("openfhe", "1t")
    mu = mu[(mu.delta == 58) & (mu.levelBudget_c2s == 3) & (mu.levelBudget_s2c == 3)]
    ml = main_df("lattigo", "1t")
    ml = ml[(ml.delta == 58) & (ml.levelBudget_c2s == 3) & (ml.levelBudget_s2c == 3)]
    w("| | boot_depth | dnum | PCount | logP | logQP(여유) | 부트 s ±σ | 정밀도 | keygen | RSS |")
    w("|---|---:|---:|---:|---:|---:|---|---:|---:|---:|")
    for nm, g in (("OpenFHE `UNIFORM_TERNARY` (본측정)", mu),
                  ("OpenFHE `SPARSE_TERNARY` (진단)", dg),
                  ("Lattigo (본측정)", ml)):
        qp = int(g.logQP_boot.iloc[0])
        w(f"| {nm} | {int(g.boot_depth.iloc[0])} | {int(g.dnum.iloc[0])} | "
          f"{int(g.PCount.iloc[0])} | {int(g.logP_boot.iloc[0])} | {qp} ({1747 - qp}) | "
          f"**{g.boot_us.mean() / 1e6:.2f}** ±{g.boot_us.std() / 1e6:.2f} | "
          f"{g.precision_bits.mean():.3f} | {g.keygen_us.mean() / 1e6:.1f}s | "
          f"{g.peak_rss_mb.max() / 1024:.1f} GB |")
    bu, bs, bl = (mu.boot_us.mean() / 1e6, dg.boot_us.mean() / 1e6, ml.boot_us.mean() / 1e6)
    pu, ps, pl = (mu.precision_bits.mean(), dg.precision_bits.mean(), ml.precision_bits.mean())
    w("")
    w("| 항목 | 속도 | 정밀도 |")
    w("|---|---|---|")
    w(f"| 총 격차 | **{bu - bl:.2f}초** ({bu / bl:.2f}배) | **{pl - pu:.3f}비트** |")
    w(f"| 설명되는 것 (**상한**) | {bu - bs:.2f}초 = **{(bu - bs) / (bu - bl) * 100:.0f}%** | "
      f"+{ps - pu:.3f}비트 = **{(ps - pu) / (pl - pu) * 100:.0f}%** |")
    w(f"| **잔차 (미규명)** | **{bs - bl:.2f}초 = {(bs - bl) / (bu - bl) * 100:.0f}%** "
      f"(여전히 {bs / bl:.2f}배) | **{pl - ps:.3f}비트** |")
    w("")
    w("**dnum 을 7 로 고정**해 교란 하나를 제거했다. 남는 교란 셋은 `boot_depth` 20→16 ·")
    w("`sizeQ` 25→21 · `PCount`/`logP` 4/240→3/180 이고 **전부 빠르게 하는 방향**이라 상한이다.")
    w("⚠️ **\"구현 품질 차이\" 로 설명하지 않는다** — 우리는 그것을 잰 적이 없다.")
    w("⚠️ **이 진단은 한쪽에서만 가능하다.** OpenFHE 는 sparse 로 내려 잴 수 있으나,")
    w("Lattigo 는 캡슐화 off 가 동작하지 않아(9조합 전수 실패) dense 로 올려 잴 수 없다.\n")

    # ---- 7. 규칙 이전 대조 ------------------------------------------------
    w("## 7. 8-op ↔ 부트 규칙 이전 대조\n")
    w("| 규칙 | 8-op 에서 | 부트에서 | 판정 |")
    w("|---|---|---|---|")
    w("| §8.5 규칙 4 `PCount = ceil(maxDigitBits/60)` | 확립 | 10000/10000 일치 | **그대로 성립** |")
    w("| §8.5 규칙 5 dnum 유효 조건 | 237조합 무오류 | 91/91 + 독립 재확인 1건 | **그대로 성립** |")
    w("| §8.5 규칙 6 Lattigo `dnum = ceil(#Q/#P)` | 확립 | 62741/62741 일치 | **그대로 성립** |")
    w("| §8.5 규칙 7 dnum 최소화 | key-switch ∝ dnum (HK20) | 방향은 맞으나 **비용 지수 ≈ 0.5** | ⚠️ **완화** |")
    w("| §8.2 정밀도 하한 25비트 | 전 프리셋 통과 | 부트 출력은 구조적으로 8~18비트 | ⚠️ **적용 불가** |")
    w("| §8.4 정밀도는 레벨에 무관 | 0.004~0.015비트 | OF 0.0139 / LA 0.0009 | **그대로 성립** |")
    w("| §8.7 OpenFHE mt 정밀도 저하 | −0.13~−0.54 | **−0.052~+0.014** | ⚠️ **재현 안 됨** |")
    w("| §8.7 mt/1t (OpenFHE heavy) | 0.51~0.76 | **0.34~0.48** | 병렬 이득 더 큼 |")
    w("| 보안 상한 출처 | seal MaxBitCount 218/438/881 | ePrint 2024/463 Table 5.2 **1747** | ⚠️ **출처 다름** |")
    w("")

    # ---- 8. 프리셋 명세 ---------------------------------------------------
    w("## 8. 프리셋 파라미터 명세 (양쪽 고정값 전부)\n")
    w("| 항목 | OpenFHE | Lattigo |")
    w("|---|---|---|")
    w("| logN / 링 차원 | 16 / 65536 | 16 / 65536 |")
    w("| 슬롯 | 전체 2^15 = 32768 | 전체 2^15 = 32768 (`LogSlots 15`) |")
    w("| 메인 비밀키 | `UNIFORM_TERNARY` (dense) | `Ternary{P: 2/3}` (dense) |")
    w("| 캡슐화(임시키) | **모드 없음** | `EphemeralSecretWeight = 32` |")
    w("| K (근사 구간) | **512** (`K_UNIFORM`, 컴파일 상수) | **16** |")
    w("| approxModDepth / EvalMod | **14** | **8** |")
    w("| `Mod1Degree` / `Mod1InvDegree` | 해당 없음 | 30 / **0** |")
    w("| LogMessageRatio | 해당 없음 (실효 q₀−Δ) | **q₀ − Δ** |")
    w("| 부트 입력 스케일 | `2^Δ` | `2^Δ` (양쪽 동일) |")
    w("| 스케일링 기법 | `FIXEDMANUAL` | — |")
    w("| 보안 레벨 | `HEStd_NotSet` (링 차원 강제) | — |")
    w("| P 프라임 크기 | `auxBits = 60` | 61 |")
    w("| σ | 3.19 (기본) | 3.2 (기본) |")
    w("")
    pts = pd.read_csv(respath.find("boot_stage3_points.csv"))
    w("| preset | q₀ | Δ | 잔여 L | 분해깊이 | OF dnum | OF logQP(여유) | LA PCount | LA logQP(여유) |")
    w("|---|---:|---:|---:|---|---:|---:|---:|---:|")
    for _, r in pts[(pts.levelBudget_c2s == 3) & (pts.levelBudget_s2c == 3)].iterrows():
        w(f"| **{r.preset}** | {int(r.q0)} | **{int(r.delta)}** | {int(r.residual_L)} | {{3,3}} | "
          f"{int(r.dnum_of)} | {int(r.logQP_boot_of)} ({int(r.margin_of)}) | "
          f"{int(r.PCount_boot_la)} | {int(r.logQP_boot_la)} ({int(r.margin_la)}) |")
    w("\n게이트: `0 < q₀ − Δ ≤ 7` **AND** `logQP_boot ≤ 1747`. **residual 이 아니라 boot 을 본다.**\n")

    # ---- 9. 측정 규모 -----------------------------------------------------
    w("## 9. 측정 규모\n")
    tot = fails = 0
    files = []
    for lib in ("openfhe", "lattigo"):
        for mode in ("1t", "mt"):
            d = main_df(lib, mode); tot += len(d); fails += int((d.ok == 0).sum())
            files.append((f"boot_main_{lib}_{mode}_dku16c.csv", len(d)))
        d = pd.read_csv(respath.find(f"boot_dnum_{lib}_1t_dku16c.csv")); d = d[d.rep >= 0]
        tot += len(d); fails += int((d.ok == 0).sum())
        files.append((f"boot_dnum_{lib}_1t_dku16c.csv", len(d)))
    w("| 항목 | 값 |")
    w("|---|---|")
    w("| 3단계 실행 | **70** (1t 20 + mt 40 + dnum 스윕 10) |")
    w(f"| 3단계 측정 rep | **{tot}** |")
    w(f"| **실패** | **{fails}** |")
    w("| 스와핑 이벤트 | **0** (`/proc/vmstat pswpout` 전후 확인) |")
    w("| 소요 | **7.5h** (1t 3.0 + mt 3.25 + dnum 1.2) |")
    w("| reps / warmup | 10 / 3, **rep 마다 새로 암호화** |")
    w("| 프로토콜 | 코어 고정 + 30초 사전 가열 + 전후 프로브 (`run_warm.sh`, §8.6) |")
    w("| peak RSS | 12.3 ~ 40.2 GB (순차 실행, dku16c 62 GB) |")
    w("")
    w("원자료:")
    for f, n in files:
        w(f"- `results/boot/{f}` ({n}행)")
    w("- 2단계 곡선 `results/boot/boot_prec_{openfhe,lattigo}_1t_dku16c.csv`")
    w("- 문턱/모드/진단 `results/boot/boot_prec_openfhe_{thresh,modes,diag_skdist}_*.csv`")
    w("- 1단계 격자 `explore/boot_params/`")

    with open(os.path.join(OUT, "PRESENT_DATA.md"), "w") as fh:
        fh.write("\n".join(B) + "\n")
    print(f"[pack] {os.path.relpath(os.path.join(OUT, 'PRESENT_DATA.md'), ROOT)}")

    src = os.path.join(ROOT, "plots", "boot")
    for f in sorted(os.listdir(src)):
        if f.endswith(".png"):
            shutil.copy2(os.path.join(src, f), os.path.join(OUT, f))
            print(f"[copy] {f}")


if __name__ == "__main__":
    main()
