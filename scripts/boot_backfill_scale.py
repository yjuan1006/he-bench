#!/usr/bin/env python3
"""1단계 Lattigo 격자 CSV 에 `evalmod_scale` 열을 **역산해 채워 넣는다.** 재실행하지 않는다.

왜 필요한가 (2026-08-12): 지시받은 1단계 스키마에 `evalmod_scale` 열이 없었다. 그런데 그것은
격자 축이라 조합마다 다르다. 2단계 하네스가 그 값을 못 받아 **라이브러리 기본값 60** 으로
돌았고, 격자가 고른 조합(scale 50)과 **logQP 가 130비트 어긋났다**(1704 → 1834, 상한 초과).
같은 사고가 3단계에서 반복되면 안 되므로 열을 채워 둔다.

역산식은 `parameters.go:206-245` 의 `LogQBootstrappingCircuit` 구성 그대로다:

    logQ_boot = q0 + Δ·잔여L + 39·s2c + scale·evalmod_levels + 56·c2s
    → scale = (logQ_boot − q0 − Δ·L − 39·s2c − 56·c2s) / evalmod_levels

⚠️ 39·56 은 `DefaultSlotsToCoeffsLogScale` / `DefaultCoeffsToSlotsLogScale` 이고 격자에서
   그대로 썼다. 값이 정수 50/55/60 으로 떨어지지 않는 행이 하나라도 있으면 **중단**한다 —
   전제가 깨졌다는 뜻이다.
⚠️ 컨텍스트를 만들지 못한 행(`ok=0` 사전 가지치기)은 logQ_boot 이 비어 있어 공란으로 둔다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import respath  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S2C_SCALE, C2S_SCALE = 39, 56          # Lattigo 기본 상수 (격자에서 그대로 사용)
ALLOWED = {50, 55, 60}                 # 격자 축


def main():
    total = 0
    for name in ("boot_grid_lattigo.csv", "boot_grid_lattigo_Lext.csv"):
        path = respath.find(name)
        d = pd.read_csv(path)
        if "evalmod_scale" in d.columns:
            print(f"[건너뜀] {name}: 이미 evalmod_scale 열이 있다")
            continue

        m = d.logQ_boot.notna() & d.evalmod_levels.notna()
        raw = ((d.logQ_boot - (d.q0 + d.delta * d.residual_L
                               + S2C_SCALE * d.levelBudget_s2c
                               + C2S_SCALE * d.levelBudget_c2s))
               / d.evalmod_levels)

        bad = d[m & ((raw % 1 != 0) | ~raw.isin(list(ALLOWED)))]
        if len(bad):
            sys.exit(f"[중단] {name}: 역산이 {sorted(ALLOWED)} 정수로 떨어지지 않는 행 {len(bad)}건\n"
                     + bad[["q0", "delta", "residual_L", "logQ_boot", "evalmod_levels"]]
                     .head(5).to_string(index=False))

        # `evalmod_levels` 바로 뒤에 끼워 넣는다 (읽는 사람이 짝을 찾기 쉽게).
        d["evalmod_scale"] = raw.where(m).astype("Int64")
        cols = list(d.columns)
        cols.remove("evalmod_scale")
        i = cols.index("evalmod_levels") + 1
        d = d[cols[:i] + ["evalmod_scale"] + cols[i:]]

        d.to_csv(path, index=False)
        n = int(m.sum())
        total += n
        vc = d.evalmod_scale.value_counts().sort_index()
        print(f"[채움] {os.path.relpath(path, ROOT)}  {n}행 "
              f"({', '.join(f'{int(k)}:{v}' for k, v in vc.items())})")

    print(f"\n총 {total}행에 evalmod_scale 을 채웠다. **격자를 재실행하지 않았다** — 역산값이다.")


if __name__ == "__main__":
    main()
