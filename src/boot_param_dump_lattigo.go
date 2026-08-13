//go:build ignore

// boot_param_dump_lattigo.go — 부트스트래핑 파라미터 격자 덤프 (1단계). 벤치·keygen 없음.
//
// `param_dump_lattigo_grid.go` 의 구조를 따르되 **부트스트래핑 파라미터**를 다룬다.
// 기존 파일은 건드리지 않는다(8-op 프리셋 A~D 의 정본 추출 경로).
//
// ⚠️ Lattigo 는 잔여(Residual)와 부트(Bootstrapping) 파라미터가 **분리된 두 객체**다.
//    `btp.ResidualParameters` / `btp.BootstrappingParameters` 를 따로 찍는다.
//    보안 판정 대상은 **부트 쪽 logQP** 다 — 잔여만 보면 상한 초과를 못 잡는다.
//
// 고정 조건 (탐색 대상 아님)
//   LogN 16 / 전체 슬롯 2^15 / dense uniform ternary(Ternary{P:2/3})
//   EphemeralSecretWeight = 0  (sparse-secret encapsulation 끄기)
//   K = 512                    (⚠️ GetK() 는 Xs 를 보지 않고 기본 16 을 준다.
//                               dense 로 바꾸면서 K 를 두면 근사 구간을 넘어 부트가
//                               예외 없이 조용히 깨진다 — parameters_literal.go:GetK)
//
// 모드
//   -mode grid    (기본) q0 × Δ × 잔여L × PCount × C2S/S2C 분해깊이 × EvalMod scale
//   -mode kcheck  K=16 vs K=512 의 EvalMod 레벨 수 대조
//   -mode repro   논문 Table 5.8 Set I 재현 (도구 검증용. 프리셋 후보 아님)
package main

