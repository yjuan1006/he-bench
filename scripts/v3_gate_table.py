#!/usr/bin/env python3
"""본측정 physics_gate + 표 + 분석.  사용법: v3_gate_table.py <preset-id>

⚠️ aggregate.py 에 넣을 수 없다 — 스키마에 P 메타데이터 열이 붙고 preset 어휘도
v1의 {small,medium,large}가 아니다. aggregate.py 의 preset 게이트가 거부하는 것은
**의도된 동작**(v1/v2/v3 혼입 방지)이므로 우회하지 않고 게이트를 여기에 옮겨 왔다.
임계값 근거는 aggregate.py 상단 주석 그대로.

  G1 std_us == 0 and reps > 1  → 측정값이 아니라 파생값·일괄계측의 흔적
  G2 relin / mul_cc_rlk > 1.02 → relin 단독이 '곱셈+relin'보다 비쌀 수 없다 (1t)
  G3 v[L] / v[L+1] > 1.02 이고 차가 2σ 밖 → 1t 레벨 단조성 위반

★ G3(단조성)는 **heavy op 한정**으로 적용한다.
  Lattigo 경량 op(add_cc/add_cp/mul_cp)는 Go GC 때문에 이 프로토콜에서 안정적으로
  측정되지 않는다 — v2 1차/2차 대조에서 위반 레벨의 교집합이 비었고(범프가 옮겨다님)
  두 실행 차이가 중앙 5.4% / 최대 38.6%였다(heavy 는 중앙 0.6% / 최대 4.4%).
  경량 op 위반은 참고로만 출력하고 판정에 쓰지 않는다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 프리셋 식별자를 인자로 받는다. A/B/C 를 같은 게이트·같은 표로 본다.
#   A: v3n15d42L12   (logN15 Δ42 depth12)
#   B: v3Bn14d42L6   (logN14 Δ42 depth6  — A와 Δ 동일, 링 차원만 다름)
#   C: v3Cn15d48L10  (logN15 Δ48 depth10 — A와 같은 N, 깊이 2단계 차이. ⚠️ Δ가 42→48로 함께 바뀐다)
PRESET = sys.argv[1] if len(sys.argv) > 1 else "v3n15d42L12"
GATE_BITS = 25.0
LIB_ORDER = {"openfhe": 0, "lattigo": 1, "seal": 2}
OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"]
# 단조성 판정 대상 = GC 영향을 받지 않는 op. **경계는 실측으로 정했다.**
#
# v2·v3 각각 Lattigo 를 동일 조건으로 두 번 돌려 op별 |2차/1차−1| 을 잰 결과
# 두 군이 깨끗하게 갈렸다(중간값 없음):
#            v2 최대   v3 최대   규모(μs)
#   mul_cc    0.386    0.227    0.4~3.4k   ← GC 영향
#   mul_cp    0.386    0.223    0.2~1.5k   ← GC 영향
#   add_cc    0.371    0.191    0.1~0.7k   ← GC 영향
#   add_cp    0.370    0.135    0.1~0.5k   ← GC 영향
#   rescale   0.044    0.043    1.4~9.5k     안정
#   rot1      0.016    0.042     10~52k      안정
#   mul_cc_rlk0.044    0.041     10~58k      안정
#   relin     0.013    0.038     10~52k      안정
#
# ⚠️ mul_cc 는 규모·편차 모두 경량 op 대역이라 **GC 영향군**이다. 판정에서 뺀다.
#    v3 1차는 mul_cc L6·L11 에서, 2차는 L8 에서 위반이 났고 교집합이 비었다.
#    mul_cc 를 뺀 집합에서는 1차·2차 모두 위반 0건이다.
#    (rescale 은 규모가 겹치는데도 안정군이다 — 단순 규모 기준이 아니다.)
HEAVY_OPS = ["mul_cc_rlk", "relin", "rescale", "rot1"]
LIGHT_OPS = ["add_cc", "add_cp", "mul_cp", "mul_cc"]
FUSE_TOL = 1.02
MONO_TOL = 1.02
DRIFT = 0.02


def physics_gate(df, mono_ops):
    viol, info = [], []
    for _, r in df[(df.std_us == 0) & (df.reps > 1)].iterrows():
        viol.append(f"[std=0] {r.library} L{int(r.level)} {r.op} (reps={int(r.reps)})")
    pm = df.pivot_table(index=["library", "level"], columns="op", values="mean_us")
    if {"relin", "mul_cc_rlk"} <= set(pm.columns):
        for idx in pm.index:
            rel, rlk = pm.loc[idx, "relin"], pm.loc[idx, "mul_cc_rlk"]
            if pd.notna(rel) and pd.notna(rlk) and rlk > 0 and rel / rlk > FUSE_TOL:
                viol.append(f"[relin>mul_cc_rlk] {idx} — {rel:.1f}/{rlk:.1f} = {rel/rlk:.4f}")
    for (lib, op), g in df.groupby(["library", "op"]):
        g = g.sort_values("level")
        v, sd, lv = g.mean_us.tolist(), g.std_us.tolist(), g.level.tolist()
        for i in range(len(v) - 1):
            if v[i] > v[i + 1] * MONO_TOL and (v[i] - v[i + 1]) > 2 * (sd[i] + sd[i + 1]):
                msg = f"[단조성] {lib} {op} L{int(lv[i])}({v[i]:.1f}) > L{int(lv[i+1])}({v[i+1]:.1f})"
                (viol if op in mono_ops else info).append(msg)
    print(f"[physics] {'✓ 게이트 통과' if not viol else f'✗ 위반 {len(viol)}건'} "
          f"({len(df)}행, 1t · 단조성은 {','.join(mono_ops)} 한정)")
    for x in viol:
        print("   " + x)
    if info:
        print(f"  (참고) 경량 op 단조성 이탈 {len(info)}건 — 판정에 쓰지 않는다:")
        for x in info:
            print("     " + x)
    return not viol


def crossings(num, den, scale=1.0):
    xs = sorted(num)
    r = [num[l] * scale / den[l] for l in xs]
    return [xs[i] + (1 - r[i]) / (r[i + 1] - r[i])
            for i in range(len(r) - 1) if (r[i] - 1) * (r[i + 1] - 1) < 0], r


def main():
    t = pd.read_csv(respath.find(f"results_{PRESET}_timing_1t_dku16c.csv"))
    if len(t[t.ok != 1]):
        print(f"※ 컨텍스트 생성 실패 {len(t[t.ok != 1])}건")
    t = t[t.ok == 1].copy()
    p = pd.read_csv(respath.find(f"results_{PRESET}_precision_1t_dku16c.csv"))

    print("=== 구성 (런타임 API 추출) ===")
    cfg = t.groupby("library").first()[["dnum", "PCount", "logP", "logQ", "logQP",
                                        "bound", "margin", "digits"]]
    for lib in sorted(cfg.index, key=lambda x: LIB_ORDER[x]):
        r = cfg.loc[lib]
        print(f"  {lib:8} dnum={int(r.dnum):>2} PCount={int(r.PCount)} logP={int(r.logP):>3} "
              f"logQ={int(r.logQ)} logQP={int(r.logQP)} 상한={int(r.bound)} 여유={int(r.margin):>3}")
        print(f"           digit: {r.digits.replace(';', ',')}")

    print()
    ok = physics_gate(t, HEAVY_OPS)

    print("\n=== op × level (mean_us, 1t) ===")
    for op in OPS:
        piv = t[t.op == op].pivot_table(index="level", columns="library", values="mean_us")
        piv = piv[[c for c in ["openfhe", "lattigo", "seal"] if c in piv.columns]]
        tag = "  ⚠️ Lattigo 값은 GC 노이즈로 신뢰 불가" if op in LIGHT_OPS else ""
        print(f"\n-- {op} --{tag}")
        print(f"{'L':>3} " + "".join(f"{c:>12}" for c in piv.columns) + "   최속")
        for L in sorted(piv.index, reverse=True):
            row = piv.loc[L]
            print(f"{int(L):>3} " + "".join(f"{row[c]:>12.1f}" for c in piv.columns)
                  + f"   {row.idxmin()}")

    print("\n=== 교차점 (v1 crossing_points 방식, ±2% 감도) ===")
    print(f"{'쌍':22}{'op':11}{'교차':>7}{'−2%':>7}{'+2%':>7}{'횟수':>5}   L1비/Lmax비   판정")
    for a, b in [("seal", "openfhe"), ("seal", "lattigo"), ("openfhe", "lattigo")]:
        for op in OPS:
            if op in LIGHT_OPS and "lattigo" in (a, b):
                continue
            A = dict(zip(t[(t.library == a) & (t.op == op)].level,
                         t[(t.library == a) & (t.op == op)].mean_us))
            B = dict(zip(t[(t.library == b) & (t.op == op)].level,
                         t[(t.library == b) & (t.op == op)].mean_us))
            c, r = crossings(A, B)
            lo, _ = crossings(A, B, 1 - DRIFT)
            hi, _ = crossings(A, B, 1 + DRIFT)
            f = lambda v: f"{v[0]:.2f}" if v else "없음"
            if bool(c) != bool(lo) or bool(c) != bool(hi):
                verdict = "±2% 안에서 갈림 → 판정 보류"
            elif c:
                verdict = "역전 있음"
            else:
                verdict = f"전 구간 {a if r[0] > 1 else b} 느림"
            print(f"{a+'/'+b:22}{op:11}{f(c):>7}{f(lo):>7}{f(hi):>7}{len(c):>5}   "
                  f"{r[0]:.3f} / {r[-1]:.3f}   {verdict}")

    print("\n=== 정밀도 (rot1, 비밀키, 레벨 전수) ===")
    pv = p.pivot_table(index=["library", "level", "rep"], columns="path",
                       values="bits").reset_index()
    pv["loss"] = pv.enc_dec - pv.rot1
    print(f"{'lib':8}{'평균':>8}{'최소':>8}{'최대':>8}{'σ':>7}{'하한미달':>9}{'KS손실':>8}"
          f"{'레벨간 변화폭':>12}")
    for lib in ["openfhe", "lattigo", "seal"]:
        g = pv[pv.library == lib]
        per = g.groupby("level").rot1.mean()
        print(f"{lib:8}{g.rot1.mean():>8.2f}{g.rot1.min():>8.2f}{g.rot1.max():>8.2f}"
              f"{g.rot1.std(ddof=1):>7.3f}{int((g.rot1 < GATE_BITS).sum()):>4}/{len(g):<4}"
              f"{g.loss.mean():>8.2f}{per.max()-per.min():>12.3f}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
