// seal_probe.cpp — 진단 전용. 지정한 레벨에서 add_cc(또는 add_cp)만 반복해
// perf로 LLC 미스를 잴 수 있게 한다. 본측정 하네스가 아니다.
#include "seal/seal.h"
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
using namespace std;
using namespace seal;

int main(int argc, char **argv)
{
    int level = 15, iters = 200;
    string op = "add_cc";
    bool freshtop = false;   // true면 maxLevel 암호문을 mod_switch 없이 그대로 사용
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-level")) level = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-iters")) iters = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-op")) op = argv[++i];
    }
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "-fresh")) freshtop = true;

    size_t logN = 15, maxLevel = 15;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-maxlevel")) maxLevel = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-logn")) logN = atoi(argv[++i]);
    }
    size_t N = size_t(1) << logN;
    vector<int> bits; bits.push_back(60);
    for (size_t i = 0; i < maxLevel; i++) bits.push_back(45);
    bits.push_back(60);

    EncryptionParameters parms(scheme_type::ckks);
    parms.set_poly_modulus_degree(N);
    parms.set_coeff_modulus(CoeffModulus::Create(N, bits));
    SEALContext ctx(parms, true, sec_level_type::none);

    KeyGenerator keygen(ctx);
    PublicKey pk; keygen.create_public_key(pk);
    Encryptor encryptor(ctx, pk);
    Evaluator evaluator(ctx);
    CKKSEncoder encoder(ctx);
    double scale = pow(2.0, 45);
    vector<double> msg(encoder.slot_count(), 1.5);

    auto cd = ctx.first_context_data();
    while (cd->chain_index() > size_t(level)) cd = cd->next_context_data();

    Plaintext pt; encoder.encode(msg, scale, pt);
    Ciphertext a, b;
    encryptor.encrypt(pt, a);
    encryptor.encrypt(pt, b);
    if (!freshtop) {
        evaluator.mod_switch_to_inplace(a, cd->parms_id());
        evaluator.mod_switch_to_inplace(b, cd->parms_id());
    }
    Plaintext pt_lv; encoder.encode(msg, a.parms_id(), a.scale(), pt_lv);
    Ciphertext dst;

    for (int i = 0; i < iters; i++) {
        if (op == "add_cc") evaluator.add(a, b, dst);
        else                evaluator.add_plain(a, pt_lv, dst);
    }
    cerr << "level=" << level << " op=" << op << " fresh=" << freshtop
         << " primes=" << a.coeff_modulus_size() << "\n";
    return 0;
}
