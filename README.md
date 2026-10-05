# Wex

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey.svg)
![Deps](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)
![Version](https://img.shields.io/badge/version-1.0.0-white.svg)

**Wex is a universal WebAssembly dumper that resolves everything.** Point it at any `.wasm`
binary — a game build, a plugin, a web app module — and it hands you back every function with
a name and a signature, every import and export, every string in linear memory, and the full
call graph: who calls whom, who calls *you*, and where indirect calls can land.

No dependencies. One file. Pure standard-library Python.

---

## What it resolves

| Thing | What you get |
|---|---|
| Functions | every index → display name (export name › debug name › `mod.name` import › `fN`), full `(params) -> results` signature, body size, local count |
| Imports | `module.name` + resolved signature for all 4 kinds (func / table / memory / global) |
| Exports | name, kind, index, and the target's signature |
| Call graph | per-function callee list **and** caller list (bidirectional xrefs) |
| Indirect calls | every `call_indirect` site + its expected type, plus the table's actual targets from element segments |
| Globals / memories / tables | types, mutability, limits |
| Data segments | offset, length, and every printable string inside with its `seg+offset` |
| Names | `name`-section debug names for module, functions, locals, types, globals |
| Start function | entry index, resolved like everything else |

Bodies are walked with a real opcode decoder (correct immediate-skipping for every MVP
opcode, `0xFC` extensions, and SIMD prefixes), so call edges are exact — not guessed from
byte patterns. Anything the walker doesn't understand is flagged per-function in
`partial_scan` instead of silently desyncing the rest.

---

## Quickstart

```bash
git clone https://github.com/lolcaken/Wex.git
cd Wex

# dump anything
python wasmdump.py game.wasm [-o outdir]
```

That's it. No install, no virtualenv, no build step. Output lands in
`<game>.wexdump/` next to the input (or wherever `-o` points):

- **`map.json`** — everything, resolved, machine-readable. Grep it, script it, diff it across builds.
- **`report.txt`** — the one-page human summary: counts, imports, exports, hottest functions, first 40 strings.

Both outputs are stamped with the WexDumper69 banner:

```text
/*
 *  __        __   ____   __  __   ____     _   _    _ __ ___    ____     ____    _ __     __     ___
 *  \          /  |  _ \  \ \/ /  |  _ \   | | | |  | '_ ` _ \  |  _ \   |  _ \  | '__|   / /_   / _ \
 *   \    /\  /  | |_| |   \  /   | | | |  | | | |  | | | | | |  | |_) |  | |_| |  | |     | '_ \  | (_) |
 *    \  /  \/   |  __/   /_/\_\  | |_| |  | |_| |  |_| |_| |_|  |  __/   |  __/   |_|     | (_) |   \__, |
 *     \/  \/    |_|               |____/    \__,_|                |_|      |_|                \___/     /_/
 *
 *  WexDumper69 - universal WASM dumper
 *  https://github.com/lolcaken/Wex
 */
```

---

## No `.wasm` file? Capture it live

Most web games never hand you the binary — it arrives over the network and goes
straight into `WebAssembly.compile` / `instantiate` / `instantiateStreaming`.
`wex-capture.js` sits in front of those entry points and keeps a copy of every
module's raw bytes:

```text
web application
      ↓
WASM bytes   ← captured here (DevTools console, game frame)
      ↓
game.wasm    ← wex.save()
      ↓
python wasmdump.py game.wasm
      ↓
map.json + report.txt
```

**Instructions:**

1. Open the game in Chrome, open DevTools (`F12`), and switch the console's frame
   context to the **game frame** (the dropdown at the top of the console that says
   `top` — pick the `gdn.poki.com` / game iframe).
2. Paste the entire contents of `wex-capture.js`, hit Enter. You'll see
   `[wex] armed.`
3. Reload the page (keep DevTools open, tick "preserve log" if you want the history).
   Every compiled module prints `[wex] captured module #N (XXXX bytes via ...)`.
4. `wex.list()` — see what's caught. `wex.save(N)` — download it as
   `wex-module-N.wasm`. `wex.saveAll()` — grab everything.
5. `python wasmdump.py wex-module-0.wasm` — full map + report.

Nothing leaves your machine. The hook is best-effort and read-only — it never
modifies bytes, so the game runs exactly as before.

### Example session

```
$ python wasmdump.py index.wasm
[wex] index.wasm (2193391 bytes)
Wex dump — (anonymous module) | types=152 imports=116 funcs=2418 exports=83 globals=2 memories=1 tables=1 data_segs=2182
[wex] wrote index.wexdump\map.json + report.txt  (2418 funcs, 5167 call edges)
```

```text
== exports ==
  jb  (func 854)  -> () -> void
  nb  (func 118)  -> (i32) -> void
  ...

== hottest funcs (by caller count) ==
  f0 a.a  (i32, i32, i32, i32) -> void  callers=183
  f118 nb  (i32) -> void  callers=169
  ...

== data strings (first 40) ==
  [seg3+0] DAILY REWARD
  [seg4+2] {"g":[%s],"v":[%s],"i":%i}
  ...
```

### Querying the map

```bash
# which functions call into the allocator?
python -c "
import json; d = json.load(open('index.wexdump/map.json'))
malloc = next(f['idx'] for f in d['funcs'] if f['display'] == 'malloc')
for c in d['callers'][str(malloc)]:
    f = d['funcs'][c]
    print(f\"f{c} {f['display']}  {f['sig']}\")"

# every string mentioning a level, a key, a URL
python -c "
import json; d = json.load(open('index.wexdump/map.json'))
for s in d['datas']:
    for t in s['strings']:
        if 'level' in t['text'].lower():
            print(f\"[seg{s['seg']}+{t['off']}] {t['text'][:120]}\")"
```

---

## The `map.json` schema

```jsonc
{
  "file": "index.wasm",
  "size": 2193391,
  "version": 1,
  "module_name": null,
  "types":   [{ "params": ["i32"], "results": ["i32"] }],
  "imports": [{ "module": "a", "name": "b", "kind": "func", "type": 3 }],
  "exports": [{ "name": "malloc", "kind": "func", "index": 129 }],
  "globals": [{ "type": "i32", "mut": false, "init_hex": "" }],
  "memories": [{ "min": 923, "max": 32768, "shared": false }],
  "tables":  [{ "elemtype": "funcref", "min": 0, "max": null }],
  "funcs": [{
    "idx": 129, "name": "malloc", "display": "malloc",
    "imported": false, "export_names": ["malloc"],
    "sig": "(i32) -> i32", "size": 312, "locals": 4
  }],
  "calls":    { "1402": [1, 129, 118] },
  "callers":  { "129": [1402, 856] },
  "indirect_calls": [{ "func": 955, "type": 12 }],
  "table_funcs": [129, 140, 196],
  "partial_scan": [],
  "datas": [{ "seg": 12, "offset": 65536, "len": 4096,
              "strings": [{ "off": 64, "len": 41, "text": "..." }] }],
  "func_names": {}, "type_names": {}, "global_names": {}, "local_names": {},
  "start": null,
  "errors": []
}
```

`funcs[i]` is index-addressable (`funcs[129]` is `f129`). `calls`/`callers` keys are
strings in JSON — cast to int. `partial_scan` lists any function whose body hit an opcode
the walker doesn't cover; treat its callees as a lower bound.

---

## How it works

1. **Parse** — every section (0–11) decoded by hand, including custom sections and the
   `name` subsection family. Unknown sections are skipped, never fatal.
2. **Name** — each function gets one display name by priority: export name › `name`-section
   debug name › `module.name` import path › `f{idx}`.
3. **Walk** — each defined body is decoded instruction-by-instruction with an
   immediate-length table covering all MVP opcodes, sign-extension ops, `0xFC` bulk-memory
   and saturating-truncation ops, and SIMD prefixes. `call`, `call_indirect`, and table
   targets are recorded; the reverse map (callers) is built by inversion.
4. **Strings** — every data segment is swept for printable-ASCII runs (≥ 5 chars) with
   exact `seg+offset` provenance.

## Limits (honest ones)

- It's a **dumper, not a decompiler** — you get structure, names, and edges, not C code.
- Function bodies behind SIMD/exception opcodes outside the covered set are flagged in
  `partial_scan` rather than force-decoded.
- Passive element/data segments (non-zero flags) are reported, not applied.
- Multi-value blocks are fine for edges but signatures show the declared type as-is.

## Contributing

Humanity welcome. Open an issue with the module that breaks it (or a minimal repro) —
`errors[]` in `map.json` tells you exactly which section complained. PRs that add opcode
coverage to the walker are the highest-value contribution: one row in a table, plus a test
binary.

## License

MIT — see [LICENSE](LICENSE). Do good things with it.
