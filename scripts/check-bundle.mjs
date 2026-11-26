import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const DIST = fileURLToPath(new URL("../frontend/dist", import.meta.url));
const ASSETS = join(DIST, "assets");
const KB = 1024;

const BUDGET = {
  initialJsKb: 95,
  cssKb: 15,
  chartsChunkKb: 175
};

if (!existsSync(ASSETS)) {
  console.error(`Missing frontend build assets at ${ASSETS}. Run frontend build first.`);
  process.exit(1);
}

const html = readFileSync(join(DIST, "index.html"), "utf8");
const preloadedOrEntry = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+)"/g)].map((m) => m[1]);
const files = readdirSync(ASSETS);
const gzipKb = (file) => gzipSync(readFileSync(join(ASSETS, file))).length / KB;

const entryJs = preloadedOrEntry.filter((f) => f.endsWith(".js"));
const entryCss = preloadedOrEntry.filter((f) => f.endsWith(".css"));
const initialJsKb = entryJs.reduce((sum, f) => sum + gzipKb(f), 0);
const initialCssKb = entryCss.reduce((sum, f) => sum + gzipKb(f), 0);
const chartsChunk = files.find((f) => f.startsWith("charts-") && f.endsWith(".js"));
const chartsPreloaded = entryJs.some((f) => f.startsWith("charts-"));

const failures = [];
console.log(`Initial JS (gzip):  ${initialJsKb.toFixed(2)} kB (budget ${BUDGET.initialJsKb} kB)`);
console.log(`Initial CSS (gzip): ${initialCssKb.toFixed(2)} kB (budget ${BUDGET.cssKb} kB)`);
if (chartsChunk) {
  const ck = gzipKb(chartsChunk);
  console.log(`Lazy charts chunk:  ${ck.toFixed(2)} kB (preloaded=${chartsPreloaded})`);
  if (ck > BUDGET.chartsChunkKb) {
    failures.push(`charts chunk ${ck.toFixed(2)} kB exceeds ${BUDGET.chartsChunkKb} kB budget`);
  }
}

if (initialJsKb > BUDGET.initialJsKb) {
  failures.push(`Initial JS ${initialJsKb.toFixed(2)} kB exceeds ${BUDGET.initialJsKb} kB budget`);
}
if (initialCssKb > BUDGET.cssKb) {
  failures.push(`Initial CSS ${initialCssKb.toFixed(2)} kB exceeds ${BUDGET.cssKb} kB budget`);
}
if (chartsPreloaded) {
  failures.push("Recharts charts chunk must stay lazy-loaded and out of initial index.html");
}

if (failures.length > 0) {
  console.error(`Bundle budget failed:\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log("Bundle budget passed.");
