//go:build ignore

// param_dump_lattigo_grid.go — 프리셋 격자 탐색용 Lattigo 파라미터 덤프. 벤치 없음.
//
// ⚠️ Lattigo 는 dnum 이 독립 변수가 아니다. core/rlwe/params.go:543
// BaseRNSDecompositionVectorSize = ceil(#Q/#P) 이므로 PCount 를 정하면 dnum 이 따라온다.
// 값은 전부 런타임 API 에서 뽑는다(params.Q()/params.P()/BaseRNSDecompositionVectorSize).
// 비트는 명목(round(log2)) — OpenFHE/SEAL 과 관례를 맞춘다.
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"strings"

	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

func bound(logN int) int {
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

func main() {
	logN := flag.Int("logN", 15, "")
	q0 := flag.Int("q0", 60, "")
	dmin := flag.Int("depth-min", 8, "")
	dmax := flag.Int("depth-max", 11, "")
	dlmin := flag.Int("delta-min", 45, "")
	dlmax := flag.Int("delta-max", 70, "")
	pcmax := flag.Int("pcount-max", 5, "")
	out := flag.String("out", "params_lattigo_grid.csv", "")
	flag.Parse()

	f, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	fmt.Fprintln(f, "library,logN,q0,delta,depth,QCount,logQ,PCount,logP,dnum,maxDigitBits,logQP,bound,margin,ok,err,digits")

	nOk, nFail := 0, 0
	for depth := *dmin; depth <= *dmax; depth++ {
		for delta := *dlmin; delta <= *dlmax; delta++ {
			for pc := 1; pc <= *pcmax; pc++ {
				logQ := []int{*q0}
				for i := 0; i < depth; i++ {
					logQ = append(logQ, delta)
				}
				logP := make([]int, pc)
				for i := range logP {
					logP[i] = 60
				}
				params, perr := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
					LogN: *logN, LogQ: logQ, LogP: logP, LogDefaultScale: delta,
				})
				if perr != nil {
					msg := strings.NewReplacer(",", " ", "\n", " ").Replace(perr.Error())
					fmt.Fprintf(f, "lattigo,%d,%d,%d,%d,,,%d,,,,,%d,,0,%s,\n",
						*logN, *q0, delta, depth, pc, bound(*logN), msg)
					nFail++
					continue
				}
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
				var dp []string
				for L := depth; L >= 1; L-- {
					p := (L + 1 + len(pm) - 1) / len(pm)
					if p > dnum {
						p = dnum
					}
					dp = append(dp, fmt.Sprintf("L%d=%d", L, p))
				}
				qp := sumQ + sumP
				fmt.Fprintf(f, "lattigo,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,1,,%s\n",
					*logN, *q0, delta, depth, len(qm), sumQ, len(pm), sumP, dnum, maxDigit,
					qp, bound(*logN), bound(*logN)-qp, strings.Join(dp, ";"))
				nOk++
			}
		}
	}
	fmt.Printf("[lattigo grid] %s  (성공 %d / 실패 %d)\n", *out, nOk, nFail)
}
