// param_dump_openfhe.cpp — 진단 전용. 벤치를 돌리지 않고 OpenFHE가 실제로 만든
// key-switch 파라미터(dnum=numPartQ, towersPerPart, P 개수/비트, 레벨별 digit 수)만 덤프한다.
//
// 두 가지 모드:
//   -mode presets  기존 v1 프리셋 3종 덤프 (§3 정합 기준 비교용, openfhe_bench.cpp와 동일 설정)
//   -mode sweep    (기본) 새 프리셋 설계용 dnum 스윕. logN × Δ × depth × dnum 전수.
//
// 값은 전부 런타임 API에서 뽑는다 — 문서 기본값·추정치를 쓰지 않는다.
// 추출 경로: CryptoParametersRNS::GetNumPartQ() / GetNumPerPartQ() / GetParamsP() / GetAuxBits()
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
using namespace lbcrypto;

// ---------------------------------------------------------------------------
// tc128 상한 — seal::CoeffModulus::MaxBitCount(N, sec_level_type::tc128).
// SEAL을 링크하지 않으므로 값을 상수로 둔다(README §측정 주의의 표와 같은 출처).
// ---------------------------------------------------------------------------
static int TC128Bound(int logN)
{
    switch (logN) {
        case 13: return 218;
        case 14: return 438;
        case 15: return 881;
        default: return -1;  // 미정의 — 여유 계산을 건너뛴다
    }
}

// 한 컨텍스트에서 뽑아낸 값 전부.
struct Dump {
    bool ok = false;
    std::string err;
    uint32_t auxBits = 0, dnum = 0, perPart = 0;
    uint32_t maxDigitBits = 0;     // max_j bitlen(∏ moduli in digit j) — sizeP 를 정하는 양
    size_t qCount = 0, pCount = 0;
    int logQ = 0, logP = 0;        // round(log2(prime)) 합 — 저장소 관례(명목 비트)
    int logQbits = 0, logPbits = 0;  // MSB 합 — 실제 비트 길이(소수는 2^k보다 크므로 보통 +1/prime)
    std::string ksTech;
    std::string digits;            // "L15=3;L14=3;..." (maxLevel → 1)
};

// round(log2)와 MSB를 함께 센다. 전자는 명목 비트(45), 후자는 실제 비트 길이(46).
static void AccumTowers(const std::vector<std::shared_ptr<ILNativeParams>>& towers,
                        int& nominal, int& msb, size_t& count)
{
    for (const auto& t : towers) {
        const auto& q = t->GetModulus();
        nominal += static_cast<int>(std::round(std::log2(q.ConvertToDouble())));
        msb += static_cast<int>(q.GetMSB());
        count++;
    }
}

