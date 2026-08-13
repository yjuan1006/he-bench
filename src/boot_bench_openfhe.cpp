// boot_bench_openfhe.cpp — 부트스트래핑 2단계(정밀도 곡선) 측정. **단일 조합 1회 실행.**
//
// 목적: Δ 를 낮추면 부트 출력 정밀도가 얼마나 떨어지는가. 그 곡선이 Δ 하한을 정한다.
// 대상점은 `explore/boot_params/boot_stage2_points.csv` (1단계 격자에서 추림).
//
// ⚠️ **스크리닝이다. 본측정이 아니다.** reps 3 / warmup 3 이라 지연시간은 확정값이 아니다.
//    본측정(reps 10)은 3단계다.
//
// 정밀도 정의는 8-op 과 **같다** — `precision_common.h` 의
//   precision_bits = -log2(전 슬롯 평균 |err|),  입력은 xorshift64* 로 언어 간 동일.
// 그래야 8-op 표(§8.4)와 나란히 놓을 수 있다.
//
// ⚠️ **정밀도 숫자만 보지 않는다** (§5-1: 예외 없이 무의미한 값을 반환한 이력).
//    아래 셋을 함께 확인하고 하나라도 어긋나면 그 조합을 fail 로 기록한다:
//      ⑴ 부트 전후 레벨이 예상대로 바뀌는가 (in = depth-1, out = depth - 잔여L)
//      ⑵ 복호값이 원본과 같은 자릿수인가 (max|got| / max|want| ∈ [0.5, 2])
//      ⑶ precision_bits 가 유한하고 양수인가
//
// ⚠️ **rep 마다 CSV 에 append + flush** 한다. 세션이 끊겨도 이미 잰 rep 은 남는다.
#include "openfhe.h"
#include "schemerns/rns-cryptoparameters.h"
#include "scheme/ckksrns/ckksrns-fhe.h"
#include "precision_common.h"

#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
using namespace lbcrypto;

static const char* CSV_HEADER =
    "library,logN,numSlots,q0,delta,residual_L,levelBudget_c2s,levelBudget_s2c,"
    "boot_depth,dnum,PCount,logQ_boot,logP_boot,logQP_boot,"
    "rep,precision_bits,worst_slot_bits,boot_us,"
    "level_in,level_out,level_out_expected,magnitude_ratio,"
    "scaling,in_scale_log2,q0_minus_scale_log2,correction_factor,"
    "setup_us,keygen_us,peak_rss_mb,ok,fail_reason\n";

static double NowUs()
{
    using namespace std::chrono;
    return duration<double, std::micro>(steady_clock::now().time_since_epoch()).count();
}

// /proc/self/status VmHWM — 프로세스 최대 상주 메모리(KB → MB).
static long PeakRssMb()
{
    std::ifstream f("/proc/self/status");
    std::string k;
    while (f >> k) {
        if (k == "VmHWM:") { long v; f >> v; return v / 1024; }
        std::getline(f, k);
    }
    return -1;
}

static void Scrub(std::string& s)
{
    for (auto& ch : s)
        if (ch == ',' || ch == '\n' || ch == '\r' || ch == '"') ch = ' ';
}