import (
	"flag"
	"fmt"
	"math"
	"math/bits"
	"os"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/tuneinsight/lattigo/v6/circuits/ckks/bootstrapping"
	"github.com/tuneinsight/lattigo/v6/ring"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

// 보안 상한 — Bossuat et al., IACR ePrint 2024/463, Table 5.2
// (λ=128, uniform ternary, σ=3.19). 8-op(A~D)의 seal MaxBitCount 기준과 **출처가 다르다**.
func bound(logN int) int {
	switch logN {
	case 13:
		return 214
	case 14:
		return 430
	case 15:
		return 868
	case 16:
		return 1747
	}
	return -1
}

const header = "library,logN,numSlots,q0,delta,residual_L," +
	"boot_depth,levelBudget_c2s,levelBudget_s2c,evalmod_levels,evalmod_scale,K," +
	"QCount_boot,logQ_boot,PCount_boot,logP_boot,logQP_boot," +
	"QCount_residual,logQ_residual,logP_residual,logQP_residual," +
	"dnum,maxDigitBits,margin_1747," +
	"mod1_degree,mod1_inv_degree,log_message_ratio,ephemeral_secret_weight,in_scale_log2," +
	"ok,fail_reason\n"

func ip(v int) *int { return &v }

// 저장소 관례: 명목 비트 = round(log2(prime)).
func nominal(q uint64) int { return int(math.Round(math.Log2(float64(q)))) }

func sumNominal(m []uint64) int {
	s := 0
	for _, q := range m {
		s += nominal(q)
	}
	return s
}

// digit 별 명목 비트합의 최대. dnum = ceil(#Q/#P) 이므로 digit 은 #P 개씩 묶인다.
func maxDigitBits(q []uint64, np, dnum int) int {
	best := 0
	for j := 0; j < dnum; j++ {
		lo, hi := j*np, (j+1)*np
		if hi > len(q) {
			hi = len(q)
		}
		b := 0
		for k := lo; k < hi; k++ {
			b += nominal(q[k])
		}
		if b > best {
			best = b
		}
	}
	return best
}

func scrub(s string) string {
	return strings.NewReplacer(",", " ", "\n", " ", "\r", " ", "\"", " ").Replace(s)
}

// ---------------------------------------------------------------------------

type fixed struct {
	logN     int
	logSlots int
	K        int
	ephem    int
	auxBits  int // Lattigo 의 P 프라임 크기. 기본 61 (OpenFHE 의 auxBits 60 과 다르다)
	mod1deg  int // Mod1Degree. 0 이면 2*(K-1) 최소요구값 (evaluator.go:89 가 요구한다)
}

// CosDiscrete 의 최소 차수. `NewEvaluator` 가 `Mod1Degree >= 2*(K-1)` 를 요구한다
// (`evaluator.go:89`). 이 검사는 **NewParametersFromLiteral 뒤**라 파라미터 객체는
// 만들어지지만 부트는 못 돈다 — 2단계 보정에서 실제로 걸렸다(2026-08-12).
func minMod1Degree(K int) int { return 2 * (K - 1) }

func (f fixed) degree() int {
	if f.mod1deg > 0 {
		return f.mod1deg
	}
	return minMod1Degree(f.K)
}

// 잔여 파라미터. LogP 는 §8.5 규칙 7 (dnum 최소화 우선, 동률이면 P 작은 쪽) 로 고른다.
// 부트 쪽 PCount 는 격자 축이지만 잔여 쪽은 사용자 회로용이라 규칙으로 정한다.
func residualLiteral(f fixed, q0, delta, L, pc int) ckks.ParametersLiteral {
	logQ := []int{q0}
	for i := 0; i < L; i++ {
		logQ = append(logQ, delta)
	}
	logP := make([]int, pc)
	for i := range logP {
		logP[i] = f.auxBits
	}
	return ckks.ParametersLiteral{
		LogN: f.logN, LogQ: logQ, LogP: logP, LogDefaultScale: delta,
		Xs: ring.Ternary{P: 2.0 / 3.0}, // dense uniform ternary
	}
}

func bestResidualPCount(qCount, maxPC int) int {
	bestPC, bestDnum := 1, qCount
	for pc := 1; pc <= maxPC; pc++ {
		d := (qCount + pc - 1) / pc
		if d < bestDnum { // dnum 최소화 우선, 동률이면 먼저 나온 작은 pc 유지
			bestDnum, bestPC = d, pc
		}
	}
	return bestPC
}

// ⚠️ (마) 구성: LogMessageRatio = q0 − Δ. OpenFHE 는 입력을 재스케일하지 않아 실효
// message ratio 가 2^(q0−Δ) 이므로 그 값에 맞춰야 양쪽이 같은 크기의 메시지를 부트한다(§10.7-18).
func bootLiteralMR(f fixed, pcBoot, c2s, s2c, evalScale, msgRatio int, xs ring.DistributionParameters) bootstrapping.ParametersLiteral {
	l := bootLiteral(f, pcBoot, c2s, s2c, evalScale, xs)
	l.LogMessageRatio = ip(msgRatio)
	l.Mod1InvDegree = ip(0) // §10.7-23: 대응 축이 없어 0 고정
	return l
}

func bootLiteral(f fixed, pcBoot, c2s, s2c, evalScale int, xs ring.DistributionParameters) bootstrapping.ParametersLiteral {
	logP := make([]int, pcBoot)
	for i := range logP {
		logP[i] = f.auxBits
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
		LogN:     ip(f.logN),
		LogSlots: ip(f.logSlots),
		LogP:     logP,
		Xs:       xs,
		CoeffsToSlotsFactorizationDepthAndLogScales: c2sD,
		SlotsToCoeffsFactorizationDepthAndLogScales: s2cD,
		Mod1Degree:                                  ip(f.degree()),
		EvalModLogScale:                             ip(evalScale),
		EphemeralSecretWeight:                       ip(f.ephem),
		K:                                           ip(f.K),
	}
}

// EvalMod 레벨 수를 컨텍스트 없이 예측한다 (mod1_parameters.go:57 Depth()).
//   depth = bits.Len64(max(Mod1Degree, 2K-1)) + DoubleAngle   (CosDiscrete, Mod1InvDegree=0)
func predEvalModLevels(K int) int {
	deg := bootstrapping.DefaultMod1Degree
	if 2*K-1 > deg {
		deg = 2*K - 1
	}
	return bits.Len64(uint64(deg)) + bootstrapping.DefaultDoubleAngle
}

// 부트 체인의 명목 logQ 예측 (parameters.go:206-245 의 LogQBootstrappingCircuit 구성 그대로).
func predBootLogQ(f fixed, q0, delta, L, c2s, s2c, evalScale int) int {
	q := q0 + delta*L
	for i := 0; i < s2c; i++ {
		qi := bootstrapping.DefaultSlotsToCoeffsLogScale
		if qi+delta < 61 { // parameters.go:220 — 작은 Δ 에서만 발동한다
			qi += delta
		}
		q += qi
	}
	q += evalScale * predEvalModLevels(f.K)
	q += bootstrapping.DefaultCoeffsToSlotsLogScale * c2s
	return q
}

type row struct {
	q0, delta, L                int
	pcBoot, c2s, s2c, evalScale int
	line                        string
}

func emit(f fixed, q0, delta, L, pcBoot, c2s, s2c, evalScale int,
	btp *bootstrapping.Parameters, forcedFail string) string {

	numSlots := 1 << f.logSlots
	if btp == nil {
		return fmt.Sprintf("lattigo,%d,%d,%d,%d,%d,,%d,%d,,%d,%d,,,%d,,,,,,,,,,%d,%d,%d,%d,%d,0,%s\n",
			f.logN, numSlots, q0, delta, L, c2s, s2c, evalScale, f.K, pcBoot,
			f.degree(), 0, q0-delta, f.ephem, delta, scrub(forcedFail))
	}

	bp, rp := btp.BootstrappingParameters, btp.ResidualParameters
	logQb, logPb := sumNominal(bp.Q()), sumNominal(bp.P())
	logQr, logPr := sumNominal(rp.Q()), sumNominal(rp.P())
	dnum := bp.BaseRNSDecompositionVectorSize(bp.MaxLevelQ(), bp.MaxLevelP())
	md := maxDigitBits(bp.Q(), bp.PCount(), dnum)

	c2sDepth, s2cDepth := 0, 0
	for _, v := range btp.CoeffsToSlotsParameters.Levels {
		c2sDepth += v
	}
	for _, v := range btp.SlotsToCoeffsParameters.Levels {
		s2cDepth += v
	}
	evalmod := btp.Mod1ParametersLiteral.Depth()
	bootDepth := bp.QCount() - rp.QCount()
	logQPb := logQb + logPb
	b := bound(f.logN)

	fail := ""
	// ⚠️ 최소 차수 게이트 (evaluator.go:89). OpenFHE correctionFactor 가드와 같은 방식 —
	// 가드가 우리가 도달하지 못하는 함수 안에 있으므로 **런타임 추출값으로 같은 식을 계산**한다.
	if btp.Mod1ParametersLiteral.Mod1Type == 0 && // CosDiscrete
		btp.Mod1ParametersLiteral.Mod1Degree < minMod1Degree(btp.Mod1ParametersLiteral.K) {
		fail = fmt.Sprintf("Mod1Degree %d < 2*(K-1)=%d — 파라미터는 만들어지나 NewEvaluator 에서 죽는다",
			btp.Mod1ParametersLiteral.Mod1Degree, minMod1Degree(btp.Mod1ParametersLiteral.K))
	}
	if q0-delta > 7 {
		if fail != "" {
			fail += " / "
		}
		fail += fmt.Sprintf("correctionFactor 커플링 위반: q0-Δ=%d > 7", q0-delta)
	}
	if logQPb > b {
		if fail != "" {
			fail += " / "
		}
		fail += fmt.Sprintf("logQP_boot %d > %d", logQPb, b)
	}
	ok := 0
	if fail == "" {
		ok = 1
	}

	return fmt.Sprintf("lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s\n",
		f.logN, numSlots, q0, delta, L,
		bootDepth, c2sDepth, s2cDepth, evalmod, evalScale, btp.Mod1ParametersLiteral.K,
		bp.QCount(), logQb, bp.PCount(), logPb, logQPb,
		rp.QCount(), logQr, logPr, logQr+logPr,
		dnum, md, b-logQPb,
		btp.Mod1ParametersLiteral.Mod1Degree, btp.Mod1ParametersLiteral.Mod1InvDegree,
		btp.Mod1ParametersLiteral.LogMessageRatio, btp.EphemeralSecretWeight, delta,
		ok, scrub(fail))
}

// ---------------------------------------------------------------------------

func runGrid(out string, f fixed, q0s, deltas []int, lmin, lmax, pcMax int,
	dfs, scales []int, workers int) {

	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprint(fh, header)

	type job struct{ q0, delta int }
	var jobs []job
	for _, q := range q0s {
		for _, d := range deltas {
			// 0 < q0 − Δ ≤ 7 (§10.5-1). q0 ≤ 60 은 축에서 이미 보장된다.
			if q-d > 7 || q-d < 1 {
				continue
			}
			jobs = append(jobs, job{q, d})
		}
	}

	b := bound(f.logN)
	results := make([]string, len(jobs))
	var nBuilt, nSkip, nFail int64
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, workers)

	for idx, jb := range jobs {
		wg.Add(1)
		go func(idx int, jb job) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			var sb strings.Builder
			var built, skip, failed int64
			for L := lmin; L <= lmax; L++ {
				// 잔여 파라미터는 (q0, Δ, L) 마다 하나면 된다 — 부트 축과 무관하다.
				resPC := bestResidualPCount(L+1, pcMax)
				res, rerr := ckks.NewParametersFromLiteral(residualLiteral(f, jb.q0, jb.delta, L, resPC))
				if rerr != nil {
					for _, pc := range rng(1, pcMax) {
						for _, c2s := range dfs {
							for _, s2c := range dfs {
								for _, sc := range scales {
									sb.WriteString(emit(f, jb.q0, jb.delta, L, pc, c2s, s2c, sc, nil,
										"잔여 파라미터 생성 실패: "+rerr.Error()))
									failed++
								}
							}
						}
					}
					continue
				}
				for _, c2s := range dfs {
					for _, s2c := range dfs {
						for _, sc := range scales {
							predQ := predBootLogQ(f, jb.q0, jb.delta, L, c2s, s2c, sc)
							for pc := 1; pc <= pcMax; pc++ {
								// 확정 탈락은 만들지 않는다. 여유 한 프라임(auxBits)을 둬
								// 예측 오차가 판정을 뒤집지 못하게 한다.
								if predQ+f.auxBits*pc > b+f.auxBits {
									sb.WriteString(emit(f, jb.q0, jb.delta, L, pc, c2s, s2c, sc, nil,
										fmt.Sprintf("예측 탈락: logQ_boot(명목) %d + logP %d > %d+%d → 미생성",
											predQ, f.auxBits*pc, b, f.auxBits)))
									skip++
									continue
								}
								btp, berr := bootstrapping.NewParametersFromLiteral(res,
									bootLiteralMR(f, pc, c2s, s2c, sc, jb.q0-jb.delta, res.Xs()))
								if berr != nil {
									sb.WriteString(emit(f, jb.q0, jb.delta, L, pc, c2s, s2c, sc, nil,
										"부트 파라미터 생성 실패: "+berr.Error()))
									failed++
									continue
								}
								sb.WriteString(emit(f, jb.q0, jb.delta, L, pc, c2s, s2c, sc, &btp, ""))
								built++
							}
						}
					}
				}
			}
			results[idx] = sb.String()
			mu.Lock()
			nBuilt += built
			nSkip += skip
			nFail += failed
			fmt.Printf("  q0=%d Δ=%d 완료 (생성 %d / 미생성 %d / 실패 %d)\n", jb.q0, jb.delta, built, skip, failed)
			mu.Unlock()
		}(idx, jb)
	}
	wg.Wait()

	for _, s := range results {
		fmt.Fprint(fh, s)
	}
	fmt.Printf("\n[boot grid] %s\n  생성 %d / 예측 탈락(미생성) %d / 실패 %d\n", out, nBuilt, nSkip, nFail)
}