// depth·Δ·q0·dnum 한 조합의 컨텍스트를 만들고 값을 뽑는다.
// dnum=0 이면 SetNumLargeDigits를 호출하지 않는다(OpenFHE 기본 규칙 관찰용).
static Dump Probe(int logN, int depth, int firstMod, int scaleMod, uint32_t dnum)
{
    Dump d;
    try {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(depth);
        params.SetScalingModSize(scaleMod);
        params.SetFirstModSize(firstMod);
        params.SetScalingTechnique(FIXEDMANUAL);
        // ★ HEStd_NotSet이 아니면 OpenFHE가 보안 검사에 맞춰 N을 조용히 올린다.
        params.SetSecurityLevel(HEStd_NotSet);
        params.SetRingDim(1u << logN);
        if (dnum > 0)
            params.SetNumLargeDigits(dnum);

        auto cc = GenCryptoContext(params);
        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        if (!cp) { d.err = "CryptoParametersRNS 캐스팅 실패"; return d; }

        // 링 차원이 요청대로 나왔는지 확인 — 조용히 올라갔으면 그 조합은 신뢰할 수 없다.
        const uint32_t nActual = cc->GetRingDimension();
        if (nActual != (1u << logN)) {
            d.err = "링 차원이 " + std::to_string(nActual) + " 로 변경됨(요청 " +
                    std::to_string(1u << logN) + ")";
            return d;
        }

        AccumTowers(cp->GetElementParams()->GetParams(), d.logQ, d.logQbits, d.qCount);
        if (auto paramsP = cp->GetParamsP())
            AccumTowers(paramsP->GetParams(), d.logP, d.logPbits, d.pCount);

        d.auxBits = cp->GetAuxBits();
        d.dnum    = cp->GetNumPartQ();
        d.perPart = cp->GetNumPerPartQ();
        d.ksTech  = (cp->GetKeySwitchTechnique() == HYBRID) ? "HYBRID" : "BV";

        // P 개수를 정하는 실제 양. rns-cryptoparameters.cpp:132-139 —
        //   maxBits = max_j bitlen(moduliPartQ[j]);  sizeP = ceil(maxBits / auxBits)
        // 명목 비트합(Δ의 정수배)이 아니라 **실제 소수곱의 비트길이**라 60 경계에서 갈린다.
        for (uint32_t j = 0; j < d.dnum; j++) {
            const uint32_t bits = cp->GetParamsPartQ(j)->GetModulus().GetLengthForBase(2);
            if (bits > d.maxDigitBits) d.maxDigitBits = bits;
        }

        // 레벨별 digit 수. 근거는 keyswitch-hybrid.cpp:325-329 —
        //   alpha = GetNumPerPartQ(); numPartQl = min(ceil(sizeQl/alpha), numPartQ)
        // sizeQl = level+1 (남은 타워 수). numPartQ는 최상위 레벨 기준 상한이다.
        std::ostringstream ds;
        for (int lvl = depth; lvl >= 1; lvl--) {
            const uint32_t sizeQl = static_cast<uint32_t>(lvl) + 1;
            uint32_t parts = (sizeQl + d.perPart - 1) / d.perPart;
            if (parts > d.dnum) parts = d.dnum;
            if (lvl != depth) ds << ";";
            ds << "L" << lvl << "=" << parts;
        }
        d.digits = ds.str();
        d.ok = true;
    }
    catch (const std::exception& e) {
        d.err = e.what();
    }
    catch (...) {
        d.err = "알 수 없는 예외";
    }
    // CSV 필드에 콤마/개행이 섞이면 스키마가 깨진다.
    for (auto& ch : d.err)
        if (ch == ',' || ch == '\n' || ch == '\r') ch = ' ';
    return d;
}

static void RunPresets()
{
    struct Preset { std::string name; int logN, depth, firstMod, scaleMod; };
    std::vector<Preset> presets = {
        {"small", 13, 5, 50, 45},
        {"medium", 14, 10, 55, 45},
        {"large", 15, 15, 60, 45},
    };
    for (auto& p : presets) {
        Dump d = Probe(p.logN, p.depth, p.firstMod, p.scaleMod, 0);
        if (!d.ok) { std::cout << "openfhe," << p.name << ",FAIL," << d.err << "\n"; continue; }
        std::cout << "openfhe," << p.name << "," << p.logN << "," << p.depth
                  << "," << d.qCount << "," << d.logQ
                  << "," << d.pCount << "," << d.logP
                  << "," << d.dnum << "," << d.perPart
                  << "," << d.ksTech << "," << d.auxBits << "\n";
        std::cout << "  levels: " << d.digits << "\n";
    }
}

