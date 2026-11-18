#!/usr/bin/env python3
"""사전/사후 캘리브레이션 프로브가 fast 밴드 안에 있었는지 확인한다.

채택/기각 장치가 아니다 — 코어 고정 + 사전 가열이 실제로 먹혔는지 사후 기록용이다.
밴드 근거(dku16c 실측): turbo 82.4~86.8ms / base 137.9~141.3ms. 사이는 비어 있다.
"""
import re
import sys

FAST_MAX = 100.0


def samples(path):
    out = []
    try:
        with open(path) as fh:
            for ln in fh:
                m = re.match(r"\s*([\d.]+) s\s+([\d.]+) ms", ln)
                if m:
                    out.append(float(m.group(2)))
    except FileNotFoundError:
        return None
    return out


def summarize(prefix):
    res = {}
    for side in ("pre", "post"):
        v = samples(f"{prefix}_{side}.txt")
        if not v:
            res[side] = (None, None, "NO_PROBE")
        else:
            # 첫 샘플은 프로브 프로세스 기동 오버헤드가 섞일 수 있어 중앙값을 본다
            v_sorted = sorted(v)
            med = v_sorted[len(v_sorted) // 2]
            res[side] = (med, max(v), "FAST" if max(v) < FAST_MAX else "SLOW")
    return res


if __name__ == "__main__":
    ok_all = True
    for prefix in sys.argv[1:]:
        r = summarize(prefix)
        line = []
        for side in ("pre", "post"):
            med, mx, st = r[side]
            line.append(f"{side}={'--' if med is None else f'{med:.1f}'}ms/{st}")
            if st != "FAST":
                ok_all = False
        print(f"{prefix.split('/')[-1]:32s} " + "  ".join(line))
    sys.exit(0 if ok_all else 1)
