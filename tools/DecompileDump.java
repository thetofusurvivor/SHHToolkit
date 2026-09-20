// Decompile a list of functions and dump the C output to a file.
//
// Used to work on g_SilentHill.sgl without the Ghidra MCP bridge: the bridge is
// a per-session client connection and does not survive a dropped connection,
// but headless works any time the project is not locked by a running GUI.
//
// Usage (project must NOT be open in the Ghidra GUI - it holds an exclusive lock):
//
//   analyzeHeadless.bat "<repo>\ghidra" SHH -process g_SilentHill.sgl \
//       -noanalysis -scriptPath "<repo>\tools" \
//       -postScript DecompileDump.java <outFile> <addr> [<addr> ...]
//
// Addresses are hex, with or without 0x, e.g. 10B72D20.
// For each address it decompiles the function containing it. If no function is
// defined there, it says so rather than failing the run.
//
//@category Analysis

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class DecompileDump extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("DecompileDump: need <outFile> <addr> [<addr> ...]");
            return;
        }

        String outPath = args[0];
        List<String> addrs = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            addrs.add(args[i]);
        }

        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        PrintWriter out = new PrintWriter(outPath, "UTF-8");
        try {
            out.println("program: " + currentProgram.getName());
            out.println("imageBase: " + currentProgram.getImageBase());
            out.println();

            for (String a : addrs) {
                String clean = a.toLowerCase().startsWith("0x") ? a.substring(2) : a;
                Address addr;
                try {
                    addr = currentProgram.getAddressFactory().getAddress(clean);
                } catch (Exception e) {
                    out.println("==== " + a + " : bad address ====");
                    continue;
                }

                Function f = getFunctionContaining(addr);
                out.println("======================================================");
                if (f == null) {
                    out.println("==== " + a + " : no function defined here ====");
                    out.println();
                    continue;
                }

                out.println("==== " + a + "  ->  " + f.getName()
                        + "  @" + f.getEntryPoint()
                        + "  (" + f.getBody().getNumAddresses() + " bytes) ====");

                // callers, which is usually the thing worth knowing next
                out.println("-- callers --");
                ReferenceIterator refs =
                        currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
                int n = 0;
                while (refs.hasNext() && n < 40) {
                    Reference r = refs.next();
                    Function from = getFunctionContaining(r.getFromAddress());
                    out.println("   " + r.getFromAddress()
                            + "  " + r.getReferenceType()
                            + (from != null ? ("  in " + from.getName()) : ""));
                    n++;
                }
                if (n == 0) {
                    out.println("   (none)");
                }

                out.println("-- decompiled --");
                DecompileResults res = dec.decompileFunction(f, 120, monitor);
                if (res != null && res.decompileCompleted()) {
                    out.println(res.getDecompiledFunction().getC());
                } else {
                    out.println("   decompilation failed: "
                            + (res == null ? "null" : res.getErrorMessage()));
                }
                out.println();
            }
        } finally {
            out.close();
            dec.dispose();
        }
        println("DecompileDump: wrote " + outPath);
    }
}
