// SPDX-License-Identifier: BSD-3-Clause-Clear
// Read-only annotations for the pinned MT7925 startup; NOT a full ISA/decompiler.
//@category NetworkWeather

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.PseudoDisassembler;
import ghidra.app.util.PseudoInstruction;
import ghidra.program.model.address.Address;

public class Mt7925AndesInspect extends GhidraScript {
    private long bits(long value, int start, int count) {
        return (value >>> start) & ((1L << count) - 1);
    }

    private long word(byte[] data) {
        long result = 0;
        for (int i = 0; i < 4; i++) result |= (data[i] & 255L) << (8 * i);
        return result;
    }

    private String describe(PseudoDisassembler decoder, Address pc, byte[] data) throws Exception {
        long value = word(data);
        boolean add = (value & 0x307f) == 0x100b;
        boolean load = (value & 0x707f) == 0x202b;
        if (add || load) {
            long offset = bits(value, 20, 1) << 11 | bits(value, 17, 3) << 12
                | bits(value, 15, 2) << 15;
            int width;
            if (add) {
                offset |= bits(value, 14, 1) | bits(value, 21, 10) << 1
                    | bits(value, 31, 1) << 17;
                width = 18;
            } else {
                offset |= bits(value, 22, 9) << 2 | bits(value, 21, 1) << 17
                    | bits(value, 31, 1) << 18;
                width = 19;
            }
            if ((offset & (1L << (width - 1))) != 0) offset -= 1L << width;
            return (add ? "nds.addigp" : "nds.lwgp") + " x" + bits(value, 7, 5)
                + ",gp," + offset + " [annotation only]";
        }
        PseudoInstruction ins = decoder.disassemble(pc, data);
        if (ins == null) return "UNDECODED";
        String result = ins.toString();
        if ((value & 0x7f) == 0x6f) {
            long immediate = bits(value, 21, 10) << 1 | bits(value, 20, 1) << 11
                | bits(value, 12, 8) << 12 | bits(value, 31, 1) << 20;
            result += " [if EXEC.IT JAL: concatenated target=0x"
                + Long.toHexString((pc.getOffset() & 0xffe00000L) | immediate)
                + "; ordinary displayed target is not authoritative]";
        }
        return result;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("ADDRESS BYTES LOCAL_4096_BYTE_TABLE");
        if (!currentProgram.getLanguageID().toString().equals("RISCV:LE:32:default"))
            throw new IllegalArgumentException("requires RISCV:LE:32:default");
        int length = Integer.decode(args[1]);
        if (length < 2 || length > 4096) throw new IllegalArgumentException("2..4096 bytes only");
        Path path = Path.of(args[2]);
        if (Files.size(path) != 4096) throw new IllegalArgumentException("exactly 4096 table bytes");
        byte[] table = Files.readAllBytes(path);
        Address pc = toAddr(Long.decode(args[0]));
        Address end = pc.add(length);
        PseudoDisassembler decoder = new PseudoDisassembler(currentProgram);
        println("EXPERIMENTAL: 0xa002 family is an observed MT7925 candidate, not upstream NEXEC.IT.");
        while (pc.compareTo(end) < 0 && !monitor.isCancelled()) {
            byte[] prefix = new byte[2];
            currentProgram.getMemory().getBytes(pc, prefix);
            int half = (prefix[0] & 255) | (prefix[1] & 255) << 8;
            if ((half & 0xe003) == 0xa002) {
                int[] positions = {4, 10, 11, 2, 5, 6, 9, 3, 7, 8};
                int index = 0;
                for (int i = 0; i < positions.length; i++) index |= ((half >>> positions[i]) & 1) << i;
                // Bit 12 is outside the ten-bit permutation. Do not silently alias it.
                if ((half & 0x1000) != 0) { println("UNRESOLVED extended table index " + pc); break; }
                byte[] data = Arrays.copyOfRange(table, index * 4, index * 4 + 4);
                println(pc + " candidate.table[" + index + "] => " + describe(decoder, pc, data));
                pc = pc.add(2);
                continue;
            }
            int count = (half & 3) == 3 ? 4 : 2;
            if (pc.add(count).compareTo(end) > 0) break;
            byte[] data = new byte[4];
            currentProgram.getMemory().getBytes(pc, data, 0, count);
            String description = describe(decoder, pc, data);
            println(pc + " " + description);
            if (description.equals("UNDECODED")) break;
            pc = pc.add(count);
        }
    }
}
