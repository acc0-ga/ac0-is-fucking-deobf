"""StackMapTable parsing / serialization.

Frame types are tuples:
  ("top",) ("int",) ("float",) ("long",) ("double",) ("null",)
  ("uninit_this",) ("obj", class_name) ("uninit", pc)

Frame.offset is stored as *instruction index* while inside Code; conversion
to/from byte offsets happens in Code.parse / Code.assemble.
"""

import struct

TOP, INT, FLOAT, LONG, DOUBLE, NULL, UNINIT_THIS, OBJ, UNINIT = range(9)


def t_int():
    return ("int",)


def t_float():
    return ("float",)


def t_long():
    return ("long",)


def t_double():
    return ("double",)


def t_top():
    return ("top",)


def t_null():
    return ("null",)


def t_obj(name):
    return ("obj", name)


def t_uninit_this():
    return ("uninit_this",)


def t_uninit(idx):
    return ("uninit", idx)


def slot_width(t):
    return 2 if t[0] in ("long", "double") else 1


def _read_type(data, off, pool):
    tag = data[off]
    if tag == 0:
        return ("top",), off + 1
    if tag == 1:
        return ("int",), off + 1
    if tag == 2:
        return ("float",), off + 1
    if tag == 3:
        return ("double",), off + 1
    if tag == 4:
        return ("long",), off + 1
    if tag == 5:
        return ("null",), off + 1
    if tag == 6:
        return ("uninit_this",), off + 1
    if tag == 7:
        (idx,) = struct.unpack_from(">H", data, off + 1)
        return ("obj", pool.class_name(idx)), off + 3
    if tag == 8:
        (pc,) = struct.unpack_from(">H", data, off + 1)
        return ("uninit", pc), off + 3
    raise ValueError("bad verification type tag %d" % tag)


def _expand(types):
    """Expand to explicit per-slot list (long/double get a following top)."""
    out = []
    for t in types:
        out.append(t)
        if slot_width(t) == 2:
            out.append(("top",))
    return out


class Frame:
    __slots__ = ("offset", "locals", "stack")

    def __init__(self, offset, locals_, stack=None):
        self.offset = offset            # instruction index inside Code
        self.locals = list(locals_)     # explicit slot list
        self.stack = list(stack or [])

    def key(self):
        return (tuple(self.locals), tuple(self.stack))

    def __repr__(self):
        return "Frame@%s locals=%s stack=%s" % (self.offset, self.locals, self.stack)


def parse(data, pool, off=0, init_locals=None):
    """Parse StackMapTable; returns (list[Frame], end_offset).
    Offsets are absolute byte offsets here; Code converts them to indices.
    Frame locals are stored *absolute*: init_locals (this + parameters) is
    the implicit base of the first frame."""
    (count,) = struct.unpack_from(">H", data, off)
    off += 2
    frames = []
    prev_offset = -1
    prev_locals = list(init_locals or [])
    for _ in range(count):
        ftype = data[off]
        off += 1
        if ftype <= 63:
            delta = ftype
            locals_ = prev_locals
            stack = []
        elif ftype <= 127:
            delta = ftype - 64
            locals_ = prev_locals
            t, off = _read_type(data, off, pool)
            stack = [t]
        elif ftype == 247:
            (delta,) = struct.unpack_from(">H", data, off)
            off += 2
            locals_ = prev_locals
            t, off = _read_type(data, off, pool)
            stack = [t]
        elif ftype <= 250:
            if ftype < 248:
                raise ValueError("bad frame type %d" % ftype)
            (delta,) = struct.unpack_from(">H", data, off)
            off += 2
            k = 251 - ftype
            # chop k logical entries off prev_locals
            locals_ = _chop(prev_locals, k)
            stack = []
        elif ftype == 251:
            (delta,) = struct.unpack_from(">H", data, off)
            off += 2
            locals_ = prev_locals
            stack = []
        elif ftype <= 254:
            (delta,) = struct.unpack_from(">H", data, off)
            off += 2
            k = ftype - 251
            locals_ = list(prev_locals)
            for _j in range(k):
                t, off = _read_type(data, off, pool)
                locals_.append(t)
                if slot_width(t) == 2:
                    locals_.append(("top",))
            stack = []
        elif ftype == 255:
            (delta,) = struct.unpack_from(">H", data, off)
            off += 2
            (nl,) = struct.unpack_from(">H", data, off)
            off += 2
            locals_ = []
            for _j in range(nl):
                t, off = _read_type(data, off, pool)
                locals_.append(t)
                if slot_width(t) == 2:
                    locals_.append(("top",))
            (ns,) = struct.unpack_from(">H", data, off)
            off += 2
            stack = []
            for _j in range(ns):
                t, off = _read_type(data, off, pool)
                stack.append(t)
        else:
            raise ValueError("bad frame type %d" % ftype)
        offset = prev_offset + delta + 1
        prev_offset = offset
        frames.append(Frame(offset, locals_, stack))
        prev_locals = locals_
    return frames, off


