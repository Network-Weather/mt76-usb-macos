// SPDX-License-Identifier: BSD-3-Clause-Clear
// Bounded, read-only NDS32 instruction inspection with explicit EX9 annotations.
//@category NetworkWeather

import ghidra.app.script.GhidraScript;
import ghidra.app.util.PseudoDisassembler;
import ghidra.app.util.PseudoInstruction;
import ghidra.program.model.address.Address;
import ghidra.program.model.scalar.Scalar;

public class Nds32Inspect extends GhidraScript {
    private long word(byte[] bytes) {
        long value = 0;
        for (int i = 0; i < 4; i++) value = (value << 8) | (bytes[i] & 255);
        return value;
    }

    private String describe(PseudoInstruction ins) throws Exception {
        String result = ins.toString();
        if (ins.getMnemonicString().equals("addi.gp")) {
            // Ghidra 12.1.3 defines semantics but omits rendered operands.
            long bits = word(ins.getBytes());
            long offset = bits & 0x7ffff;
            if ((offset & 0x40000) != 0) offset -= 0x80000;
            result += " r" + ((bits >>> 20) & 31) + ",gp," + offset;
        }
        return result;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("ADDRESS BYTES ITB_ADDRESS");
        if (!currentProgram.getLanguageID().toString().equals("NDS32:LE:32:default"))
            throw new IllegalArgumentException("requires NDS32 little-endian-data program");
        Address pc = toAddr(Long.decode(args[0]));
        int length = Integer.decode(args[1]);
        if (length < 2 || length > 4096) throw new IllegalArgumentException("2..4096 bytes only");
        Address end = pc.add(length);
        long table = Long.decode(args[2]);
        PseudoDisassembler decoder = new PseudoDisassembler(currentProgram);
        while (pc.compareTo(end) < 0 && !monitor.isCancelled()) {
            PseudoInstruction ins = decoder.disassemble(pc);
            if (ins == null) { println("UNDECODED " + pc); break; }
            String result = pc + " " + describe(ins);
            if (ins.getMnemonicString().equals("ex9.it")) {
                Object[] operands = ins.getOpObjects(0);
                if (operands.length != 1 || !(operands[0] instanceof Scalar))
                    throw new IllegalStateException("unexpected EX9 operand");
                long index = ((Scalar) operands[0]).getUnsignedValue();
                if (index >= 512) throw new IllegalStateException("EX9 index too large");
                Address fetch = toAddr(table + index * 4);
                byte[] bytes = new byte[4];
                currentProgram.getMemory().getBytes(fetch, bytes);
                PseudoInstruction expanded = decoder.disassemble(pc, bytes);
                result += " => " + (expanded == null ? "UNDECODED" : describe(expanded));
                long bits = word(bytes);
                if ((bits >>> 25) == 0x24) {
                    // EX9 J/JAL uses concatenation, not the regular PC-relative displacement.
                    long target = (pc.getOffset() & 0xfe000000L) | ((bits & 0xffffff) << 1);
                    result += " [EX9 absolute target=0x" + Long.toHexString(target)
                        + "; ignore ordinary displayed branch target]";
                }
            }
            println(result);
            pc = pc.add(ins.getLength());
        }
    }
}