func rng(a, b int) []int {
	v := make([]int, 0, b-a+1)
	for i := a; i <= b; i++ {
		v = append(v, i)
	}
	return v
}

// K=16 vs K=512 대조. 나머지 조건은 동일하게 두고 EvalMod 레벨 수만 본다.
func runKCheck(out string, f fixed) {
	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprintln(fh, "logN,numSlots,q0,delta,residual_L,ephemeral_secret_weight,Xs,K_set,K_runtime,"+
		"evalmod_levels,QCount_boot,logQ_boot,PCount_boot,logP_boot,logQP_boot,err")

	q0, delta, L := 45, 35, 10
	fmt.Printf("\n=== Lattigo K 검증 (dense Xs, EphemeralSecretWeight=0, q0=%d Δ=%d 잔여L=%d) ===\n", q0, delta, L)
	fmt.Printf("  %-6s %-9s %-9s %-9s %-9s %-9s\n", "K설정", "K실측", "EvalMod", "QCount", "logQ_boot", "logQP_boot")
	res, err := ckks.NewParametersFromLiteral(residualLiteral(f, q0, delta, L, bestResidualPCount(L+1, 8)))
	if err != nil {
		panic(err)
	}
	for _, K := range []int{16, 512} {
		ff := f
		ff.K = K
		btp, berr := bootstrapping.NewParametersFromLiteral(res, bootLiteral(ff, 2, 4, 3, 60, res.Xs()))
		if berr != nil {
			fmt.Fprintf(fh, "%d,%d,%d,%d,%d,%d,ternary_p2over3,%d,,,,,,,,%s\n",
				f.logN, 1<<f.logSlots, q0, delta, L, f.ephem, K, scrub(berr.Error()))
			fmt.Printf("  %-6d 실패: %v\n", K, berr)
			continue
		}
		bp := btp.BootstrappingParameters
		lq, lp := sumNominal(bp.Q()), sumNominal(bp.P())
		em := btp.Mod1ParametersLiteral.Depth()
		fmt.Fprintf(fh, "%d,%d,%d,%d,%d,%d,ternary_p2over3,%d,%d,%d,%d,%d,%d,%d,%d,\n",
			f.logN, 1<<f.logSlots, q0, delta, L, f.ephem, K, btp.Mod1ParametersLiteral.K,
			em, bp.QCount(), lq, bp.PCount(), lp, lq+lp)
		fmt.Printf("  %-6d %-9d %-9d %-9d %-9d %-9d\n", K, btp.Mod1ParametersLiteral.K, em, bp.QCount(), lq, lq+lp)
	}
	fmt.Printf("[kcheck] %s\n", out)
}

