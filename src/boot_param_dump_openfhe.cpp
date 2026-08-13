// boot_param_dump_openfhe.cpp — 부트스트래핑 파라미터 격자 덤프 (1단계). 벤치·keygen 없음.
//
// `param_dump_openfhe.cpp` 의 구조를 따르되 **부트스트래핑 체인**을 다룬다. 기존 파일은
// 건드리지 않는다(8-op 프리셋 A~D 의 정본 추출 경로라 손대면 그 값들의 재현성이 깨진다).
//
// ⚠️ **EvalBootstrapKeyGen 은 호출하지 않는다.** 파라미터만 본다.
//    EvalBootstrapSetup 은 `precompute=false` 로 부른다 — 이 인자를 켜면 인코딩·디코딩
//    행렬 평문을 전부 미리 만들어(`ckksrns-fhe.cpp:153` 의 `if (precompute)` 블록)
//    조합당 수십 초·수 GB 가 든다. correctionFactor 설정은 그 블록 **앞**(:100-119)이라
//    precompute 없이도 런타임 값을 읽을 수 있다.
//
// 모드
//   -mode grid   (기본) q0 × Δ × 잔여L × levelBudget × dnum 격자
//   -mode cf     correctionFactor 규칙 실측 검증 (q0 고정, Δ 스윕)
//   -mode dnum   §8.5 규칙 5(dnum 유효 조건)이 부트 체인에서도 성립하는지 예측 대조
//   -mode repro  논문 Table 5.8 Set II 재현 (도구 검증용. 프리셋 후보 아님)
//   -mode diag   Set II 재현 격차의 성분 분해 (단건. 격자 아님)
//
// 값은 전부 런타임 API 추출이다. 예외는 K 하나뿐이며 그 자리에 근거를 남겼다.
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"
#include "scheme/ckksrns/ckksrns-fhe.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>
using namespace lbcrypto;

// ---------------------------------------------------------------------------
// 보안 상한. **8-op 과 출처가 다르다.**
//   8-op(A~D)   : seal::CoeffModulus::MaxBitCount(N, tc128) = 218 / 438 / 881
//   부트 세트    : Bossuat et al., IACR ePrint 2024/463, Table 5.2
//                 (λ=128, uniform ternary, σ=3.19) = 214 / 430 / 868 / 1747
// SEAL 의 MaxBitCount 는 N=32768 이 최대라 logN 16 상한을 주지 못한다.
// ---------------------------------------------------------------------------
static int Bound(int logN)
{
    switch (logN) {
        case 13: return 214;
        case 14: return 430;
        case 15: return 868;
        case 16: return 1747;
        default: return -1;
    }
}

// K — 근사 구간 [-K, K]. **OpenFHE 는 이 값을 API 로 노출하지 않는다.**
// `ckksrns-fhe.h:424` 의 컴파일 상수 `K_UNIFORM = 512` (SPARSE 는 K_SPARSE=28,
// SPARSE_ENCAPSULATED 는 16). 이 한 칸만 소스 상수이고 나머지는 전부 런타임 추출이다.
static constexpr uint32_t K_UNIFORM_SRC = 512;

// ---------------------------------------------------------------------------

struct Ctx {
    bool ok = false;
    std::string err;
    uint32_t dnum = 0, perPart = 0, auxBits = 0, maxDigitBits = 0, correctionFactor = 0;
    size_t qCount = 0, pCount = 0;
    int logQ = 0, logP = 0;              // round(log2) 합 — 저장소 관례(명목 비트)
    std::vector<int> qNominal;           // 타워별 명목 비트 (index 0 = q0)
    int deg = 0;                         // ckksrns-fhe.cpp:534 의 deg. 가드는 deg <= correctionFactor
};

static void ScrubCsv(std::string& s)
{
    for (auto& ch : s)
        if (ch == ',' || ch == '\n' || ch == '\r' || ch == '"') ch = ' ';
}

