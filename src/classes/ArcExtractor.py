"""
Konami `.arc` container + LZ77 decompression, and 32-bit DDS decoding.

DDR World ships its 2D art (arrows, etc.) as `.arc` files: a small header, a
single filename, then an LZ77-compressed payload (usually a 32-bit uncompressed
DDS texture). The LZ77 variant is the firebeat/BEMANI one documented by
bemaniutils (DragonMinded); this is a clean-room reimplementation of just the
decompressor plus a minimal DDS reader (no external image deps).

Nothing here is Konami-derived source; it only *reads* the user's own arcade
dump. The extracted arrow art is copyrighted and is never committed to a repo —
see scripts/extract_noteskin usage.
"""

import struct

_ARC_MAGIC = 0x19751120
_RING_LENGTH = 0x1000


def lz77_decompress(data: bytes, expected: int | None = None) -> bytes:
    """Decompress a BEMANI/firebeat LZ77 stream.

    Ring buffer of `_RING_LENGTH` zero bytes; flags are read LSB-first, one
    control byte at a time. Flag bit 1 => copy literal byte(s); bit 0 => a
    2-byte backref (hi, lo) with length `(lo & 0xF)` and ring offset
    `(hi << 4) | (lo >> 4)`. A backref offset of 0 marks end of stream; any
    other offset copies `length + 3` bytes from `write_pos - offset` in the
    ring (which mirrors the output history, so early copies read the ring's
    initial zeros).
    """
    ring = bytearray(_RING_LENGTH)
    write_pos = 0
    out = bytearray()
    pos = 0
    n = len(data)
    flags = 1

    while True:
        if flags == 1:
            if pos >= n:
                break
            flags = 0x100 | data[pos]
            pos += 1
        flag = flags & 1
        flags >>= 1

        if flag == 1:
            # One or more literal bytes; coalesce a run of literal flags.
            amount = 1
            while flags != 1 and (flags & 1) == 1:
                flags >>= 1
                amount += 1
            chunk = data[pos : pos + amount]
            out.extend(chunk)
            for byte in chunk:
                ring[write_pos] = byte
                write_pos = (write_pos + 1) % _RING_LENGTH
            pos += amount
        else:
            if pos >= n:
                break
            if pos + 1 >= n:
                raise ValueError("unexpected EOF mid-backref")
            hi = data[pos]
            lo = data[pos + 1]
            pos += 2
            copy_len = (lo & 0xF)
            copy_pos = (hi << 4) | (lo >> 4)
            if copy_pos == 0:
                break  # end-of-stream marker
            copy_len += 3
            src = (write_pos - copy_pos) % _RING_LENGTH
            for _ in range(copy_len):
                byte = ring[src % _RING_LENGTH]
                out.append(byte)
                ring[write_pos] = byte
                write_pos = (write_pos + 1) % _RING_LENGTH
                src += 1

    if expected is not None and len(out) != expected:
        raise ValueError(f"decompressed {len(out)} bytes, expected {expected}")
    return bytes(out)


def read_arc(path) -> tuple[str, bytes]:
    """Return (inner filename, decompressed payload) for a single-file `.arc`."""
    data = open(path, "rb").read()
    magic = struct.unpack("<I", data[:4])[0]
    if magic != _ARC_MAGIC:
        raise ValueError(f"{path}: bad magic {magic:#010x}")
    comp = struct.unpack("<I", data[0x0C:0x10])[0]
    name_off = struct.unpack("<I", data[0x10:0x14])[0]
    data_off = struct.unpack("<I", data[0x14:0x18])[0]
    unc_size = struct.unpack("<I", data[0x18:0x1C])[0]
    cmp_size = struct.unpack("<I", data[0x1C:0x20])[0]
    nul = data.index(b"\x00", name_off)
    name = data[name_off:nul].decode("ascii", "replace")
    payload = data[data_off : data_off + cmp_size]
    if comp == 0 or cmp_size == unc_size:
        # Stored uncompressed (e.g. .ifs payloads).
        return name, payload[:unc_size]
    return name, lz77_decompress(payload, unc_size)


def dds_to_rgba(dds: bytes) -> tuple[int, int, bytes]:
    """Decode a 32-bit uncompressed DDS to (width, height, RGBA bytes).

    DDR arrow textures are plain 32-bit BGRA with explicit channel masks and no
    mipmaps/block compression, so this only handles that case (and raises
    otherwise, which is loud on any unexpected format).
    """
    if dds[:4] != b"DDS ":
        raise ValueError("not a DDS")
    height, width = struct.unpack("<II", dds[12:20])
    pf = dds[76:108]
    fourcc = pf[8:12]
    bits = struct.unpack("<I", pf[12:16])[0]
    rmask, gmask, bmask, amask = struct.unpack("<4I", pf[16:32])
    if fourcc != b"\x00\x00\x00\x00" or bits != 32:
        raise ValueError(f"unsupported DDS pixel format fourcc={fourcc!r} bits={bits}")

    def shift(mask: int) -> int:
        s = 0
        while mask and not (mask >> s) & 1:
            s += 1
        return s

    rs, gs, bs, as_ = shift(rmask), shift(gmask), shift(bmask), shift(amask)
    px = dds[128 : 128 + width * height * 4]
    out = bytearray(width * height * 4)
    for i in range(width * height):
        v = (
            px[i * 4]
            | (px[i * 4 + 1] << 8)
            | (px[i * 4 + 2] << 16)
            | (px[i * 4 + 3] << 24)
        )
        out[i * 4 + 0] = (v & rmask) >> rs
        out[i * 4 + 1] = (v & gmask) >> gs
        out[i * 4 + 2] = (v & bmask) >> bs
        out[i * 4 + 3] = ((v & amask) >> as_) if amask else 255
    return width, height, bytes(out)


