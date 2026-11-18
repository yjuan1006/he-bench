#!/usr/bin/env python3
"""부트스트래핑 1단계 격자의 손계산 대조 — §8.5 규칙이 부트 체인에서도 성립하는가.

`PROJECT_CONTEXT.md §10` 의 검증 절 (a)~(d) 를 격자 **전수**에 대해 다시 돌린다.
`boot_dnumrule_openfhe.csv` 는 규칙 5 를 **실패하는 dnum 까지 일부러 시도한** 표본이고,
이 스크립트는 **살아남은 조합 전체**를 본다. 둘은 보완 관계다.

  (a) OpenFHE PCount = ceil(maxDigitBits / auxBits(60)).  ceil(QCount/dnum) 이 아니다 (규칙 4)
  (b) OpenFHE 부트 깊이 = approxModDepth(14) + levelBudget 합 (함정 2)
  (c) Lattigo dnum = ceil(#Q / #P) (규칙 6)
  (d) OpenFHE dnum 유효 조건 (규칙 5) — 별도 표본 CSV 로 확인

불일치가 하나라도 있으면 **0 이 아닌 코드로 끝난다.** 조용히 넘어가지 않는다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

AUXBITS_OF = 60      # OpenFHE NATIVEINT=64 상수 (§8.5 규칙 3)
APPROX_MOD_DEPTH = 14  # UNIFORM_TERNARY: PS깊이 8 + R_UNIFORM 6 (ckksrns-fhe.h:424-431)


def ceil_div(a, b):
    return -(-a // b)


def main():
    bad = 0

    of = pd.read_csv(respath.find("boot_grid_openfhe.csv"))
    ofb = of[of.QCount_boot.notna()].copy()

    # (a) PCount = ceil(maxDigitBits / 60)
    pred = ofb.maxDigitBits.astype(int).map(lambda b: ceil_div(b, AUXBITS_OF))
    miss = ofb[pred != ofb.PCount_boot.astype(int)]
    print(f"(a) OpenFHE PCount = ceil(maxDigitBits/{AUXBITS_OF})  "
          f"→ 대조 {len(ofb)} / 불일치 {len(miss)}")
    if len(miss):
        bad += 1
        print(miss[["q0", "delta", "residual_L", "dnum", "maxDigitBits", "PCount_boot"]].head(10)
              .to_string(index=False))
    # 참고: naive 공식이 왜 안 되는지 같은 표본에서 보여 둔다
    naive = ofb.apply(lambda r: ceil_div(int(r.QCount_boot), int(r.dnum)), axis=1)
    print(f"    (참고) naive ceil(QCount/dnum) 로는 "
          f"{int((naive == ofb.PCount_boot.astype(int)).sum())}/{len(ofb)} 만 맞는다")

    # (b) 부트 깊이 = approxModDepth + levelBudget 합
    predbd = APPROX_MOD_DEPTH + ofb.levelBudget_c2s + ofb.levelBudget_s2c
    miss = ofb[predbd != ofb.boot_depth]
    print(f"(b) OpenFHE 부트 깊이 = {APPROX_MOD_DEPTH} + lb합  "
          f"→ 대조 {len(ofb)} / 불일치 {len(miss)}")
    if len(miss):
        bad += 1
    # evalmod_levels 는 런타임 유도값 — 손계산 14 와 같아야 한다
    em = sorted(ofb.evalmod_levels.dropna().unique().tolist())
    print(f"    런타임 approxModDepth = {em}  (손계산 {APPROX_MOD_DEPTH})")
    if em != [APPROX_MOD_DEPTH]:
        bad += 1

    # (c) Lattigo dnum = ceil(#Q/#P)
    la = pd.read_csv(respath.find("boot_grid_lattigo.csv"))
    lab = la[la.QCount_boot.notna()].copy()
    predd = lab.apply(lambda r: ceil_div(int(r.QCount_boot), int(r.PCount_boot)), axis=1)
    miss = lab[predd != lab.dnum.astype(int)]
    print(f"(c) Lattigo dnum = ceil(#Q/#P)  → 대조 {len(lab)} / 불일치 {len(miss)}")
    if len(miss):
        bad += 1
        print(miss[["q0", "delta", "residual_L", "QCount_boot", "PCount_boot", "dnum"]].head(10)
              .to_string(index=False))

    # (d) OpenFHE dnum 유효 조건 (규칙 5) — 실패까지 시도한 표본 CSV
    dn = pd.read_csv(respath.find("boot_dnumrule_openfhe.csv"))
    miss = dn[dn.predicted_valid != dn.actual_ok]
    print(f"(d) OpenFHE dnum 유효 조건 (§8.5 규칙5)  → 대조 {len(dn)} / 불일치 {len(miss)}")
    if len(miss):
        bad += 1
        print(miss.head(10).to_string(index=False))

    # 온전성: 통과 조합의 logQP_boot 밴드
    for name, d in (("openfhe", of), ("lattigo", la)):
        ok = d[d.ok == 1]
        if not len(ok):
            continue
        lo, hi = int(ok.logQP_boot.min()), int(ok.logQP_boot.max())
        print(f"[온전성] {name} ok=1 의 logQP_boot {lo}~{hi} (상한 1747)")
        if hi > 1747:
            print("   ⚠️ 상한 초과가 ok=1 로 들어왔다 — boot 이 아니라 residual 을 보고 있는지 확인")
            bad += 1

    if bad:
        print(f"\n✗ 불일치 {bad}건 — 멈추고 보고할 것")
        sys.exit(1)
    print("\n✓ (a)~(d) 전부 일치")


if __name__ == "__main__":
    main()