// 컨텍스트 하나를 만들고 EvalBootstrapSetup(precompute=false) 까지만 진행한다.
static Ctx Build(int logN, uint32_t numSlots, int totalDepth, int q0, int delta, uint32_t dnum,
                 const std::vector<uint32_t>& levelBudget)
{
    Ctx c;
    try {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(totalDepth);          // 잔여 L + 부트 깊이
        params.SetScalingModSize(delta);
        params.SetFirstModSize(q0);
        params.SetScalingTechnique(FIXEDMANUAL);
        params.SetSecretKeyDist(UNIFORM_TERNARY);           // dense. sparse-secret encapsulation 없음
        params.SetSecurityLevel(HEStd_NotSet);              // 링 차원을 우리가 강제한다
        params.SetRingDim(1u << logN);
        if (dnum > 0)
            params.SetNumLargeDigits(dnum);

        auto cc = GenCryptoContext(params);
        cc->Enable(PKE);
        cc->Enable(KEYSWITCH);
        cc->Enable(LEVELEDSHE);
        cc->Enable(ADVANCEDSHE);
        cc->Enable(FHE);

        const uint32_t nActual = cc->GetRingDimension();
        if (nActual != (1u << logN)) {
            c.err = "링 차원이 " + std::to_string(nActual) + " 로 변경됨";
            return c;
        }

        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        if (!cp) { c.err = "CryptoParametersRNS 캐스팅 실패"; return c; }

        for (const auto& t : cp->GetElementParams()->GetParams()) {
            const int b = static_cast<int>(
                std::round(std::log2(t->GetModulus().ConvertToDouble())));
            c.qNominal.push_back(b);
            c.logQ += b;
            c.qCount++;
        }
        if (auto pp = cp->GetParamsP()) {
            for (const auto& t : pp->GetParams()) {
                c.logP += static_cast<int>(std::round(std::log2(t->GetModulus().ConvertToDouble())));
                c.pCount++;
            }
        }

        c.auxBits = cp->GetAuxBits();
        c.dnum    = cp->GetNumPartQ();
        c.perPart = cp->GetNumPerPartQ();
        for (uint32_t j = 0; j < c.dnum; j++) {
            const uint32_t bits = cp->GetParamsPartQ(j)->GetModulus().GetLengthForBase(2);
            if (bits > c.maxDigitBits) c.maxDigitBits = bits;
        }

        // ★ keygen 전까지. precompute=false 로 correctionFactor 설정 구간만 통과시킨다.
        cc->EvalBootstrapSetup(levelBudget, {0, 0}, numSlots, /*correctionFactor=*/0,
                               /*precompute=*/false);
        c.correctionFactor = cc->GetCKKSBootCorrectionFactor();

        // ckksrns-fhe.cpp:532-537 과 같은 계산.
        //   qDouble = GetBigModulus()  = 비합성 스케일링에서 Q[0] (= q0 소수)
        //   powP    = 2^GetPlaintextModulus(); CKKS 의 평문 모듈러스는 scalingModSize 다
        //             (gen-cryptocontext-ckksrns-internal.h:95 에서 EncodingParams 로 들어간다)
        // ⚠️ 그 가드(`deg > correctionFactor` 예외)는 EvalBootstrapSetup 이 아니라
        //    **EvalBootstrap 본체**(:429-537)에 있다. keygen 없이 예외를 띄울 수 없으므로
        //    라이브러리와 같은 입력으로 같은 식을 계산해 대조한다.
        const double qDouble = cp->GetElementParams()->GetParams()[0]->GetModulus().ConvertToDouble();
        const double powP    = std::pow(2.0, static_cast<double>(cp->GetPlaintextModulus()));
        c.deg = static_cast<int>(std::round(std::log2(qDouble / powP)));

        c.ok = true;
    }
    catch (const std::exception& e) { c.err = e.what(); }
    catch (...) { c.err = "알 수 없는 예외"; }
    ScrubCsv(c.err);
    return c;
}

static const char* HEADER =
    "library,logN,numSlots,q0,delta,residual_L,"
    "boot_depth,levelBudget_c2s,levelBudget_s2c,evalmod_levels,K,"
    "QCount_boot,logQ_boot,PCount_boot,logP_boot,logQP_boot,"
    "QCount_residual,logQ_residual,logP_residual,logQP_residual,"
    "dnum,maxDigitBits,margin_1747,"
    "mod1_degree,mod1_inv_degree,log_message_ratio,ephemeral_secret_weight,in_scale_log2,"
    "ok,fail_reason\n";

