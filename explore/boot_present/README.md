# explore/boot_present — 부트스트래핑 3단계 발표 자료 팩

**이 폴더만 보면 발표 자료를 만들 수 있다.** pptx 는 별도 세션에서 만든다.

| 파일 | 무엇인가 |
|---|---|
| `PRESENT_DATA.md` | 발표에 들어갈 **수치 전부**. 9개 절 |
| `STORY.md` | 확정된 슬라이드 구성 13장 (제목/내용/그림/한 줄 메시지) |
| `CAVEATS.md` | **해석 오류 6건** — 발표 전 반드시 읽을 것 |
| `QA.md` | 예상 질문 10건과 답 |
| `boot_*.png` | 플롯 5장 (원본은 `plots/boot/`) |

⚠️ `PRESENT_DATA.md` 의 수치는 **원자료 CSV 에서 재추출**한 것이다
(`scripts/boot_present_pack.py`). `PROJECT_CONTEXT.md §10` 서술과 어긋나면 **이쪽이 맞다**.
재생성: `.venv/bin/python scripts/boot_present_pack.py`

⚠️ 미규명 항목 전체 목록(10건)은 `docs/PROJECT_CONTEXT.md §10.11.8` 에 있다.
발표에는 **2건만** 넣는다(`STORY.md` S13).

원자료 위치: 측정본 `results/boot/`, 1단계 격자 `explore/boot_params/`,
프로브 추적 `traces/boot{,_main,_dnum}/`.
