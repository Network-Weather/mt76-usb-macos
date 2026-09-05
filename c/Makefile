# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather

CC ?= clang
CFLAGS ?= -Wall -Wextra -O2 -std=c11
FRAMEWORKS = -framework IOKit -framework CoreFoundation

SMOKE_OBJS = mt7921_smoke.o mt7921_dev.o mt7921_mcu.o mt7921_usb.o mt7921_rxd.o mt7921_rxd_connac3.o mt7921_chip.o
TEST_OBJS = test_rxd.o mt7921_rxd.o mt7921_rxd_connac3.o mt7921_mcu.o mt7921_usb.o mt7921_dev.o mt7921_chip.o
SMOKE_OBJS += mt7921_radio.o
TEST_OBJS += mt7921_radio.o

all: mt7921_smoke mt76_radio_probe test_rxd

mt76_radio_probe: mt76_radio_probe.o $(filter-out mt7921_smoke.o,$(SMOKE_OBJS))
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

mt7921_smoke: $(SMOKE_OBJS)
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

test_rxd: $(TEST_OBJS)
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

-include $(wildcard *.d)

test: test_rxd
	./test_rxd

clean:
	rm -f *.o *.d mt7921_smoke mt76_radio_probe test_rxd

.PHONY: all test clean
