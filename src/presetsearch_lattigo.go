//go:build ignore

// presetsearch_lattigo.go — 프리셋 확정을 위한 탐색 측정 (Lattigo). 본측정 아님.
//
// ⚠️ Lattigo는 dnum이 독립 변수가 아니다. core/rlwe/params.go:543
// BaseRNSDecompositionVectorSize = ceil(#Q/#P) 이므로 **PCount를 정하면 dnum이 종속 결정**된다.
// 실험 1은 PCount {1..5}(logP 60/120/180/240/300)를 스윕하고 그때 나오는 dnum을 기록한다.
//
// 측정 로직은 lattigo_bench.go 그대로:
//   - measure(): warmup 후 reps회, 연산 1회만 타이밍, ns→μs, 표본표준편차(n-1)
//   - 출력 암호문은 타이머 밖에서 미리 할당
//   - 레벨 진입: 해당 레벨로 직접 NewCiphertext/Encrypt (lattigo_bench.go와 동일)
//   - relin 직접 계측: degree-2 입력을 타이머 밖에서 만들고 out-of-place Relinearize 반복
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"runtime"
	"strings"
	"time"

	"github.com/tuneinsight/lattigo/v6/core/rlwe"
	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

// ---- precision_common.h 이식 (비트 단위 동일해야 함) ----
type rng struct{ s uint64 }

func newRng() *rng { return &rng{s: 0x2026072500000001} }
func (r *rng) next() uint64 {
	r.s ^= r.s >> 12
	r.s ^= r.s << 25
	r.s ^= r.s >> 27
	return r.s * 2685821657736338717
}
func (r *rng) val() float64 { return float64(r.next()>>11)/9007199254740992.0*2.0 - 1.0 }
func makeInputs(slots int) (x, y []float64) {
	r := newRng()
	x, y = make([]float64, slots), make([]float64, slots)
	for i := 0; i < slots; i++ {
		x[i], y[i] = r.val(), r.val()
	}
	return
}
func precisionBits(got, want []float64) float64 {
	s := 0.0
	for i := range want {
		s += math.Abs(got[i] - want[i])
	}
	m := s / float64(len(want))
	if m <= 0 {
		return 999.0
	}
	return -math.Log2(m)
}

func tc128Bound(logN int) int {
	switch logN {
	case 13:
		return 218
	case 14:
		return 438
	case 15:
		return 881
	}
	return -1
}

func measure(reps, warmup int, fn func() error) (float64, float64) {
	for i := 0; i < warmup; i++ {
		if err := fn(); err != nil {
			panic(err)
		}
	}
	ts := make([]float64, reps)
	for i := 0; i < reps; i++ {
		t0 := time.Now()
		if err := fn(); err != nil {
			panic(err)
		}
		ts[i] = float64(time.Since(t0).Nanoseconds()) / 1000.0
	}
	sum := 0.0
	for _, v := range ts {
		sum += v
	}
	mean := sum / float64(reps)
	sd := 0.0
	if reps > 1 {
		ss := 0.0
		for _, v := range ts {
			ss += (v - mean) * (v - mean)
		}
		sd = math.Sqrt(ss / float64(reps-1))
	}
	return mean, sd
}

// measureBatch — 파괴적(in-place) 연산용 배치 계측. presetsearch_openfhe.cpp 와 동일 규약.
// 타이머 밖에서 K개 사본을 준비(reset)하고 타이머 안에서 K회 수행(runK)한 뒤 K로 나눈다.
// ⚠️ rep 값이 "K회 평균"이라 std 의 의미가 단발 계측과 다르다(CSV rep_mode 열로 구분).
func measureBatch(reps, warmup, K int, reset func(), runK func()) (float64, float64) {
	for i := 0; i < warmup; i++ {
		reset()
		runK()
	}
	ts := make([]float64, reps)
	for i := 0; i < reps; i++ {
		reset()
		t0 := time.Now()
		runK()
		ts[i] = float64(time.Since(t0).Nanoseconds()) / 1000.0 / float64(K)
	}
	sum := 0.0
	for _, v := range ts {
		sum += v
	}
	mean := sum / float64(reps)
	sd := 0.0
	if reps > 1 {
		ss := 0.0
		for _, v := range ts {
			ss += (v - mean) * (v - mean)
		}
		sd = math.Sqrt(ss / float64(reps-1))
	}
	return mean, sd
}

