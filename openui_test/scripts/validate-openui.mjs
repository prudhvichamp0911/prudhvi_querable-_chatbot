/**
 * Validates OpenUI Lang with the official parser (@openuidev/lang-core)
 * against the same library the browser renders (openuiChatLibrary).
 *
 *   node scripts/validate-openui.mjs file1.txt [file2.txt ...]
 *   echo "root = Card([...])" | node scripts/validate-openui.mjs -
 *
 * Prints one JSON line per input and exits 1 if any input is invalid.
 */
import { readFileSync } from "node:fs";
import { createParser } from "@openuidev/lang-core";
import { openuiChatLibrary } from "@openuidev/react-ui/genui-lib";

const parser = createParser(openuiChatLibrary.toJSONSchema(), "Card");
const inputs = process.argv.slice(2);
let failed = false;

for (const input of inputs.length ? inputs : ["-"]) {
  const text = readFileSync(input === "-" ? 0 : input, "utf8");
  const result = parser.parse(text);
  const ok = result.root?.typeName === "Card" && result.meta.errors.length === 0 && result.meta.unresolved.length === 0;
  if (!ok) failed = true;
  console.log(
    JSON.stringify({
      input,
      ok,
      root: result.root?.typeName ?? null,
      children: result.root?.props?.children?.length ?? 0,
      statements: result.meta.statementCount,
      unresolved: result.meta.unresolved,
      orphaned: result.meta.orphaned,
      errors: result.meta.errors.map((e) => `${e.code}: ${e.message}`.slice(0, 300)),
    }),
  );
}
process.exit(failed ? 1 : 0);
