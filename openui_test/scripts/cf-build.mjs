// Cloudflare Workers build (OpenNext). Cross-platform wrapper so the same
// command works in Workers Builds (Linux) and on Windows dev machines.
//
// CLOUDFLARE_BUILD=1 turns on server minification in next.config.ts; without
// it the Worker bundle is over the Workers script-size limit.
import { spawnSync } from "node:child_process";

const result = spawnSync(
  "npx",
  ["opennextjs-cloudflare", "build", "-c", "../wrangler.jsonc", ...process.argv.slice(2)],
  { stdio: "inherit", shell: true, env: { ...process.env, CLOUDFLARE_BUILD: "1" } },
);
process.exit(result.status ?? 1);