// 한 행. ctx 가 null 이면 컨텍스트를 만들지 않은 경우(사전 가지치기)다.
static void Emit(std::ofstream& csv, int logN, uint32_t numSlots, int q0, int delta, int L,
                 uint32_t bootDepth, uint32_t lb0, uint32_t lb1, uint32_t evalmod,
                 const Ctx* c, uint32_t dnumReq, const std::string& forcedFail)
{
    csv << "openfhe," << logN << "," << numSlots << "," << q0 << "," << delta << "," << L << ","
        << bootDepth << "," << lb0 << "," << lb1 << "," << evalmod << "," << K_UNIFORM_SRC << ",";

    if (!c || !c->ok) {
        std::string why = forcedFail;
        if (c && !c->ok) why = c->err;
        ScrubCsv(why);
        csv << ",,,,,,,,," << dnumReq << ",,,"
            << ",," << (q0 - delta) << ",," << delta << ",0," << why << "\n";
        return;
    }

    // 잔여 체인 = 아래 (L+1) 타워. OpenFHE 는 P 가 컨텍스트 하나에 하나뿐이라
    // 잔여 구간도 같은 P 를 쓴다 (Lattigo 는 잔여/부트 파라미터가 분리돼 있다 — 비대칭).
    int logQres = 0;
    for (int i = 0; i <= L && i < static_cast<int>(c->qNominal.size()); i++)
        logQres += c->qNominal[i];

    const int logQP    = c->logQ + c->logP;
    const int logQPres = logQres + c->logP;
    const int bound    = Bound(logN);
    const int margin   = bound - logQP;

    std::string fail;
    if (c->deg > static_cast<int>(c->correctionFactor))
        fail = "correctionFactor 위반: deg=" + std::to_string(c->deg) +
               " > cf=" + std::to_string(c->correctionFactor);
    if (logQP > bound) {
        if (!fail.empty()) fail += " / ";
        fail += "logQP_boot " + std::to_string(logQP) + " > " + std::to_string(bound);
    }
    const int ok = fail.empty() ? 1 : 0;

    csv << c->qCount << "," << c->logQ << "," << c->pCount << "," << c->logP << "," << logQP << ","
        << (L + 1) << "," << logQres << "," << c->logP << "," << logQPres << ","
        << c->dnum << "," << c->maxDigitBits << "," << margin << ","
        << ",," << (q0 - delta) << ",," << delta << ","          // OpenFHE 는 mod1_degree /
        << ok << "," << fail << "\n";                           // inv_degree / 캡슐화 모드가 없다
}

// §8.5 규칙 4 예측: digit 별 명목 비트합의 최대 → PCount = ceil(maxBits/auxBits).
static int PredictMaxDigitBits(int sizeQ, int q0, int delta, uint32_t dnum)
{
    const int a = (sizeQ + static_cast<int>(dnum) - 1) / static_cast<int>(dnum);
    int best    = 0;
    for (uint32_t j = 0; j < dnum; j++) {
        const int lo = static_cast<int>(j) * a;
        const int hi = std::min(lo + a, sizeQ);
        int bits     = 0;
        for (int k = lo; k < hi; k++) bits += (k == 0) ? q0 : delta;
        best = std::max(best, bits);
    }
    return best;
}

// §8.5 규칙 5: a = ceil(sizeQ/dnum) 일 때 sizeQ <= a*(dnum-1) 이면 컨텍스트 생성 실패.
static bool DnumPredictedValid(int sizeQ, uint32_t dnum)
{
    if (dnum <= 1) return true;
    const int a = (sizeQ + static_cast<int>(dnum) - 1) / static_cast<int>(dnum);
    return !(sizeQ <= a * (static_cast<int>(dnum) - 1));
}

// ---------------------------------------------------------------------------

