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

No `.wasm` file? Paste `wex-capture.js` in the game frame's console, reload,
`wex.save(N)`, then dump the downloaded file. Details in the script header.

MIT — see [LICENSE](LICENSE).
