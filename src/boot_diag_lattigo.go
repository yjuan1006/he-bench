//go:build ignore

// boot_diag_lattigo.go — Lattigo 부트 복호 실패 규명. **진단 전용, 측정 아니다.**
//
// 증상(2026-08-12): 부트가 완주하고 레벨 전이도 정상인데 복호 결과가 **모듈러스 크기의
// 균등 난수**다(정밀도 −340비트, 자릿수 2^342). 값이 어긋난 게 아니라 복호가 성립하지 않는다.
// 키 불일치는 배제됐다 — `keys.go:91-104`, 잔여/부트 링 차원이 같으면 skN2 는 같은 비밀키를
// 부트 모듈러스 기저로 확장한 것이다.
//
// 세 단계로 좁힌다:
//   A) 부트 없이 암호화→복호가 되는가        → 되면 부트 회로 문제, 안 되면 파라미터/키 문제
//   C) Lattigo 자체 기본 파라미터가 우리 흐름에서 도는가 → 돌면 우리 하네스는 정상
//   B) 입력 스케일을 2^Δ 로 바꾸면 달라지는가  → (가) 채택 근거의 재검토
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"time"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/ring"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

func ip(v int) *int { return &v }

type rng struct{ s uint64 }

func (r *rng) next() uint64 {
	r.s ^= r.s >> 12
	r.s ^= r.s << 25
	r.s ^= r.s >> 27
	return r.s * 2685821657736338717
}
func (r *rng) val() float64 { return float64(r.next()>>11)/9007199254740992.0*2.0 - 1.0 }

func makeInputs(n int) []float64 {
	r := &rng{s: 0x2026072500000001}
	x := make([]float64, n)
	for i := range x {
		x[i] = r.val()
		r.val()
	}
	return x
}

func precBits(got, want []float64) (mean, worst, magRatio float64) {
	s, maxErr, gm, wm := 0.0, 0.0, 0.0, 0.0
	for i := range want {
		e := math.Abs(got[i] - want[i])
		s += e
		maxErr = math.Max(maxErr, e)
		gm = math.Max(gm, math.Abs(got[i]))
		wm = math.Max(wm, math.Abs(want[i]))
	}
	m := s / float64(len(want))
	mean = 999
	if m > 0 {
		mean = -math.Log2(m)
	}
	worst = 999
	if maxErr > 0 {
		worst = -math.Log2(maxErr)
	}
	if wm > 0 {
		magRatio = gm / wm
	}
	return
}

func resLiteral(q0, delta, L, pcRes int) ckks.ParametersLiteral {
	lq := []int{q0}
	for i := 0; i < L; i++ {
		lq = append(lq, delta)
	}
	lp := make([]int, pcRes)
	for i := range lp {
		lp[i] = 61
	}
	return ckks.ParametersLiteral{
		LogN: 16, LogQ: lq, LogP: lp, LogDefaultScale: delta,
		Xs: ring.Ternary{P: 2.0 / 3.0},
	}
}

func ourBtpLiteralEph(pc, c2s, s2c, evalScale, K, eph int, xs ring.DistributionParameters) bootstrapping.ParametersLiteral {
	l := ourBtpLiteral(pc, c2s, s2c, evalScale, K, xs)
	l.EphemeralSecretWeight = ip(eph)
	return l
}

func ourBtpLiteral(pc, c2s, s2c, evalScale, K int, xs ring.DistributionParameters) bootstrapping.ParametersLiteral {
	lp := make([]int, pc)
	for i := range lp {
		lp[i] = 61
	}
	c2sD := make([][]int, c2s)
	for i := range c2sD {
		c2sD[i] = []int{bootstrapping.DefaultCoeffsToSlotsLogScale}
	}
	s2cD := make([][]int, s2c)
	for i := range s2cD {
		s2cD[i] = []int{bootstrapping.DefaultSlotsToCoeffsLogScale}
	}
	return bootstrapping.ParametersLiteral{
		LogN: ip(16), LogSlots: ip(15), LogP: lp, Xs: xs,
		Mod1Degree: ip(2 * (K - 1)),
		CoeffsToSlotsFactorizationDepthAndLogScales: c2sD,
		SlotsToCoeffsFactorizationDepthAndLogScales: s2cD,
		EvalModLogScale:       ip(evalScale),
		EphemeralSecretWeight: ip(0),
		K:                     ip(K),
	}
}

