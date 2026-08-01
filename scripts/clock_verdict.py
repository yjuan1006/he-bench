#!/usr/bin/env python3
"""캘리브레이션 트레이스로 실행의 채택/기각을 판정한다 (절대 상태 판정).

왜 절대 판정인가:
  "상태 변화"만 보면 실행 전체가 느린 상태에 머문 경우를 통과시킨다.
  실측(2026-07-25)에서 small asc 실행 하나가 전 구간 slow였고, 모든 레벨·op가
  균일하게 1.68배 부풀려졌는데 변화가 없어 "안정적"으로 보였다.
  따라서 밴드 자체를 절대 기준으로 못박는다.

밴드 근거 (dku16c, calib 커널 5e7 xorshift 반복):
  fast(전코어 터보 상태) 실측 82.4~86.8 ms
  slow(base 클럭 상태)   실측 137.9~141.3 ms
  두 밴드 사이는 비어 있다 → 경계 100 ms는 어느 쪽에도 가깝지 않은 안전한 분리선.
"""
import re
import sys

FAST_MAX = 100.0   # 이 값 미만이면 fast 밴드. slow 밴드(~138)와 충분히 떨어져 있다.
FAST_MIN = 60.0    # 이보다 빠르면 커널이 바뀐 것 → 트레이스 자체를 의심한다.


def parse(path):
    rows = []
    with open(path) as fh:
        for ln in fh:
            m = re.match(r"\s*([\d.]+) s\s+([\d.]+) ms", ln)
            if m:
                rows.append((float(m.group(1)), float(m.group(2))))
    return rows


def verdict(path, min_coverage_s=0.0):
    rows = parse(path)
    if not rows:
        return False, "NO_TRACE (모니터가 샘플을 남기지 못함)"
    v = [x[1] for x in rows]
    dur = rows[-1][0]
    slow = [x for x in rows if x[1] >= FAST_MAX]
    weird = [x for x in rows if x[1] < FAST_MIN]
    stat = (f"samples={len(v)} window={dur:.0f}s min={min(v):.1f} max={max(v):.1f} "
            f"slow_samples={len(slow)}")
    if weird:
        return False, f"REJECT {stat} — {len(weird)}개 샘플이 {FAST_MIN}ms 미만(비정상)"
    if slow:
        first = slow[0][0]
        return False, f"REJECT {stat} — 첫 slow 샘플 t={first:.1f}s"
    if dur < min_coverage_s:
        return False, f"REJECT {stat} — 커버리지 부족(<{min_coverage_s:.0f}s)"
    return True, f"ACCEPT {stat}"


if __name__ == "__main__":
    cov = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    ok, msg = verdict(sys.argv[1], cov)
    print(msg)
    sys.exit(0 if ok else 1)
