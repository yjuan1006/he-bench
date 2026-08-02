// ksprec_seal.cpp — 새 프리셋 후보 비교 참조 (SEAL). 절차는 ksprec_openfhe.cpp 와 동일.
//
// 체인은 지시대로 CoeffModulus::Create(N, {60, 40×13, 60}) — 마지막 60이 특수소수 P.
// SEAL은 digit을 **Q 프라임 1개 단위**로 분해하므로 dnum = 해당 레벨의 Q 프라임 수이고
// 최대 digit = 가장 큰 Q 프라임(= q0 60비트)이다. 즉 digit−P = 0 —
// v1 §5.3에서 SEAL large만 손실이 2.18비트로 튀었던 그 배치가 그대로 재현된다.
#include "precision_common.h"
#include "seal/seal.h"
#include <cstring>
#include <iostream>
#include <vector>

using namespace seal;
using namespace std;

int main(int argc, char **argv)
{
    int reps = 5, logN = 15, q0 = 60;
    string spec = "13:40";   // "depth:delta,..." (SEAL은 P가 고정이라 셋째 인자를 받지 않는다)
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-reps")) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-combos")) spec = argv[++i];
        else if (!strcmp(argv[i], "-logN")) logN = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-q0")) q0 = atoi(argv[++i]);
    }
    vector<pair<int,int>> combos;   // (depth, delta)
    {
        size_t i = 0;
        while (i < spec.size()) {
            size_t j = spec.find(',', i); if (j == string::npos) j = spec.size();
            int dp = 0, dl = 0;
            // "d:Δ" 또는 "d:Δ:x"(x 무시) 둘 다 받는다 — 세 라이브러리 드라이버를 공유하기 위해.
            if (sscanf(spec.substr(i, j - i).c_str(), "%d:%d", &dp, &dl) == 2)
                combos.push_back({dp, dl});
            i = j + 1;
        }
    }
    printf("library,logN,q0,delta,depth,dnum,PCount,logP,maxDigitBits,level,path,rep,bits\n");
    for (auto &cb : combos) {
    const int delta = cb.second, depth = cb.first;
    const size_t N = size_t(1) << logN;

    vector<int> bits = {q0};
    for (int i = 0; i < depth; i++) bits.push_back(delta);
    bits.push_back(60);  // 특수소수 P

    EncryptionParameters parms(scheme_type::ckks);
    parms.set_poly_modulus_degree(N);
    parms.set_coeff_modulus(CoeffModulus::Create(N, bits));
    // 링 차원 강제 (OpenFHE HEStd_NotSet 과 동일 성격)
    SEALContext ctx(parms, true, sec_level_type::none);

    // logP / maxDigitBits — P는 마지막 프라임, digit은 Q 프라임 1개씩.
    // ⚠️ 명목 비트(round(log2))로 센다 — 세 라이브러리 관례 통일(v1 §5.3과 동일 기준).
    //    SEAL은 2^k 바로 아래, OpenFHE/Lattigo는 바로 위 소수를 골라 실제 비트길이가 갈린다.
    const auto &coeff = parms.coeff_modulus();
    auto nominal = [](const Modulus &m) {
        return (int)llround(log2((double)m.value()));
    };
    const int logP = nominal(coeff.back());
    const size_t pCount = 1;
    int maxDigitBits = 0;
    for (size_t i = 0; i + 1 < coeff.size(); i++)
        maxDigitBits = max(maxDigitBits, nominal(coeff[i]));
    const size_t dnum = coeff.size() - 1;  // Q 프라임 수 = 최상위 레벨 digit 수

    CKKSEncoder encoder(ctx);
    const size_t slots = encoder.slot_count();
    vector<double> x, y;
    precision_common::make_inputs(slots, x, y);
    vector<double> want_rot(slots);
    for (size_t i = 0; i < slots; i++) want_rot[i] = x[(i + 1) % slots];
    const double scale = pow(2.0, delta);

    for (int rep = 0; rep < reps; rep++) {
        KeyGenerator keygen(ctx);
        SecretKey sk = keygen.secret_key();
        GaloisKeys gks;
        keygen.create_galois_keys(vector<int>{1}, gks);

        Encryptor encryptor(ctx, sk);   // ★ 비밀키 암호화
        Decryptor decryptor(ctx, sk);
        Evaluator evaluator(ctx);

        Plaintext pt_x;
        encoder.encode(x, scale, pt_x);
        Ciphertext ct_x;
        encryptor.encrypt_symmetric(pt_x, ct_x);

        auto dec = [&](const Ciphertext &ct) {
            Plaintext r;
            decryptor.decrypt(ct, r);
            vector<double> v;
            encoder.decode(r, v);
            v.resize(slots);
            return v;
        };
        auto report = [&](const char *path, const vector<double> &got,
                          const vector<double> &want) {
            printf("seal,%d,%d,%d,%d,%zu,%zu,%d,%d,%d,%s,%d,%.4f\n",
                   logN, q0, delta, depth, dnum, pCount, logP, maxDigitBits,
                   depth, path, rep, precision_common::precision_bits(got, want));
        };

        report("enc_dec", dec(ct_x), x);
        Ciphertext ct_rot;
        evaluator.rotate_vector(ct_x, 1, gks, ct_rot);
        report("rot1", dec(ct_rot), want_rot);
        fflush(stdout);
    }
    }
    return 0;
}