// ---------------------------------------------------------------------------
// A) 부트 없이 암호화 → 복호. keygen 도 setup 도 필요 없다 — 즉시 끝난다.
func runA() {
	fmt.Println("\n=== (A) 부트 없이 암호화→복호 ===")
	fmt.Printf("%-28s%-12s%-12s%-12s%-10s\n", "조건", "정밀도", "최악슬롯", "자릿수비", "판정")
	for _, c := range []struct {
		label            string
		q0, delta, L, sc int
	}{
		{"(60,55,L=6) 스케일 2^Δ=55", 60, 55, 6, 55},
		{"(60,55,L=6) 스케일 2^52", 60, 55, 6, 52},
		{"(60,58,L=4) 스케일 2^Δ=58", 60, 58, 4, 58},
		{"(60,58,L=4) 스케일 2^52", 60, 58, 4, 52},
	} {
		params, err := ckks.NewParametersFromLiteral(resLiteral(c.q0, c.delta, c.L, 4))
		if err != nil {
			fmt.Printf("%-28s 파라미터 실패: %v\n", c.label, err)
			continue
		}
		x := makeInputs(params.MaxSlots())
		ecd := ckks.NewEncoder(params)
		kgen := rlwe.NewKeyGenerator(params)
		sk := kgen.GenSecretKeyNew()
		enc := rlwe.NewEncryptor(params, sk)
		dec := rlwe.NewDecryptor(params, sk)

		pt := ckks.NewPlaintext(params, 0)
		pt.Scale = rlwe.NewScale(math.Exp2(float64(c.sc)))
		if err := ecd.Encode(x, pt); err != nil {
			fmt.Printf("%-28s 인코딩 실패: %v\n", c.label, err)
			continue
		}
		ct, err := enc.EncryptNew(pt)
		if err != nil {
			fmt.Printf("%-28s 암호화 실패: %v\n", c.label, err)
			continue
		}
		got := make([]float64, params.MaxSlots())
		if err := ecd.Decode(dec.DecryptNew(ct), got); err != nil {
			fmt.Printf("%-28s 디코딩 실패: %v\n", c.label, err)
			continue
		}
		p, w, mr := precBits(got, x)
		verdict := "정상"
		if p < 5 || mr < 0.5 || mr > 2 {
			verdict = "✗ 비정상"
		}
		fmt.Printf("%-28s%-12.3f%-12.3f%-12.4f%-10s\n", c.label, p, w, mr, verdict)
	}
}

// ---------------------------------------------------------------------------
// 공통 부트 실행 — 파라미터를 받아 1회 부트하고 결과를 찍는다.
func bootOnce(label string, res ckks.Parameters, btpLit bootstrapping.ParametersLiteral, inScaleLog2 int) {
	fmt.Printf("\n--- %s ---\n", label)
	btp, err := bootstrapping.NewParametersFromLiteral(res, btpLit)
	if err != nil {
		fmt.Printf("  부트 파라미터 실패: %v\n", err)
		return
	}
	bp := btp.BootstrappingParameters
	sumNom := func(m []uint64) int {
		s := 0
		for _, q := range m {
			s += int(math.Round(math.Log2(float64(q))))
		}
		return s
	}
	fmt.Printf("  체인: QCount %d / logQ %d / PCount %d / logP %d / logQP %d / EvalMod %d / K %d / Mod1Degree %d\n",
		bp.QCount(), sumNom(bp.Q()), bp.PCount(), sumNom(bp.P()), sumNom(bp.Q())+sumNom(bp.P()),
		btp.Mod1ParametersLiteral.Depth(), btp.Mod1ParametersLiteral.K, btp.Mod1ParametersLiteral.Mod1Degree)
	fmt.Printf("  Xs %v / EphemeralSecretWeight %d / 잔여 logQ %d, LogDefaultScale %d\n",
		res.Xs(), btp.EphemeralSecretWeight, sumNom(res.Q()), res.LogDefaultScale())

	t := time.Now()
	kgen := rlwe.NewKeyGenerator(res)
	sk := kgen.GenSecretKeyNew()
	evk, _, err := btp.GenEvaluationKeys(sk)
	if err != nil {
		fmt.Printf("  평가키 실패: %v\n", err)
		return
	}
	kg := time.Since(t)

	t = time.Now()
	eval, err := bootstrapping.NewEvaluator(btp, evk)
	if err != nil {
		fmt.Printf("  평가기 실패: %v\n", err)
		return
	}
	su := time.Since(t)

	x := makeInputs(res.MaxSlots())
	ecd := ckks.NewEncoder(res)
	enc := rlwe.NewEncryptor(res, sk)
	dec := rlwe.NewDecryptor(res, sk)
	pt := ckks.NewPlaintext(res, 0)
	if inScaleLog2 > 0 {
		pt.Scale = rlwe.NewScale(math.Exp2(float64(inScaleLog2)))
	}
	if err := ecd.Encode(x, pt); err != nil {
		fmt.Printf("  인코딩 실패: %v\n", err)
		return
	}
	ct, err := enc.EncryptNew(pt)
	if err != nil {
		fmt.Printf("  암호화 실패: %v\n", err)
		return
	}
	fmt.Printf("  입력: 레벨 %d, 스케일 2^%.1f, Q[0]/스케일 = 2^%.1f  (keygen %.0fs, setup %.0fs)\n",
		ct.Level(), math.Log2(ct.Scale.Float64()),
		math.Log2(float64(res.Q()[0]))-math.Log2(ct.Scale.Float64()), kg.Seconds(), su.Seconds())

	t = time.Now()
	ctb, err := eval.Bootstrap(ct)
	bt := time.Since(t)
	if err != nil {
		fmt.Printf("  ✗ 부트 실패: %v\n", err)
		return
	}
	got := make([]float64, res.MaxSlots())
	if err := ecd.Decode(dec.DecryptNew(ctb), got); err != nil {
		fmt.Printf("  디코딩 실패: %v\n", err)
		return
	}
	p, w, mr := precBits(got, x)
	verdict := "정상"
	if p < 5 || mr < 0.5 || mr > 2 {
		verdict = "✗ 비정상"
	}
	fmt.Printf("  출력: 레벨 %d (기대 %d), 스케일 2^%.1f, 부트 %.1fs\n",
		ctb.Level(), eval.OutputLevel(), math.Log2(ctb.Scale.Float64()), bt.Seconds())
	fmt.Printf("  ▶ 정밀도 %.3f비트 / 최악슬롯 %.3f / 자릿수비 %.4g  → %s\n", p, w, mr, verdict)
}

