"""JVM constant pool: raw entry list preserving original indices.

Entries are tuples: (tag, ...)
  1  (1, str)                Utf8
  3  (3, int32)              Integer
  4  (4, bits32)             Float  (raw IEEE bits)
  5  (5, int64)              Long   (raw bits)
  6  (6, bits64)             Double (raw bits)
  7  (7, u2)                 Class -> utf8 index
  8  (8, u2)                 String -> utf8 index
  9  (9, u2, u2)             Fieldref -> class, nat
  10 (10, u2, u2)            Methodref
  11 (11, u2, u2)            InterfaceMethodref
  12 (12, u2, u2)            NameAndType -> name, desc
  15 (15, u1, u2)            MethodHandle -> kind, ref
  16 (16, u2)                MethodType -> desc
  17 (17, u2, u2)            Dynamic -> bsm index, nat
  18 (18, u2, u2)            InvokeDynamic -> bsm index, nat
  19 (19, u2)                Module -> utf8
  20 (20, u2)                Package -> utf8
"""

import struct

UTF8 = 1
INT = 3
FLOAT = 4
LONG = 5
DOUBLE = 6
CLASS = 7
STRING = 8
FIELDREF = 9
METHODREF = 10
IREF = 11
NAT = 12
MHANDLE = 15
MTYPE = 16
DYNAMIC = 17
INDY = 18
MODULE = 19
PACKAGE = 20

_ENTRY_SIZES = {UTF8: None, INT: 4, FLOAT: 4, LONG: 8, DOUBLE: 8, CLASS: 2, STRING: 2,
                FIELDREF: 4, METHODREF: 4, IREF: 4, NAT: 4, MHANDLE: 3, MTYPE: 2,
                DYNAMIC: 4, INDY: 4, MODULE: 2, PACKAGE: 2}


class Pool:
    def __init__(self, entries=None):
        # index 0 is None (JVMS)
        self.entries = entries if entries is not None else [None]

    # ---------- parsing ----------
    @classmethod
    def parse(cls, data, offset):
        (count,) = struct.unpack_from(">H", data, offset)
        offset += 2
        entries = [None]
        i = 1
        while i < count:
            tag = data[offset]
            offset += 1
            if tag == UTF8:
                (ln,) = struct.unpack_from(">H", data, offset)
                raw = data[offset + 2:offset + 2 + ln]
                offset += 2 + ln
                entries.append((UTF8, _decode_utf8(raw)))
            elif tag in (INT, FLOAT):
                (v,) = struct.unpack_from(">i", data, offset) if tag == INT else struct.unpack_from(">I", data, offset)
                offset += 4
                entries.append((tag, v))
            elif tag in (LONG, DOUBLE):
                (v,) = struct.unpack_from(">q", data, offset) if tag == LONG else struct.unpack_from(">Q", data, offset)
                offset += 8
                entries.append((tag, v))
                entries.append(None)  # long/double take two slots
                i += 1
            elif tag in (CLASS, STRING, MODULE, PACKAGE, MTYPE):
                (v,) = struct.unpack_from(">H", data, offset)
                offset += 2
                entries.append((tag, v))
            elif tag in (FIELDREF, METHODREF, IREF, NAT, DYNAMIC, INDY):
                a, b = struct.unpack_from(">HH", data, offset)
                offset += 4
                entries.append((tag, a, b))
            elif tag == MHANDLE:
                k = data[offset]
                (r,) = struct.unpack_from(">H", data, offset + 1)
                offset += 3
                entries.append((tag, k, r))
            else:
                raise ValueError("bad constant pool tag %d at %d" % (tag, offset))
            i += 1
        return cls(entries), offset

    # ---------- serializing ----------
    def to_bytes(self):
        # constant_pool_count = number of slots + 1 (index 0 unused).
        # long/double occupy two slots; the None placeholder counts.
        out = [struct.pack(">H", len(self.entries))]
        for e in self.entries[1:]:
            if e is None:
                continue
            tag = e[0]
            if tag == UTF8:
                raw = _encode_utf8(e[1])
                out.append(struct.pack(">BH", UTF8, len(raw)) + raw)
            elif tag == INT:
                out.append(struct.pack(">Bi", INT, e[1]))
            elif tag == FLOAT:
                out.append(struct.pack(">BI", FLOAT, e[1] & 0xFFFFFFFF))
            elif tag == LONG:
                out.append(struct.pack(">Bq", LONG, e[1]))
            elif tag == DOUBLE:
                out.append(struct.pack(">BQ", DOUBLE, e[1] & ((1 << 64) - 1)))
            elif tag in (CLASS, STRING, MODULE, PACKAGE, MTYPE):
                out.append(struct.pack(">BH", tag, e[1]))
            elif tag in (FIELDREF, METHODREF, IREF, NAT, DYNAMIC, INDY):
                out.append(struct.pack(">BHH", tag, e[1], e[2]))
            elif tag == MHANDLE:
                out.append(struct.pack(">BBH", MHANDLE, e[1], e[2]))
        return b"".join(out)

    # ---------- adding ----------
    def _find(self, entry):
        try:
            return self.entries.index(entry)
        except ValueError:
            return None

    def add(self, entry):
        idx = self._find(entry)
        if idx is not None:
            return idx
        self.entries.append(entry)
        idx = len(self.entries) - 1
        if entry[0] in (LONG, DOUBLE):
            self.entries.append(None)  # long/double take two slots
        return idx

    def utf8(self, s):
        return self.add((UTF8, s))

    def class_idx(self, internal_name):
        return self.add((CLASS, self.utf8(internal_name)))

    def string_idx(self, s):
        return self.add((STRING, self.utf8(s)))

    def nat(self, name, desc):
        return self.add((NAT, self.utf8(name), self.utf8(desc)))

    def member_ref(self, tag, owner, name, desc):
        return self.add((tag, self.class_idx(owner), self.nat(name, desc)))

    def int_const(self, v):
        return self.add((INT, v))

    def long_const(self, v):
        return self.add((LONG, v))

    def float_const(self, bits):
        return self.add((FLOAT, bits))

    def double_const(self, bits):
        return self.add((DOUBLE, bits))

    def utf8_at(self, idx):
        e = self.entries[idx]
        if e[0] != UTF8:
            raise ValueError("expected utf8 at %d" % idx)
        return e[1]

    def class_name(self, idx):
        e = self.entries[idx]
        assert e[0] == CLASS, e
        return self.utf8_at(e[1])

    def entry(self, idx):
        return self.entries[idx]

    def tag(self, idx):
        e = self.entries[idx]
        return e[0] if e else None

    def size(self):
        return len(self.entries)