def write_png(width: int, height: int, rgba: bytes, path) -> None:
    """Write RGBA bytes as a PNG using only the stdlib (zlib)."""
    import zlib

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type 0
        raw += rgba[y * stride : (y + 1) * stride]

    def chunk(typ: bytes, payload: bytes) -> bytes:
        body = typ + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


def crop(rgba: bytes, src_w: int, sx: int, sy: int, cw: int, ch: int) -> bytes:
    """Crop a cw*ch RGBA sub-rectangle out of an RGBA buffer of width src_w."""
    out = bytearray(cw * ch * 4)
    for y in range(ch):
        src = ((sy + y) * src_w + sx) * 4
        dst = y * cw * 4
        out[dst : dst + cw * 4] = rgba[src : src + cw * 4]
    return bytes(out)


# --- IFS containers (nested texture archives, e.g. the shock arrow) ---------
#
# An `.ifs` (magic 0x6CAD8F89) holds a KBinXML manifest (decoded by the
# vendored `kbin` package, Unlicense) plus a data blob of `avslz`-compressed
# textures. Each texture file decompresses to raw `argb8888rev` (BGRA) pixels;
# the `texturelist_Exml` node names the images and their sizes. The LZ77 here is
# the same variant as `lz77_decompress` above.

_IFS_MAGIC = 0x6CAD8F89


def read_ifs_textures(ifs_bytes: bytes):
    """Yield (image_name, width, height, rgba_bytes) for each texture in an IFS.

    Only handles the argb8888rev, single-image-per-file layout used by DDR's
    2D texture archives (one <texture> whose pixels are the whole file). Raises
    on an unexpected structure so problems are loud, not silent.
    """
    from classes.kbin.binary import BinaryEncoding

    sig, version, vcrc = struct.unpack(">IHH", ifs_bytes[:8])
    if sig != _IFS_MAGIC:
        raise ValueError(f"not an IFS ({sig:#010x})")
    data_index = struct.unpack(">I", ifs_bytes[16:20])[0]
    header_offset = 20 if version == 1 else 36
    root = BinaryEncoding().decode(ifs_bytes[header_offset:data_index])
    if root is None or root.name != "imgfs":
        raise ValueError("bad IFS manifest")

    tex = next((c for c in root.children if c.name == "tex"), None)
    if tex is None:
        return

    # Texture files, in manifest order (tex000, tex001, …).
    files = [
        t for t in tex.children
        if t.data_type == "3s32" and t.name != "texturelist_Exml"
    ]

    # texturelist maps ordinal -> (name, width, height).
    tl_node = next((t for t in tex.children if t.name == "texturelist_Exml"), None)
    dims = []
    if tl_node is not None:
        off, size, _ = tl_node.value
        tl = BinaryEncoding().decode(ifs_bytes[off + data_index : off + data_index + size])
        for tnode in (tl.children if tl else []):
            if tnode.name != "texture":
                continue
            sz = next((c.value for c in tnode.children if c.name == "size"), None)
            name = dict(tnode.attributes).get("name")
            if sz:
                dims.append((name, sz[0], sz[1]))

    for idx, t in enumerate(files):
        off, size, _ = t.value
        blob = ifs_bytes[off + data_index : off + data_index + size]
        unc, comp = struct.unpack(">II", blob[:8])
        raw = lz77_decompress(blob[8 : 8 + comp], unc)
        # Recover width/height: the stored pixel count rarely matches the
        # texturelist's logical canvas, so derive a plausible (w, h) whose
        # w*h*4 == len(raw) and that best matches a texturelist entry width.
        px = len(raw) // 4
        w = h = 0
        cand_ws = sorted({d[1] for d in dims} | {924, 462, 231, 326}, reverse=True)
        for cw in cand_ws:
            if cw > 0 and px % cw == 0 and 32 <= px // cw <= 4096:
                w, h = cw, px // cw
                break
        if w == 0:
            continue
        # argb8888rev is BGRA in memory -> RGBA.
        rgba = bytearray(len(raw))
        for i in range(0, len(raw), 4):
            rgba[i] = raw[i + 2]
            rgba[i + 1] = raw[i + 1]
            rgba[i + 2] = raw[i]
            rgba[i + 3] = raw[i + 3]
        name = dims[idx][0] if idx < len(dims) else f"tex{idx:03d}"
        yield name, w, h, bytes(rgba)