// C) Lattigo 자체 기본 파라미터. **우리 파라미터를 하나도 안 쓴다.**
func runC() {
	fmt.Println("\n=== (C) Lattigo 자체 기본 파라미터 (문서값 정밀도 26.6비트) ===")
	d := bootstrapping.DefaultParametersSparse[0] // N16QP1546H192H32
	res, err := ckks.NewParametersFromLiteral(d.SchemeParams)
	if err != nil {
		fmt.Printf("  잔여 파라미터 실패: %v\n", err)
		return
	}
	bootOnce("N16QP1546H192H32 (sparse H192 + 캡슐화 H32, K 기본 16)", res, d.BootstrappingParams, 0)
}

// B) 입력 스케일 2^Δ vs 2^(q0−8).
func runB() {
	fmt.Println("\n=== (B) 입력 스케일 대조 ===")
	// q0−Δ=5 : 2^Δ 로 넣으면 ScaleDown 이 거부해야 한다
	res1, _ := ckks.NewParametersFromLiteral(resLiteral(60, 55, 6, 4))
	bootOnce("(60,55,L=6) 입력 2^Δ=55  [q0-Δ=5]", res1, ourBtpLiteral(6, 3, 3, 50, 512, res1.Xs()), 55)
	// q0−Δ=7 : 2^Δ 로 넣어도 게이트를 통과한다
	res2, _ := ckks.NewParametersFromLiteral(resLiteral(55, 48, 10, 4))
	bootOnce("(55,48,L=10) 입력 2^Δ=48 [q0-Δ=7]", res2, ourBtpLiteral(4, 3, 3, 50, 512, res2.Xs()), 48)
}

// D) 캡슐화 × K 2×2 — (A)(B)(C) 로 좁힌 뒤 남은 두 축을 가른다.
//    ⚠️ **진단이다.** §10.1 의 "dense + 캡슐화 off" 확정을 바꾸는 것이 아니다.
func runD() {
	fmt.Println("\n=== (D) 캡슐화 × K — 우리 파라미터 (55,48,L=10) ===")
	res, err := ckks.NewParametersFromLiteral(resLiteral(55, 48, 10, 4))
	if err != nil {
		panic(err)
	}
	for _, c := range []struct {
		label   string
		K, eph  int
	}{
		{"캡슐화 32(켬) + K 16   ← Lattigo 표준 dense 구성", 16, 32},
		{"캡슐화 32(켬) + K 512", 512, 32},
		{"캡슐화 0(끔)  + K 16", 16, 0},
	} {
		bootOnce(c.label, res, ourBtpLiteralEph(4, 3, 3, 50, c.K, c.eph, res.Xs()), 0)
	}
	fmt.Println("\n※ 캡슐화 0 + K 512 는 이미 측정됨: 정밀도 −492비트 (쓰레기).")
}

