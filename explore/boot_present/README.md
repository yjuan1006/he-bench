# explore/boot_present — 부트스트래핑 3단계 발표 자료 팩

**이 폴더만 보면 발표 자료를 만들 수 있다.** pptx 는 별도 세션에서 만든다.
발표 주제는 **"정합된 조건에서 두 라이브러리의 부트 성능 차이"** — **속도가 중심, 정밀도는 보조축**이다.

| 파일 | 무엇인가 |
|---|---|
| `PRESENT_DATA.md` | 발표에 들어갈 **수치 전부**. 10개 절(§6b = 격차 분해) |
| `STORY.md` | 확정된 슬라이드 구성 **14장 + 백업 2장** (제목/내용/그림/한 줄 메시지) |
| `CAVEATS.md` | **해석 오류 6건** — 발표 전 반드시 읽을 것 |
| `QA.md` | 예상 질문 10건과 답 |
| `boot_speed_*.png` | **속도 4장** (발표의 중심, 3부) |
| `boot_delta_precision` · `boot_preset_compare` · `boot_dnum_tradeoff` | 기존 3장 — 3~4부에서 계속 쓴다 |
| `boot_lb_time` · `boot_lb_precision` | 기존 2장 — **백업 슬라이드**. 지우지 않았다 |

플롯 원본은 `plots/boot/`. 재생성: 속도 4장 `scripts/boot_speed_plots.py`,
기존 5장 `scripts/boot_plots.py` (두 스크립트는 서로 건드리지 않는다).
스타일은 **8-op 규약(`scripts/v3_plots.py`)을 그대로 복제**한 것이다 — 같은 세트로 보여야 한다.

⚠️ `PRESENT_DATA.md` 의 수치는 **원자료 CSV 에서 재추출**한 것이다
(`scripts/boot_present_pack.py`). `PROJECT_CONTEXT.md §10` 서술과 어긋나면 **이쪽이 맞다**.
재생성: `.venv/bin/python scripts/boot_present_pack.py`

⚠️ 미규명 항목 전체 목록(11건)은 `docs/PROJECT_CONTEXT.md §10.11.9` 에 있다.
발표에는 **2건만** 넣는다(`STORY.md` S14).

⚠️ **S6("남은 비대칭")을 3부 앞에 두는 것이 구성의 핵심**이다 — 3.30배를 보여주기 전에
"일의 양이 다르다"(EvalMod 14 vs 8)를 먼저 말해야 오해가 생기지 않는다.

원자료 위치: 측정본 `results/boot/`, 1단계 격자 `explore/boot_params/`,
프로브 추적 `traces/boot{,_main,_dnum}/`.
