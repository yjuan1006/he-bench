#!/usr/bin/env python3
"""HEXL 아암(8-op 확장)의 정밀도를 하나의 요약 CSV 로 합친다.

출력: explore/hexl8_summary_precision.csv
  preset,logN,depth,delta,mode,library,dnum,PCount,logP,level,rep,enc_dec,rot1,ks_loss

**`v3_summary_precision.csv` 와 같은 스키마**다(컬럼·순서·의미 동일). 산출 로직도
`v3_unify.py` 의 정밀도 절반을 그대로 미러링한다 — 두 파일을 나란히 놓고 baseline↔HEXL 을
같은 방식으로 대조하기 위함이다.

⚠️ **baseline 과 한 파일에 섞지 않는다.** 빌드 옵션이 다른 조건이므로
   `v3_summary_precision.csv` 에 병합하면 §2 의 "HEXL 은 파일명으로 분리" 방침이 깨진다.
   타이밍 쪽도 같은 이유로 `hexl8_summary_timing.csv` 가 따로 있다(`v3_hexl8_plots.py`).

⚠️ **Lattigo 행이 없다.** Lattigo 에는 HEXL 대응물이 없어 아예 측정하지 않았다.
   비워 두는 것이 맞고, baseline Lattigo 값을 끌어와 채우면 그것이 곧 혼입이다.
   (타이밍 요약 `hexl8_summary_timing.csv` 는 플롯용이라 Lattigo 를 baseline 값으로
   함께 싣지만, 이 파일은 성격이 달라 그렇게 하지 않는다.)

⚠️ **프리셋 A 뿐이다.** HEXL 아암 자체가 A 만 측정됐다(`PROJECT_CONTEXT.md §9.6-3`).
   그래서 preset 열은 전부 'A' 지만, v3 쪽과 스키마를 맞추려고 열은 유지한다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402  (경로 해석 — scripts/respath.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "explore")

PRESET = "A"
P = "results_v3n15d42L12"

# (mode, library) → (정밀도 CSV, 메타 참조용 타이밍 CSV)
# mt 타이밍은 런이 여러 개라 run1 을 메타 출처로 쓴다 — logN/depth/delta 는 런마다 같다.
SOURCES = [
    ("1t", "openfhe", f"{P}_hexl8_precision_1t_dku16c.csv",
     f"{P}_hexl8_timing_1t_dku16c.csv"),
    ("1t", "seal", f"{P}_hexl8_precision_1t_seal_dku16c.csv",
     f"{P}_hexl8_timing_1t_seal_dku16c.csv"),
    ("mt", "openfhe", f"{P}_hexl8_precision_mt_dku16c.csv",
     f"{P}_hexl8_timing_mt_run1_dku16c.csv"),
    ("mt", "seal", f"{P}_hexl8_precision_mt_seal_dku16c.csv",
     f"{P}_hexl8_timing_mt_seal_run1_dku16c.csv"),
]

COLS = ["preset", "logN", "depth", "delta", "mode", "library",
        "dnum", "PCount", "logP", "level", "rep", "enc_dec", "rot1", "ks_loss"]


def main():
    frames = []
    for mode, lib, pname, tname in SOURCES:
        p = pd.read_csv(respath.find(pname))

        # 한 파일에 한 라이브러리만 들어 있어야 한다. 섞여 있으면 아래 메타 조인이
        # 조용히 엉뚱한 값을 붙이므로 여기서 막는다.
        libs = set(p["library"].unique())
        if libs != {lib}:
            sys.exit(f"[혼입] {pname}: library 가 {sorted(libs)} — {lib} 하나여야 한다.")

        # v3_unify.py 와 동일한 피벗: path(enc_dec/rot1)를 열로 펴고 KS 손실을
        # **같은 rep 끼리 짝지어** 뺀다. 평균끼리 빼면 반복 간 상관이 사라진다.
        pv = p.pivot_table(index=["library", "dnum", "PCount", "logP", "level", "rep"],
                           columns="path", values="bits").reset_index()
        pv["ks_loss"] = pv["enc_dec"] - pv["rot1"]

        # 메타(logN/depth/delta)는 v3_unify.py 와 같이 **타이밍 CSV 에서** 가져온다.
        t = pd.read_csv(respath.find(tname))
        t = t[t.ok == 1]
        meta = t.groupby("library").first()[["logN", "depth", "delta"]]
        pv = pv.join(meta, on="library")

        # 정밀도 CSV 자신도 logN/depth/delta 를 들고 있다 — 두 출처가 어긋나면
        # 짝이 안 맞는 파일을 붙인 것이므로 중단한다(조용한 오염 방지).
        own = p.groupby("library").first()[["logN", "depth", "delta"]]
        if not own.loc[lib].equals(meta.loc[lib]):
            sys.exit(f"[불일치] {pname} 과 {tname} 의 (logN, depth, delta) 가 다르다:\n"
                     f"  정밀도 {dict(own.loc[lib])}\n  타이밍 {dict(meta.loc[lib])}")

        pv["preset"], pv["mode"] = PRESET, mode
        frames.append(pv[COLS])

    d = pd.concat(frames, ignore_index=True)
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, "hexl8_summary_precision.csv")
    d.to_csv(f, index=False)
    print(f"[precision] {os.path.relpath(f, ROOT)}  ({len(d)}행)")

    print("\n=== 구성 확인 ===")
    print(f"{'preset':7}{'mode':5}{'lib':9}{'행':>5}{'레벨':>5}{'rep':>5}  "
          f"{'enc_dec 최소':>12}{'rot1 최소':>10}{'KS손실 중앙':>12}")
    for (md, lib), g in d.groupby(["mode", "library"], sort=False):
        print(f"{PRESET:7}{md:5}{lib:9}{len(g):>5}{g.level.nunique():>5}"
              f"{g.rep.nunique():>5}  {g.enc_dec.min():>12.3f}{g.rot1.min():>10.3f}"
              f"{g.ks_loss.median():>12.3f}")
    print("\n※ Lattigo 행 없음 — HEXL 대응물이 없어 미측정이다(baseline 값으로 채우지 않는다).")
    print("※ 정밀도 하한 판정은 평균이 아니라 **rot1 최소값 ≥ 25비트**다(PROJECT_CONTEXT §8.2).")


if __name__ == "__main__":
    main()
