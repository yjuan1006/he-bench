// seal_align.cpp — 진단 전용. large L15 add_cc 계단이 '용량 임계'인지 '정렬 conflict miss'인지 가른다.
// a, b, dst 할당 사이에 패딩을 끼워 8 MiB 정렬을 깨뜨린 뒤 같은 연산을 잰다.
#include "seal/seal.h"
#include <chrono>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
using namespace std;
using namespace seal;

static void addr_info(const char *tag, const void *p)
{
    uintptr_t a = (uintptr_t)p;
    auto al = [&](uintptr_t m) { return (a % m) == 0 ? "yes" : "no"; };
    printf("  %-4s addr=0x%016lx  4K=%s 64K=%s 1M=%s 2M=%s 8M=%s  (mod 8MiB = %8lu KiB)\n",
           tag, (unsigned long)a, al(1u<<12), al(1u<<16), al(1u<<20), al(1u<<21), al(1u<<23),
           (unsigned long)((a % (1ul<<23)) / 1024));
}

int main(int argc, char **argv)
{
    int level = 15, iters = 800;
    size_t padbytes = 0;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-level")) level = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-iters")) iters = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-pad")) padbytes = strtoull(argv[++i], nullptr, 10);
    }
    size_t logN = 15, maxLevel = 15, N = size_t(1) << logN;
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
    vector<double> msg(encoder.slot_count(), 1.5);
    Plaintext pt; encoder.encode(msg, pow(2.0, 45), pt);

    auto cd = ctx.first_context_data();
    while (cd->chain_index() > size_t(level)) cd = cd->next_context_data();

    // 패딩은 SEAL 메모리 풀에서 뽑아야 암호문 주소가 실제로 밀린다.
    // 상대 간격을 실제로 바꾸려면 같은 '암호문' 할당 경로에서 크기가 다른 블록을
    // 사이에 끼워야 한다. Plaintext::reserve는 다른 풀 버킷으로 가서 간격이 안 바뀐다.
    vector<Ciphertext> pads;
    auto pad_ct = [&](int padlevel) {
        if (padlevel < 0) return;
        auto pd = ctx.first_context_data();
        while (pd->chain_index() > size_t(padlevel)) pd = pd->next_context_data();
        Ciphertext c; encryptor.encrypt(pt, c);
        evaluator.mod_switch_to_inplace(c, pd->parms_id());
        pads.push_back(std::move(c));
    };
    int padlevel = (int)padbytes;   // -pad 를 '패딩 암호문의 레벨'로 재해석

    Ciphertext a, b, dst;
    encryptor.encrypt(pt, a);
    pad_ct(padlevel);
    encryptor.encrypt(pt, b);
    pad_ct(padlevel);
    if (level != (int)maxLevel) {
        evaluator.mod_switch_to_inplace(a, cd->parms_id());
        evaluator.mod_switch_to_inplace(b, cd->parms_id());
    }
    evaluator.add(a, b, dst);   // dst 최초 할당

    printf("level=%d primes=%zu pad=%zu B\n", level, a.coeff_modulus_size(), padbytes);
    addr_info("a", a.data()); addr_info("b", b.data()); addr_info("dst", dst.data());
    size_t ctbytes = 2 * N * a.coeff_modulus_size() * 8;
    printf("  ct size = %zu B (%.3f MiB)\n", ctbytes, ctbytes / 1048576.0);

    for (int i = 0; i < 50; i++) evaluator.add(a, b, dst);   // warm
    auto t0 = chrono::steady_clock::now();
    for (int i = 0; i < iters; i++) evaluator.add(a, b, dst);
    auto t1 = chrono::steady_clock::now();
    double us = chrono::duration<double, micro>(t1 - t0).count() / iters;
    printf("  add_cc op당 = %.1f us\n", us);
    return 0;
}