// 분해깊이(C2S, S2C)별 회전키 개수. levelBudget 의 실제 비용을 간접적으로 보여주는 지표다.
//
// ⚠️ 회전키 집합은 DFT 행렬 리터럴(LogSlots·Levels·LogBSGSRatio)에만 의존하고
//    q0·Δ·잔여L·PCount·EvalMod scale 과는 무관하다. 그래서 격자 CSV 에 열로 붙이지 않고
//    (c2s, s2c) 9행짜리 별표로 뽑는다. **무관하다는 것 자체를 두 기준점으로 대조 검증한다.**
//
// ⚠️ OpenFHE 에는 대응물이 없다 — `FHECKKSRNS::FindBootstrapRotationIndices` 는
//    `ckksrns-fhe.h:342`(`private:` 331 이후)라 접근할 수 없고, 공개 경로는
//    `EvalBootstrapKeyGen` 뿐인데 그것은 keygen 이다. **이번 단계에서는 못 얻는다.**
func runGalois(out string, f fixed, dfs []int) {
	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprintln(fh, "library,logN,numSlots,c2s_depth,s2c_depth,galois_c2s,galois_s2c,"+
		"galois_union,galois_total_with_conj,invariant_check")

	// 기준점 두 개 — 회전키 집합이 (q0, Δ, L, PCount, scale) 과 무관한지 대조한다.
	type ref struct{ q0, delta, L, pc, scale int }
	refs := []ref{{45, 40, 10, 2, 60}, {40, 33, 5, 3, 50}}

	fmt.Printf("\n=== Lattigo 분해깊이별 회전키 개수 (logN %d, 슬롯 2^%d) ===\n", f.logN, f.logSlots)
	fmt.Printf("  %-5s %-5s %-9s %-9s %-9s %-12s %s\n", "C2S", "S2C", "C2S키", "S2C키", "합집합", "+켤레", "기준점무관")
	for _, c2s := range dfs {
		for _, s2c := range dfs {
			var counts []int
			var nc2s, ns2c, nUnion int
			okInvariant := true
			for _, r := range refs {
				res, rerr := ckks.NewParametersFromLiteral(
					residualLiteral(f, r.q0, r.delta, r.L, bestResidualPCount(r.L+1, 8)))
				if rerr != nil {
					panic(rerr)
				}
				btp, berr := bootstrapping.NewParametersFromLiteral(res,
					bootLiteral(f, r.pc, c2s, s2c, r.scale, res.Xs()))
				if berr != nil {
					panic(berr)
				}
				bp := btp.BootstrappingParameters
				a := btp.CoeffsToSlotsParameters.GaloisElements(bp)
				b := btp.SlotsToCoeffsParameters.GaloisElements(bp)
				u := map[uint64]bool{}
				for _, g := range a {
					u[g] = true
				}
				for _, g := range b {
					u[g] = true
				}
				// keys.go:109 — 켤레(complex conjugation) 자기동형이 항상 하나 더 붙는다
				u[bp.GaloisElementForComplexConjugation()] = true
				nc2s, ns2c = len(a), len(b)
				nUnion = len(u)
				counts = append(counts, len(u))
			}
			for _, c := range counts[1:] {
				if c != counts[0] {
					okInvariant = false
				}
			}
			// 합집합에는 켤레가 이미 들어 있다 — 켤레를 뺀 값을 galois_union 으로 적는다
			fmt.Fprintf(fh, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%t\n",
				f.logN, 1<<f.logSlots, c2s, s2c, nc2s, ns2c, nUnion-1, nUnion, okInvariant)
			mark := "예"
			if !okInvariant {
				mark = "✗ 아니오"
			}
			fmt.Printf("  %-5d %-5d %-9d %-9d %-9d %-12d %s\n", c2s, s2c, nc2s, ns2c, nUnion-1, nUnion, mark)
		}
	}
	fmt.Printf("[galois] %s\n", out)
	fmt.Println("※ OpenFHE 대응물은 keygen 없이 얻을 수 없다 (FindBootstrapRotationIndices 가 private).")
}

