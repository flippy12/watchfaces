#!/usr/bin/env python3
"""Outil de (dé)compilation des cadrans Huawei .hwt (montres LiteOS : Watch Fit 4 Pro, ...).

Commandes :
  unpack  cadran.hwt  dossier/      -> PNG + layout.json + manifest.json
  pack    dossier/    cadran.hwt    -> reconstruit le .hwt
  render  dossier/    apercu.png [--time 10:08] [--date 2025-09-28] [--aod] [--battery 69] [--steps 7589]
  verify  cadran.hwt                -> unpack + pack en mémoire, compare octet par octet

Dépendance : Pillow (pip install pillow).
Voir FORMAT.md pour la description du format.
"""
import argparse, datetime, io, json, os, struct, sys, zipfile

from PIL import Image

INNER = "com.huawei.watchface"
IMG_MAGIC = b"\x45\x23\x88\x88"
RLE = 0x23456789          # mot marqueur : RLE, pixel, nombre
RLE_MIN = 4               # répétitions >= 4 compressées, <= 3 en clair

# --------------------------------------------------------------------------- images

def decode_image(blob):
    if not blob:
        return None
    if blob[:4] != IMG_MAGIC:
        raise ValueError("image : signature inconnue %s" % blob[:4].hex())
    w, h = struct.unpack("<HH", blob[4:8])
    words = struct.unpack("<%dI" % ((len(blob) - 8) // 4), blob[8:])
    px, i = [], 0
    while i < len(words):
        if words[i] == RLE:
            px.extend([words[i + 1]] * words[i + 2]); i += 3
        else:
            px.append(words[i]); i += 1
    if len(px) != w * h:
        raise ValueError("image : %d pixels décodés au lieu de %d" % (len(px), w * h))
    raw = struct.pack("<%dI" % len(px), *px)
    return Image.frombytes("RGBA", (w, h), raw, "raw", "BGRA")


def encode_image(img):
    img = img.convert("RGBA")
    w, h = img.size
    if w > 0xFFFF or h > 0xFFFF:
        raise ValueError("image trop grande")
    raw = img.tobytes("raw", "BGRA")
    px = struct.unpack("<%dI" % (w * h), raw)
    out, i, n = [], 0, len(px)
    while i < n:
        j = i + 1
        while j < n and px[j] == px[i]:
            j += 1
        c = j - i
        if c >= RLE_MIN or px[i] == RLE:
            out += [RLE, px[i], c]
        else:
            out += [px[i]] * c
        i = j
    return IMG_MAGIC + struct.pack("<HH", w, h) + struct.pack("<%dI" % len(out), *out)

# --------------------------------------------------------------------------- protobuf

# Schéma déduit des exemples. type : int | str | bytes | <Message> ; rep = répété.
SCHEMA = {
    "Watchface": {1: ("groups", "Group", True), 2: ("title", "str", False), 3: ("title_cn", "str", False)},
    "Group": {1: ("type", "int", False), 2: ("f2", "int", False), 4: ("background", "str", False),
              5: ("elements", "Element", True), 8: ("widgets", "Widget", True)},
    "Element": {1: ("index", "int", False), 2: ("kind", "int", False), 4: ("image", "ImageElem", False),
                5: ("image_list", "ImageList", False), 6: ("number", "NumberElem", False)},
    "ImageElem": {1: ("image", "str", False), 2: ("pos", "Pos", False), 5: ("f5", "int", False)},
    "ImageList": {1: ("images", "str", True), 2: ("pos", "Pos", False), 3: ("data", "int", False),
                  6: ("aod", "int", False)},
    "NumberElem": {1: ("digits", "str", True), 2: ("f2", "bytes", False), 3: ("pos", "Pos", False),
                   4: ("f4", "int", False), 5: ("f5", "int", False), 6: ("f6", "bytes", False),
                   7: ("f7", "int", False), 8: ("f8", "int", False), 13: ("f13", "int", False)},
    "Widget": {1: ("index", "int", False), 2: ("f2", "int", False), 5: ("rect", "Rect", False),
               6: ("options", "Element", True), 8: ("widget_type", "int", False)},
    "Pos": {1: ("x", "int", False), 2: ("y", "int", False)},
    "Rect": {1: ("x", "int", False), 2: ("y", "int", False), 3: ("w", "int", False), 4: ("h", "int", False)},
}


def _varint(b, i):
    r = s = 0
    while True:
        x = b[i]; i += 1
        r |= (x & 0x7F) << s; s += 7
        if x < 0x80:
            return r, i


def _enc_varint(v):
    if v < 0:
        v &= 0xFFFFFFFF   # entiers négatifs codés sur 32 bits (5 octets), comme le format d'origine
    out = bytearray()
    while True:
        x = v & 0x7F; v >>= 7
        if v:
            out.append(x | 0x80)
        else:
            out.append(x); return bytes(out)


def pb_decode(b, msg):
    sch = SCHEMA[msg]
    res, i = {}, 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
            if 1 << 31 <= v < 1 << 32:
                v -= 1 << 32
            raw = v
        elif wt == 2:
            l, i = _varint(b, i); raw = b[i:i + l]; i += l
        else:
            raise ValueError("type protobuf %d non géré (%s.%d)" % (wt, msg, f))
        if f not in sch:
            res.setdefault("_%d" % f, []).append({"wt": wt, "v": raw} if wt == 0 else {"wt": 2, "hex": raw.hex()})
            continue
        name, typ, rep = sch[f]
        if typ == "int":
            val = raw
        elif typ == "str":
            val = raw.decode("utf-8")
        elif typ == "bytes":
            val = raw.hex()
        else:
            val = pb_decode(raw, typ)
        if rep:
            res.setdefault(name, []).append(val)
        else:
            if name in res:
                raise ValueError("champ %s.%s répété" % (msg, name))
            res[name] = val
    return res


def pb_encode(obj, msg):
    sch = SCHEMA[msg]
    byname = {v[0]: (k, v[1], v[2]) for k, v in sch.items()}
    items = []
    for name, val in obj.items():
        if name.startswith("_"):
            f = int(name[1:])
            for e in val:
                items.append((f, e["wt"], e["v"] if e["wt"] == 0 else bytes.fromhex(e["hex"])))
            continue
        if name not in byname:
            raise ValueError("champ inconnu %s.%s" % (msg, name))
        f, typ, rep = byname[name]
        for v in (val if rep else [val]):
            if typ == "int":
                items.append((f, 0, int(v)))
            elif typ == "str":
                items.append((f, 2, v.encode("utf-8")))
            elif typ == "bytes":
                items.append((f, 2, bytes.fromhex(v)))
            else:
                items.append((f, 2, pb_encode(v, typ)))
    items.sort(key=lambda t: t[0])   # stable : garde l'ordre des répétés
    out = bytearray()
    for f, wt, v in items:
        out += _enc_varint(f << 3 | wt)
        if wt == 0:
            out += _enc_varint(v)
        else:
            out += _enc_varint(len(v)) + v
    return bytes(out)

# --------------------------------------------------------------------------- binaire

def parse_inner(d):
    ver, L, T, S = struct.unpack("<HHII", d[:12])
    reserved = d[12:16]
    layout = d[16:16 + L]
    table = d[16 + L:16 + L + T]
    data = d[16 + L + T:16 + L + T + S]
    if len(d) != 16 + L + T + S:
        raise ValueError("taille incohérente")
    images = []
    for k in range(T // 8):
        o, s = struct.unpack("<II", table[k * 8:k * 8 + 8])
        images.append(data[o:o + s])
    first = struct.unpack("<I", table[:4])[0] if T else 8
    return {"version": ver, "reserved": reserved.hex(), "data_prefix": data[:first].hex(),
            "layout": pb_decode(layout, "Watchface"), "images": images}


def build_inner(version, reserved, prefix, layout, images):
    lay = pb_encode(layout, "Watchface")
    table, data = bytearray(), bytearray(prefix)
    for blob in images:
        table += struct.pack("<II", len(data), len(blob))
        data += blob
    return struct.pack("<HHII", version, len(lay), len(table), len(data)) + reserved + lay + bytes(table) + bytes(data)

# --------------------------------------------------------------------------- commandes

def unpack(hwt, out):
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    zf = zipfile.ZipFile(hwt)
    entries = []
    for zi in zf.infolist():
        entries.append(zi.filename)
        if zi.filename == INNER or zi.is_dir():
            continue
        p = os.path.join(out, zi.filename)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(zf.read(zi))
    inner = parse_inner(zf.read(INNER))
    names = []
    for k, blob in enumerate(inner["images"]):
        name = "%03d" % (k + 1)
        img = decode_image(blob)
        if img is None:
            names.append(None)
        else:
            img.save(os.path.join(out, "images", name + ".png"))
            names.append(name)
    manifest = {"version": inner["version"], "reserved": inner["reserved"], "data_prefix": inner["data_prefix"],
                "images": names, "zip_entries": entries}
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    with open(os.path.join(out, "layout.json"), "w") as fh:
        json.dump(inner["layout"], fh, indent=2, ensure_ascii=False)
    print("%d images, layout -> %s" % (len(names), out))


def load_dir(src):
    man = json.load(open(os.path.join(src, "manifest.json")))
    layout = json.load(open(os.path.join(src, "layout.json")))
    imgs = {}
    for n in man["images"]:
        if n:
            imgs[n] = Image.open(os.path.join(src, "images", n + ".png")).convert("RGBA")
    return man, layout, imgs


def check_refs(layout, man):
    known = {n for n in man["images"] if n}
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("image", "background") and isinstance(v, str) and v:
                    yield v
                elif k in ("images", "digits"):
                    yield from v
                else:
                    yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    missing = sorted({r for r in walk(layout) if r not in known})
    if missing:
        raise SystemExit("images référencées mais absentes : %s" % ", ".join(missing))


def build_from_dir(src):
    man, layout, imgs = load_dir(src)
    check_refs(layout, man)
    blobs = [encode_image(imgs[n]) if n else b"" for n in man["images"]]
    return build_inner(man["version"], bytes.fromhex(man["reserved"]), bytes.fromhex(man["data_prefix"]),
                       layout, blobs), man


def pack(src, hwt):
    inner, man = build_from_dir(src)
    entries = man.get("zip_entries") or [INNER, "description.xml", "preview/", "preview/cover.jpg",
                                          "preview/icon_small.jpg"]
    with zipfile.ZipFile(hwt, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            if e == INNER:
                zf.writestr(INNER, inner)
            elif e.endswith("/"):
                zf.writestr(zipfile.ZipInfo(e), b"")
            elif os.path.exists(os.path.join(src, e)):
                zf.write(os.path.join(src, e), e)
            else:
                print("attention : %s manquant" % e, file=sys.stderr)
    print("%s écrit (%d octets pour %s)" % (hwt, len(inner), INNER))


def verify(hwt):
    import tempfile
    zf = zipfile.ZipFile(hwt)
    orig = zf.read(INNER)
    with tempfile.TemporaryDirectory() as tmp:
        unpack(hwt, tmp)
        rebuilt, _ = build_from_dir(tmp)
    if rebuilt == orig:
        print("OK : reconstruction identique octet pour octet (%d octets)" % len(orig))
        return True
    n = next((i for i in range(min(len(orig), len(rebuilt))) if orig[i] != rebuilt[i]), None)
    print("DIFFÉRENT : tailles %d / %d, premier écart à l'octet %s" % (len(orig), len(rebuilt), n))
    return False

# --------------------------------------------------------------------------- aperçu

SCREEN = (408, 480)


def data_values(t, args):
    h, m = t.hour, t.minute
    return {59: h // 10, 60: h % 10, 61: m // 10, 62: m % 10,
            70: t.day // 10, 71: t.day % 10, 41: t.month // 10, 42: t.month % 10,
            52: t.isoweekday(),  # 1 = lundi ... 7 = dimanche
            72: 0}  # 72 : indicateur (point rouge), éteint par défaut


def render(src, out, args):
    man, layout, imgs = load_dir(src)
    t = datetime.datetime.combine(datetime.date.fromisoformat(args.date),
                                  datetime.time.fromisoformat(args.time))
    vals = data_values(t, args)
    canvas = Image.new("RGBA", SCREEN, (0, 0, 0, 255))

    def put(name, x, y):
        if name in imgs:
            canvas.alpha_composite(imgs[name], (max(x, 0), max(y, 0)))

    def draw_elem(e, number_value=None):
        if "image" in e:
            ie = e["image"]; p = ie.get("pos", {})
            put(ie["image"], p.get("x", 0), p.get("y", 0))
        if "image_list" in e:
            il = e["image_list"]
            if bool(il.get("aod", 0)) != args.aod:
                return
            p = il.get("pos", {}); v = vals.get(il.get("data"), 0)
            lst = il["images"]
            put(lst[min(v, len(lst) - 1)], p.get("x", 0), p.get("y", 0))
        if "number" in e:
            ne = e["number"]; p = ne.get("pos", {}); x = p.get("x", 0)
            for ch in str(number_value if number_value is not None else 0):
                name = ne["digits"][int(ch)]
                put(name, x, p.get("y", 0)); x += imgs[name].width if name in imgs else 0

    for g in layout.get("groups", []):
        if g.get("background") and not args.aod:
            put(g["background"], 0, 0)
        for e in g.get("elements", []):
            draw_elem(e)
        for wdg in g.get("widgets", []):
            r = wdg.get("rect", {})
            for e in wdg.get("options", []):
                num = None
                if "number" in e:
                    # heuristique : la position la plus à droite reçoit la batterie
                    num = args.battery if e["number"]["pos"]["x"] > 300 else args.steps
                draw_elem(e, num)
    canvas.convert("RGB").save(out)
    print("aperçu -> %s" % out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("unpack"); a.add_argument("hwt"); a.add_argument("out")
    a = sp.add_parser("pack"); a.add_argument("src"); a.add_argument("hwt")
    a = sp.add_parser("verify"); a.add_argument("hwt", nargs="+")
    a = sp.add_parser("render"); a.add_argument("src"); a.add_argument("out")
    a.add_argument("--time", default="10:08"); a.add_argument("--date", default="2025-09-28")
    a.add_argument("--aod", action="store_true")
    a.add_argument("--battery", type=int, default=69); a.add_argument("--steps", type=int, default=7589)
    args = ap.parse_args()
    if args.cmd == "unpack":
        unpack(args.hwt, args.out)
    elif args.cmd == "pack":
        pack(args.src, args.hwt)
    elif args.cmd == "verify":
        ok = all([verify(h) for h in args.hwt]); sys.exit(0 if ok else 1)
    elif args.cmd == "render":
        render(args.src, args.out, args)


if __name__ == "__main__":
    main()
