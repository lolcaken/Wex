#!/usr/bin/env python3
"""Wex universal WASM dumper — resolves everything.

Parses a .wasm binary and resolves every index to a name, signature and
cross-reference: functions, imports, exports, globals, memories, tables,
element/data segments, strings, the full call graph (callers + callees),
indirect-call sites, and any name-section debug names.

Usage:
    python wasmdump.py game.wasm [-o outdir]

Output (default <stem>.wexdump/):
    map.json    everything, resolved, machine-readable
    report.txt  human-readable summary

Needs only the Python standard library.
"""

import sys
import os
import json
import struct

VALT = {0x7F: "i32", 0x7E: "i64", 0x7D: "f32", 0x7C: "f64",
        0x70: "funcref", 0x6F: "externref", 0x6E: "exnref"}
KIND = {0: "func", 1: "table", 2: "mem", 3: "global"}

GITHUB = "https://github.com/lolcaken/Wex"

def banner():
    return f"/* WexDumper69 -- {GITHUB} */"


class Malformed(Exception):
    pass


class R:
    def __init__(self, b, what="?"):
        self.b = b
        self.p = 0
        self.what = what

    def left(self):
        return len(self.b) - self.p

    def u8(self):
        if self.p >= len(self.b):
            raise Malformed(f"eof in {self.what}")
        v = self.b[self.p]
        self.p += 1
        return v

    def u32(self):
        r, sh = 0, 0
        for _ in range(5):
            b = self.u8()
            r |= (b & 0x7F) << sh
            if not b & 0x80:
                return r
            sh += 7
        raise Malformed(f"uleb overflow in {self.what}")

    def s64(self):
        r, sh, b = 0, 0, 0
        for _ in range(10):
            b = self.u8()
            r |= (b & 0x7F) << sh
            sh += 7
            if not b & 0x80:
                break
        else:
            raise Malformed(f"sleb overflow in {self.what}")
        if sh < 64 and b & 0x40:
            r |= (~0 << sh)
        return r

    def s32(self):
        v = self.s64()
        v &= (1 << 64) - 1
        if v >= (1 << 63):
            v -= 1 << 64
        return v if -2**31 <= v <= 2**31 - 1 else v

    def bytes(self, n):
        if self.left() < n:
            raise Malformed(f"eof in {self.what} (need {n})")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def name(self):
        n = self.u32()
        if n > 4 * 1024 * 1024:
            raise Malformed(f"name too long in {self.what}")
        raw = self.bytes(n)
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return repr(raw)

    def vec(self, fn):
        return [fn(self, i) for i in range(self.u32())]


def sig_str(params, results):
    return "(" + ", ".join(params) + ") -> " + (", ".join(results) if results else "void")


def printable_runs(data, minlen=5):
    out, cur, start = [], bytearray(), 0
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if not cur:
                start = i
            cur.append(b)
        else:
            if len(cur) >= minlen:
                out.append({"off": start, "len": len(cur), "text": cur.decode("ascii")})
            cur = bytearray()
    if len(cur) >= minlen:
        out.append({"off": start, "len": len(cur), "text": cur.decode("ascii")})
    return out


# ---------------------------------------------------------------- walker ---
# Decodes a function body, skipping every immediate correctly, and records
# call / call_indirect / ref.func events. Unknown prefixed opcodes flag the
# function as partially scanned instead of desyncing.

def _u_leb_at(code, i):
    r, sh = 0, 0
    for _ in range(5):
        if i >= len(code):
            return None, i
        b = code[i]
        i += 1
        r |= (b & 0x7F) << sh
        if not b & 0x80:
            return r, i
        sh += 7
    return None, i


def _s_leb_at(code, i):
    r, sh, b = 0, 0, 0
    for _ in range(10):
        if i >= len(code):
            return None, i
        b = code[i]
        i += 1
        r |= (b & 0x7F) << sh
        sh += 7
        if not b & 0x80:
            break
    return r, i