// E) Lattigo 가 **실제로 검증한 dense 설계**를 우리 파라미터에 그대로 적용한다.
//    `default_parameters.go:136-150` N16QP1788H32768H32 (문서 정밀도 24.4비트) 의 네 항목:
//      EphemeralSecretWeight 32 / K 16 / LogMessageRatio 2 / Mod1InvDegree 7
//    입력 스케일은 2^(q0 − LogMessageRatio) — 2^Δ 가 아니다(2배 오차의 원인).
//    두 번째 행이 §10.1 의 운명을 가른다: 캡슐화만 끄면 성립하는가?
func runE() {
	q0, delta, L := 55, 48, 10
	fmt.Printf("\n=== (E) Lattigo 검증된 dense 설계 적용 — (%d,%d,L=%d) ===\n", q0, delta, L)
	res, err := ckks.NewParametersFromLiteral(resLiteral(q0, delta, L, 4))
	if err != nil {
		panic(err)
	}
	for _, c := range []struct {
		label                 string
		eph, K, msgRatio, inv int
	}{
		{"캡슐화 32 + K16 + msgRatio 2 + InvDeg 7", 32, 16, 2, 7},
		{"캡슐화  0 + K16 + msgRatio 2 + InvDeg 7  ← §10.1 판가름", 0, 16, 2, 7},
	} {
		lit := ourBtpLiteral(4, 3, 3, 50, c.K, res.Xs())
		lit.EphemeralSecretWeight = ip(c.eph)
		lit.LogMessageRatio = ip(c.msgRatio)
		lit.Mod1InvDegree = ip(c.inv)
		bootOnce(c.label, res, lit, q0-c.msgRatio)
	}
	fmt.Println("\n※ 1단계 격자는 EvalMod 13 전제였다. 위 EvalMod 값이 다르면 격자 재실행 검토 대상이다.")
}

// F) (라) 사망 판정 전 마지막 확인 + **정합된 조합**.
//    (A) 실측: OpenFHE 는 입력을 재스케일하지 않으므로 실효 message ratio = 2^(q0−Δ) 다
//        (런타임 `q0_minus_scale_log2` 열: (60,55)→5, (60,58)→2). 즉 OpenFHE 의
//        LogMessageRatio 대응값은 **q0 − Δ** 이고, (55,48) 에서는 **7** 이다.
//    → Lattigo 를 msgRatio 7 + 입력 2^Δ 로 두면 `scaleUp` 이 정확히 1 이 되어
//      2배 오차도 없고 **양쪽이 같은 크기의 메시지를 부트한다**.
func runF() {
	q0, delta, L := 55, 48, 10
	fmt.Printf("\n=== (F) 캡슐화 off + K 512 — 정합 조합 탐색 (%d,%d,L=%d) ===\n", q0, delta, L)
	fmt.Printf("    OpenFHE 실효 msgRatio = q0−Δ = %d (입력을 재스케일하지 않음)\n", q0-delta)
	res, err := ckks.NewParametersFromLiteral(resLiteral(q0, delta, L, 4))
	if err != nil {
		panic(err)
	}
	for _, c := range []struct {
		label              string
		msgRatio, inv, eph int
	}{
		{"[남은 칸] 캡슐화0 K512 msgRatio 2 InvDeg 7", 2, 7, 0},
		{"[정합]    캡슐화0 K512 msgRatio 7(=q0−Δ) InvDeg 0", q0 - delta, 0, 0},
		{"[정합]    캡슐화0 K512 msgRatio 7(=q0−Δ) InvDeg 7", q0 - delta, 7, 0},
	} {
		lit := ourBtpLiteral(4, 3, 3, 50, 512, res.Xs())
		lit.EphemeralSecretWeight = ip(c.eph)
		lit.LogMessageRatio = ip(c.msgRatio)
		lit.Mod1InvDegree = ip(c.inv)
		bootOnce(c.label, res, lit, q0-c.msgRatio)
	}
	fmt.Println("\n※ 1단계 격자 전제: EvalMod 13 / logQP 1714. 위 값과 대조할 것.")
}

func main() {
	mode := flag.String("mode", "A", "A|B|C|D|E|F")
	flag.Parse()
	switch *mode {
	case "A":
		runA()
	case "B":
		runB()
	case "C":
		runC()
	case "D":
		runD()
	case "E":
		runE()
	case "F":
		runF()
	default:
		fmt.Fprintln(os.Stderr, "알 수 없는 mode")
		os.Exit(2)
	}
}