struct GridCfg {
    int logN = 16;
    uint32_t numSlots = 1u << 15;
    // 2026-08-12 축 재설계 (§10.7-20): Δ ≤ 50 은 부트 파탄(자릿수 4~6배), Δ ≥ 60 은
    // scalingModSize 제약으로 불가. q0 는 Δ 에 종속(0 < q0−Δ ≤ 7, q0 ≤ 60).
    std::vector<int> q0s    = {53, 54, 55, 56, 57, 58, 59, 60};
    std::vector<int> deltas = {52, 53, 55, 58, 59};
    int lmin = 3, lmax = 30;
    int cfLimit = 7;                    // q0 - Δ 필터 (correctionFactor). 런타임 값과 대조한다
    std::vector<std::pair<uint32_t, uint32_t>> budgets = {{1,1},{2,2},{3,3},{4,4},{3,4},{4,3}};
};

static void RunGrid(const std::string& out, const GridCfg& g)
{
    std::ofstream csv(out);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; std::exit(2); }
    csv << HEADER;

    const int bound = Bound(g.logN);

    // 부트 깊이는 컨텍스트 없이 얻는다 (정적 함수).
    std::map<std::pair<uint32_t,uint32_t>, uint32_t> bootDepth, evalmod;
    for (auto& lb : g.budgets) {
        const std::vector<uint32_t> v{lb.first, lb.second};
        const uint32_t bd = FHECKKSRNS::GetBootstrapDepth(v, UNIFORM_TERNARY);
        bootDepth[lb] = bd;
        evalmod[lb]   = bd - lb.first - lb.second;      // = approxModDepth (런타임 유도)
    }

    std::cout << "levelBudget → 부트 깊이 (FHECKKSRNS::GetBootstrapDepth, UNIFORM_TERNARY)\n";
    for (auto& lb : g.budgets)
        std::cout << "  {" << lb.first << "," << lb.second << "} → " << bootDepth[lb]
                  << "  (approxModDepth " << evalmod[lb] << ")\n";

    // 컨텍스트는 (q0, Δ, sizeQ, dnum) 에만 의존한다 — levelBudget 은 sizeQ 를 통해서만 들어간다.
    // 그래서 sizeQ 로 묶어 한 번 만들고 해당하는 (L, levelBudget) 행을 전부 찍는다.
    long nCtx = 0, nRow = 0, nSkipQP = 0, nSkipPred = 0, nFail = 0;

    for (int q0 : g.q0s) {
        for (int delta : g.deltas) {
            if (q0 - delta > g.cfLimit || q0 - delta < 1) continue;  // 0 < q0−Δ ≤ 7

            // sizeQ → 그 sizeQ 를 만드는 (L, levelBudget) 목록
            std::map<int, std::vector<std::pair<int, std::pair<uint32_t,uint32_t>>>> bySize;
            for (int L = g.lmin; L <= g.lmax; L++)
                for (auto& lb : g.budgets)
                    bySize[L + static_cast<int>(bootDepth[lb]) + 1].push_back({L, lb});

            for (auto& [sizeQ, targets] : bySize) {
                const int logQnom = q0 + delta * (sizeQ - 1);

                // 최소 logP(=auxBits 1개) 로도 상한을 넘으면 어떤 dnum 도 못 살린다.
                if (logQnom + 60 > bound) {
                    for (auto& [L, lb] : targets) {
                        Emit(csv, g.logN, g.numSlots, q0, delta, L, bootDepth[lb], lb.first,
                             lb.second, evalmod[lb], nullptr, 0,
                             "상한 초과 확정: logQ_boot(명목) " + std::to_string(logQnom) +
                             " + 최소 logP 60 > " + std::to_string(bound));
                        nRow++; nSkipQP++;
                    }
                    continue;
                }

                for (uint32_t dnum = 1; dnum <= static_cast<uint32_t>(sizeQ); dnum++) {
                    if (!DnumPredictedValid(sizeQ, dnum)) continue;   // §8.5 규칙 5

                    // §8.5 규칙 4 로 logP 를 예측해 확정 탈락은 컨텍스트를 만들지 않는다.
                    // 여유 60(=auxBits 1개)을 둬 예측 오차가 판정을 뒤집지 못하게 한다.
                    const int predP = 60 * ((PredictMaxDigitBits(sizeQ, q0, delta, dnum) + 59) / 60);
                    if (logQnom + predP > bound + 60) {
                        for (auto& [L, lb] : targets) {
                            Emit(csv, g.logN, g.numSlots, q0, delta, L, bootDepth[lb], lb.first,
                                 lb.second, evalmod[lb], nullptr, dnum,
                                 "예측 탈락(§8.5 규칙4): logQ " + std::to_string(logQnom) +
                                 " + 예측 logP " + std::to_string(predP) + " > " +
                                 std::to_string(bound) + "+60 → 컨텍스트 미생성");
                            nRow++; nSkipPred++;
                        }
                        continue;
                    }

                    const std::vector<uint32_t> lbAny{targets[0].second.first, targets[0].second.second};
                    Ctx c = Build(g.logN, g.numSlots, sizeQ - 1, q0, delta, dnum, lbAny);
                    nCtx++;
                    if (!c.ok) nFail++;

                    for (auto& [L, lb] : targets) {
                        Emit(csv, g.logN, g.numSlots, q0, delta, L, bootDepth[lb], lb.first,
                             lb.second, evalmod[lb], &c, dnum, "");
                        nRow++;
                    }
                }
            }
            std::cout << "  q0=" << q0 << " Δ=" << delta << " 완료 (누적 컨텍스트 " << nCtx << ")\n"
                      << std::flush;
        }
    }
    csv.close();
    std::cout << "\n[boot grid] " << out << "\n"
              << "  행 " << nRow << " / 생성한 컨텍스트 " << nCtx << " (실패 " << nFail << ")\n"
              << "  미생성: 상한 확정 탈락 " << nSkipQP << " 행, 규칙4 예측 탈락 " << nSkipPred << " 행\n";
}