int main(int argc, char** argv)
{
    int logN = 16, q0 = 45, delta = 40, L = 12, lb0 = 3, lb1 = 3, reps = 3, warmup = 3;
    uint32_t dnum = 4, numSlots = 1u << 15;
    std::string out = "boot_prec_openfhe.csv";
    // ⚠️ 8-op 세트는 FIXEDMANUAL 고정이다. 이 플래그는 **부트 세트 한정**이며
    //    FIXEDMANUAL + EvalBootstrap 이 스케일 장부 문제로 깨지는지 대조하기 위한 것이다.
    std::string scaling = "FIXEDMANUAL";
    // ⚠️ **진단 전용.** 메인키가 sparse 가 되면 Table 5.2 를 못 쓰므로 **프리셋 후보가 아니다**.
    //    9.1비트 격차(§10.7-24)가 K/EvalMod 축으로 설명되는지 보려는 단발 측정에만 쓴다.
    std::string skdist = "UNIFORM_TERNARY";
    // ⚠️ mt 는 타이밍과 정밀도를 **분리 실행**한다(§8.6-2). 한 프로세스에서 정밀도가 뒤에
    //    오면 그 구간이 대부분 직렬이라 post 프로브가 타이밍이 아니라 식은 구간을 잰다.
    std::string runMode = "both";   // both | timing | precision

    for (int i = 1; i < argc; i++) {
        if (!std::strcmp(argv[i], "-out") && i + 1 < argc) out = argv[++i];
        else if (!std::strcmp(argv[i], "-logN") && i + 1 < argc) logN = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-q0") && i + 1 < argc) q0 = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-delta") && i + 1 < argc) delta = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-L") && i + 1 < argc) L = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-lb") && i + 2 < argc) { lb0 = std::atoi(argv[++i]); lb1 = std::atoi(argv[++i]); }
        else if (!std::strcmp(argv[i], "-dnum") && i + 1 < argc) dnum = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-slots") && i + 1 < argc) numSlots = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-reps") && i + 1 < argc) reps = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-warmup") && i + 1 < argc) warmup = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "-scaling") && i + 1 < argc) scaling = argv[++i];
        else if (!std::strcmp(argv[i], "-skdist") && i + 1 < argc) skdist = argv[++i];
        else if (!std::strcmp(argv[i], "-mode") && i + 1 < argc) runMode = argv[++i];
        else {
            std::cerr << "사용법: boot_bench_openfhe -out CSV -q0 Q -delta D -L L "
                         "-lb C2S S2C -dnum N [-slots S] [-reps 3] [-warmup 3]\n";
            return 2;
        }
    }

    const std::vector<uint32_t> levelBudget{static_cast<uint32_t>(lb0), static_cast<uint32_t>(lb1)};
    SecretKeyDist skd = UNIFORM_TERNARY;
    if (skdist == "SPARSE_TERNARY")           skd = SPARSE_TERNARY;
    else if (skdist == "SPARSE_ENCAPSULATED") skd = SPARSE_ENCAPSULATED;
    else if (skdist != "UNIFORM_TERNARY") { std::cerr << "알 수 없는 -skdist\n"; return 2; }
    const uint32_t bootDepth = FHECKKSRNS::GetBootstrapDepth(levelBudget, skd);
    const int depth = L + static_cast<int>(bootDepth);

    // 헤더는 파일이 없을 때만 (증분 append).
    // ⚠️ **스키마 가드.** 이 파일은 rep 마다 append 되므로, 열을 추가한 뒤 옛 파일에
    //    이어 붙이면 헤더와 행의 열 수가 어긋나 통째로 파싱 불가가 된다(2026-08-12 실제 발생).
    //    기존 헤더가 현재 스키마와 다르면 **거부**한다 — 조용히 섞지 않는다.
    bool needHeader = true;
    {
        std::ifstream chk(out);
        if (chk.good()) {
            std::string first;
            if (std::getline(chk, first)) {
                std::string want(CSV_HEADER);
                if (!want.empty() && want.back() == '\n') want.pop_back();
                if (first != want) {
                    std::cerr << "[스키마 불일치] " << out << " 의 헤더가 현재 스키마와 다르다.\n"
                              << "  기존: " << first << "\n  현재: " << want << "\n"
                              << "  → 다른 파일명을 쓰거나 기존 파일을 superseded/ 로 옮길 것.\n";
                    return 2;
                }
                needHeader = false;
            }
        }
    }
    std::ofstream csv(out, std::ios::app);
    if (!csv) { std::cerr << "출력 파일을 열 수 없다: " << out << "\n"; return 2; }
    if (needHeader) { csv << CSV_HEADER; csv.flush(); }

    // 한 조합이 통째로 실패해도 사유가 CSV 에 남게 한다(조용한 누락 금지).
    auto emitFail = [&](const std::string& why, double setupUs, double kgUs) {
        std::string w = why; Scrub(w);
        csv << "openfhe," << logN << "," << numSlots << "," << q0 << "," << delta << "," << L << ","
            << lb0 << "," << lb1 << "," << bootDepth << "," << dnum << ",,,,"
            << ",-1,,,,,," << "," << scaling << ",,,," << (long)setupUs << "," << (long)kgUs << ","
            << PeakRssMb() << ",0," << w << "\n";
        csv.flush();
    };

    double setupUs = 0, kgUs = 0;
    try {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(depth);
        params.SetScalingModSize(delta);
        params.SetFirstModSize(q0);
        ScalingTechnique st = FIXEDMANUAL;
        if (scaling == "FIXEDAUTO")         st = FIXEDAUTO;
        else if (scaling == "FLEXIBLEAUTO") st = FLEXIBLEAUTO;
        else if (scaling != "FIXEDMANUAL") {
            emitFail("알 수 없는 -scaling: " + scaling, 0, 0); return 2;
        }
        params.SetScalingTechnique(st);
        params.SetSecretKeyDist(skd);
        params.SetSecurityLevel(HEStd_NotSet);
        params.SetRingDim(1u << logN);
        params.SetNumLargeDigits(dnum);
        params.SetBatchSize(numSlots);

        auto cc = GenCryptoContext(params);
        cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE);
        cc->Enable(ADVANCEDSHE); cc->Enable(FHE);

        if (cc->GetRingDimension() != (1u << logN)) {
            emitFail("링 차원이 " + std::to_string(cc->GetRingDimension()) + " 로 변경됨", 0, 0);
            return 1;
        }

        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        int logQ = 0, logP = 0;
        size_t qCount = 0, pCount = 0;
        for (const auto& t : cp->GetElementParams()->GetParams()) {
            logQ += (int)std::round(std::log2(t->GetModulus().ConvertToDouble())); qCount++;
        }
        if (auto pp = cp->GetParamsP())
            for (const auto& t : pp->GetParams()) {
                logP += (int)std::round(std::log2(t->GetModulus().ConvertToDouble())); pCount++;
            }
        const int logQP = logQ + logP;

        // --- setup: 인코딩/디코딩 행렬 사전계산 포함 (1단계에서 껐던 구간) ---
        double t0 = NowUs();
        cc->EvalBootstrapSetup(levelBudget, {0, 0}, numSlots);
        setupUs = NowUs() - t0;

        // --- keygen ---
        t0 = NowUs();
        auto keys = cc->KeyGen();
        cc->EvalMultKeyGen(keys.secretKey);
        cc->EvalBootstrapKeyGen(keys.secretKey, numSlots);
        kgUs = NowUs() - t0;

        // --- 입력: 8-op 정밀도 하네스와 동일한 수열 ---
        std::vector<double> x, yUnused;
        precision_common::make_inputs(numSlots, x, yUnused);

        // ⚠️ 비밀키 암호화 — §8.4 정밀도 정본과 같은 조건(공개키 암호화 노이즈 배제).
        // 레벨 depth-1 = 타워 1개만 남긴 상태. 부트가 여기서 끌어올린다.
        // ⚠️ **rep 마다 새로 암호화한다.** 같은 암호문을 복제해 쓰면 부트 근사오차가
        //    지배적이라 반복 간 값이 완전히 동일해지고(2단계 Lattigo 6회 전부 14.562074),
        //    §4 의 "평균 + 표본표준편차" 가 의미를 잃는다.
        Plaintext pt = cc->MakeCKKSPackedPlaintext(x, 1, depth - 1, nullptr, numSlots);
        auto ctProbe = cc->Encrypt(keys.secretKey, pt);      // 메타 추출용 1개
        const uint32_t levelIn = ctProbe->GetLevel();
        // ⚠️ 부트 입력 스케일을 **런타임으로 추출**한다. Lattigo 와 같은 값이어야
        //    "같은 크기의 메시지를 부트한다"가 성립한다(2026-08-12 결정 1).
        const double inScaleLog2 = std::log2(ctProbe->GetScalingFactor());
        const uint32_t cf = cc->GetCKKSBootCorrectionFactor();
        const uint32_t levelOutExpected = static_cast<uint32_t>(depth - L);   // = bootDepth

        double wantMax = 0;
        for (uint32_t i = 0; i < numSlots; i++) wantMax = std::max(wantMax, std::fabs(x[i]));

        for (int r = -warmup; r < reps; r++) {
            std::string fail;
            double bootUs = 0, prec = 0, worst = 0, magRatio = 0;
            uint32_t levelOut = 0;
            try {
                auto ctIn = cc->Encrypt(keys.secretKey, pt);   // rep 마다 새 암호문
                const double s = NowUs();
                auto ctb = cc->EvalBootstrap(ctIn);
                bootUs = NowUs() - s;
                levelOut = ctb->GetLevel();

                if (runMode == "timing") {
                    // ⚠️ 정밀도 구간을 아예 돌지 않는다 — mt 에서 이 구간이 직렬이라
                    //    post 프로브가 식은 코어를 잰다(§8.6-2).
                    prec = -1; worst = -1; magRatio = -1;
                }
                else {
                    Plaintext res;
                    cc->Decrypt(keys.secretKey, ctb, &res);
                    res->SetLength(numSlots);
                    const auto& got = res->GetRealPackedValue();

                    std::vector<double> g(got.begin(), got.begin() + numSlots);
                    std::vector<double> w(x.begin(), x.begin() + numSlots);
                    prec = precision_common::precision_bits(g, w);

                    double maxErr = 0, gotMax = 0;
                    for (uint32_t i = 0; i < numSlots; i++) {
                        maxErr = std::max(maxErr, std::fabs(g[i] - w[i]));
                        gotMax = std::max(gotMax, std::fabs(g[i]));
                    }
                    worst    = (maxErr > 0) ? -std::log2(maxErr) : 999.0;
                    magRatio = (wantMax > 0) ? gotMax / wantMax : 0.0;
                }

                // --- 정상성 검증 셋 (timing 모드는 레벨만 본다) ---
                if (runMode == "timing") {
                    if (levelOut > levelOutExpected)
                        fail = "잔여 레벨 부족: out=" + std::to_string(levelOut);
                } else
                // ⚠️ 레벨은 **부등호**로 본다. GetBootstrapDepth 는 보수적이라 실측이
                //    1 적게(= 잔여 레벨이 1 많게) 나오는 조합이 있다
                //    (2026-08-12 (50,48,L=10) 에서 out=19, 예상 20). 그건 손해가 아니다.
                //    잔여가 **약속보다 적을 때만** 실패로 본다.
                if (levelOut > levelOutExpected)
                    fail = "잔여 레벨 부족: out=" + std::to_string(levelOut) +
                           " > 예상=" + std::to_string(levelOutExpected);
                else if (!(magRatio > 0.5 && magRatio < 2.0))
                    fail = "자릿수 이상: max|got|/max|want|=" + std::to_string(magRatio);
                else if (!std::isfinite(prec) || prec <= 0.0)
                    fail = "정밀도 이상: " + std::to_string(prec) + "비트";

            }
            catch (const std::exception& e) { fail = std::string("부트 예외: ") + e.what(); }
            catch (...) { fail = "부트 알 수 없는 예외"; }

            // ⚠️ warmup 도 **행으로 남긴다**(rep 음수). 예전에는 warmup 실패 시 즉시
            //    중단해 정밀도 숫자를 하나도 못 남겼다 — "Decode 통과 ≠ 정상" 이므로
            //    실패해도 정밀도·자릿수·시간을 봐야 한다(2026-08-12).
            Scrub(fail);
            csv << "openfhe," << logN << "," << numSlots << "," << q0 << "," << delta << "," << L << ","
                << lb0 << "," << lb1 << "," << bootDepth << "," << cp->GetNumPartQ() << ","
                << pCount << "," << logQ << "," << logP << "," << logQP << ","
                << r << "," << prec << "," << worst << "," << (long)bootUs << ","
                << levelIn << "," << levelOut << "," << levelOutExpected << "," << magRatio << ","
                << scaling << "|" << skdist << "|" << runMode << "," << inScaleLog2 << "," << (q0 - inScaleLog2) << "," << cf << ","
                << (long)setupUs << "," << (long)kgUs << "," << PeakRssMb() << ","
                << (fail.empty() ? 1 : 0) << "," << fail << "\n";
            csv.flush();   // ★ rep 마다 디스크로

            std::cout << "  rep " << r << "  정밀도 " << prec << "비트  최악슬롯 " << worst
                      << "  부트 " << (long)(bootUs / 1000) << "ms  레벨 " << levelIn << "→" << levelOut
                      << (fail.empty() ? "" : ("  ✗ " + fail)) << std::endl;
        }
        std::cout << "  입력 스케일 2^" << inScaleLog2 << "  q0-스케일 = " << (q0 - inScaleLog2)
                  << "  correctionFactor(런타임) = " << cf << "  기법 " << scaling << "\n";
        std::cout << "[boot] openfhe q0=" << q0 << " Δ=" << delta << " L=" << L
                  << " lb{" << lb0 << "," << lb1 << "} dnum=" << cp->GetNumPartQ()
                  << "  setup " << (long)(setupUs / 1e6) << "s  keygen " << (long)(kgUs / 1e6)
                  << "s  peakRSS " << PeakRssMb() << "MB\n";
    }
    catch (const std::exception& e) { emitFail(std::string("설정/키생성 예외: ") + e.what(), setupUs, kgUs); return 1; }
    catch (...) { emitFail("설정/키생성 알 수 없는 예외", setupUs, kgUs); return 1; }
    return 0;
}
