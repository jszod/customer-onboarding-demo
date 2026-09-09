# Every target lives in make/common.mk and is defined exactly once (§14, §15).
# This file, and python/Makefile, are entry points into it -- not copies of the
# target list. A second SDK's makefile would be this same line again.
include make/common.mk