// K × Mod1Degree 조합이 **실제로 돌 수 있는지** 검사한다 (2026-08-12 추가).
//
// ⚠️ 1단계 격자는 `bootstrapping.NewParametersFromLiteral` 까지만 불렀는데, 최소 차수 검사는
//    그보다 **뒤인 `NewEvaluator`** 에 있다(`evaluator.go:89`):
//        Mod1Type == CosDiscrete && Mod1Degree < 2*(K−1)  → 에러
//    즉 파라미터 객체는 만들어지지만 부트는 못 돈다. 2단계 보정 1점에서 이걸로 죽었다.
//
// 여기서 확인하는 것:
//   ⑴ K 별 최소 차수와, 그 차수를 줬을 때 **EvalMod 깊이가 바뀌는가** (바뀌면 격자 재실행)
//   ⑵ `NewEvaluator` 를 키 없이(nil) 불러 최소 차수 검사까지 도달하는 비용
//      — 싸면 격자 게이트에 넣을 수 있다
func runEvalCheck(out string, f fixed) {
	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprintln(fh, "K,mod1degree_set,mod1degree_runtime,min_required,degree_ok,"+
		"evalmod_levels,QCount_boot,logQ_boot,PCount_boot,logP_boot,logQP_boot,"+
		"newevaluator_verdict,newevaluator_us")

	q0, delta, L, pc, c2s, s2c, sc := 45, 40, 12, 4, 3, 3, 60
	res, rerr := ckks.NewParametersFromLiteral(residualLiteral(f, q0, delta, L, bestResidualPCount(L+1, 8)))
	if rerr != nil {
		panic(rerr)
	}

	fmt.Printf("\n=== K × Mod1Degree 유효성 (q0=%d Δ=%d 잔여L=%d, 분해깊이 {%d,%d}) ===\n",
		q0, delta, L, c2s, s2c)
	fmt.Printf("%-5s%-12s%-11s%-9s%-9s%-9s%-9s%-9s  %s\n",
		"K", "Mod1Degree", "최소요구", "차수OK", "EvalMod", "QCount", "logQ", "logQP", "NewEvaluator(nil)")

	for _, K := range []int{128, 256, 512} {
		minReq := 2 * (K - 1)
		for _, deg := range []int{bootstrapping.DefaultMod1Degree, minReq} {
			ff := f
			ff.K = K
			lit := bootLiteral(ff, pc, c2s, s2c, sc, res.Xs())
			lit.Mod1Degree = ip(deg)
			btp, berr := bootstrapping.NewParametersFromLiteral(res, lit)
			if berr != nil {
				fmt.Printf("%-5d%-12d%-11d  파라미터 생성 실패: %v\n", K, deg, minReq, berr)
				continue
			}
			bp := btp.BootstrappingParameters
			em := btp.Mod1ParametersLiteral.Depth()
			lq, lp := sumNominal(bp.Q()), sumNominal(bp.P())
			degOK := btp.Mod1ParametersLiteral.Mod1Degree >= minReq

			// ⚠️ 키 없이(nil) 부른다. 잔여/부트 LogN 이 같으면 evk 는 최소 차수 검사
			// **뒤에서만** 참조되므로(evaluator.go:59 의 && 단축 평가) 여기까지는 안전하다.
			// 검사를 통과하면 그다음 initialize()/checkKeys(nil) 에서 패닉하는데,
			// 그 패닉 자체가 "차수 검사는 통과했다"는 신호다.
			verdict, us := func() (v string, us int64) {
				t := time.Now()
				defer func() {
					us = time.Since(t).Microseconds()
					if e := recover(); e != nil {
						v = "차수검사 통과(이후 키 없어 패닉)"
					}
				}()
				_, e := bootstrapping.NewEvaluator(btp, nil)
				if e != nil {
					if strings.Contains(e.Error(), "minimum degree") {
						return "차수검사 실패", 0
					}
					return "다른 오류: " + scrub(e.Error()), 0
				}
				return "통과(키 없이도 생성됨)", 0
			}()

			fmt.Fprintf(fh, "%d,%d,%d,%d,%t,%d,%d,%d,%d,%d,%d,%s,%d\n",
				K, deg, btp.Mod1ParametersLiteral.Mod1Degree, minReq, degOK,
				em, bp.QCount(), lq, bp.PCount(), lp, lq+lp, verdict, us)
			fmt.Printf("%-5d%-12d%-11d%-9t%-9d%-9d%-9d%-9d  %s (%.1fms)\n",
				K, deg, minReq, degOK, em, bp.QCount(), lq, lq+lp, verdict, float64(us)/1000)
		}
	}
	fmt.Println("\n※ 최소 차수 검사는 CosDiscrete 에만 있다 (evaluator.go:89).")
	fmt.Println("  SinContinuous 는 DoubleAngle!=0 을 막고(:85), CosContinuous 에는 차수 제약이 없다.")
	fmt.Printf("[evalcheck] %s\n", out)
}