// correctionFactor 규칙 실측: q0 고정, Δ 스윕. 런타임 cf 와 deg 를 그대로 찍는다.
static void RunCf(const std::string& out, int logN, uint32_t numSlots, int q0,
                  const std::vector<int>& deltas)
{
    std::ofstream csv(out);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; std::exit(2); }
    csv << "logN,numSlots,q0,delta,q0_minus_delta,correctionFactor_runtime,deg_runtime,"
           "guard_violated,setup_threw,err\n";

    std::cout << "\n=== correctionFactor 실측 (logN " << logN << ", slots " << numSlots
              << ", FIXEDMANUAL, UNIFORM_TERNARY) ===\n"
              << "  q0-Δ  Δ    cf   deg  가드위반  Setup예외\n";
    for (int d : deltas) {
        Ctx c = Build(logN, numSlots, 20, q0, d, 3, {3, 3});
        const bool threw = !c.ok;
        const int viol   = (!threw && c.deg > static_cast<int>(c.correctionFactor)) ? 1 : 0;
        csv << logN << "," << numSlots << "," << q0 << "," << d << "," << (q0 - d) << ","
            << (threw ? 0 : c.correctionFactor) << "," << (threw ? 0 : c.deg) << ","
            << viol << "," << (threw ? 1 : 0) << "," << c.err << "\n";
        std::cout << std::setw(6) << (q0 - d) << std::setw(5) << d
                  << std::setw(6) << (threw ? -1 : static_cast<int>(c.correctionFactor))
                  << std::setw(6) << (threw ? -1 : c.deg)
                  << std::setw(10) << (viol ? "예" : "아니오")
                  << std::setw(10) << (threw ? "예" : "아니오")
                  << (threw ? ("  " + c.err) : "") << "\n";
    }
    csv.close();
    std::cout << "[cf] " << out << "\n";
}

