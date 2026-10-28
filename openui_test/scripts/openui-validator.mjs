/**
 * Long-running OpenUI Lang validator used by the FastAPI backend.
 *
 * Reads one JSON request per line on stdin: {"id": "...", "text": "..."}
 * Writes one JSON response per line on stdout:
 *   {"id", "ok", "root", "errors": [...], "unresolved": [...], "orphaned": [...]}
 *
 * Validation uses the official parser (@openuidev/lang-core createParser)
 * with the JSON schema of the exact library the browser renders
 * (openuiChatLibrary), exported to backend/openui/library.json by
 * generate-openui-assets.mjs. Loading the schema instead of the React
 * package keeps start-up fast.
 */
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createParser } from "@openuidev/lang-core";

const here = dirname(fileURLToPath(import.meta.url));
const library = JSON.parse(readFileSync(resolve(here, "../../backend/openui/library.json"), "utf8"));
const parser = createParser(library.schema, library.root ?? "Card");
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on("line", (line) => {
  let id = null;
  try {
    const request = JSON.parse(line);
    id = request.id ?? null;
    const result = parser.parse(String(request.text ?? ""));
    const errors = result.meta.errors.map((e) => `${e.code}: ${e.message}`.slice(0, 400));
    process.stdout.write(
      JSON.stringify({
        id,
        ok: result.root?.typeName === "Card" && errors.length === 0 && result.meta.unresolved.length === 0,
        root: result.root?.typeName ?? null,
        errors,
        unresolved: result.meta.unresolved,
        orphaned: result.meta.orphaned,
      }) + "\n",
    );
  } catch (error) {
    process.stdout.write(JSON.stringify({ id, ok: false, root: null, errors: [`validator: ${error}`], unresolved: [], orphaned: [] }) + "\n");
  }
});