// 배치 크기 — 암호문 1개의 바이트 수로 상한을 건다(logN15·L12 는 1개가 ~6.8MB).
func batchKFor(logN, level int, budgetBytes int64, kmax int) int {
	ctBytes := 2.0 * float64(level+1) * float64(int64(1)<<uint(logN)) * 8.0
	k := int(float64(budgetBytes) / ctBytes)
	if k < 4 {
		k = 4
	}
	if k > kmax {
		k = kmax
	}
	return k
}

type cfg struct {
	delta  int
	pcount int
	logN   int
	depth  int
}

func main() {
	expSel := flag.Int("exp", 1, "1=P 탐색 / 2=Δ 스윕")
	reps := flag.Int("reps", 30, "반복")
	warmup := flag.Int("warmup", 3, "warmup")
	precreps := flag.Int("precreps", 5, "정밀도 반복")
	out := flag.String("out", "timing.csv", "타이밍 CSV")
	precout := flag.String("precout", "precision.csv", "정밀도 CSV")
	combos := flag.String("combos", "", "\"logN:depth:delta:pcount,...\" — 지정 시 maxLevel 한 점 heavy 3종")
	mainrun := flag.String("mainrun", "", "\"logN:depth:delta:pcount\" — 레벨 전수 · 8-op · 정밀도")
	leveldrop := flag.String("leveldrop", "", "\"logN:depth:delta:pcount\" — 순수 레벨 강하 전용 (exp 9)")
	verifyout := flag.String("verifyout", "", "exp 9 검증 CSV")
	batchbudget := flag.Int64("batchbudget", 64*1024*1024, "in-place 배치 메모리 예산(바이트)")
	batchkmax := flag.Int("batchkmax", 2048, "in-place 배치 최대 K")
	thlabel := flag.String("threads", "1t", "스레드 조건 라벨 (기록용)")
	flag.Parse()
	if *combos != "" {
		*expSel = 6
	}
	if *mainrun != "" {
		*expSel = 7
	}
	if *leveldrop != "" {
		*expSel = 9
	}

	const q0 = 15*0 + 60
	logN := 15
	depth := 13

	var cfgs []cfg
	var levels []int
	var ops []string
	if *expSel == 1 {
		for pc := 1; pc <= 5; pc++ {
			cfgs = append(cfgs, cfg{40, pc, 15, 13})
		}
		levels = []int{13, 7, 1}
		ops = []string{"mul_cc", "mul_cc_rlk", "relin", "rot1"}
	} else if *expSel == 2 {
		// logP 120 고정 = PCount 2 (dnum은 ceil(14/2)=7 로 종속 결정)
		for d := 40; d <= 50; d++ {
			cfgs = append(cfgs, cfg{d, 2, 15, 13})
		}
		levels = []int{13}
		ops = []string{"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"}
	} else if *expSel == 9 {
		// 순수 레벨 강하 전용. 기존 8-op 경로는 건드리지 않는다.
		var ln, dp, dl, pc int
		if _, err := fmt.Sscanf(strings.TrimSpace(*leveldrop), "%d:%d:%d:%d", &ln, &dp, &dl, &pc); err != nil {
			fmt.Fprintf(os.Stderr, "-leveldrop 파싱 실패: %s\n", *leveldrop)
			os.Exit(2)
		}
		cfgs = append(cfgs, cfg{dl, pc, ln, dp})
		for L := dp; L >= 1; L-- {
			levels = append(levels, L)
		}
		ops = []string{"leveldrop", "leveldrop_ip", "leveldrop_oop", "clone_only"}
	} else if *expSel == 7 {
		var ln, dp, dl, pc int
		if _, err := fmt.Sscanf(strings.TrimSpace(*mainrun), "%d:%d:%d:%d", &ln, &dp, &dl, &pc); err != nil {
			fmt.Fprintf(os.Stderr, "-mainrun 파싱 실패: %s\n", *mainrun)
			os.Exit(2)
		}
		cfgs = append(cfgs, cfg{dl, pc, ln, dp})
		for L := dp; L >= 1; L-- {
			levels = append(levels, L)
		}
		ops = []string{"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"}
	} else if *expSel == 6 {
		// 최적 P 선정용: 임의 조합의 maxLevel 성능만.
		for _, tok := range strings.Split(*combos, ",") {
			var ln, dp, dl, pc int
			if _, err := fmt.Sscanf(strings.TrimSpace(tok), "%d:%d:%d:%d", &ln, &dp, &dl, &pc); err != nil {
				fmt.Fprintf(os.Stderr, "[warn] 조합 파싱 실패: %s\n", tok)
				continue
			}
			cfgs = append(cfgs, cfg{dl, pc, ln, dp})
		}
		ops = []string{"mul_cc_rlk", "relin", "rot1"}
	} else if *expSel == 4 {
		// P 선택 확인: depth 12 / Δ 42 에서 PCount 5/4/3 (logP 300/240/180) 비교.
		// dnum 은 ceil(#Q/#P) 로 종속 결정되므로 각 PCount 에서 실제 값을 기록한다.
		depth = 12
		for _, pc := range []int{5, 4, 3} {
			cfgs = append(cfgs, cfg{42, pc, 15, 12})
		}
		levels = []int{12}
		ops = []string{"mul_cc_rlk", "relin", "rot1"}
	} else if *expSel == 5 {
		// v3 본측정: Δ42 depth12 (QCount 13). PCount 5 → logP 300, dnum 3(종속), logQP 864, 여유 17.
		// QCount 13 에서도 ceil(13/5)=3 이라 depth13 과 같은 dnum 이 나온다.
		depth = 12
		cfgs = append(cfgs, cfg{42, 5, 15, 12})
		for L := depth; L >= 1; L-- {
			levels = append(levels, L)
		}
		ops = []string{"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"}
	} else {
		// 본측정: 확정 프리셋. PCount 5 → logP 300, dnum 3 (종속), logQP 880.
		cfgs = append(cfgs, cfg{40, 5, 15, 13})
		for L := depth; L >= 1; L-- {
			levels = append(levels, L)
		}
		ops = []string{"add_cc", "add_cp", "mul_cp", "mul_cc", "mul_cc_rlk", "relin", "rescale", "rot1"}
	}

	fo, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer fo.Close()
	// nthreads = GOMAXPROCS 런타임 실측. Lattigo 는 단건 연산 내부를 병렬화하지 않으므로
	// 이 값이 커도 op 내부는 단일 스레드다 — 늘어난 것은 런타임(GC 등)이 쓸 수 있는 코어 수다.
	nthreads := runtime.GOMAXPROCS(0)
	fmt.Fprintf(os.Stderr, "[lattigo] threads=%s GOMAXPROCS=%d NumCPU=%d (op 내부 병렬화 없음)\n",
		*thlabel, nthreads, runtime.NumCPU())
	hdr := "library,exp,logN,q0,delta,depth,dnum,PCount,logP,logQ,logQP,bound,margin," +
		"maxLevel,level,op,mean_us,std_us,reps,digits,threads,nthreads,ok,err"
	if *expSel == 9 {
		hdr += ",batch_k,rep_mode"
	}
	fmt.Fprintln(fo, hdr)
	var fv *os.File
	if *expSel == 9 && *verifyout != "" {
		fv, err = os.Create(*verifyout)
		if err != nil {
			panic(err)
		}
		defer fv.Close()
		fmt.Fprintln(fv, "library,logN,depth,delta,dnum,level,level_before,level_after,"+
			"scale_before,scale_after,scale_ratio,max_abs_diff,bits_before,bits_after,ok")
	}
	var fp *os.File
	wantPrec := *expSel == 1 || *expSel == 3 || *expSel == 5 || *expSel == 7
	if wantPrec {
		fp, err = os.Create(*precout)
		if err != nil {
			panic(err)
		}
		defer fp.Close()
		fmt.Fprintln(fp, "library,exp,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits")
	}

	for _, c := range cfgs {
		if c.logN > 0 {
			logN = c.logN
		}
		if c.depth > 0 {
			depth = c.depth
		}
		if *expSel == 6 {
			levels = []int{depth}
		}
		logQ := []int{q0}
		for i := 0; i < depth; i++ {
			logQ = append(logQ, c.delta)
		}
		logPl := make([]int, c.pcount)
		for i := range logPl {
			logPl[i] = 60
		}

		params, perr := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
			LogN: logN, LogQ: logQ, LogP: logPl, LogDefaultScale: c.delta,
		})
		if perr != nil {
			msg := strings.NewReplacer(",", " ", "\n", " ").Replace(perr.Error())
			fmt.Fprintf(fo, "lattigo,%d,%d,%d,%d,%d,,,,,,,,,,,,,,,%s,%d,0,%s\n",
				*expSel, logN, q0, c.delta, depth, *thlabel, nthreads, msg)
			fmt.Fprintf(os.Stderr, "[skip] Δ=%d PCount=%d: %s\n", c.delta, c.pcount, msg)
			continue
		}

		// 런타임 값에서 뽑는다. 명목 비트(round(log2)) — 세 라이브러리 관례 통일.
		nominal := func(q uint64) int { return int(math.Round(math.Log2(float64(q)))) }
		qm, pm := params.Q(), params.P()
		sumQ, sumP := 0, 0
		for _, q := range qm {
			sumQ += nominal(q)
		}
		for _, p := range pm {
			sumP += nominal(p)
		}
		dnum := params.BaseRNSDecompositionVectorSize(params.MaxLevelQ(), params.MaxLevelP())
		maxDigit := 0
		for j := 0; j < dnum; j++ {
			lo, hi := j*len(pm), (j+1)*len(pm)
			if hi > len(qm) {
				hi = len(qm)
			}
			b := 0
			for k := lo; k < hi; k++ {
				b += nominal(qm[k])
			}
			if b > maxDigit {
				maxDigit = b
			}
		}
		bound := tc128Bound(logN)
		logQP := sumQ + sumP
		margin := bound - logQP
		maxLevel := params.MaxLevel()
		// 레벨별 digit 수 = ceil((L+1)/#P), dnum 상한
		var dparts []string
		for L := depth; L >= 1; L-- {
			p := (L + 1 + len(pm) - 1) / len(pm)
			if p > dnum {
				p = dnum
			}
			dparts = append(dparts, fmt.Sprintf("L%d=%d", L, p))
		}
		digits := strings.Join(dparts, ";")

		fmt.Fprintf(os.Stderr, "[lattigo exp%d] Δ=%d PCount=%d → dnum=%d logP=%d logQP=%d 여유=%d\n",
			*expSel, c.delta, len(pm), dnum, sumP, logQP, margin)

		kgen := ckks.NewKeyGenerator(params)
		sk, pk := kgen.GenKeyPairNew()
		rlk := kgen.GenRelinearizationKeyNew(sk)
		galEl := params.GaloisElementForRotation(1)
		gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
		evk := rlwe.NewMemEvaluationKeySet(rlk, gks...)
		ecd := ckks.NewEncoder(params)
		enc := ckks.NewEncryptor(params, pk)
		eval := ckks.NewEvaluator(params, evk)
		slots := params.MaxSlots()
		values := make([]float64, slots)
		for i := range values {
			values[i] = 0.5
		}

		// ══════════════════════════════════════════════════════════════════
		// exp 9 — 순수 레벨 강하(leveldrop). 아래 기존 8-op 루프는 건드리지 않는다.
		//
		// Rescale 과 다른 함수다(소스 확인, v6.2.0):
		//   Rescale   — 마지막 소수로 나눈다(스케일 변함)
		//   DropLevel — schemes/ckks/evaluator.go:466-469 주석 "No rescaling is applied
		//               during this procedure". 구현은 op0.Resize(deg, level-levels) →
		//               ring/poly.go:48 `pol.Coeffs = pol.Coeffs[:level+1]` = **슬라이스 절단**.
		//               ct.Scale 은 손대지 않는다.
		//   DropLevelNew — CopyNew(전체 깊은 복사) 후 DropLevel.
		// ⚠️ 따라서 Lattigo 의 in-place 강하는 산술이 전혀 없는 O(1) 연산이다.
		//    OpenFHE(타워 해제) · SEAL(잔여 타워 복사) 과 **작업량이 대응하지 않는다**.
		if *expSel == 9 {
			x, _ := makeInputs(slots)
			dec9 := ckks.NewDecryptor(params, sk)
			decode := func(ct *rlwe.Ciphertext) []float64 {
				pp := dec9.DecryptNew(ct)
				v := make([]float64, slots)
				if err := ecd.Decode(pp, v); err != nil {
					panic(err)
				}
				return v
			}
			for _, L := range levels {
				ptx := ckks.NewPlaintext(params, L)
				if err := ecd.Encode(x, ptx); err != nil {
					panic(err)
				}
				ct, err := enc.EncryptNew(ptx)
				if err != nil {
					panic(err)
				}

				// ---- 검증: 레벨 -1, 스케일 보존, 복호값 불변 ----
				lvB := ct.Level()
				sfB, _ := ct.Scale.Value.Float64()
				vB := decode(ct)
				ctD := eval.DropLevelNew(ct, 1)
				lvA := ctD.Level()
				sfA, _ := ctD.Scale.Value.Float64()
				vA := decode(ctD)
				mx := 0.0
				for i := range vB {
					if d := math.Abs(vB[i] - vA[i]); d > mx {
						mx = d
					}
				}
				okLv := lvA+1 == lvB
				if !okLv {
					fmt.Fprintf(os.Stderr, "  !! L=%d 레벨이 1 줄지 않았다 (%d -> %d)\n", L, lvB, lvA)
				}
				bitsB, bitsA := precisionBits(vB, x), precisionBits(vA, x)
				ratio := 0.0
				if sfB > 0 {
					ratio = sfA / sfB
				}
				okN := 0
				if okLv {
					okN = 1
				}
				if fv != nil {
					fmt.Fprintf(fv, "lattigo,%d,%d,%d,%d,%d,%d,%d,%.17g,%.17g,%.17g,%.6g,%.4f,%.4f,%d\n",
						logN, depth, c.delta, dnum, L, lvB, lvA, sfB, sfA, ratio, mx, bitsB, bitsA, okN)
				}

				emit := func(op string, m, sd float64, bk int, rm string) {
					fmt.Fprintf(fo, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%.3f,%.3f,%d,%s,%s,%d,1,,%d,%s\n",
						*expSel, logN, q0, c.delta, depth, dnum, len(pm), sumP, sumQ, logQP,
						bound, margin, maxLevel, L, op, m, sd, *reps, digits, *thlabel, nthreads, bk, rm)
				}

				// ---- 계측 1: out-of-place (DropLevelNew = CopyNew + 절단) ----
				mOop, sOop := measure(*reps, *warmup, func() error {
					eval.DropLevelNew(ct, 1)
					return nil
				})
				// ---- 계측 2(분해용): CopyNew 만 ----
				mCl, sCl := measure(*reps, *warmup, func() error {
					ct.CopyNew()
					return nil
				})
				// ---- 계측 3: in-place = Lattigo 가 레벨을 내리는 가장 싼 방법(O(1) 절단).
				//   파괴적이라 타이머 밖에서 K개 사본을 만들고 타이머 안에서 K회 수행한다.
				K := batchKFor(logN, L, *batchbudget, *batchkmax)
				pool := make([]*rlwe.Ciphertext, K)
				reset := func() {
					for i := 0; i < K; i++ {
						pool[i] = ct.CopyNew()
					}
				}
				runK := func() {
					for i := 0; i < K; i++ {
						eval.DropLevel(pool[i], 1)
					}
				}
				mIp, sIp := measureBatch(*reps, *warmup, K, reset, runK)
				if pool[0].Level()+1 != lvB {
					fmt.Fprintf(os.Stderr, "  !! L=%d in-place 강하가 레벨을 바꾸지 않았다\n", L)
				}

				// Lattigo 는 in-place 가 가장 싸다(O(1) 절단) → leveldrop == leveldrop_ip.
				emit("leveldrop", mIp, sIp, K, "batch")
				emit("leveldrop_ip", mIp, sIp, K, "batch")
				emit("leveldrop_oop", mOop, sOop, 1, "single")
				emit("clone_only", mCl, sCl, 1, "single")
				fo.Sync()
				if fv != nil {
					fv.Sync()
				}
				fmt.Fprintf(os.Stderr, "  L=%d leveldrop=%.4fus(K=%d) oop=%.3fus clone=%.3fus lv %d->%d scale %.g maxdiff %.3g\n",
					L, mIp, K, mOop, mCl, lvB, lvA, ratio, mx)
			}
			continue // 기존 8-op 루프·정밀도 블록을 건너뛴다
		}

		for _, L := range levels {
			pt := ckks.NewPlaintext(params, L)
			if err := ecd.Encode(values, pt); err != nil {
				panic(err)
			}
			ctA := ckks.NewCiphertext(params, 1, L)
			if err := enc.Encrypt(pt, ctA); err != nil {
				panic(err)
			}
			ctB := ckks.NewCiphertext(params, 1, L)
			if err := enc.Encrypt(pt, ctB); err != nil {
				panic(err)
			}
			outAdd := ckks.NewCiphertext(params, 1, L)
			outMulCP := ckks.NewCiphertext(params, 1, L)
			outMul2 := ckks.NewCiphertext(params, 2, L)
			outMulRlk := ckks.NewCiphertext(params, 1, L)
			outRot := ckks.NewCiphertext(params, 1, L)
			outRescale := ckks.NewCiphertext(params, 1, L-1)
			ctResIn := ckks.NewCiphertext(params, 1, L)
			if err := eval.MulRelin(ctA, ctB, ctResIn); err != nil {
				panic(err)
			}

			fns := map[string]func() error{
				"add_cc":     func() error { return eval.Add(ctA, ctB, outAdd) },
				"add_cp":     func() error { return eval.Add(ctA, pt, outAdd) },
				"mul_cp":     func() error { return eval.Mul(ctA, pt, outMulCP) },
				"mul_cc":     func() error { return eval.Mul(ctA, ctB, outMul2) },
				"mul_cc_rlk": func() error { return eval.MulRelin(ctA, ctB, outMulRlk) },
				"rescale":    func() error { return eval.Rescale(ctResIn, outRescale) },
				"rot1":       func() error { return eval.Rotate(ctA, 1, outRot) },
			}
			res := map[string][2]float64{}
			for _, op := range ops {
				if fn, okf := fns[op]; okf {
					m, s := measure(*reps, *warmup, fn)
					res[op] = [2]float64{m, s}
				}
			}
			// relin 직접 계측 — 다른 op 뒤에.
			for _, op := range ops {
				if op == "relin" {
					relinIn := ckks.NewCiphertext(params, 2, L)
					if err := eval.Mul(ctA, ctB, relinIn); err != nil {
						panic(err)
					}
					outRelin := ckks.NewCiphertext(params, 1, L)
					m, s := measure(*reps, *warmup, func() error {
						return eval.Relinearize(relinIn, outRelin)
					})
					res["relin"] = [2]float64{m, s}
				}
			}

			for _, op := range ops {
				r := res[op]
				fmt.Fprintf(fo, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%.3f,%.3f,%d,%s,%s,%d,1,\n",
					*expSel, logN, q0, c.delta, depth, dnum, len(pm), sumP, sumQ, logQP,
					bound, margin, maxLevel, L, op, r[0], r[1], *reps, digits, *thlabel, nthreads)
			}
			fo.Sync()
			fmt.Fprintf(os.Stderr, "  L=%d done\n", L)
		}

		// ---- 정밀도 : 타이밍이 끝난 뒤, 비밀키 암호화 ----
		// ★ 각 레벨에서 새로 암호화한 뒤 DropLevel 로 진입 — 끌고 내려가면 누적 노이즈가 섞인다.
		if wantPrec {
			x, _ := makeInputs(slots)
			wantRot := make([]float64, slots)
			for i := 0; i < slots; i++ {
				wantRot[i] = x[(i+1)%slots]
			}
			for rep := 0; rep < *precreps; rep++ {
				kg2 := ckks.NewKeyGenerator(params)
				sk2 := kg2.GenSecretKeyNew()
				g2 := kg2.GenGaloisKeysNew([]uint64{galEl}, sk2)
				evk2 := rlwe.NewMemEvaluationKeySet(nil, g2...)
				enc2 := ckks.NewEncryptor(params, sk2) // ★ 비밀키 암호화
				dec2 := ckks.NewDecryptor(params, sk2)
				ev2 := ckks.NewEvaluator(params, evk2)
				decode := func(ct *rlwe.Ciphertext) []float64 {
					p := dec2.DecryptNew(ct)
					v := make([]float64, slots)
					if err := ecd.Decode(p, v); err != nil {
						panic(err)
					}
					return v
				}
				prow := func(L int, path string, got, want []float64) {
					fmt.Fprintf(fp, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%.4f\n",
						*expSel, logN, q0, c.delta, depth, dnum, len(pm), sumP, maxDigit,
						L, path, rep, precisionBits(got, want))
				}
				for _, L := range levels {
					ptx := ckks.NewPlaintext(params, maxLevel)
					if err := ecd.Encode(x, ptx); err != nil {
						panic(err)
					}
					ct, err := enc2.EncryptNew(ptx) // 레벨마다 새로 암호화
					if err != nil {
						panic(err)
					}
					if d := maxLevel - L; d > 0 {
						ev2.DropLevel(ct, d) // 스케일 불변 drop
					}
					prow(L, "enc_dec", decode(ct), x)
					cr, err := ev2.RotateNew(ct, 1)
					if err != nil {
						panic(err)
					}
					prow(L, "rot1", decode(cr), wantRot)
				}
				fp.Sync()
			}
		}
	}
	fmt.Fprintf(os.Stderr, "wrote %s\n", *out)
}