static void RunSweep(const std::string& outPath)
{
    // 조합 정의 — q0는 60 고정, 깊이는 logN마다 다르다.
    const int q0 = 60;
    const std::vector<int> deltas = {40, 45, 50};
    struct Shape { int logN; std::vector<int> depths; };
    const std::vector<Shape> shapes = {
        {14, {5, 6, 7}},
        {15, {12, 13, 14, 15}},
    };

    std::ofstream csv(outPath);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << outPath << "\n"; std::exit(2); }
    csv << "logN,q0,delta,depth,dnum_req,ok,err,auxBits,ksTech,"
           "QCount,logQ,logQ_bits,dnum,perPart,maxDigitBits,PCount,logP,logP_bits,"
           "logQP,logQP_bits,bound_tc128,margin,digits\n";

    std::cout << "logN |  Δ | depth | QCount | logQ | dnum | PCount | logP | logQP | 상한 | 여유\n";
    std::cout << "-----+----+-------+--------+------+------+--------+------+-------+------+------\n";

    int nOk = 0, nFail = 0;
    for (const auto& sh : shapes) {
        for (int delta : deltas) {
            for (int depth : sh.depths) {
                // QCount = depth + 1 (FIXEDMANUAL, extra modulus 없음). dnum은 1..QCount 전수.
                const int qCountExpected = depth + 1;
                for (uint32_t dnum = 1; dnum <= static_cast<uint32_t>(qCountExpected); dnum++) {
                    Dump d = Probe(sh.logN, depth, q0, delta, dnum);
                    const int bound = TC128Bound(sh.logN);

                    csv << sh.logN << "," << q0 << "," << delta << "," << depth << "," << dnum << ","
                        << (d.ok ? 1 : 0) << "," << d.err << ",";
                    if (d.ok) {
                        const int logQP     = d.logQ + d.logP;
                        const int logQPbits = d.logQbits + d.logPbits;
                        const int margin    = bound - logQP;
                        csv << d.auxBits << "," << d.ksTech << ","
                            << d.qCount << "," << d.logQ << "," << d.logQbits << ","
                            << d.dnum << "," << d.perPart << "," << d.maxDigitBits << ","
                            << d.pCount << "," << d.logP << "," << d.logPbits << ","
                            << logQP << "," << logQPbits << "," << bound << "," << margin << ","
                            << d.digits << "\n";
                        std::cout << std::setw(4) << sh.logN << " |"
                                  << std::setw(3) << delta << " |"
                                  << std::setw(6) << depth << " |"
                                  << std::setw(7) << d.qCount << " |"
                                  << std::setw(5) << d.logQ << " |"
                                  << std::setw(5) << d.dnum << " |"
                                  << std::setw(7) << d.pCount << " |"
                                  << std::setw(5) << d.logP << " |"
                                  << std::setw(6) << logQP << " |"
                                  << std::setw(5) << bound << " |"
                                  << std::setw(5) << margin
                                  << (margin < 0 ? "  ✗ 초과" : "") << "\n";
                        nOk++;
                    }
                    else {
                        csv << ",,,,,,,,,,,,,," << "\n";
                        std::cout << std::setw(4) << sh.logN << " |"
                                  << std::setw(3) << delta << " |"
                                  << std::setw(6) << depth << " |"
                                  << std::setw(7) << "-" << " |"
                                  << std::setw(5) << "-" << " |"
                                  << std::setw(5) << dnum << " |  실패: " << d.err << "\n";
                        nFail++;
                    }
                }
            }
        }
    }
    csv.close();
    std::cout << "\n[dump] " << outPath << "  (성공 " << nOk << " / 실패 " << nFail << ")\n";
}

int main(int argc, char** argv)
{
    std::string mode = "sweep";
    std::string out  = "params_openfhe_dnum_sweep.csv";
    for (int i = 1; i < argc; i++) {
        if (!std::strcmp(argv[i], "-mode") && i + 1 < argc) mode = argv[++i];
        else if (!std::strcmp(argv[i], "-out") && i + 1 < argc) out = argv[++i];
        else { std::cerr << "사용법: param_dump_openfhe [-mode sweep|presets] [-out CSV]\n"; return 2; }
    }
    if (mode == "presets") RunPresets();
    else if (mode == "sweep") RunSweep(out);
    else { std::cerr << "알 수 없는 mode: " << mode << "\n"; return 2; }
    return 0;
}
