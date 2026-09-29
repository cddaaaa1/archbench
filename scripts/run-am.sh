#!/bin/bash
# 只跑能在裸机 AM(没有 libc) 上构建的程序, 其余 10 个依赖 fopen 等文件 I/O
# 用法: bash run-am.sh ARCH=minirv-npc mainargs=test [nproc=4]
cd "$(dirname "$0")"

# 每个 Verilator 进程都占几百 MB, 默认限制并发
: "${nproc:=4}"

benchlist="
  100.blockchain  101.igemm   102.queen    103.dinic
  104.malloc      105.bf      106.qsort    107.stream
  108.ntt         200.genann  203.rsa
"

export nproc benchlist
exec bash run.sh "$@"
