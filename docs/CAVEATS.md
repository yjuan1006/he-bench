# CAVEATS — 프로젝트 전역 해석 규칙

수치 자체는 각 결과 문서(`analysis/out/*.md`, `docs/PROJECT_CONTEXT.md` 각 절, `docs/paper/`)가
정본이다. 여기 있는 것은 **그 수치를 어떻게 읽으면 안 되는가**다. 발표·논문 작성 시 이 문서를
먼저 확인할 것.

---

## 1. leveldrop(순수 레벨 강하, §11) — 2026-08-23

⚠️ `analysis/out/`에는 ip 통일(2026-08-23) 이전 산출물이 섞여 있다. leveldrop 수치를 인용할
때는 반드시 `drop_verification_*.csv`(ip 기준)를 쓰고, `table_numbers.md`·`table5_leveldrop.csv`를
인용하지 마라. 상세는 `analysis/out/STALE_NOTICE.md`.

근거: `docs/PROJECT_CONTEXT.md` §11, `analysis/out/drop_verification_report.md`,
`docs/paper/leveldrop_protocol_note.md`.

### 1.1 Lattigo drop 점추정값 인용 금지

`leveldrop_ip` 실측값이 **23~121ns**로 Go 시계 호출 오버헤드(86ns)와 같은 자릿수다. 동일조건
재실행 2회 대조(A~D)에서 32쌍 중 16쌍이 재실행 간 5% 문턱을 초과했다(중앙값 5.0%, 최대 35.2%).

❌ "Lattigo의 레벨 강하는 0.081μs이다" (또는 임의의 특정 ns/μs 값)
✅ **"Lattigo의 레벨 강하 비용은 10¹~10² ns 대역이며, Go 시계 분해능과 같은 자릿수라 점추정치는
재현되지 않는다. 다만 이 대역의 하이퍼보수적 상한(1μs)을 가정해도 계단 이득 대비 무시 가능하다는
결론은 바뀌지 않는다(2000배 이상 여유)."**

### 1.2 SEAL ip/oop 역전을 라이브러리 우열로 읽기 금지

SEAL만 제자리(ip) 강하가 새 암호문 반환(oop)보다 최대 4.3배 비싸다 — OpenFHE·Lattigo는 반대
방향(ip가 최대 1000~24000배 싸다).

❌ "SEAL의 레벨 강하가 다른 두 라이브러리보다 본질적으로 느리다/SEAL이 열등하다"
✅ **"SEAL은 `mod_switch_to_next_inplace`(임시버퍼+2회복사)와 `mod_switch_to_next`(남길 성분만
직접복사)의 구조가 달라 ip/oop 비용 방향이 반대다. 이는 API 경로 선택의 결과이지 라이브러리
우열이 아니다 — SEAL도 oop 경로를 쓰면 OpenFHE와 비슷한 자릿수이고, 그조차 계단 이득 대비
무시 가능하다."**

### 1.3 8-op 표와 leveldrop 표의 값·σ 나란히 비교 금지

8-op은 "연산 1회 단발 계측 × reps 30"이고 `leveldrop_ip`는 파괴적 연산이라 "K회 일괄 실행의
상각값(÷K)"이다 — 측정하는 양 자체가 다르다. `rep_mode=batch` 행의 `std_us`는 K개 평균의 rep간
산포라 단발 계측 std와 의미가 다르다(약 1/√K로 작게 보임).

❌ 8-op의 `rescale` std_us와 leveldrop의 `leveldrop_ip` std_us를 같은 표·같은 축에 놓고
   "이쪽이 더 안정적이다"라고 비교
✅ **"두 측정은 단발 계측과 상각 계측으로 프로토콜이 다르다. σ를 직접 비교하지 않고, 자릿수
(order-of-magnitude) 비교만 사용한다 — 이 정도 격차(최소 1자릿수, 대개 3~5자릿수)에서는
프로토콜 차이가 결론에 영향을 주지 못한다(`leveldrop_protocol_note.md` §5 수치 논증)."**

---

## 2. 8-op 본측정 (v3 A~D)

*(TODO — 아직 채우지 않음. 필요 시 추가.)*

## 3. 부트스트래핑

*(TODO — 아직 채우지 않음. `explore/boot_present/CAVEATS.md`에 부트 발표용 임시본이 있으나
이 문서로 정식 이관 전이다.)*