def _chop(locals_, k):
    """Remove k trailing logical entries from an expanded slot list."""
    out = list(locals_)
    for _ in range(k):
        if not out:
            break
        if out[-1] == ("top",) and len(out) >= 2 and out[-2][0] in ("long", "double"):
            out.pop()
        out.pop()
    return out


def _write_type(t, pool):
    if t[0] == "top":
        return b"\x00"
    if t[0] == "int":
        return b"\x01"
    if t[0] == "float":
        return b"\x02"
    if t[0] == "double":
        return b"\x03"
    if t[0] == "long":
        return b"\x04"
    if t[0] == "null":
        return b"\x05"
    if t[0] == "uninit_this":
        return b"\x06"
    if t[0] == "obj":
        return struct.pack(">BH", 7, pool.class_idx(t[1]))
    if t[0] == "uninit":
        return struct.pack(">BH", 8, t[1])
    raise ValueError("bad type %r" % (t,))


def _logical_locals(locals_):
    """Slot list -> logical entries (collapse long+top pairs back)."""
    out = []
    i = 0
    while i < len(locals_):
        t = locals_[i]
        out.append(t)
        if slot_width(t) == 2 and i + 1 < len(locals_) and locals_[i + 1] == ("top",):
            i += 2
        else:
            i += 1
    return out


def _nlogical(locals_):
    return len(_logical_locals(locals_))


def serialize(frames, pool, init_locals=None):
    out = [struct.pack(">H", len(frames))]
    prev_offset = -1
    prev_locals = list(init_locals or [])
    for fr in frames:
        delta = fr.offset - prev_offset - 1
        assert delta >= 0, "frames must be sorted by offset"
        same_locals = fr.locals == prev_locals
        rec = None
        if same_locals and not fr.stack:
            if delta <= 63:
                rec = bytes([delta])                              # tag 0..63
            else:
                rec = struct.pack(">BH", 251, delta)
        elif same_locals and len(fr.stack) == 1:
            if delta <= 63:
                rec = bytes([64 + delta]) + _write_type(fr.stack[0], pool)
            else:
                rec = struct.pack(">BH", 247, delta) + _write_type(fr.stack[0], pool)
        else:
            handled = False
            if not fr.stack:
                nl_prev, nl_new = _nlogical(prev_locals), _nlogical(fr.locals)
                if nl_new < nl_prev and fr.locals == _chop(prev_locals, nl_prev - nl_new):
                    k = nl_prev - nl_new
                    if 1 <= k <= 3:
                        rec = bytes([251 - k]) + struct.pack(">H", delta)   # 250..248
                        handled = True
                if not handled and nl_new > nl_prev and nl_new - nl_prev <= 3 and \
                        fr.locals[:len(prev_locals)] == prev_locals:
                    k = nl_new - nl_prev
                    rec = bytes([251 + k]) + struct.pack(">H", delta)       # 252..254
                    for t in _logical_locals(fr.locals)[nl_prev:]:
                        rec += _write_type(t, pool)
                    handled = True
            if not handled:
                stack = fr.stack or []
                logical = _logical_locals(fr.locals)
                rec = struct.pack(">BHH", 255, delta, len(logical))
                for t in logical:
                    rec += _write_type(t, pool)
                rec += struct.pack(">H", len(stack))
                for t in stack:
                    rec += _write_type(t, pool)
        out.append(rec)
        prev_offset = fr.offset
        prev_locals = fr.locals
    return b"".join(out)


def expand_types(types):
    return _expand(types)