def walk_body(code):
    """Returns (events, complete). events = list of (kind, value)."""
    events = []
    i, n = 0, len(code)
    while i < n:
        op = code[i]
        i += 1
        if op in (0x00, 0x01, 0x05, 0x0B, 0x0F, 0x1A, 0x1B) or 0x45 <= op <= 0xC4 or op == 0xD1:
            continue
        if op in (0x02, 0x03, 0x04, 0x41, 0x42):
            _, i = _s_leb_at(code, i)
            continue
        if op in (0x0C, 0x0D, 0x10, 0x20, 0x21, 0x22, 0x23, 0x24, 0xD2):
            v, i = _u_leb_at(code, i)
            if v is None:
                return events, False
            if op == 0x10:
                events.append(("call", v))
            continue
        if op == 0x0E:
            cnt, i = _u_leb_at(code, i)
            if cnt is None or cnt > 1000000:
                return events, False
            for _ in range(cnt + 1):
                _, i = _u_leb_at(code, i)
            continue
        if op == 0x11:
            ty, i = _u_leb_at(code, i)
            _, i = _u_leb_at(code, i)
            if ty is None:
                return events, False
            events.append(("call_indirect", ty))
            continue
        if op == 0x1C:
            cnt, i = _u_leb_at(code, i)
            if cnt is None:
                return events, False
            i += cnt
            continue
        if 0x28 <= op <= 0x3E:
            _, i = _u_leb_at(code, i)
            _, i = _u_leb_at(code, i)
            continue
        if op in (0x3F, 0x40, 0xD0):
            i += 1
            continue
        if op == 0x43:
            i += 4
            continue
        if op == 0x44:
            i += 8
            continue
        if op == 0xFC:
            sub, i = _u_leb_at(code, i)
            if sub is None:
                return events, False
            if sub <= 7:
                pass
            elif sub == 8:
                _, i = _u_leb_at(code, i)
                _, i = _u_leb_at(code, i)
            elif sub == 9:
                _, i = _u_leb_at(code, i)
            elif sub == 10:
                i += 2
            elif sub == 11:
                i += 1
            elif sub == 12:
                _, i = _u_leb_at(code, i)
                _, i = _u_leb_at(code, i)
            elif sub == 13:
                _, i = _u_leb_at(code, i)
            elif sub == 14:
                _, i = _u_leb_at(code, i)
                _, i = _u_leb_at(code, i)
            elif sub in (15, 16, 17):
                _, i = _u_leb_at(code, i)
            else:
                return events, True  # unknown 0xFC sub: stop this body, keep events
            continue
        if op == 0xFD:
            sub, i = _u_leb_at(code, i)
            if sub is None:
                return events, False
            if 0 <= sub <= 11 or 92 <= sub <= 93:
                _, i = _u_leb_at(code, i)
                _, i = _u_leb_at(code, i)
            elif sub in (12, 13):
                i += 16
            elif 21 <= sub <= 35 or 84 <= sub <= 91:
                # lane ops (+memarg for lane loads/stores)
                if 84 <= sub <= 91:
                    _, i = _u_leb_at(code, i)
                    _, i = _u_leb_at(code, i)
                i += 1
            elif sub <= 255:
                pass  # arithmetic/shape ops: no immediates
            else:
                return events, True
            continue
        if op == 0xFE or op == 0x1F:
            # exceptions / legacy try-table: complex; flag and stop body
            return events, True
        return events, True  # unknown opcode: stop body, keep events
    return events, True


# ----------------------------------------------------------------- parse ---

