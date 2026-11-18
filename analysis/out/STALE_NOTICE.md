# STALE 표시 — ip 통일(2026-08-23) 이전 leveldrop 관련 산출물

이 문서는 파일을 지우거나 옮기지 않는다. `analysis/out/`에 남아있는 **커밋 대상 밖** 파일 중,
2026-08-23 `leveldrop_ip` 정본 확정 이전에 만들어져 **최신 결론과 수치가 충돌할 수 있는 것**을
표시만 해 둔다. 인용 전에 반드시 이 문서를 먼저 확인할 것 — 정본은 언제나
`drop_verification_*.csv` / `drop_verification_report.md`(`docs/PROJECT_CONTEXT.md` §11 참조).

---

## STALE — 확정 대체됨

### `table5_leveldrop.csv` (2026-08-21 07:44, `fill_table_numbers.py` 산출)

- **왜 stale**: 이 파일의 `drop` 컬럼은 "각 라이브러리의 최저비용 경로"라는 옛 정의를 쓴다 —
  OpenFHE·Lattigo는 `_ip`, **SEAL만 `_oop`**(같은 파일을 만든 `table_numbers.md` §3.1이 이 선택을
  명시적으로 정당화하고 있다 — 아래 참조). 2026-08-23 이후 정본은 **세 라이브러리 전부
  `leveldrop_ip`**로 통일됐다.
- **대체**: `analysis/out/drop_verification_orderofmag.csv` (ip 기준, `drop_verification_report.md` §2).
- **충돌 수치 1개**: `A,seal,12,mul_cc_rlk` 행 — 이 파일의 `drop=362.979μs`(SEAL `_oop` 기준) vs
  정본 `leveldrop_ip=867.368μs`. **2.39배 차이.**

### `table_numbers.md` §3.1 (2026-08-21 07:44, `fill_table_numbers.py` 산출)

- **왜 stale**: §3.1이 정확히 "본문 표 5에 쓸 변종: `leveldrop`(SEAL만 `_oop`)"라고 결론짓고
  그 이유(SEAL 제자리 경로가 임시버퍼+2회복사라 더 비싸다는 것)까지 정확히 짚어냈다 — **이번
  세션이 도달한 기전 설명과 방향은 같지만, 결론(어느 쪽을 정본으로 쓸 것인가)이 반대다.**
  당시는 "라이브러리별 최저비용"을 택했고, 이번엔 "배치 최적화기가 실제 수행하는 것은 제자리
  강하"라는 이유로 **비용이 더 크더라도 ip를 정본으로** 택했다.
- **대체**: `analysis/out/drop_verification_report.md` §1(ip/oop 역전, §1.1).
- **충돌 수치**: 위 `table5_leveldrop.csv`와 동일(362.979 vs 867.368, SEAL·A·L12).
- 문서 전체(표3/4/5+그림1 캡션)가 섞여 있어 §3만 분리해 고치는 것은 이 노트의 범위 밖이다 —
  파일 전체를 stale로 취급한다.

### `leveldrop_variants_appendix.csv` (2026-08-21 07:44, `fill_table_numbers.py` 산출)

- **왜 stale**: `leveldrop`(=옛 혼합 변종)과 `leveldrop_ip`(=순수 ip)를 **같은 파일 안에 별도
  행으로** 담고 있다 — 예: `A,seal,leveldrop,...,us_L1=10.674,us_maxL=362.979` (oop 값) vs
  `A,seal,leveldrop_ip,...,us_L1=43.678,us_maxL=867.368` (ip 값). 두 행이 이름만 보면 어느 쪽이
  "레벨 강하 비용"인지 혼동을 일으킨다 — 지금 정본은 후자(`leveldrop_ip`)뿐이다.
- **대체**: `analysis/out/drop_variant_comparison_presetA_wide.csv` (ip/oop/clone_only/oop−clone
  4열 구조로 재구성, Lattigo는 ip만 사용).
- **충돌 수치 1개**: 위와 동일한 `A,seal` 행(362.979 vs 867.368, 오차 2.39배).

### `leveldrop_vs_8op.csv` (2026-08-19 10:36, `leveldrop_net.py` 산출) — ⚠️ 확정 대체

- **왜 stale**: 이 파일의 `leveldrop` 컬럼도 SEAL만 `_oop`인 옛 혼합 정의다(OpenFHE·Lattigo는
  ip와 값이 같아 눈에 안 띄지만, SEAL은 다르다).
- **대체**: **`analysis/out/drop_verification_orderofmag.csv`(ip 기준)로 확정 대체됐다.**
  가능성이 아니라 확정이다 — 이번 세션이 이 파일을 대체할 목적으로 `drop_verification_
  orderofmag.csv`를 새로 만들었다.
- **충돌 수치 1개**: `A,seal,12` 행 — 이 파일의 `leveldrop=362.979μs` vs 정본
  `drop_ip=867.368μs`(`drop_verification_orderofmag.csv`의 동일 행). **2.39배 차이.**

---

## 판정 보류 — 확인 필요 (stale로 몰지 않음)

### `precision_levels.csv` (2026-08-21 07:44, `fill_table_numbers.py` 산출)

- leveldrop 관련 여부 자체가 불확실하다. 스키마를 확인한 결과 지표가 `enc_dec`/`rot1`/`ks_loss`
  (복호 정밀도·key-switch 손실 비트)로, leveldrop 강하 비용과는 다른 축으로 보인다
  (`fill_table_numbers.py:973` `MET = ["enc_dec", "rot1", "ks_loss"]`, `ks_loss = enc_dec − rot1`
  정의 — `scripts/v3_unify.py:68` 참조). 다만 leveldrop 강하 전후 정밀도 검증
  (`results/leveldrop/*_verify_*.csv`)과 목적이 겹칠 가능성을 완전히 배제하지 못해 **판정을
  보류**한다. leveldrop 인용에는 어차피 쓰지 않으므로(§1 확인 근거는
  `results/leveldrop/*_verify_*.csv`와 `drop_verification_report.md`가 이미 담당) 실무 영향은
  없다.

---

## 사용 규칙

leveldrop 수치를 인용할 때는 **항상 `drop_verification_*.csv`(ip 기준) 또는
`drop_verification_report.md`를 쓴다.** 위 STALE 3건(`table5_leveldrop.csv`,
`table_numbers.md`, `leveldrop_variants_appendix.csv`)과 확정 대체 1건
(`leveldrop_vs_8op.csv`)은 인용하지 않는다. 자세한 사용 규칙은 `docs/CAVEATS.md` 참조.
