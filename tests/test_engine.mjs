// Tests for the prediction engine — run with:  node tests/test_engine.mjs
// The app ships as a single self-contained index.html, so we (1) statically check the
// embedded FIFA allocation table, and (2) evaluate the page script inside a tiny DOM stub
// to exercise the pure logic (standings, tiebreakers, scoring) without a browser.
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
let passed = 0, failed = 0;
const ok = (name, cond) => { if (cond) { passed++; console.log("  ✓", name); }
  else { failed++; console.log("  ✗", name); } };

// ── 1. Static integrity of FIFA Annex C third-place table ──────────────────────
console.log("FIFA third-place allocation table (Annex C):");
const THIRD = JSON.parse(html.match(/const THIRD_TABLE = (\{[\s\S]*?\});/)[1]);
const TSLOTS = eval("(" + html.match(/const TSLOTS = (\{[^;]*\});/)[1] + ")");
const keys = Object.keys(THIRD);
ok("has all 495 group combinations", keys.length === 495);
ok("every key is 8 distinct sorted group letters",
   keys.every(k => k.length === 8 && [...k].every((c,i,a)=> i===0 || a[i-1] < c)));
let validAssign = true;
for (const k of keys) {
  const a = THIRD[k];
  const ms = Object.keys(a);
  if (ms.length !== 8) validAssign = false;
  for (const m of ms) {
    if (!TSLOTS[m].includes(a[m])) validAssign = false;   // respects eligibility
    if (!k.includes(a[m])) validAssign = false;            // only places qualifying groups
  }
  if (new Set(Object.values(a)).size !== 8) validAssign = false; // no group used twice
}
ok("every assignment respects FIFA eligibility + uses each qualifier once", validAssign);

// ── 2. Evaluate the page script in a minimal DOM stub ──────────────────────────
console.log("Prediction engine (standings, tiebreakers, scoring):");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const noop = () => {};
const el = { textContent:"", innerHTML:"", value:"", style:{}, dataset:{},
  classList:{add:noop,remove:noop,contains:()=>false,toggle:noop},
  querySelector:()=>null, querySelectorAll:()=>[], appendChild:noop,
  addEventListener:noop, dispatchEvent:noop, focus:noop, scrollIntoView:noop, click:noop };
const documentStub = { getElementById:()=>el, querySelector:()=>el, querySelectorAll:()=>[],
  createElement:()=>el, body:el, addEventListener:noop };
const ctx = { document:documentStub, localStorage:{getItem:()=>null,setItem:noop},
  fetch:()=>Promise.reject(0), location:{origin:"",pathname:"/",href:"http://x/"},
  navigator:{}, setTimeout:()=>0, clearTimeout:noop, alert:noop, confirm:()=>true,
  prompt:()=>null, btoa, atob, console, JSON, Math, Date, Set, Map, Object, Array };
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(script, ctx);   // function declarations (computeGroup, scoreOf, …) land on ctx

// normalization mirrors the pipeline (the load-bearing join key)
ok("normTeam: United States → usa", ctx.normTeam("United States") === "usa");
ok("normTeam: Côte d'Ivoire → ivorycoast", ctx.normTeam("Côte d'Ivoire") === "ivorycoast");
ok("normTeam: Congo DR → drcongo", ctx.normTeam("Congo DR") === "drcongo");

// head-to-head reads the real result of two teams' game (Group A: Mexico 2-0 South Africa)
ok("h2h: Mexico beat South Africa → +1", ctx.h2h("A","Mexico","South Africa") === 1);
ok("h2h: reversed → -1", ctx.h2h("A","South Africa","Mexico") === -1);

// standings are computed, not hardcoded — Mexico tops Group A on real results
const A = ctx.computeGroup("A");
ok("computeGroup returns sorted standings objects", Array.isArray(A) && A[0] && "pts" in A[0]);
ok("Group A leader is Mexico (real results)", A[0].team === "Mexico");

// scoring rubric: exact = 5, right result = 2, wrong = 0 (A0 real = Mexico 2-0 South Africa)
ok("scoreOf: exact score → 5 pts", ctx.scoreOf({predicted:{A0:{h:"2",a:"0"}}}).pts === 5);
ok("scoreOf: right winner, wrong score → 2 pts", ctx.scoreOf({predicted:{A0:{h:"1",a:"0"}}}).pts === 2);
ok("scoreOf: wrong result → 0 pts", ctx.scoreOf({predicted:{A0:{h:"0",a:"1"}}}).pts === 0);
ok("scoreOf: unplayed game is not scored", ctx.scoreOf({predicted:{A4:{h:"1",a:"0"}}}).decided === 0);

console.log(`\n${failed ? "✗" : "✓"} ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