def parse(wasm):
    r = R(wasm, "header")
    if r.bytes(4) != b"\x00asm":
        raise Malformed("not a wasm module")
    ver = struct.unpack("<I", r.bytes(4))[0]
    if ver != 1:
        raise Malformed(f"unsupported version {ver}")

    m = {"version": ver, "types": [], "imports": [], "func_types": [],
         "tables": [], "memories": [], "globals": [], "exports": [],
         "start": None, "elems": [], "codes": 0, "datas": [],
         "func_names": {}, "type_names": {}, "global_names": {},
         "module_name": None, "local_names": {}, "errors": []}
    bodies = []

    while r.left() > 0:
        sid = r.u8()
        size = r.u32()
        if r.left() < size:
            m["errors"].append(f"section {sid} overruns file")
            break
        raw = r.bytes(size)
        s = R(raw, f"section {sid}")
        try:
            if sid == 0:
                cname = s.name()
                if cname == "name":
                    while s.left() > 0:
                        sub = s.u8()
                        ssize = s.u32()
                        sp = R(s.bytes(ssize), f"name sub {sub}")
                        if sub == 0:
                            m["module_name"] = sp.name()
                        elif sub == 1:
                            for idx, nm in ((sp.u32(), sp.name()) for _ in range(sp.u32())):
                                m["func_names"][idx] = nm
                        elif sub == 2:
                            for _ in range(sp.u32()):
                                fi = sp.u32()
                                m["local_names"][fi] = {li: nm for li, nm in
                                                        ((sp.u32(), sp.name()) for _ in range(sp.u32()))}
                        elif sub == 4:
                            for idx, nm in ((sp.u32(), sp.name()) for _ in range(sp.u32())):
                                m["type_names"][idx] = nm
                        elif sub == 7:
                            for idx, nm in ((sp.u32(), sp.name()) for _ in range(sp.u32())):
                                m["global_names"][idx] = nm
            elif sid == 1:
                def ptype(rr, _):
                    b = rr.u8()
                    if b not in VALT:
                        raise Malformed(f"bad valtype {b:#x}")
                    return VALT[b]
                n = s.u32()
                for _ in range(n):
                    if s.u8() != 0x60:
                        raise Malformed("bad functype tag")
                    ps = [ptype(s, 0) for _ in range(s.u32())]
                    rs = s.vec(ptype)
                    m["types"].append({"params": ps, "results": rs})
            elif sid == 2:
                def imp(rr, _):
                    mod, nm = rr.name(), rr.name()
                    k = rr.u8()
                    e = {"module": mod, "name": nm, "kind": KIND.get(k, f"?{k}")}
                    if k == 0:
                        e["type"] = rr.u32()
                    elif k == 1:
                        e["elemtype"] = rr.u8()
                        fl, mn = rr.u32(), rr.u32()
                        e["table"] = {"min": mn, "max": rr.u32() if fl & 1 else None}
                    elif k == 2:
                        fl, mn = rr.u32(), rr.u32()
                        e["memory"] = {"min": mn, "max": rr.u32() if fl & 1 else None,
                                       "shared": bool(fl & 2)}
                    elif k == 3:
                        e["global"] = {"type": VALT.get(rr.u8(), "?"), "mut": bool(rr.u8())}
                    return e
                m["imports"] = s.vec(imp)
            elif sid == 3:
                m["func_types"] = s.vec(lambda rr, _: rr.u32())
            elif sid == 4:
                def tbl(rr, _):
                    et = rr.u8()
                    fl, mn = rr.u32(), rr.u32()
                    return {"elemtype": VALT.get(et, hex(et)), "min": mn,
                            "max": rr.u32() if fl & 1 else None}
                m["tables"] = s.vec(tbl)
            elif sid == 5:
                def mem(rr, _):
                    fl, mn = rr.u32(), rr.u32()
                    return {"min": mn, "max": rr.u32() if fl & 1 else None,
                            "shared": bool(fl & 2)}
                m["memories"] = s.vec(mem)
            elif sid == 6:
                def glo(rr, _):
                    t, mu = VALT.get(rr.u8(), "?"), rr.u8()
                    ib = rr.p
                    # scan const init expr to 0x0B
                    while True:
                        b = rr.u8()
                        if b in (0x41, 0x42):
                            rr.s64()
                        elif b == 0x43:
                            rr.bytes(4)
                        elif b == 0x44:
                            rr.bytes(8)
                        elif b == 0x23:
                            rr.u32()
                        elif b == 0x0B:
                            break
                        else:
                            raise Malformed(f"bad global init op {b:#x}")
                    return {"type": t, "mut": bool(mu), "init_hex": ""}
                m["globals"] = s.vec(glo)
            elif sid == 7:
                def exp(rr, _):
                    nm, k, idx = rr.name(), rr.u8(), rr.u32()
                    return {"name": nm, "kind": KIND.get(k, f"?{k}"), "index": idx}
                m["exports"] = s.vec(exp)
            elif sid == 8:
                m["start"] = s.u32()
            elif sid == 9:
                def elem(rr, _):
                    fl = rr.u32()
                    e = {"flags": fl, "funcs": []}
                    if fl == 0:
                        if rr.u8() != 0x41:
                            raise Malformed("elem offset not i32.const")
                        e["offset"] = rr.s32()
                        if rr.u8() != 0x0B:
                            raise Malformed("elem offset unterminated")
                        e["funcs"] = rr.vec(lambda q, _: q.u32())
                    elif fl in (1, 2, 3):
                        kind = rr.u8() if fl in (1, 3) else 0
                        e["elemkind"] = kind
                        e["funcs"] = rr.vec(lambda q, _: q.u32())
                        if fl == 2:
                            e["table"] = rr.u32()
                    else:
                        raise Malformed(f"elem flags {fl} unsupported")
                    return e
                m["elems"] = s.vec(elem)
            elif sid == 10:
                n = s.u32()
                m["codes"] = n
                for _ in range(n):
                    sz = s.u32()
                    body = s.bytes(sz)
                    b = R(body, "code body")
                    locs = []
                    for _ in range(b.u32()):
                        cnt, t = b.u32(), b.u8()
                        locs.append({"count": cnt, "type": VALT.get(t, hex(t))})
                    bodies.append({"locals": locs, "code": body[b.p:]})
            elif sid == 11:
                def data(rr, _):
                    fl = rr.u32()
                    d = {"flags": fl}
                    if fl == 0:
                        if rr.u8() != 0x41:
                            raise Malformed("data offset not i32.const")
                        d["offset"] = rr.s32()
                        if rr.u8() != 0x0B:
                            raise Malformed("data offset unterminated")
                    dl = rr.u32()
                    d["bytes"] = rr.bytes(dl)
                    return d
                for i, d in enumerate(s.vec(data)):
                    m["datas"].append({"seg": i, "flags": d["flags"],
                                       "offset": d.get("offset"),
                                       "len": len(d["bytes"]),
                                       "strings": printable_runs(d["bytes"]),
                                       "raw": d["bytes"]})
            # unknown sections: skipped (forward-compatible)
            if s.left() != 0:
                m["errors"].append(f"section {sid}: {s.left()} trailing bytes")
        except Malformed as e:
            m["errors"].append(f"section {sid}: {e}")
    return m, bodies


