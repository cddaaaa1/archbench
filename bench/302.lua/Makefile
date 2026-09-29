NAME = lua
SRCS = $(shell find src -name "*.c")
CFLAGS += -DLUA_INTONLY_NUMBERS -Wno-error=array-parameter
diskfilelist = am.filelist
include $(BENCH_HOME)/Makefile
