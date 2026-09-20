// Find every instruction using a given scalar constant, and report the
// containing function. Much more useful than a raw byte scan because it
// resolves the function each hit lives in.
//
// Usage:
//   analyzeHeadless.bat "<repo>\ghidra" SHH -process g_SilentHill.sgl \
//       -noanalysis -scriptPath "<repo>\tools" \
//       -postScript FindConstUse.java <outFile> <value> [<value> ...]
//
// Values are decimal, e.g. 1280 720.
//
//@category Analysis

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.OperandType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;

public class FindConstUse extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("FindConstUse: need <outFile> <value> [<value> ...]");
            return;
        }
        String outPath = args[0];
        Set<Long> wanted = new HashSet<>();
        for (int i = 1; i < args.length; i++) {
            wanted.add(Long.parseLong(args[i]));
        }

        PrintWriter out = new PrintWriter(outPath, "UTF-8");
        try {
            out.println("scanning for scalar operands: " + wanted);
            out.println();

            InstructionIterator it = currentProgram.getListing().getInstructions(true);
            int hits = 0;
            while (it.hasNext() && !monitor.isCancelled()) {
                Instruction ins = it.next();
                for (int op = 0; op < ins.getNumOperands(); op++) {
                    Object[] objs = ins.getOpObjects(op);
                    for (Object o : objs) {
                        if (!(o instanceof Scalar)) {
                            continue;
                        }
                        long v = ((Scalar) o).getUnsignedValue();
                        if (!wanted.contains(v)) {
                            continue;
                        }
                        Address a = ins.getAddress();
                        Function f = getFunctionContaining(a);
                        out.println(String.format("%-12s %-8d %-40s %s",
                                a.toString(), v, ins.toString(),
                                f != null ? f.getName() + " @" + f.getEntryPoint() : "(no function)"));
                        hits++;
                    }
                }
            }
            out.println();
            out.println("total hits: " + hits);
        } finally {
            out.close();
        }
        println("FindConstUse: wrote " + outPath);
    }
}
