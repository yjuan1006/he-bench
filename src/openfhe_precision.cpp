// openfhe_precision.cpp — OpenFHE CKKS 정밀도 측정 (독립 프로그램).
// ★ openfhe_bench.cpp 는 수정 금지이므로 별도 프로그램으로 만든다.
//
// 절차는 seal_precision.cpp 와 동일해야 한다(비교 성립 조건):
//   - 입력 벡터: precision_common.h 의 xorshift64* 규약 (동일 수열)
//   - 오차 정의: -log2(전 슬롯 평균 |err|)
//   - 레벨 진입: 스케일을 바꾸지 않는 모듈러스 drop
//     SEAL의 mod_switch_to ↔ OpenFHE의 LevelReduce(ct, nullptr, g)
//     (ModReduce를 쓰면 스케일까지 나눠져 SEAL 절차와 달라진다)
//   - 컨텍스트 설정은 openfhe_bench.cpp 와 동일 (FIXEDMANUAL / HEStd_NotSet / SetRingDim)
//
// 경로: enc_dec, mul_cp_rs, rot1, relin(rescale 없음), mul_cc_relin_rs
#include "openfhe.h"
#include "precision_common.h"
#include <iostream>
#include <string>
#include <vector>

using namespace lbcrypto;
using namespace std;

struct Preset { string name; int logN, depth, firstMod, scaleMod; };
static const Preset PRESETS[] = {
    {"small", 13, 5, 50, 45},
    {"medium", 14, 10, 55, 45},
    {"large", 15, 15, 60, 45},
};

int main(int argc, char **argv)
{
    string preset_name = "small";
    int reps = 5;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-preset")) preset_name = argv[++i];
        else if (!strcmp(argv[i], "-reps")) reps = atoi(argv[++i]);
    }
    const Preset *P = nullptr;
    for (auto &p : PRESETS) if (p.name == preset_name) P = &p;
    if (!P) { cerr << "unknown preset: " << preset_name << "\n"; return 1; }

    CCParams<CryptoContextCKKSRNS> params;
    params.SetMultiplicativeDepth(P->depth);
    params.SetScalingModSize(P->scaleMod);
    params.SetFirstModSize(P->firstMod);
    params.SetScalingTechnique(FIXEDMANUAL);
    params.SetSecurityLevel(HEStd_NotSet);
    params.SetRingDim(1u << P->logN);
    auto cc = GenCryptoContext(params);
    cc->Enable(PKE); cc->Enable(KEYSWITCH); cc->Enable(LEVELEDSHE);

    size_t slots = (size_t(1) << P->logN) / 2;
    vector<double> x, y;
    precision_common::make_inputs(slots, x, y);
    vector<double> want_mul(slots), want_rot(slots);
    for (size_t i = 0; i < slots; i++) want_mul[i] = x[i] * y[i];
    for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];

    printf("library,preset,logN,maxLevel,level,path,rep,bits\n");

    for (int rep = 0; rep < reps; rep++) {
        // 반복마다 키를 새로 만든다 — 비밀키·암호화 오차 표본이 바뀌므로 산포의 원천이다.
        auto keys = cc->KeyGen();
        cc->EvalMultKeyGen(keys.secretKey);
        cc->EvalRotateKeyGen(keys.secretKey, {1});

        for (int level : {P->depth, 1}) {
            uint32_t g = static_cast<uint32_t>(P->depth - level);   // 목표 GetLevel

            Plaintext pt_x0 = cc->MakeCKKSPackedPlaintext(x, 1, 0);
            Plaintext pt_y0 = cc->MakeCKKSPackedPlaintext(y, 1, 0);
            auto ct_x = cc->Encrypt(keys.publicKey, pt_x0);
            auto ct_y = cc->Encrypt(keys.publicKey, pt_y0);
            if (g > 0) {
                ct_x = cc->LevelReduce(ct_x, nullptr, g);
                ct_y = cc->LevelReduce(ct_y, nullptr, g);
            }
            // 평문 피연산자는 ct와 같은 레벨이어야 한다.
            Plaintext pt_y_lv = cc->MakeCKKSPackedPlaintext(y, 1, g);

            auto dec = [&](const Ciphertext<DCRTPoly> &c) {
                Plaintext r;
                cc->Decrypt(keys.secretKey, c, &r);
                r->SetLength(slots);
                return r->GetRealPackedValue();
            };
            auto report = [&](const char *path, const vector<double> &got,
                              const vector<double> &want) {
                printf("openfhe,%s,%d,%d,%d,%s,%d,%.4f\n", P->name.c_str(), P->logN,
                       P->depth, level, path, rep,
                       precision_common::precision_bits(got, want));
            };

            report("enc_dec", dec(ct_x), x);
            report("mul_cp_rs", dec(cc->Rescale(cc->EvalMult(ct_x, pt_y_lv))), want_mul);
            report("rot1", dec(cc->EvalRotate(ct_x, 1)), want_rot);
            // relin 단독: rescale 없이 key-switch 노이즈를 그대로 노출
            report("relin", dec(cc->Relinearize(cc->EvalMultNoRelin(ct_x, ct_y))), want_mul);
            report("mul_cc_relin_rs", dec(cc->Rescale(cc->EvalMult(ct_x, ct_y))), want_mul);
        }
    }
    return 0;
}