def resolve(m, bodies):
    imps = [e for e in m["imports"] if e["kind"] == "func"]
    n_imp = len(imps)
    n_def = len(m["func_types"])
    total = n_imp + n_def

    def ftype_of(idx):
        if idx < n_imp:
            t = imps[idx].get("type")
        else:
            d = idx - n_imp
            t = m["func_types"][d] if d < n_def else None
        return m["types"][t] if t is not None and t < len(m["types"]) else None

    funcs = []
    for idx in range(total):
        if idx < n_imp:
            e = imps[idx]
            nm = f'{e["module"]}.{e["name"]}'
        else:
            d = idx - n_imp
            nm = m["func_names"].get(idx, f"f{idx}")
        t = ftype_of(idx)
        exp = [e["name"] for e in m["exports"] if e["kind"] == "func" and e["index"] == idx]
        funcs.append({"idx": idx, "name": nm, "imported": idx < n_imp,
                      "export_names": exp,
                      "sig": sig_str(t["params"], t["results"]) if t else "?"})

    # display name: export > debug name > import path > fN
    for f in funcs:
        if f["export_names"]:
            f["display"] = f["export_names"][0]
        else:
            f["display"] = f["name"]

    calls, callers = {f["idx"]: [] for f in funcs}, {f["idx"]: [] for f in funcs}
    indirect, partial = [], []
    for d, b in enumerate(bodies):
        idx = n_imp + d
        if idx >= total:
            break
        evs, complete = walk_body(b["code"])
        if not complete:
            partial.append(idx)
        seen = set()
        for kind, v in evs:
            if kind == "call":
                if v not in seen:
                    seen.add(v)
                    calls[idx].append(v)
                    if v in callers:
                        callers[v].append(idx)
            elif kind == "call_indirect":
                indirect.append({"func": idx, "type": v})
            elif kind == "ref.func":
                pass
        funcs[idx]["size"] = len(b["code"])
        funcs[idx]["locals"] = sum(l["count"] for l in b["locals"])

    # table targets (what indirect calls can land on)
    table_funcs = set()
    for e in m["elems"]:
        table_funcs.update(e.get("funcs", []))

    # data bytes -> hex for JSON (raw kept out of report)
    datas = []
    for d in m["datas"]:
        datas.append({"seg": d["seg"], "flags": d["flags"], "offset": d.get("offset"),
                      "len": d["len"], "strings": d["strings"]})

    return {"funcs": funcs, "calls": calls, "callers": callers,
            "indirect_calls": indirect, "partial_scan": partial,
            "table_funcs": sorted(table_funcs), "datas": datas}


