//go:build ignore

// ksprec_lattigo.go — 새 프리셋 후보 비교 참조 (Lattigo). 절차는 ksprec_openfhe.cpp 와 동일.
// ★ lattigo_precision.go(v1 정본)는 건드리지 않는다 — 그쪽은 프리셋 고정·공개키다.
//
// ⚠️ Lattigo는 dnum을 직접 못 정한다. core/rlwe/params.go:543
// BaseRNSDecompositionVectorSize = ceil(#Q / #P) 이므로 **dnum은 LogP 길이의 종속변수**다.
// OpenFHE처럼 (logP, dnum)을 독립으로 놓을 수 없다 — 재현 가능한 것은
// "OpenFHE의 (logP, dnum) 쌍이 마침 ceil(#Q/#P) 관계를 만족하는" 점뿐이다.
// #Q=14(q0 60 + Δ40×13)에서:
//     LogP {60}         → logP  60, dnum 14   ← OpenFHE dnum=14/logP=60  과 일치
//     LogP {60,60}      → logP 120, dnum  7   ← OpenFHE dnum= 7/logP=120 과 일치
//     LogP {60,60,60}   → logP 180, dnum  5   ← OpenFHE dnum= 5/logP=180 과 일치
//     LogP {60}×4       → logP 240, dnum  4   ← OpenFHE dnum= 4/logP=240 과 일치
//     LogP {60}×5       → logP 300, dnum  3   ← OpenFHE는 dnum=2에서 logP 300 (불일치)
// 기본값은 {60,60}(dnum 7, logP 120) — v1 large Lattigo와 같은 logP라 §5.3과 이어진다.
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"strings"

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
func (r *rng) val() float64 {
	return float64(r.next()>>11)/9007199254740992.0*2.0 - 1.0
}
func makeInputs(slots int) (x, y []float64) {
	r := newRng()
	x = make([]float64, slots)
	y = make([]float64, slots)
	for i := 0; i < slots; i++ {
		x[i] = r.val()
		y[i] = r.val()
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

func main() {
	reps := flag.Int("reps", 5, "반복 횟수")
	logPFlag := flag.String("logp", "60,60", "특수소수 비트 목록 (dnum = ceil(#Q/#P) 로 종속 결정)")
	combos := flag.String("combos", "", "\"depth:delta:pcount,...\" — 지정 시 -logp 를 무시하고 이 목록을 순회한다")
	logNf := flag.Int("logN", 15, "링 차원 지수")
	q0f := flag.Int("q0", 60, "첫 모듈러스 비트")
	flag.Parse()

	fmt.Println("library,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits")

	type combo struct{ depth, delta, pcount int }
	var list []combo
	if *combos != "" {
		for _, tok := range strings.Split(*combos, ",") {
			var dp, dl, pc int
			if _, err := fmt.Sscanf(strings.TrimSpace(tok), "%d:%d:%d", &dp, &dl, &pc); err != nil {
				fmt.Fprintf(os.Stderr, "[warn] 조합 파싱 실패: %s\n", tok)
				continue
			}
			list = append(list, combo{dp, dl, pc})
		}
	} else {
		pc := len(strings.Split(*logPFlag, ","))
		list = append(list, combo{13, 40, pc})
	}

	for _, cb := range list {
		runOne(*logNf, *q0f, cb.depth, cb.delta, cb.pcount, *reps)
	}
}

func runOne(logN, q0, depth, delta, pcount, reps int) {
	logQ := []int{q0}
	for i := 0; i < depth; i++ {
		logQ = append(logQ, delta)
	}
	logP := make([]int, pcount)
	for i := range logP {
		logP[i] = 60
	}

	params, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
		LogN: logN, LogQ: logQ, LogP: logP, LogDefaultScale: delta,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "[skip] depth=%d Δ=%d PCount=%d: %v\n", depth, delta, pcount, err)
		return
	}
	maxLevel := params.MaxLevel()
	slots := params.MaxSlots()

	// logP / dnum / maxDigitBits 를 런타임 값에서 뽑는다.
	qm, pm := params.Q(), params.P()
	// ⚠️ 명목 비트(round(log2))로 센다 — 실제 비트길이(bits.Len64)를 쓰면 SEAL과
	// 비교 불가해진다. Lattigo는 2^k 바로 위, SEAL은 바로 아래 소수를 고른다.
	nominal := func(q uint64) int { return int(math.Round(math.Log2(float64(q)))) }
	sumP := 0
	for _, p := range pm {
		sumP += nominal(p)
	}
	dnum := params.BaseRNSDecompositionVectorSize(params.MaxLevelQ(), params.MaxLevelP())
	// digit j = Q 프라임 [j*#P, (j+1)*#P) — 그 곱의 비트길이가 digit 크기다.
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

	x, _ := makeInputs(slots)
	wantRot := make([]float64, slots)
	for i := 0; i < slots; i++ {
		wantRot[i] = x[(i+1)%slots]
	}

	for rep := 0; rep < reps; rep++ {
		kgen := ckks.NewKeyGenerator(params)
		sk := kgen.GenSecretKeyNew()
		galEl := params.GaloisElementForRotation(1)
		gks := kgen.GenGaloisKeysNew([]uint64{galEl}, sk)
		evk := rlwe.NewMemEvaluationKeySet(nil, gks...)
		ecd := ckks.NewEncoder(params)
		enc := ckks.NewEncryptor(params, sk) // ★ 비밀키 암호화
		dec := ckks.NewDecryptor(params, sk)
		eval := ckks.NewEvaluator(params, evk)

		decode := func(ct *rlwe.Ciphertext) []float64 {
			pt := dec.DecryptNew(ct)
			v := make([]float64, slots)
			if err := ecd.Decode(pt, v); err != nil {
				panic(err)
			}
			return v
		}
		report := func(path string, got, want []float64) {
			fmt.Printf("lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%.4f\n",
				logN, q0, delta, depth, dnum, len(pm), sumP, maxDigit,
				maxLevel, path, rep, precisionBits(got, want))
		}

		ptX := ckks.NewPlaintext(params, maxLevel)
		if err := ecd.Encode(x, ptX); err != nil {
			panic(err)
		}
		ctX, err := enc.EncryptNew(ptX)
		if err != nil {
			panic(err)
		}
		report("enc_dec", decode(ctX), x)

		cRot, err := eval.RotateNew(ctX, 1)
		if err != nil {
			panic(err)
		}
		report("rot1", decode(cRot), wantRot)
	}
}