// 단건 진단 — Table 5.8 Set I 재현 격차(+70)를 성분별로 분해한다. **격자가 아니다.**
// logQ 를 잔여 / S2C / EvalMod / C2S 네 덩어리로 쪼개 어디서 벌어지는지 본다.
func runDiag(out string, f fixed) {
	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprintln(fh, "case,K_set,K_runtime,c2s_depth,s2c_depth,evalmod_scale,PCount,"+
		"evalmod_levels,QCount_boot,logQ_boot,logP_boot,logQP_boot,"+
		"bits_residual,bits_s2c,bits_evalmod,bits_c2s,q_prime_bits")

	q0, delta, L := 45, 35, 10
	type cs struct {
		label              string
		K, c2s, s2c, scale int
		pc                 int
	}
	// K=256 → Depth = bits.Len64(max(30, 511)) + 3 = 9 + 3 = 12 (논문 Set I 의 EvalMod 12).
	// v6.2.0 에서 K=512 로는 12 가 나올 수 없다 — max(2K−1)=1023 이 10비트라 13 이 된다.
	cases := []cs{
		{"우리 재현 (K512, C2S3/S2C4)", 512, 3, 4, 60, 5},
		{"K512, C2S4/S2C3", 512, 4, 3, 60, 5},
		{"K256 → EvalMod 12, C2S3/S2C4", 256, 3, 4, 60, 5},
		{"K256 → EvalMod 12, C2S4/S2C3", 256, 4, 3, 60, 5},
	}

	fmt.Printf("\n=== Set I (Lattigo) 성분 분해 — logQ 1499 vs 논문 1464 ===\n")
	fmt.Printf("%-32s%7s%9s%8s%9s%9s%9s%9s%9s\n", "case", "EvalMod", "QCount",
		"logQ", "잔여", "S2C", "EvalMod", "C2S", "logQP")
	for _, c := range cases {
		ff := f
		ff.K = c.K
		res, rerr := ckks.NewParametersFromLiteral(residualLiteral(ff, q0, delta, L, bestResidualPCount(L+1, 8)))
		if rerr != nil {
			panic(rerr)
		}
		btp, berr := bootstrapping.NewParametersFromLiteral(res, bootLiteral(ff, c.pc, c.c2s, c.s2c, c.scale, res.Xs()))
		if berr != nil {
			fmt.Printf("%-32s 실패: %v\n", c.label, berr)
			continue
		}
		bp := btp.BootstrappingParameters
		em := btp.Mod1ParametersLiteral.Depth()
		lq, lp := sumNominal(bp.Q()), sumNominal(bp.P())

		// parameters.go:206-245 의 구성 순서 그대로: [잔여] + [S2C] + [EvalMod] + [C2S]
		qb := bp.Q()
		bitsRes := sumNominal(qb[:res.QCount()])
		off := res.QCount()
		bitsS2C := sumNominal(qb[off : off+c.s2c])
		off += c.s2c
		bitsEM := sumNominal(qb[off : off+em])
		off += em
		bitsC2S := sumNominal(qb[off:])

		var pb []string
		for _, q := range qb {
			pb = append(pb, fmt.Sprint(nominal(q)))
		}
		fmt.Fprintf(fh, "\"%s\",%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s\n",
			c.label, c.K, btp.Mod1ParametersLiteral.K, c.c2s, c.s2c, c.scale, c.pc,
			em, bp.QCount(), lq, lp, lq+lp, bitsRes, bitsS2C, bitsEM, bitsC2S,
			strings.Join(pb, ";"))
		fmt.Printf("%-32s%7d%9d%8d%9d%9d%9d%9d%9d\n", c.label, em, bp.QCount(), lq,
			bitsRes, bitsS2C, bitsEM, bitsC2S, lq+lp)
	}
	fmt.Println("\n논문 Set I: logQ 1464 / logP 305 / logQP 1734, S2C 4 / EvalMod 12 / C2S 3, K 512")
	fmt.Println("※ v6.2.0 의 mod1.ParametersLiteral.Depth() 는 bits.Len64(max(Mod1Degree, 2K−1)) + DoubleAngle 다.")
	fmt.Println("  K=512 로 EvalMod 12 를 만들 수 없다 (10+3=13). K≤256 이어야 12 가 된다.")
	fmt.Printf("[diag] %s\n", out)
}

