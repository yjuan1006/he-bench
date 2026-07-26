// param_dump_openfhe.cpp — 진단 전용. 벤치를 돌리지 않고 OpenFHE가 실제로 만든
// key-switch 파라미터(dnum=numPartQ, towersPerPart, P 개수/비트, 레벨별 digit 수)만 덤프한다.
//
// 컨텍스트 생성은 openfhe_bench.cpp와 완전히 동일한 설정을 쓴다(§3 정합 기준 비교용).
// 추출 경로: CryptoParametersRNS::GetNumPartQ() / GetNumPerPartQ() / GetParamsP() / GetAuxBits()
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"
#include <iostream>
#include <vector>
using namespace lbcrypto;

struct Preset { std::string name; int logN, depth, firstMod, scaleMod; };

int main()
{
    std::vector<Preset> presets = {
        {"small", 13, 5, 50, 45},
        {"medium", 14, 10, 55, 45},
        {"large", 15, 15, 60, 45},
    };
    for (auto& p : presets) {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(p.depth);
        params.SetScalingModSize(p.scaleMod);
        params.SetFirstModSize(p.firstMod);
        params.SetScalingTechnique(FIXEDMANUAL);
        params.SetSecurityLevel(HEStd_NotSet);
        params.SetRingDim(1u << p.logN);
        auto cc = GenCryptoContext(params);

        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        const auto& towersQ = cc->GetCryptoParameters()->GetElementParams()->GetParams();
        int logQ = 0;
        for (auto& t : towersQ) logQ += (int)std::round(std::log2(t->GetModulus().ConvertToDouble()));

        int logP = 0; size_t pCount = 0;
        if (auto paramsP = cp->GetParamsP()) {
            for (auto& t : paramsP->GetParams()) {
                logP += (int)std::round(std::log2(t->GetModulus().ConvertToDouble()));
                pCount++;
            }
        }
        uint32_t dnum = cp->GetNumPartQ();
        uint32_t perPart = cp->GetNumPerPartQ();

        std::cout << "openfhe," << p.name << "," << p.logN << "," << p.depth
                  << "," << towersQ.size() << "," << logQ
                  << "," << pCount << "," << logP
                  << "," << dnum << "," << perPart
                  << "," << (cp->GetKeySwitchTechnique() == HYBRID ? "HYBRID" : "BV")
                  << "," << cp->GetAuxBits() << "\n";

        // 레벨별 digit 수: HYBRID에서 레벨 L(=towers L+1개)일 때 실제로 쓰이는 파트 수는
        // ceil((L+1)/perPart) 로 줄어든다. numPartQ는 최상위 레벨 기준 상한이다.
        std::cout << "  levels:";
        for (int lvl = p.depth; lvl >= 1; lvl--) {
            int towers = lvl + 1;
            int parts = (towers + (int)perPart - 1) / (int)perPart;
            if (parts > (int)dnum) parts = dnum;
            std::cout << " L" << lvl << "=" << parts;
        }
        std::cout << "\n";
    }
    return 0;
}