// §8.5 규칙 5 대조: 예측 유효/무효 vs 실제 컨텍스트 생성 성공/실패.
static void RunDnum(const std::string& out, int logN, uint32_t numSlots,
                    const std::vector<int>& sizes, int q0, int delta)
{
    std::ofstream csv(out);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; std::exit(2); }
    csv << "logN,q0,delta,sizeQ,dnum,predicted_valid,actual_ok,predicted_maxDigitBits,"
           "runtime_maxDigitBits,predicted_PCount,runtime_PCount,match,err\n";

    int nMatchRule5 = 0, nMissRule5 = 0, nMatchRule4 = 0, nMissRule4 = 0;
    for (int sizeQ : sizes) {
        for (uint32_t dnum = 1; dnum <= static_cast<uint32_t>(sizeQ); dnum++) {
            const bool pv = DnumPredictedValid(sizeQ, dnum);
            Ctx c = Build(logN, numSlots, sizeQ - 1, q0, delta, dnum, {3, 3});
            const int predMd = PredictMaxDigitBits(sizeQ, q0, delta, dnum);
            const int predPc = (predMd + 59) / 60;
            const int m4     = (c.ok && predPc == static_cast<int>(c.pCount)) ? 1 : 0;
            if (pv == c.ok) nMatchRule5++; else nMissRule5++;
            if (c.ok) { if (m4) nMatchRule4++; else nMissRule4++; }
            csv << logN << "," << q0 << "," << delta << "," << sizeQ << "," << dnum << ","
                << (pv ? 1 : 0) << "," << (c.ok ? 1 : 0) << "," << predMd << ","
                << (c.ok ? static_cast<int>(c.maxDigitBits) : -1) << "," << predPc << ","
                << (c.ok ? static_cast<int>(c.pCount) : -1) << "," << m4 << "," << c.err << "\n";
        }
        std::cout << "  sizeQ=" << sizeQ << " 완료\n" << std::flush;
    }
    csv.close();
    std::cout << "[dnum] " << out << "\n"
              << "  규칙5(유효 조건) 일치 " << nMatchRule5 << " / 불일치 " << nMissRule5 << "\n"
              << "  규칙4(PCount)   일치 " << nMatchRule4 << " / 불일치 " << nMissRule4 << "\n";
}

// 논문 Table 5.8 Set II 재현. **프리셋 후보가 아니라 도구 검증용**이다.
//   Set II (OpenFHE v1.2.0): q0 60, Δ 2^58, 잔여L 6, UNIFORM_TERNARY, dnum 3
//     → logQ 1511 / logP 180 / logQP 1691, S2C 3 / EvalMod 13 / C2S 3
// ⚠️ 논문은 FLEXIBLEAUTO 였으나 본 프로젝트는 FIXEDMANUAL 고정 지시가 있어 그대로 둔다.
static void RunRepro(const std::string& out, int logN, uint32_t numSlots)
{
    std::ofstream csv(out);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; std::exit(2); }
    csv << HEADER;

    const int q0 = 60, delta = 58, L = 6;
    const std::vector<uint32_t> lb{3, 3};
    const uint32_t bd = FHECKKSRNS::GetBootstrapDepth(lb, UNIFORM_TERNARY);
    Ctx c = Build(logN, numSlots, L + static_cast<int>(bd), q0, delta, 3, lb);
    Emit(csv, logN, numSlots, q0, delta, L, bd, lb[0], lb[1], bd - lb[0] - lb[1], &c, 3, "");
    csv.close();

    std::cout << "\n=== Table 5.8 Set II 재현 (OpenFHE) ===\n";
    std::cout << "논문: logQ 1511 / logP 180 / logQP 1691, S2C 3 / EvalMod 13 / C2S 3, dnum 3\n";
    if (!c.ok) { std::cout << "재현 실패: " << c.err << "\n"; return; }
    std::cout << "실측: logQ " << c.logQ << " / logP " << c.logP << " / logQP "
              << (c.logQ + c.logP) << ", S2C " << lb[1] << " / EvalMod " << (bd - lb[0] - lb[1])
              << " / C2S " << lb[0] << ", dnum " << c.dnum << "\n";
    std::cout << "차이: logQ " << (c.logQ - 1511) << " / logP " << (c.logP - 180)
              << " / logQP " << (c.logQ + c.logP - 1691)
              << " / EvalMod " << (static_cast<int>(bd - lb[0] - lb[1]) - 13) << "\n";
    std::cout << "[repro] " << out << "\n";
}

