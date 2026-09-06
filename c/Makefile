# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather

CC ?= clang
CFLAGS ?= -Wall -Wextra -O2 -std=c11
FRAMEWORKS = -framework IOKit -framework CoreFoundation

SMOKE_OBJS = mt7921_smoke.o mt7921_dev.o mt7921_mcu.o mt7921_usb.o mt7921_rxd.o mt7921_rxd_connac3.o mt7921_chip.o
TEST_OBJS = test_rxd.o mt7921_rxd.o mt7921_rxd_connac3.o mt7921_mcu.o mt7921_usb.o mt7921_dev.o mt7921_chip.o
SMOKE_OBJS += mt7921_radio.o mt76_csi.o
TEST_OBJS += mt7921_radio.o mt76_csi.o

all: mt7921_smoke mt76_radio_probe mt76_session_probe mt76_csi_probe test_rxd test_session

mt76_csi_probe: mt76_csi_probe.o mt76_session.o $(filter-out mt7921_smoke.o,$(SMOKE_OBJS))
	$(CC) $(CFLAGS) $(FRAMEWORKS) -pthread -o $@ $^

mt76_session_probe: mt76_session_probe.o mt76_session.o $(filter-out mt7921_smoke.o,$(SMOKE_OBJS))
	$(CC) $(CFLAGS) $(FRAMEWORKS) -pthread -o $@ $^

test_session: test_session.o mt76_session.o $(filter-out mt7921_smoke.o,$(SMOKE_OBJS))
	$(CC) $(CFLAGS) $(FRAMEWORKS) -pthread -o $@ $^

mt76_radio_probe: mt76_radio_probe.o $(filter-out mt7921_smoke.o,$(SMOKE_OBJS))
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

mt7921_smoke: $(SMOKE_OBJS)
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

test_rxd: $(TEST_OBJS)
	$(CC) $(CFLAGS) $(FRAMEWORKS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

-include $(wildcard *.d)

test: test_rxd test_session
	./test_rxd
	./test_session

sanitize:
	$(CC) $(CFLAGS) -g -fsanitize=address,undefined -fno-omit-frame-pointer -I. \
		test_radio.c ../tests/c_parity_bridge.c mt7921_radio.c mt76_csi.c mt7921_rxd.c mt7921_rxd_connac3.c \
		mt7921_mcu.c mt7921_dev.c mt7921_usb.c mt7921_chip.c $(FRAMEWORKS) -o test_radio_sanitize
	./test_radio_sanitize
	$(CC) $(CFLAGS) -g -fsanitize=address,undefined -fno-omit-frame-pointer -I. \
		test_session.c mt76_session.c mt7921_mcu.c mt7921_dev.c mt7921_usb.c mt7921_chip.c \
		$(FRAMEWORKS) -pthread -o test_session_sanitize
	./test_session_sanitize

clean:
	rm -f *.o *.d mt7921_smoke mt76_radio_probe mt76_session_probe mt76_csi_probe test_rxd test_radio_sanitize test_session test_session_sanitize

.PHONY: all test sanitize clean