def _decode_utf8(raw):
    # JVM modified UTF-8: \x00 encoded as C0 80, surrogate pairs as 3-byte sequences
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        out = []
        i = 0
        n = len(raw)
        while i < n:
            b = raw[i]
            if b < 0x80:
                out.append(chr(b)); i += 1
            elif (b & 0xE0) == 0xC0:
                c = ((b & 0x1F) << 6) | (raw[i + 1] & 0x3F); i += 2
                out.append(chr(c))
            elif (b & 0xF0) == 0xE0:
                c = ((b & 0x0F) << 12) | ((raw[i + 1] & 0x3F) << 6) | (raw[i + 2] & 0x3F); i += 3
                out.append(chr(c))
            else:
                out.append("?"); i += 1
        s = "".join(out)
        # combine surrogate pairs into real characters
        return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace") if any(
            0xD800 <= ord(c) <= 0xDFFF for c in s) else s


def _encode_utf8(s):
    try:
        return s.encode("utf-8")
    except UnicodeEncodeError:
        pass
    out = bytearray()
    for ch in s:
        c = ord(ch)
        if c == 0:
            out += b"\xc0\x80"
        elif c < 0x80:
            out.append(c)
        elif c < 0x800:
            out.append(0xC0 | (c >> 6))
            out.append(0x80 | (c & 0x3F))
        elif 0xD800 <= c <= 0xDFFF:
            # lone surrogate: encode as raw 3-byte MUTF-8
            out.append(0xE0 | (c >> 12))
            out.append(0x80 | ((c >> 6) & 0x3F))
            out.append(0x80 | (c & 0x3F))
        else:
            out.append(0xE0 | (c >> 12))
            out.append(0x80 | ((c >> 6) & 0x3F))
            out.append(0x80 | (c & 0x3F))
    return bytes(out)