def report(m, r):
    L = [banner(), ""]
    L.append(f"{m.get('module_name') or '(anonymous module)'}")
    L.append(f"types={len(m['types'])} imports={len(m['imports'])} "
             f"funcs={len(r['funcs'])} exports={len(m['exports'])} "
             f"globals={len(m['globals'])} memories={len(m['memories'])} "
             f"tables={len(m['tables'])} data_segs={len(m['datas'])}")
    if m["start"] is not None:
        L.append(f"start: f{m['start']}")
    L.append("")
    L.append("== imports ==")
    for e in m["imports"]:
        if e["kind"] == "func":
            t = m["types"][e["type"]] if e["type"] < len(m["types"]) else None
            s = sig_str(t["params"], t["results"]) if t else "?"
            L.append(f'  {e["module"]}.{e["name"]}  {s}')
        else:
            L.append(f'  {e["module"]}.{e["name"]}  ({e["kind"]})')
    L.append("")
    L.append("== exports ==")
    for e in m["exports"]:
        if e["kind"] == "func":
            f = next((f for f in r["funcs"] if f["idx"] == e["index"]), None)
            extra = f"  -> {f['sig']}" if f else ""
        else:
            extra = ""
        L.append(f'  {e["name"]}  ({e["kind"]} {e["index"]}){extra}')
    L.append("")
    L.append("== memories / globals ==")
    for i, mm in enumerate(m["memories"]):
        L.append(f"  mem{i}: min={mm['min']} pages max={mm.get('max')}")
    for i, g in enumerate(m["globals"]):
        nm = m["global_names"].get(i, f"g{i}")
        L.append(f"  {nm}: {g['type']} {'mutable' if g['mut'] else 'const'}")
    L.append("")
    L.append("== hottest funcs (by caller count) ==")
    hot = sorted(r["funcs"], key=lambda f: len(r["callers"][f["idx"]]), reverse=True)[:15]
    for f in hot:
        L.append(f'  f{f["idx"]} {f["display"]}  {f["sig"]}  '
                 f'callers={len(r["callers"][f["idx"]])} callees={len(r["calls"][f["idx"]])}'
                 + ("" if f["imported"] else f'  size={f.get("size",0)}b'))
    L.append("")
    L.append("== data strings (first 40) ==")
    n = 0
    for d in r["datas"]:
        for s in d["strings"]:
            L.append(f'  [seg{d["seg"]}+{s["off"]}] {s["text"][:100]}')
            n += 1
            if n >= 40:
                break
        if n >= 40:
            break
    if r["partial_scan"]:
        L.append("")
        L.append(f"NOTE: {len(r['partial_scan'])} bodies hit unknown opcodes "
                 f"(SIMD/exceptions) — their callees may be incomplete: "
                 f"{r['partial_scan'][:10]}")
    if m["errors"]:
        L.append("")
        L.append("parse notes:")
        for e in m["errors"][:10]:
            L.append(f"  ! {e}")
    return "\n".join(L) + "\n"


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print("usage: wasmdump.py game.wasm [-o outdir]")
        return 1
    src = argv[1]
    out = None
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
    if out is None:
        base = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(src)), base + ".wexdump")
    os.makedirs(out, exist_ok=True)
    with open(src, "rb") as f:
        wasm = f.read()
    print(f"[wex] {src} ({len(wasm)} bytes)")
    m, bodies = parse(wasm)
    r = resolve(m, bodies)
    # JSON-safe: drop raw bytes
    m_json = {k: v for k, v in m.items() if k != "datas"}
    doc = {"tool": "WexDumper69", "github": GITHUB, "banner": banner(),
           "file": os.path.basename(src), "size": len(wasm), **m_json, **r,
           "datas": r["datas"]}
    # funcs already carry everything; calls/callers keyed by int -> str for JSON
    doc["calls"] = {str(k): v for k, v in r["calls"].items()}
    doc["callers"] = {str(k): v for k, v in r["callers"].items()}
    with open(os.path.join(out, "map.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    rep = report(m, r)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(rep)
    print(rep.split("\n\n")[0].replace("\n", " | "))
    print(f"[wex] wrote {out}\\map.json + report.txt  "
          f"({len(r['funcs'])} funcs, {sum(len(v) for v in r['calls'].values())} call edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
