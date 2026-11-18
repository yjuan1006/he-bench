// ksprec_openfhe.cpp — 새 프리셋 후보의 key-switch 정밀도 사전 측정 (OpenFHE).
//
// 본측정이 아니다. Δ와 dnum 스윕 범위를 정하기 위한 게이트 기준용 소규모 측정이다.
// ★ openfhe_precision.cpp(v1 정밀도 정본)는 건드리지 않는다 — 그쪽은 프리셋 고정·공개키다.
//
// v1 §5에서 얻은 절차 제약을 그대로 지킨다:
//   - **비밀키 암호화.** 공개키는 암호화 노이즈가 KS 노이즈를 덮는다
//     (§5.1에서 OpenFHE KS 손실이 0.05비트로 보였으나 §5.2 비밀키에서 실제 3.66)
//   - **rot1 경로.** relin은 곱셈 직후라 스케일이 Δ²이고 KS 노이즈가 2^Δ배 억제된다(§5.4)
//   - **maxLevel**에서만 측정 — digit 수가 가장 많은 최악 조건
//   - 입력 벡터·오차 정의는 precision_common.h 규약(시드 고정)
//
// 각 행에 logP/PCount/maxDigitBits를 함께 실어 digit−P 를 사후 계산할 수 있게 한다.
#include "openfhe.h"
#include "precision_common.h"
#include "schemerns/rns-cryptoparameters.h"
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

using namespace lbcrypto;
using namespace std;

struct Combo { int logN, q0, delta, depth; uint32_t dnum; };

// "depth:delta:dnum,depth:delta:dnum,..." 를 파싱한다. logN·q0는 고정.
static vector<Combo> ParseCombos(const string &spec, int logN, int q0)
{
    vector<Combo> out;
    size_t i = 0;
    while (i < spec.size()) {
        size_t j = spec.find(',', i);
        if (j == string::npos) j = spec.size();
        string tok = spec.substr(i, j - i);
        int dp = 0, dl = 0; unsigned dn = 0;
        if (sscanf(tok.c_str(), "%d:%d:%u", &dp, &dl, &dn) == 3)
            out.push_back({logN, q0, dl, dp, dn});
        else
            fprintf(stderr, "[warn] 조합 파싱 실패: %s\n", tok.c_str());
        i = j + 1;
    }
    return out;
}

int main(int argc, char **argv)
{
    int reps = 5, logN = 15, q0 = 60;
    string spec;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-reps")) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-combos")) spec = argv[++i];
        else if (!strcmp(argv[i], "-logN")) logN = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-q0")) q0 = atoi(argv[++i]);
    }

    // 기본값 = v2 탐색 당시 조합(재현용). -combos 로 덮어쓴다.
    vector<Combo> combos = {
        {15, 60, 40, 13, 2}, {15, 60, 40, 13, 3}, {15, 60, 40, 13, 4},
        {15, 60, 40, 13, 5}, {15, 60, 40, 13, 7}, {15, 60, 40, 13, 14},
        {15, 60, 45, 13, 5}, {15, 60, 45, 13, 7}, {15, 60, 45, 13, 14},
    };
    if (!spec.empty()) combos = ParseCombos(spec, logN, q0);

    printf("library,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits\n");

    for (const auto &c : combos) {
        CCParams<CryptoContextCKKSRNS> params;
        params.SetMultiplicativeDepth(c.depth);
        params.SetScalingModSize(c.delta);
        params.SetFirstModSize(c.q0);
        params.SetScalingTechnique(FIXEDMANUAL);
        params.SetSecurityLevel(HEStd_NotSet);   // 링 차원 강제
        params.SetRingDim(1u << c.logN);
        params.SetNumLargeDigits(c.dnum);

        CryptoContext<DCRTPoly> cc;
        try {
            cc = GenCryptoContext(params);
        }
        catch (const std::exception &e) {
            fprintf(stderr, "[skip] delta=%d dnum=%u: %s\n", c.delta, c.dnum, e.what());
            continue;
        }
        cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE);

        auto cp = std::dynamic_pointer_cast<CryptoParametersRNS>(cc->GetCryptoParameters());
        int logP = 0; size_t pCount = 0;
        if (auto pp = cp->GetParamsP())
            for (auto &t : pp->GetParams()) {
                logP += (int)llround(log2(t->GetModulus().ConvertToDouble()));
                pCount++;
            }
        // ⚠️ 명목 비트(round(log2))로 센다 — 실제 비트길이를 쓰면 세 라이브러리가
        // 비교 불가해진다. OpenFHE/Lattigo는 2^k 바로 위, SEAL은 바로 아래 소수를 골라
        // 같은 "60비트 소수"가 61 vs 60으로 갈린다. v1 §5.3의 digit−P 도 명목 기준이다.
        int maxDigitBits = 0;
        for (uint32_t j = 0; j < cp->GetNumPartQ(); j++) {
            int b = 0;
            for (auto &t : cp->GetParamsPartQ(j)->GetParams())
                b += (int)llround(log2(t->GetModulus().ConvertToDouble()));
            if (b > maxDigitBits) maxDigitBits = b;
        }

        const size_t slots = (size_t(1) << c.logN) / 2;
        vector<double> x, y;
        precision_common::make_inputs(slots, x, y);
        vector<double> want_rot(slots);
        for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];

        for (int rep = 0; rep < reps; rep++) {
            // 반복마다 키 재생성 — 비밀키·암호화 오차 표본이 산포의 원천이다(§5.2).
            auto keys = cc->KeyGen();
            cc->EvalRotateKeyGen(keys.secretKey, {1});

            Plaintext pt_x = cc->MakeCKKSPackedPlaintext(x, 1, 0);
            // ★ 비밀키 암호화 — 공개키를 쓰면 KS 노이즈가 덮인다
            auto ct_x = cc->Encrypt(keys.secretKey, pt_x);

            auto dec = [&](const Ciphertext<DCRTPoly> &ct) {
                Plaintext r;
                cc->Decrypt(keys.secretKey, ct, &r);
                r->SetLength(slots);
                return r->GetRealPackedValue();
            };
            auto report = [&](const char *path, const vector<double> &got,
                              const vector<double> &want) {
                printf("openfhe,%d,%d,%d,%d,%u,%zu,%d,%d,%d,%s,%d,%.4f\n",
                       c.logN, c.q0, c.delta, c.depth, cp->GetNumPartQ(), pCount, logP,
                       maxDigitBits, c.depth, path, rep,
                       precision_common::precision_bits(got, want));
            };

            report("enc_dec", dec(ct_x), x);
            report("rot1", dec(cc->EvalRotate(ct_x, 1)), want_rot);
            fflush(stdout);
        }
    }
    return 0;
}
