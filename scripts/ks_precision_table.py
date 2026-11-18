#!/usr/bin/env python3
"""params_ks_precision.csv → 요약표. 새 프리셋 후보의 Δ·dnum 스윕 범위 결정용.

입력은 ksprec_{openfhe,lattigo,seal} 의 원시 출력(반복별 1행)을 이어붙인 것이다.
지표는 전부 -log2(전 슬롯 평균|err|), maxLevel·비밀키 암호화·rot1 경로 기준.

KS 손실 = enc_dec − rot1 을 **같은 rep끼리 짝지어** 계산한다.
평균끼리 빼면 반복 간 상관이 사라져 표준오차가 과대평가된다 — OpenFHE rot1은
반복 산포가 크므로(σ 0.26~1.06) 이 차이가 실제로 결론을 바꾼다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_ORDER = {"openfhe": 0, "lattigo": 1, "seal": 2}


def main(path):
    d = pd.read_csv(path if os.path.exists(path) else os.path.join(ROOT, path))
    key = ["library", "delta", "dnum", "PCount", "logP", "maxDigitBits"]
    piv = d.pivot_table(index=key + ["rep"], columns="path", values="bits").reset_index()
    missing = [c for c in ("enc_dec", "rot1") if c not in piv.columns]
    if missing:
        sys.exit(f"[schema] {path}: path 컬럼에 {missing} 없음 — rot1 경로 측정본이 아니다.")
    piv["loss"] = piv["enc_dec"] - piv["rot1"]

    g = piv.groupby(key).agg(
        enc_dec=("enc_dec", "mean"), sd_enc=("enc_dec", "std"),
        rot1=("rot1", "mean"), sd_rot=("rot1", "std"),
        loss=("loss", "mean"), sd_loss=("loss", "std"), n=("loss", "size"),
    ).reset_index()
    g["se_loss"] = g.sd_loss / np.sqrt(g.n)
    g["digit_P"] = g.maxDigitBits - g.logP
    g = g.sort_values(["library", "delta", "dnum"],
                      key=lambda c: c.map(LIB_ORDER) if c.name == "library" else c)

    hdr = (f"{'lib':8} {'Δ':>3} {'dnum':>4} {'logP':>5} {'maxDig':>6} {'dig−P':>6} "
           f"{'enc_dec':>8} {'rot1':>8} {'KS손실':>7} {'±SE':>6} | {'σ(enc)':>7} {'σ(rot1)':>8}")
    print(hdr)
    print("-" * len(hdr))
    prev = None
    for _, r in g.iterrows():
        if prev is not None and (r.library, r.delta) != prev:
            print()
        prev = (r.library, r.delta)
        print(f"{r.library:8} {int(r.delta):>3} {int(r.dnum):>4} {int(r.logP):>5} "
              f"{int(r.maxDigitBits):>6} {int(r.digit_P):>+6} {r.enc_dec:>8.2f} {r.rot1:>8.2f} "
              f"{r.loss:>7.2f} {r.se_loss:>6.2f} | {r.sd_enc:>7.3f} {r.sd_rot:>8.3f}")
    print(f"\n※ n={int(g.n.iloc[0])}회. OpenFHE rot1은 반복 산포가 커(σ 최대 {g[g.library=='openfhe'].sd_rot.max():.2f}) "
          f"손실 차이 ~0.5비트 이하는 이 표본수로 분해되지 않는다.")


if __name__ == "__main__":
    # 파일명만 줘도 respath 가 explore/params/ 아래에서 찾는다(2026-08-08 개편).
    main(respath.find(sys.argv[1] if len(sys.argv) > 1 else "params_ks_precision.csv"))
