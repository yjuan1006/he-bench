// param_dump_seal_grid.cpp — 프리셋 격자 탐색용 SEAL 파라미터 덤프. 벤치 없음.
//
// SEAL 은 특수소수 1개 구조라 logP 는 항상 60 한 점이고 dnum 도 해당 레벨의 Q 프라임 수로
// 종속 결정된다 — 선택 여지가 없다. 값은 런타임(CoeffModulus::Create 결과)에서 뽑는다.
// 비트는 명목(round(log2)) — SEAL 은 2^k 바로 아래 소수를 골라 실제 비트길이가 1 작다.
#include "seal/seal.h"
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <vector>
using namespace seal;
using namespace std;

static int Bound(int logN) {
    switch (logN) { case 13: return 218; case 14: return 438; case 15: return 881; }
    return -1;
}

int main(int argc, char** argv)
{
    int logN = 15, q0 = 60, dmin = 8, dmax = 11, dlmin = 45, dlmax = 70;
    string out = "params_seal_grid.csv";
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "-logN")) logN = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-q0")) q0 = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-depth-min")) dmin = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-depth-max")) dmax = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-delta-min")) dlmin = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-delta-max")) dlmax = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-out")) out = argv[++i];
    }
    ofstream csv(out);
    csv << "library,logN,q0,delta,depth,QCount,logQ,PCount,logP,dnum,maxDigitBits,"
           "logQP,bound,margin,ok,err,digits\n";
    int nOk = 0, nFail = 0;
    const size_t N = size_t(1) << logN;
    for (int depth = dmin; depth <= dmax; depth++) {
        for (int delta = dlmin; delta <= dlmax; delta++) {
            vector<int> bits = {q0};
            for (int i = 0; i < depth; i++) bits.push_back(delta);
            bits.push_back(60);
            EncryptionParameters parms(scheme_type::ckks);
            parms.set_poly_modulus_degree(N);
            string err;
            try { parms.set_coeff_modulus(CoeffModulus::Create(N, bits)); }
            catch (const exception& e) { err = e.what(); }
            if (err.empty()) {
                SEALContext ctx(parms, true, sec_level_type::none);
                if (!ctx.parameters_set()) err = ctx.parameter_error_message();
            }
            if (!err.empty()) {
                for (auto& c : err) if (c == ',' || c == '\n') c = ' ';
                csv << "seal," << logN << "," << q0 << "," << delta << "," << depth
                    << ",,,,,,,," << Bound(logN) << ",,0," << err << ",\n";
                nFail++; continue;
            }
            const auto& co = parms.coeff_modulus();
            auto nom = [](const Modulus& m) { return (int)llround(log2((double)m.value())); };
            int logQ = 0, maxDigit = 0;
            for (size_t i = 0; i + 1 < co.size(); i++) { logQ += nom(co[i]); maxDigit = max(maxDigit, nom(co[i])); }
            const int logP = nom(co.back()), qp = logQ + logP, b = Bound(logN);
            ostringstream ds;
            for (int L = depth; L >= 1; L--) { if (L != depth) ds << ";"; ds << "L" << L << "=" << (L + 1); }
            csv << "seal," << logN << "," << q0 << "," << delta << "," << depth << ","
                << (co.size() - 1) << "," << logQ << ",1," << logP << "," << (co.size() - 1)
                << "," << maxDigit << "," << qp << "," << b << "," << (b - qp) << ",1,,"
                << ds.str() << "\n";
            nOk++;
        }
    }
    cout << "[seal grid] " << out << "  (성공 " << nOk << " / 실패 " << nFail << ")\n";
    return 0;
}
