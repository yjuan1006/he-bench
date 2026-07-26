//go:build ignore

// param_dump_lattigo.go — 진단 전용. 벤치를 돌리지 않고 Lattigo가 실제로 만든
// key-switch 파라미터(P 개수/비트, 레벨별 RNS 분해 digit 수)만 덤프한다.
//
// 프리셋 정의는 lattigo_bench.go와 동일해야 한다(§3 정합 기준 비교용).
// 추출 경로:
//   params.QCount() / params.LogQ() / params.PCount() / params.LogP()
//   params.BaseRNSDecompositionVectorSize(levelQ, levelP)
//     → 소스(core/rlwe/params.go:543): Ceil(lenQi/lenPi) = (levelQ+levelP+1)/(levelP+1)
package main

import (
	"fmt"

	"github.com/tuneinsight/lattigo/v6/schemes/ckks"
)

type preset struct {
	Name string
	LogN int
	LogQ []int
	LogP []int
}

func main() {
	mk := func(name string, logN, first, depth, scale int, logP []int) preset {
		q := []int{first}
		for i := 0; i < depth; i++ {
			q = append(q, scale)
		}
		return preset{name, logN, q, logP}
	}
	presets := []preset{
		mk("small", 13, 50, 5, 45, []int{55}),
		mk("medium", 14, 55, 10, 45, []int{55, 55}),
		mk("large", 15, 60, 15, 45, []int{60, 60}),
	}

	fmt.Println("lib,preset,logN,maxLevel,QCount,logQ,PCount,logP")
	for _, p := range presets {
		params, err := ckks.NewParametersFromLiteral(ckks.ParametersLiteral{
			LogN: p.LogN, LogQ: p.LogQ, LogP: p.LogP, LogDefaultScale: 45,
		})
		if err != nil {
			fmt.Println("ERR", p.Name, err)
			continue
		}
		maxLevel := params.MaxLevel()
		levelP := params.PCount() - 1
		fmt.Printf("lattigo,%s,%d,%d,%d,%.0f,%d,%.0f\n",
			p.Name, params.LogN(), maxLevel, params.QCount(), params.LogQ(),
			params.PCount(), params.LogP())
		fmt.Printf("  levels(levelP=%d):", levelP)
		for l := maxLevel; l >= 1; l-- {
			fmt.Printf(" L%d=%d", l, params.BaseRNSDecompositionVectorSize(l, levelP))
		}
		fmt.Println()
	}
}
