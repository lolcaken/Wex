// == WexDumper69 · runtime capture ==
/* WexDumper69 -- https://github.com/lolcaken/Wex */
//
// Paste this in the DevTools console of the GAME FRAME (not the page),
// ideally before the game boots (or just reload right after pasting with
// "preserve log" on). It hooks every WebAssembly entry point, keeps a copy
// of each module's raw bytes, and lets you pull them out as valid .wasm
// files — which you then feed to wasmdump.py:
//
//   web application
//         ↓
//   WASM bytes  ← captured here
//         ↓
//   game.wasm  (via wex.save())
//         ↓
//   python wasmdump.py game.wasm
//         ↓
//   map.json + report.txt
//
// Console API:
//   wex.list()    — table of captured modules (index, size, via, url)
//   wex.save(i)   — download module i as wex-module-i.wasm
//   wex.saveAll() — download them all
//   wex.clear()   — drop captured bytes
(() => {
  if (window.wex && window.wex._armed) {
    console.log("[wex] already armed.");
    return;
  }
  const mods = []; // {bytes: Uint8Array, via, url, when, imports}

  function bytesOf(src) {
    if (src instanceof ArrayBuffer) return new Uint8Array(src);
    if (ArrayBuffer.isView(src)) {
      return new Uint8Array(src.buffer, src.byteOffset, src.byteLength);
    }
    return null;
  }

  function keep(src, via, imports) {
    const b = bytesOf(src);
    if (!b || b.length < 8) return;
    if (b[0] !== 0x00 || b[1] !== 0x61 || b[2] !== 0x73 || b[3] !== 0x6d) return;
    const copy = new Uint8Array(b.length);
    copy.set(b);
    mods.push({
      bytes: copy,
      via,
      url: location.href.slice(0, 160),
      when: new Date().toISOString(),
      imports: imports ? Object.keys(imports) : [],
    });
    console.log(`[wex] captured module #${mods.length - 1} (${copy.length} bytes via ${via})`);
  }

  // new WebAssembly.Module(bytes)
  const OrigModule = WebAssembly.Module;
  WebAssembly.Module = new Proxy(OrigModule, {
    construct(t, args) {
      keep(args[0], "new Module");
      return new t(...args);
    },
  });

  // WebAssembly.compile(bytes)
  const origCompile = WebAssembly.compile.bind(WebAssembly);
  WebAssembly.compile = (src) => {
    keep(src, "compile");
    return origCompile(src);
  };

  // WebAssembly.instantiate(bytes|module, imports)
  const origInst = WebAssembly.instantiate.bind(WebAssembly);
  WebAssembly.instantiate = (src, imports) => {
    keep(src, "instantiate", imports);
    return origInst(src, imports);
  };

  // WebAssembly.instantiateStreaming(fetch(...))
  const origStream = WebAssembly.instantiateStreaming.bind(WebAssembly);
  WebAssembly.instantiateStreaming = (respP, imports) => {
    try {
      Promise.resolve(respP)
        .then((r) => r.clone().arrayBuffer())
        .then((ab) => keep(ab, "instantiateStreaming",
                            imports && imports[Object.keys(imports)[0]] !== undefined
                              ? Object.assign({}, ...Object.keys(imports).map((k) => ({ [k]: Object.keys(imports[k] || {}) })))
                              : undefined))
        .catch(() => {});
    } catch (e) { /* capture is best-effort; never break the game */ }
    return origStream(respP, imports);
  };

  function download(i) {
    const m = mods[i];
    if (!m) {
      console.log(`[wex] no module #${i} (see wex.list())`);
      return;
    }
    const blob = new Blob([m.bytes], { type: "application/wasm" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wex-module-${i}.wasm`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 4000);
    console.log(`[wex] saved wex-module-${i}.wasm (${m.bytes.length} bytes) -> feed it to wasmdump.py`);
  }

  window.wex = {
    _armed: true,
    list() {
      console.table(mods.map((m, i) => ({
        idx: i, bytes: m.bytes.length, via: m.via,
        imports: m.imports.join(",") || "-",
        when: m.when,
      })));
      return mods.length;
    },
    save: download,
    saveAll() {
      mods.forEach((_, i) => download(i));
    },
    clear() {
      mods.length = 0;
      console.log("[wex] cleared.");
    },
  };
  console.log("[wex] armed. capturing WebAssembly modules — run wex.list() anytime.");
})();