// 단건 진단 — Table 5.8 재현 격차를 성분별로 분해한다. **격자가 아니다.**
// 체인을 (q0, Δ, totalDepth) 로 직접 주고 dnum·스케일링 기법을 바꿔 가며 P 구성만 본다.
// ⚠️ FLEXIBLEAUTO 는 **원인 규명용 대조 1회**다. 프로젝트 기본은 FIXEDMANUAL 이다.
struct DiagCase {
    std::string label;
    int totalDepth, q0, delta;
    uint32_t dnum;
    ScalingTechnique st;
};

static void RunDiag(const std::string& out, int logN, uint32_t numSlots)
{
    // Set II: q0 60 / Δ 58 / 잔여L 6. 우리 부트 깊이 20 → 27타워, 논문 19 → 26타워.
    const std::vector<DiagCase> cases = {
        {"우리 재현 (27타워, dnum=numPartQ 3)",        26, 60, 58, 3,  FIXEDMANUAL},
        {"dnum=9 (= perPart 3) 27타워",               26, 60, 58, 9,  FIXEDMANUAL},
        {"논문 체인 길이 26타워, dnum=numPartQ 3",      25, 60, 58, 3,  FIXEDMANUAL},
        {"논문 체인 길이 26타워, dnum=9 (perPart 3)",   25, 60, 58, 9,  FIXEDMANUAL},
        {"잔여만 7타워, dnum=numPartQ 3",               6, 60, 58, 3,  FIXEDMANUAL},
        {"[대조1회] FLEXIBLEAUTO 27타워 dnum 3",       26, 60, 58, 3,  FLEXIBLEAUTO},
        {"[대조1회] FLEXIBLEAUTO 27타워 dnum 9",       26, 60, 58, 9,  FLEXIBLEAUTO},
    };

    std::ofstream csv(out);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; std::exit(2); }
    csv << "case,scaling,q0,delta,totalDepth,dnum_req,ok,QCount,logQ,dnum_rt,perPart,"
           "maxDigitBits,PCount,logP,logQP,q_tower_bits,err\n";

    std::cout << "\n=== Set II (OpenFHE) 성분 분해 — logP 540 vs 논문 180 ===\n";
    std::cout << std::left << std::setw(42) << "case" << std::right
              << std::setw(8) << "QCount" << std::setw(7) << "logQ"
              << std::setw(6) << "dnum" << std::setw(9) << "perPart"
              << std::setw(9) << "maxDig" << std::setw(8) << "PCount"
              << std::setw(7) << "logP" << std::setw(8) << "logQP" << "\n";

    for (const auto& c : cases) {
        CCParams<CryptoContextCKKSRNS> params;
        Ctx d;
        // Build() 는 FIXEDMANUAL 고정이라 여기서는 직접 만든다 (스케일링 기법 대조 때문).
        try {
            params.SetMultiplicativeDepth(c.totalDepth);
            params.SetScalingModSize(c.delta);
            params.SetFirstModSize(c.q0);
            params.SetScalingTechnique(c.st);
            params.SetSecretKeyDist(UNIFORM_TERNARY);
            params.SetSecurityLevel(HEStd_NotSet);
            params.SetRingDim(1u << logN);
            params.SetNumLargeDigits(c.dnum);
            auto cc = GenCryptoContext(params);
            cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE);
            cc->Enable(ADVANCEDSHE); cc->Enable(FHE);
            auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
            for (const auto& t : cp->GetElementParams()->GetParams()) {
                const int b = static_cast<int>(
                    std::round(std::log2(t->GetModulus().ConvertToDouble())));
                d.qNominal.push_back(b); d.logQ += b; d.qCount++;
            }
            if (auto pp = cp->GetParamsP())
                for (const auto& t : pp->GetParams()) {
                    d.logP += static_cast<int>(
                        std::round(std::log2(t->GetModulus().ConvertToDouble())));
                    d.pCount++;
                }
            d.dnum = cp->GetNumPartQ();
            d.perPart = cp->GetNumPerPartQ();
            for (uint32_t j = 0; j < d.dnum; j++) {
                const uint32_t b = cp->GetParamsPartQ(j)->GetModulus().GetLengthForBase(2);
                if (b > d.maxDigitBits) d.maxDigitBits = b;
            }
            d.ok = true;
        }
        catch (const std::exception& e) { d.err = e.what(); }
        catch (...) { d.err = "알 수 없는 예외"; }
        ScrubCsv(d.err);

        std::ostringstream tb;
        for (size_t i = 0; i < d.qNominal.size(); i++) tb << (i ? ";" : "") << d.qNominal[i];
        const char* stName = (c.st == FIXEDMANUAL) ? "FIXEDMANUAL" : "FLEXIBLEAUTO";
        csv << "\"" << c.label << "\"," << stName << "," << c.q0 << "," << c.delta << ","
            << c.totalDepth << "," << c.dnum << "," << (d.ok ? 1 : 0) << ",";
        if (d.ok)
            csv << d.qCount << "," << d.logQ << "," << d.dnum << "," << d.perPart << ","
                << d.maxDigitBits << "," << d.pCount << "," << d.logP << ","
                << (d.logQ + d.logP) << "," << tb.str() << ",\n";
        else
            csv << ",,,,,,,,," << d.err << "\n";

        std::cout << std::left << std::setw(42) << c.label << std::right;
        if (d.ok)
            std::cout << std::setw(8) << d.qCount << std::setw(7) << d.logQ
                      << std::setw(6) << d.dnum << std::setw(9) << d.perPart
                      << std::setw(9) << d.maxDigitBits << std::setw(8) << d.pCount
                      << std::setw(7) << d.logP << std::setw(8) << (d.logQ + d.logP) << "\n";
        else
            std::cout << "   실패: " << d.err << "\n";
    }
    csv.close();
    std::cout << "\n논문 Set II: logQ 1511 / logP 180 / logQP 1691, dnum 3, S2C 3 / EvalMod 13 / C2S 3\n";
    std::cout << "[diag] " << out << "\n";
}

