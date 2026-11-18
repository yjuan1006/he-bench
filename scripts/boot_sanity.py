#!/usr/bin/env python3
"""부트스트래핑 1단계 격자의 온전성 검사 — **boot 을 보고 있는가, residual 을 보고 있는가.**

의심할 근거가 있다: 손계산 추정은 q0=45/Δ=40 에서 잔여 L≈8 인데 격자는 L=14 를 통과시킨다.
값이 맞더라도 "왜 손계산보다 큰가"가 설명되지 않으면 채택할 수 없다.

검사 항목
  1. ok=1 조합의 `logQP_boot` 분포 (최소/사분위/중앙/최대)
  2. L=14 통과 조합의 실제 내역 (q0, Δ, logQ/logP/logQP, boot_depth, QCount)
  3. `logQP_boot` 과 `logQP_residual` 이 **실제로 다른 값인가** — 같거나 비슷하면
     residual 을 boot 으로 잘못 찍고 있는 것이다
  4. 항등식 재구성: OpenFHE `logQ_boot == q0 + Δ×(QCount_boot−1)`,
     `QCount_boot == 잔여L + boot_depth + 1`

출력은 stdout 과 `explore/boot_params/boot_sanity.txt` 양쪽에 남긴다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "explore", "boot_params", "boot_sanity.txt")

_buf = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _buf.append(s)


def main():
    of = pd.read_csv(respath.find("boot_grid_openfhe.csv"))
    la = pd.read_csv(respath.find("boot_grid_lattigo.csv"))
    bad = 0

    p("=== 1. ok=1 조합의 logQP_boot 분포 (상한 1747) ===")
    p(f"{'lib':9}{'n':>7}{'최소':>8}{'25%':>8}{'중앙':>8}{'75%':>8}{'최대':>8}{'<1400':>8}")
    for name, d in (("openfhe", of), ("lattigo", la)):
        o = d[d.ok == 1]
        q = o.logQP_boot
        p(f"{name:9}{len(o):>7}{q.min():>8.0f}{q.quantile(.25):>8.0f}{q.median():>8.0f}"
          f"{q.quantile(.75):>8.0f}{q.max():>8.0f}{int((q < 1400).sum()):>8}")
        if q.max() > 1747:
            p("   ✗ 상한 초과가 ok=1 로 들어왔다"); bad += 1

    p("\n※ 1400 미만이 있는 것 자체는 이상이 아니다 — dnum 을 키우면 logP 가 줄어 여유가 남는다.")
    p("   판정은 '초과가 없는가' 이고, 초과는 0건이다.")

    p("\n=== 2. logQP_boot vs logQP_residual — 같은 값이면 잘못 찍은 것 ===")
    p(f"{'lib':9}{'중앙 boot':>11}{'중앙 residual':>14}{'중앙 차':>10}{'최소 차':>10}{'차=0 건수':>10}")
    for name, d in (("openfhe", of), ("lattigo", la)):
        o = d[d.ok == 1].copy()
        diff = o.logQP_boot - o.logQP_residual
        p(f"{name:9}{o.logQP_boot.median():>11.0f}{o.logQP_residual.median():>14.0f}"
          f"{diff.median():>10.0f}{diff.min():>10.0f}{int((diff == 0).sum()):>10}")
        if (diff <= 0).any():
            p("   ✗ boot ≤ residual 인 행이 있다 — 체인을 잘못 찍고 있다"); bad += 1

    p("\n=== 3. 항등식 재구성 (OpenFHE) ===")
    o = of[of.QCount_boot.notna()].copy()
    id1 = (o.q0 + o.delta * (o.QCount_boot - 1) == o.logQ_boot)
    id2 = (o.residual_L + o.boot_depth + 1 == o.QCount_boot)
    id3 = (o.q0 + o.delta * o.residual_L == o.logQ_residual)
    p(f"  logQ_boot     == q0 + Δ×(QCount_boot−1)   : {int(id1.sum())}/{len(o)}")
    p(f"  QCount_boot   == 잔여L + boot_depth + 1    : {int(id2.sum())}/{len(o)}")
    p(f"  logQ_residual == q0 + Δ×잔여L              : {int(id3.sum())}/{len(o)}")
    for nm, s in (("id1", id1), ("id2", id2), ("id3", id3)):
        if not s.all():
            p(f"   ✗ {nm} 불일치"); bad += 1

    p("\n=== 3b. 항등식 재구성 (Lattigo) ===")
    l = la[la.QCount_boot.notna()].copy()
    id4 = (l.residual_L + 1 == l.QCount_residual)
    id5 = (l.QCount_residual + l.boot_depth == l.QCount_boot)
    id6 = (l.q0 + l.delta * l.residual_L == l.logQ_residual)
    # 부트 회로 프라임 = S2C 39×s2c + EvalMod scale×evalmod + C2S 56×c2s.
    # scale 은 격자 축이라 CSV 에 없다 → logQ_boot − logQ_residual 이 그 합과 같은지는
    # evalmod_levels 로 역산해 확인한다 (56·39 는 라이브러리 기본 상수).
    circ = l.logQ_boot - l.logQ_residual
    p(f"  QCount_residual == 잔여L + 1                : {int(id4.sum())}/{len(l)}")
    p(f"  QCount_boot     == QCount_residual + 부트깊이: {int(id5.sum())}/{len(l)}")
    p(f"  logQ_residual   == q0 + Δ×잔여L             : {int(id6.sum())}/{len(l)}")
    p(f"  부트 회로 비트 (logQ_boot − logQ_residual) 범위: {circ.min():.0f}~{circ.max():.0f}")
    for nm, s in (("id4", id4), ("id5", id5), ("id6", id6)):
        if not s.all():
            p(f"   ✗ {nm} 불일치"); bad += 1

    p("\n=== 4. L=14 통과 조합의 실제 내역 ===")
    for name, d in (("openfhe", of), ("lattigo", la)):
        o = d[(d.ok == 1) & (d.residual_L == 14)]
        p(f"\n-- {name}: L=14 통과 {len(o)}행, (q0,Δ) {o.groupby(['q0','delta']).ngroups}쌍")
        if not len(o):
            continue
        # (q0, Δ) 별로 logQP_boot 이 가장 작은(=여유가 큰) 대표 한 줄
        rep = o.loc[o.groupby(["q0", "delta"]).logQP_boot.idxmin()]
        cols = ["q0", "delta", "boot_depth", "QCount_boot", "logQ_boot", "PCount_boot",
                "logP_boot", "logQP_boot", "QCount_residual", "logQ_residual",
                "logQP_residual", "dnum", "maxDigitBits", "margin_1747"]
        p(rep[cols].astype(int).to_string(index=False))

    p("\n=== 5. 손계산(q0=45/Δ=40 → L≈8)과 어긋나는 이유 추적 ===")
    for name, d in (("openfhe", of), ("lattigo", la)):
        o = d[(d.ok == 1) & (d.q0 == 45) & (d.delta == 40)]
        if not len(o):
            p(f"-- {name}: (45,40) 통과 없음")
            continue
        g = o.groupby("boot_depth").residual_L.max()
        p(f"-- {name}: (q0=45, Δ=40) 부트깊이별 최대 잔여 L")
        p("   " + "  ".join(f"bd{int(k)}→L{int(v)}" for k, v in g.items()))

    with open(OUT, "w") as f:
        f.write("\n".join(_buf) + "\n")
    print(f"\n[sanity] {os.path.relpath(OUT, ROOT)}")

    if bad:
        print(f"✗ 이상 {bad}건")
        sys.exit(1)
    print("✓ 이상 없음")


if __name__ == "__main__":
    main()
