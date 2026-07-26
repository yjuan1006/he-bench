#include <stdlib.h>
// 고정 정수 워크로드의 소요시간을 1초 간격으로 기록한다. SEAL과 무관 —
// 머신 상태(클럭/steal)만 본다.
#include <stdio.h>
#include <time.h>
#include <stdint.h>
static uint64_t kernel(uint64_t n){ uint64_t x=88172645463325252ULL;
  for(uint64_t i=0;i<n;i++){ x^=x<<13; x^=x>>7; x^=x<<17; } return x; }
int main(int argc,char**argv){
  int secs = argc>1? atoi(argv[1]) : 180;
  struct timespec a,b; uint64_t sink=0;
  struct timespec t0; clock_gettime(CLOCK_MONOTONIC,&t0);
  for(;;){
    clock_gettime(CLOCK_MONOTONIC,&a);
    sink^=kernel(50000000ULL);
    clock_gettime(CLOCK_MONOTONIC,&b);
    double ms=(b.tv_sec-a.tv_sec)*1e3+(b.tv_nsec-a.tv_nsec)/1e6;
    double el=(b.tv_sec-t0.tv_sec)+(b.tv_nsec-t0.tv_nsec)/1e9;
    printf("%7.1f s  %8.2f ms\n", el, ms); fflush(stdout);
    if(el>secs) break;
  }
  return (int)(sink&1);
}