// 논문 Table 5.8 Set I 재현. **프리셋 후보가 아니라 도구 검증용**이다.
//   Set I (Lattigo v5.0.2): q0 45, Δ 2^35, 잔여L 10, dense + encapsulation off, K 512
//     → logQ 1464 / logP 305 / logQP 1734, S2C 4 / EvalMod 12 / C2S 3
func runRepro(out string, f fixed) {
	fh, err := os.Create(out)
	if err != nil {
		panic(err)
	}
	defer fh.Close()
	fmt.Fprint(fh, header)

	q0, delta, L := 45, 35, 10
	pc, c2s, s2c, sc := 5, 3, 4, 60 // logP 305 = 5 × 61
	res, rerr := ckks.NewParametersFromLiteral(residualLiteral(f, q0, delta, L, bestResidualPCount(L+1, 8)))
	if rerr != nil {
		panic(rerr)
	}
	btp, berr := bootstrapping.NewParametersFromLiteral(res, bootLiteral(f, pc, c2s, s2c, sc, res.Xs()))

	fmt.Printf("\n=== Table 5.8 Set I 재현 (Lattigo) ===\n")
	fmt.Printf("논문: logQ 1464 / logP 305 / logQP 1734, S2C 4 / EvalMod 12 / C2S 3, K 512\n")
	if berr != nil {
		fmt.Fprint(fh, emit(f, q0, delta, L, pc, c2s, s2c, sc, nil, berr.Error()))
		fmt.Printf("재현 실패: %v\n", berr)
		return
	}
	fmt.Fprint(fh, emit(f, q0, delta, L, pc, c2s, s2c, sc, &btp, ""))
	bp := btp.BootstrappingParameters
	lq, lp := sumNominal(bp.Q()), sumNominal(bp.P())
	em := btp.Mod1ParametersLiteral.Depth()
	fmt.Printf("실측: logQ %d / logP %d / logQP %d, S2C %d / EvalMod %d / C2S %d, K %d\n",
		lq, lp, lq+lp, s2c, em, c2s, btp.Mod1ParametersLiteral.K)
	fmt.Printf("차이: logQ %+d / logP %+d / logQP %+d / EvalMod %+d\n",
		lq-1464, lp-305, lq+lp-1734, em-12)
	fmt.Printf("[repro] %s\n", out)
}

