// SPDX-License-Identifier: BSD-3-Clause-Clear
// Read-only bounded stock-decoder inspection. Custom/overlapping ISAs need separate checks.
//@category NetworkWeather

import ghidra.app.script.GhidraScript;
import ghidra.app.util.PseudoDisassembler;
import ghidra.app.util.PseudoInstruction;
import ghidra.program.model.address.Address;

public class InstructionWindow extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) throw new IllegalArgumentException("ADDRESS BYTES");
        int count = Integer.decode(args[1]);
        if (count < 2 || count > 4096) throw new IllegalArgumentException("2..4096 bytes only");
        Address pc = toAddr(Long.decode(args[0]));
        Address end = pc.add(count);
        PseudoDisassembler decoder = new PseudoDisassembler(currentProgram);
        println("language=" + currentProgram.getLanguageID());
        println("Stock decoding only: custom extensions can overlap valid standard opcodes.");
        while (pc.compareTo(end) < 0 && !monitor.isCancelled()) {
            PseudoInstruction instruction = decoder.disassemble(pc);
            if (instruction == null) { println("UNDECODED " + pc); break; }
            if (pc.add(instruction.getLength()).compareTo(end) > 0) break;
            println(pc + " " + instruction);
            pc = pc.add(instruction.getLength());
        }
    }
}
