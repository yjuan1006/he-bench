#!/bin/bash
export LD_LIBRARY_PATH=$HOME/openfhe-install/lib:$LD_LIBRARY_PATH
cd ~/he-bench/build_openfhe
echo "===== large 1t start $(date) ====="
OMP_NUM_THREADS=1 ./openfhe_bench -preset large -reps 30 -out ../results_openfhe_large_1t.csv
echo "LARGE_1T_EXIT=$?"
echo "===== large mt start $(date) ====="
./openfhe_bench -preset large -reps 30 -out ../results_openfhe_large_mt.csv
echo "LARGE_MT_EXIT=$?"
echo "===== ALL_LARGE_DONE $(date) ====="