// ---------------------------------------------------------------------------

func main() {
	mode := flag.String("mode", "grid", "grid|kcheck|galois|diag|evalcheck|repro")
	out := flag.String("out", "", "")
	logN := flag.Int("logN", 16, "")
	logSlots := flag.Int("logSlots", 15, "전체 슬롯")
	K := flag.Int("K", 16, "(마) 구성: 캡슐화가 켜져 ModUp 이 sparse 임시키(H=32) 아래라 16")
	ephem := flag.Int("ephemeral", 32, "(마) 구성: 캡슐화 켬. 0 은 v6.2.0 에서 동작하지 않는다(§10.7-17)")
	aux := flag.Int("auxbits", 61, "P 프라임 크기 (Lattigo 기본 61)")
	mdeg := flag.Int("mod1degree", 0, "0 이면 2*(K-1) 최소요구값 (evaluator.go:89)")
	lmin := flag.Int("L-min", 3, "")
	lmax := flag.Int("L-max", 30, "2026-08-12: 여유가 250비트 이상 생겨 20 으로는 천장에 걸린다")
	pcMax := flag.Int("pcount-max", 8, "")
	workers := flag.Int("workers", 4, "동시 실행 수")
	flag.Parse()

	f := fixed{logN: *logN, logSlots: *logSlots, K: *K, ephem: *ephem, auxBits: *aux, mod1deg: *mdeg}
	if *out == "" {
		*out = map[string]string{
			"grid":   "boot_grid_lattigo.csv",
			"kcheck": "boot_kcheck_lattigo.csv",
			"galois": "boot_galois_lattigo.csv",
			"diag":   "boot_diag_lattigo.csv",
			"evalcheck": "boot_evalcheck_lattigo.csv",
			"repro":  "boot_repro_lattigo.csv",
		}[*mode]
		if *out == "" {
			fmt.Fprintln(os.Stderr, "알 수 없는 mode:", *mode)
			os.Exit(2)
		}
	}

	// 2026-08-12 축 재설계 (§10.7-20). Δ ≤ 50 은 OpenFHE 부트가 파탄나고(자릿수 4~6배),
	// Δ ≥ 60 은 scalingModSize 제약으로 불가하다. q0 는 Δ 에 종속시킨다 — (마)에서
	// LogMessageRatio = q0 − Δ 이므로 이 차이가 메시지 비를 직접 정한다.
	deltas := []int{52, 53, 55, 58, 59}
	q0s := []int{}
	for d := 53; d <= 60; d++ {
		q0s = append(q0s, d)
	}
	dfs := []int{2, 3, 4}
	scales := []int{50, 55, 60}
	sort.Ints(q0s)
	sort.Ints(deltas)

	switch *mode {
	case "grid":
		if *workers < 1 {
			*workers = 1
		}
		if *workers > runtime.NumCPU() {
			*workers = runtime.NumCPU()
		}
		runGrid(*out, f, q0s, deltas, *lmin, *lmax, *pcMax, dfs, scales, *workers)
	case "kcheck":
		runKCheck(*out, f)
	case "galois":
		// 분해깊이 1 은 격자 축 밖이지만 OpenFHE levelBudget {1,1}(인수분해 없음)의
		// 회전 비용을 보여 주려고 함께 찍는다.
		runGalois(*out, f, []int{1, 2, 3, 4})
	case "evalcheck":
		runEvalCheck(*out, f)
	case "diag":
		runDiag(*out, f)
	case "repro":
		runRepro(*out, f)
	}
}
