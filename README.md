# Wex

/* WexDumper69 -- https://github.com/lolcaken/Wex */

Universal WASM dumper. Every function named, every call resolved. One file, zero dependencies.

```bash
git clone https://github.com/lolcaken/Wex.git
cd Wex
python wasmdump.py game.wasm [-o outdir]
```

Outputs `<game>.wexdump/` with `map.json` (everything, resolved) and `report.txt` (summary).
`funcs[i]` is index-addressable. `calls`/`callers` give you both directions of every edge.

## Run the dumper (.py)

Needs Python 3.8+. Nothing to install.

```bash
python wasmdump.py game.wasm            # -> game.wexdump/map.json + report.txt
python wasmdump.py game.wasm -o out/    # -> out/map.json + report.txt
```

## Run the capture hook (.js)

For sites that never hand you the `.wasm` file:

1. Open the site in Chrome, hit **F12**.
2. At the top of the console, switch the frame dropdown from `top` to the **game frame**. (use use the devtools picker tool and click canva)
3. Paste all of `wex-capture.js`, Enter. You'll see `[wex] armed.`
4. Reload the page (keep DevTools open).
5. `wex.list()` — modules caught. `wex.save(0)` — downloads `wex-module-0.wasm`.
6. `python wasmdump.py wex-module-0.wasm` — full map + report.

Only works where the site actually ships wasm — pure-JS games catch nothing
(verified: zero `.wasm` resources = zero modules, correctly).

MIT — see [LICENSE](LICENSE).