// ---------------------------------------------------------------------------

int main(int argc, char** argv)
{
    std::string mode = "grid";
    std::string out;
    GridCfg g;
    int cfQ0 = 60;
    std::vector<int> cfDeltas = {50, 52, 53, 55, 60};
    std::vector<int> dnumSizes = {24, 30, 37};
    int dnumQ0 = 45, dnumDelta = 40;

    for (int i = 1; i < argc; i++) {
        if (!std::strcmp(argv[i], "-mode") && i + 1 < argc) mode = argv[++i];
        else if (!std::strcmp(argv[i], "-out") && i + 1 < argc) out = argv[++i];
        else if (!std::strcmp(argv[i], "-logN") && i + 1 < argc) g.logN = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-slots") && i + 1 < argc)
            g.numSlots = static_cast<uint32_t>(std::atoi(argv[++i]));
        else if (!std::strcmp(argv[i], "-L-min") && i + 1 < argc) g.lmin = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-L-max") && i + 1 < argc) g.lmax = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-cf-limit") && i + 1 < argc) g.cfLimit = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-cf-q0") && i + 1 < argc) cfQ0 = std::atoi(argv[++i]);
        else {
            std::cerr << "사용법: boot_param_dump_openfhe [-mode grid|cf|dnum|repro|diag] [-out CSV]\n"
                         "        [-logN N] [-slots S] [-L-min L] [-L-max L] [-cf-limit D] [-cf-q0 Q]\n";
            return 2;
        }
    }
    if (out.empty()) {
        if (mode == "grid")       out = "boot_grid_openfhe.csv";
        else if (mode == "cf")    out = "boot_cf_openfhe.csv";
        else if (mode == "dnum")  out = "boot_dnumrule_openfhe.csv";
        else if (mode == "diag")  out = "boot_diag_openfhe.csv";
        else                      out = "boot_repro_openfhe.csv";
    }

    if (mode == "grid")       RunGrid(out, g);
    else if (mode == "cf")    RunCf(out, g.logN, g.numSlots, cfQ0, cfDeltas);
    else if (mode == "dnum")  RunDnum(out, g.logN, g.numSlots, dnumSizes, dnumQ0, dnumDelta);
    else if (mode == "repro") RunRepro(out, g.logN, g.numSlots);
    else if (mode == "diag")  RunDiag(out, g.logN, g.numSlots);
    else { std::cerr << "알 수 없는 mode: " << mode << "\n"; return 2; }
    return 0;
}
