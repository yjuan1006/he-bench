#!/usr/bin/env python3
"""결과 CSV 위치 해석 — 2026-08-08 `results/` 트리 개편 대응.

개편 전에는 측정 CSV 68개가 전부 리포 루트에 평평하게 쌓여 있었고, 스크립트마다
`os.path.join(ROOT, 파일명)` 이 하드코딩돼 있었다. 디렉터리로 나누면서 그 하드코딩을
전수 고쳐야 했는데, **탐색 경로를 여기 한 곳에 모아** 다음 개편에서 같은 일을
반복하지 않도록 한다. 스크립트는 파일명(basename)만 알면 된다.

⚠️ 같은 이름이 두 곳에 있으면 조용히 하나를 고르지 않고 **중단**한다.
   이 저장소는 반쪽 입력·스키마 혼입 같은 '조용한 오염'으로 사고를 낸 이력이 있고
   (`PROJECT_CONTEXT.md §5`), 파일 위치도 같은 성격의 사고원이다.
   예: 새 측정본이 루트에 떨어졌는데 `results/v3/A/` 의 구본이 함께 남아 있는 상태.

⚠️ 이 모듈은 **위치만** 해석한다. 어느 것이 채택본이고 어느 것이 대체본인지는
   각 디렉터리의 `README.md` 가 정본이다(예: `results/hexl/arm` 채택 ↔ `superseded` 대체).
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 탐색 대상. 순서는 우선순위가 아니다 — 중복이면 고르지 않고 중단하므로 의미가 없다.
# 목록 순서는 README 의 구조 표와 맞춰 둔다(사람이 대조하기 쉽게).
SEARCH_DIRS = [
    "",                                    # 리포 루트 — 갓 나온 측정본이 임시로 놓일 수 있다
    "results/v3/A", "results/v3/A/runs",
    "results/v3/B",
    "results/v3/C",
    "results/v3/D",
    "results/hexl/arm", "results/hexl/superseded",
    "results/baseline_mt_runs", "results/baseline_mt_runs/superseded",
    "results/v2_discarded", "results/v2_discarded/runs",
    "archive/v1/results",                   # 구 프리셋(v1) — 읽기 전용
    "explore", "explore/params",
    "explore/boot_params",                  # 부트스트래핑 1단계 격자 덤프 (§10)
    "results/boot",                         # 부트스트래핑 2단계 측정본 (§10.8 후보의 실측)
]


def _is_path(name):
    """구분자가 들어갔으면 호출자가 위치를 명시한 것 — 탐색하지 않고 그대로 존중한다."""
    return os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name)


def _candidates(name):
    """탐색 경로 + CWD 에서 실제로 존재하는 후보를 전부 모은다.

    ⚠️ CWD 를 마지막에 '덧붙이는' 게 아니라 **후보의 하나로 넣는다.** 예전 판은
    `os.path.exists(name)` 로 CWD 를 먼저 확인하고 즉시 반환했는데, 그러면
    리포 루트에서 돌릴 때 루트의 잔여본이 탐색보다 먼저 잡혀 **중복 가드가
    통째로 무력화된다**(2026-08-08 실측 확인). 아래 중복 판정을 반드시 거치게 한다.
    """
    dirs = [os.path.join(ROOT, d) for d in SEARCH_DIRS]
    dirs.append(os.path.abspath(os.curdir))
    out, seen = [], set()
    for d in dirs:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        rp = os.path.realpath(p)        # ROOT 와 CWD 가 같을 때 자기 자신을 중복으로 세지 않는다
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def find(name):
    """파일명 → 경로. 못 찾거나 여러 곳에 있으면 sys.exit 로 중단한다."""
    if _is_path(name):
        if os.path.exists(name):
            return name
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            return p
        sys.exit(f"[respath] {name} 없음 (리포 루트 기준으로도 해석: {p})")

    hits = _candidates(name)
    if not hits:
        sys.exit(f"[respath] '{name}' 을 찾을 수 없다.\n"
                 f"  탐색 경로: {', '.join(d or '<루트>' for d in SEARCH_DIRS)}")
    if len(hits) > 1:
        rel = "\n  ".join(os.path.relpath(h, ROOT) for h in hits)
        sys.exit(f"[respath] '{name}' 이 여러 곳에 있다 — 어느 쪽이 맞는지 스크립트가 "
                 f"임의로 고르지 않는다. 하나만 남길 것:\n  {rel}")
    return hits[0]


def exists(name):
    """find() 와 같은 규칙으로 찾되, 없으면 중단하지 않고 False.

    ⚠️ 중복은 '있음'으로 본다 — 존재 여부 판정에서 중단하지 않고, 실제로 읽는
    find() 에서 걸리게 한다(가드 메시지를 한 곳에서만 낸다).
    """
    if _is_path(name):
        return os.path.exists(name) or os.path.exists(os.path.join(ROOT, name))
    return bool(_candidates(name))


def avail(pattern):
    """가드 메시지용: 탐색 경로 전체에서 패턴에 맞는 파일을 리포 상대경로로 반환."""
    found = []
    for d in SEARCH_DIRS:
        found += glob.glob(os.path.join(ROOT, d, pattern))
    return sorted({os.path.relpath(p, ROOT) for p in found})
