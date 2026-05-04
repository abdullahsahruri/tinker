# =============================================================================
# Phase-3C SoC smoke firmware build.
#
# Cross-compiles main.c + start.S with riscv64-unknown-elf-gcc into
# firmware.elf, then emits firmware.hex (one 32-bit word per line, hex,
# little-endian) for $readmemh consumption by wb_imem.
#
# The .hex format objcopy emits with `-O verilog` is byte-stream with
# `@addr` markers — incompatible with our 32-b/word memory array.
# We therefore go through a flat .bin and a small Python helper
# (scripts/bin2hex.py) that packs 4 bytes/word in little-endian order.
# =============================================================================

CROSS    ?= riscv64-unknown-elf-
CC       := $(CROSS)gcc
OBJCOPY  := $(CROSS)objcopy
OBJDUMP  := $(CROSS)objdump

ARCH     := rv32i
ABI      := ilp32
CFLAGS   := -march=$(ARCH) -mabi=$(ABI) \
            -nostdlib -nostartfiles -ffreestanding \
            -Os -fno-pic -fno-builtin \
            -Wall -Wextra -mno-relax
LDFLAGS  := -march=$(ARCH) -mabi=$(ABI) \
            -nostdlib -nostartfiles -ffreestanding \
            -T linker.ld -Wl,--no-relax \
            -Wl,-Map=firmware.map

REPO_ROOT := $(realpath ../..)
BIN2HEX   := $(REPO_ROOT)/scripts/bin2hex.py

# Match wb_imem.v SIZE_BYTES default (8 KB / 4 = 2048 words). Pad firmware.hex
# to this depth so iverilog's $readmemh has exactly enough lines.
IMEM_WORDS := 2048

OBJS := start.o main.o

.PHONY: all clean lst

all: firmware.hex

start.o: start.S
	$(CC) $(CFLAGS) -c $< -o $@

main.o: main.c
	$(CC) $(CFLAGS) -c $< -o $@

firmware.elf: $(OBJS) linker.ld
	$(CC) $(LDFLAGS) -o $@ $(OBJS)

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

firmware.hex: firmware.bin
	python3 $(BIN2HEX) $< $@ --pad-words=$(IMEM_WORDS)

lst: firmware.elf
	$(OBJDUMP) -d -S firmware.elf > firmware.lst

clean:
	rm -f $(OBJS) firmware.elf firmware.bin firmware.hex firmware.map firmware.lst
