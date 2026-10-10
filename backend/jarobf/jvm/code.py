"""Code attribute: disassembly, assembly, safe insertion with frame/handler fixups.

Instruction operands that are branch targets are stored as *instruction
indices*. StackMapTable frame offsets are also stored as instruction indices
(converted back to byte offsets on assembly). Exception table indices likewise.
"""

import struct

from .opcodes import OPCODES, MNEMONIC, BRANCH_OPS, TABLESWITCH, LOOKUPSWITCH, WIDE
from . import frames as fr_mod

_INVERT = {0x99: 0x9A, 0x9A: 0x99, 0x9B: 0x9C, 0x9C: 0x9B, 0x9D: 0x9E, 0x9E: 0x9D,
           0x9F: 0xA0, 0xA0: 0x9F, 0xA1: 0xA2, 0xA2: 0xA1, 0xA3: 0xA4, 0xA4: 0xA3,
           0xA5: 0xA6, 0xA6: 0xA5, 0xC6: 0xC7, 0xC7: 0xC6}


class Insn:
    __slots__ = ("op", "args", "wide")

    def __init__(self, op, args=(), wide=False):
        self.op = op
        self.args = args
        self.wide = wide

    @property
    def name(self):
        return OPCODES[self.op][0]

    def __repr__(self):
        return "<%s %r%s>" % (self.name, self.args, " wide" if self.wide else "")


def ins(name, *args, **kw):
    """Build an Insn by mnemonic: ins('iload', 3), ins('goto', target)."""
    op = MNEMONIC[name]
    return Insn(op, tuple(args), kw.get("wide", False))


def disassemble(code_bytes, pool, pc_base=0):
    """Returns (list[Insn], raw_handlers, attrs_bytes_list).
    Branch targets resolved to instruction indices."""
    insns = []
    pos = 0
    n = len(code_bytes)
    offset_to_idx = {}
    # first pass: instruction boundaries
    while pos < n:
        offset_to_idx[pos] = len(insns)
        op = code_bytes[pos]
        if op not in OPCODES:
            raise ValueError("unknown opcode 0x%02x at %d" % (op, pos))
        name, fmt = OPCODES[op]
        start = pos
        pos += 1
        if fmt is None:
            args = ()
        elif fmt == "b":
            args = (struct.unpack_from(">b", code_bytes, pos)[0],); pos += 1
        elif fmt == "s":
            args = (struct.unpack_from(">h", code_bytes, pos)[0],); pos += 2
        elif fmt == "cp1":
            args = (code_bytes[pos],); pos += 1
        elif fmt == "cp2":
            args = (struct.unpack_from(">H", code_bytes, pos)[0],); pos += 2
        elif fmt == "local":
            args = (code_bytes[pos],); pos += 1
        elif fmt == "iinc":
            args = (code_bytes[pos], struct.unpack_from(">b", code_bytes, pos + 1)[0]); pos += 2
        elif fmt == "branch":
            args = (start + struct.unpack_from(">h", code_bytes, pos)[0],); pos += 2
        elif fmt == "branch4":
            args = (start + struct.unpack_from(">i", code_bytes, pos)[0],); pos += 4
        elif fmt == "newarray":
            args = (code_bytes[pos],); pos += 1
        elif fmt == "invokeinterface":
            idx, cnt = struct.unpack_from(">HB", code_bytes, pos)
            if code_bytes[pos + 3] != 0:
                raise ValueError("invokeinterface reserved byte != 0 at %d" % pos)
            args = (idx, cnt); pos += 4
        elif fmt == "invokedynamic":
            (idx,) = struct.unpack_from(">H", code_bytes, pos)
            if code_bytes[pos + 2] != 0 or code_bytes[pos + 3] != 0:
                raise ValueError("invokedynamic reserved bytes != 0 at %d" % pos)
            args = (idx,); pos += 4
        elif fmt == "multianewarray":
            idx, dims = struct.unpack_from(">HB", code_bytes, pos)
            args = (idx, dims); pos += 3
        elif fmt == "wide":
            wop = code_bytes[pos]
            pos += 1
            if wop == MNEMONIC["iinc"]:
                idx, c = struct.unpack_from(">Hh", code_bytes, pos); pos += 4
                insns.append(Insn(MNEMONIC["iinc"], (idx, c), wide=True))
                continue
            idx, = struct.unpack_from(">H", code_bytes, pos); pos += 2
            insns.append(Insn(wop, (idx,), wide=True))
            continue
        elif fmt == "tableswitch":
            pad = (4 - (pos % 4)) % 4
            pos += pad
            default, low, high = struct.unpack_from(">iii", code_bytes, pos)
            pos += 12
            cnt = high - low + 1
            offs = list(struct.unpack_from(">%di" % cnt, code_bytes, pos))
            pos += 4 * cnt
            args = (default, low, offs)
        elif fmt == "lookupswitch":
            pad = (4 - (pos % 4)) % 4
            pos += pad
            default, npairs = struct.unpack_from(">ii", code_bytes, pos)
            pos += 8
            pairs = []
            for _i in range(npairs):
                k, o = struct.unpack_from(">ii", code_bytes, pos)
                pos += 8
                pairs.append((k, o))
            args = (default, pairs)
        else:
            raise ValueError("fmt %s" % fmt)
        insns.append(Insn(op, args))
    # resolve branch targets (byte offsets -> indices)
    # switch operand offsets are encoded relative to the branch opcode itself
    end_index = len(insns)
    ins_offsets, _ = _compute_offsets(insns)
    for ic, insn in enumerate(insns):
        fmt = OPCODES[insn.op][1]
        if fmt in ("branch", "branch4"):
            tgt = insn.args[0]
            insn.args = (offset_to_idx[tgt] if tgt in offset_to_idx else end_index,)
        elif fmt == "tableswitch":
            default, low, offs = insn.args
            base = ins_offsets[ic]
            insn.args = (offset_to_idx.get(base + default, end_index), low,
                         [offset_to_idx.get(base + o, end_index) for o in offs])
        elif fmt == "lookupswitch":
            default, pairs = insn.args
            base = ins_offsets[ic]
            insn.args = (offset_to_idx.get(base + default, end_index),
                         [(k, offset_to_idx.get(base + o, end_index)) for k, o in pairs])
    return insns


def _insn_size(insn, offset, wide_flag=None):
    fmt = OPCODES[insn.op][1]
    w = insn.wide if wide_flag is None else wide_flag
    if fmt is None:
        return 1
    if fmt == "b":
        return 2
    if fmt in ("s", "cp2", "local", "branch", "newarray"):
        if fmt == "branch" and w:
            return 5
        return 3 if fmt in ("s", "cp2", "branch") else (4 if w else 2)
    if fmt == "cp1":
        return 2
    if fmt == "iinc":
        return 6 if w else 3
    if fmt == "branch4":
        return 5
    if fmt in ("invokeinterface", "invokedynamic"):
        return 5
    if fmt == "multianewarray":
        return 4
    if fmt == "wide":
        raise ValueError("wide handled via flag")
    if fmt == "tableswitch":
        pad = (4 - ((offset + 1) % 4)) % 4
        return 1 + pad + 12 + 4 * len(insn.args[2])
    if fmt == "lookupswitch":
        pad = (4 - ((offset + 1) % 4)) % 4
        return 1 + pad + 8 + 8 * len(insn.args[1])
    raise ValueError(fmt)


def _compute_offsets(insns):
    offsets = []
    pos = 0
    for insn in insns:
        offsets.append(pos)
        pos += _insn_size(insn, pos)
    return offsets, pos


def assemble(insns, pool):
    """Returns code bytes. Handles short/long branch relaxation + wide."""
    insns = list(insns)
    # mark wide where needed
    for insn in insns:
        fmt = OPCODES[insn.op][1]
        if fmt in ("local", "iinc") and (insn.args[0] > 255 or (fmt == "iinc" and not (-128 <= insn.args[1] <= 127))):
            insn.wide = True
        if fmt in ("local", "iinc") and insn.args[0] <= 255 and fmt == "local":
            pass
    while True:
        offsets, total = _compute_offsets(insns)
        overflow = None
        for i, insn in enumerate(insns):
            fmt = OPCODES[insn.op][1]
            if fmt == "branch" and not insn.wide:
                tgt = insn.args[0]
                if tgt >= len(insns):
                    continue
                delta = offsets[tgt] - offsets[i]
                if not (-32768 <= delta <= 32767):
                    overflow = i
                    break
        if overflow is None:
            break
        # expand overflowing branch
        insn = insns[overflow]
        if insn.op in (MNEMONIC["goto"], MNEMONIC["jsr"]):
            insn.op = MNEMONIC["goto_w"] if insn.op == MNEMONIC["goto"] else MNEMONIC["jsr_w"]
        else:
            # insert one instruction: shift old targets first, then splice
            _shift_targets(insns, overflow + 1, 1)
            tgt = insns[overflow].args[0]
            inv = Insn(_INVERT[insn.op], (overflow + 2,))
            gw = Insn(MNEMONIC["goto_w"], (tgt,))
            insns[overflow:overflow + 1] = [inv, gw]
    offsets, total = _compute_offsets(insns)
    out = bytearray()

    def s2(v):
        if not (-32768 <= v <= 32767):
            raise ValueError("short out of range: %d" % v)
        return struct.pack(">h", v)

    for i, insn in enumerate(insns):
        op = insn.op
        fmt = OPCODES[op][1]
        off = offsets[i]
        out.append(op)
        if fmt is None:
            pass
        elif fmt == "b":
            out.append(insn.args[0] & 0xFF)
        elif fmt == "s":
            out += s2(insn.args[0])
        elif fmt == "cp1":
            if not (0 <= insn.args[0] <= 255):
                raise ValueError("cp1 index out of range: %r" % (insn.args[0],))
            out.append(insn.args[0])
        elif fmt == "cp2":
            out += struct.pack(">H", insn.args[0])
        elif fmt == "newarray":
            out.append(insn.args[0] & 0xFF)
        elif fmt == "local":
            if insn.wide:
                out.append(WIDE)
                out += struct.pack(">H", insn.args[0])
            else:
                out.append(insn.args[0])
        elif fmt == "iinc":
            if insn.wide:
                out.append(WIDE)
                out += struct.pack(">Hh", insn.args[0], insn.args[1])
            else:
                out += struct.pack(">Bb", insn.args[0], insn.args[1])
        elif fmt == "branch":
            tgt = insn.args[0]
            if insn.wide:
                raise ValueError("short branch marked wide; use goto_w/jsr_w")
            out += s2(offsets[tgt] - off)
        elif fmt == "branch4":
            out += struct.pack(">i", offsets[insn.args[0]] - off)
        elif fmt == "invokeinterface":
            out += struct.pack(">HB", insn.args[0], insn.args[1]) + b"\x00"
        elif fmt == "invokedynamic":
            out += struct.pack(">H", insn.args[0]) + b"\x00\x00"
        elif fmt == "multianewarray":
            out += struct.pack(">HB", insn.args[0], insn.args[1])
        elif fmt == "tableswitch":
            default, low, offs = insn.args
            pad = (4 - (len(out) % 4)) % 4
            out += b"\x00" * pad
            out += struct.pack(">iii", offsets[default] - off, low, low + len(offs) - 1)
            for o in offs:
                out += struct.pack(">i", offsets[o] - off)
        elif fmt == "lookupswitch":
            default, pairs = insn.args
            pad = (4 - (len(out) % 4)) % 4
            out += b"\x00" * pad
            out += struct.pack(">ii", offsets[default] - off, len(pairs))
            for k, o in sorted(pairs, key=lambda p: p[0]):
                out += struct.pack(">ii", k, offsets[o] - off)
        else:
            raise ValueError(fmt)
    if len(out) != total:
        raise AssertionError((len(out), total))
    return bytes(out)


def _shift_targets(insns, from_idx, delta):
    """Shift branch/switch targets >= from_idx by delta."""
    for insn in insns:
        fmt = OPCODES[insn.op][1]
        if fmt in ("branch", "branch4"):
            if insn.args[0] >= from_idx:
                insn.args = (insn.args[0] + delta,)
        elif fmt == "tableswitch":
            d, low, offs = insn.args
            if d >= from_idx:
                d += delta
            offs = [o + delta if o >= from_idx else o for o in offs]
            insn.args = (d, low, offs)
        elif fmt == "lookupswitch":
            d, pairs = insn.args
            if d >= from_idx:
                d += delta
            pairs = [(k, o + delta if o >= from_idx else o) for k, o in pairs]
            insn.args = (d, pairs)


def _fix_local(insns, at, count):
    """No-op placeholder for expansion (locals unaffected by insertion)."""


class Handler:
    __slots__ = ("start", "end", "handler", "catch_type")

    def __init__(self, start, end, handler, catch_type):
        self.start = start
        self.end = end
        self.handler = handler
        self.catch_type = catch_type

    def __repr__(self):
        return "Handler(%d,%d,%d,%s)" % (self.start, self.end, self.handler, self.catch_type)


class Code:
    def __init__(self, max_stack, max_locals, insns, handlers, frames=None,
                 raw_attrs=None, init_locals=None):
        self.max_stack = max_stack
        self.max_locals = max_locals
        self.insns = insns
        self.handlers = handlers
        self.frames = frames or []      # Frame with .offset = instruction index
        self.raw_attrs = raw_attrs or []  # (name_idx, bytes) unknown/kept attrs
        self.init_locals = list(init_locals or [])  # implicit first-frame locals

    # ---------------- parsing ----------------
    @classmethod
    def parse(cls, data, off, pool, drop_debug=True, init_locals=None):
        max_stack, max_locals, code_len = struct.unpack_from(">HHI", data, off)
        off += 8
        code = data[off:off + code_len]
        off += code_len
        (exc_n,) = struct.unpack_from(">H", data, off)
        off += 2
        raw_handlers = []
        for _i in range(exc_n):
            s, e, h, ct = struct.unpack_from(">HHHH", data, off)
            off += 8
            raw_handlers.append((s, e, h, ct))
        (attr_n,) = struct.unpack_from(">H", data, off)
        off += 2
        frames = []
        raw_attrs = []
        for _i in range(attr_n):
            (name_idx,) = struct.unpack_from(">H", data, off)
            (alen,) = struct.unpack_from(">I", data, off + 2)
            body = data[off + 6:off + 6 + alen]
            off += 6 + alen
            aname = pool.utf8_at(name_idx)
            if aname == "StackMapTable":
                frames, _end = fr_mod.parse(body, pool, 0, init_locals)
            elif aname in ("LineNumberTable", "LocalVariableTable", "LocalVariableTypeTable"):
                if not drop_debug:
                    raw_attrs.append((name_idx, body))
            else:
                raw_attrs.append((name_idx, body))
        insns = disassemble(code, pool)
        # convert byte offsets to instruction indices for handlers and frames
        offsets, _total = _compute_offsets(insns)
        off2idx = {o: i for i, o in enumerate(offsets)}
        handlers = []
        for s, e, h, ct in raw_handlers:
            handlers.append(Handler(off2idx[s], off2idx.get(e, len(insns)),
                                    off2idx[h], ct))
        for f in frames:
            f.offset = off2idx[f.offset]
            f.stack = [_fix_uninit(t, off2idx) for t in f.stack]
            f.locals = [_fix_uninit(t, off2idx) for t in f.locals]
        return cls(max_stack, max_locals, insns, handlers, frames, raw_attrs,
                   init_locals=init_locals)

    # ---------------- serializing ----------------
    def assemble_code(self, pool):
        return assemble(self.insns, pool)

    def to_bytes(self, pool):
        code = self.assemble_code(pool)
        offsets, _total = _compute_offsets(self.insns)
        out = bytearray()
        out += struct.pack(">HHI", self.max_stack, self.max_locals, len(code))
        out += code
        out += struct.pack(">H", len(self.handlers))
        for h in self.handlers:
            s = offsets[h.start]
            e = offsets[h.end] if h.end < len(offsets) else len(code)
            hg = offsets[h.handler]
            out += struct.pack(">HHHH", s, e, hg, h.catch_type)
        # attributes
        attrs = []
        if self.frames:
            # convert instruction indices back to byte offsets
            saved = []
            for f in self.frames:
                saved.append((f.offset, f.locals, f.stack))
                f.offset = offsets[f.offset]
                f.locals = [_unfix_uninit(t, offsets) for t in f.locals]
                f.stack = [_unfix_uninit(t, offsets) for t in f.stack]
            try:
                body = fr_mod.serialize(self.frames, pool, self.init_locals)
            finally:
                for f, (o, lo, st) in zip(self.frames, saved):
                    f.offset, f.locals, f.stack = o, lo, st
            attrs.append((pool.utf8("StackMapTable"), body))
        for name_idx, body in self.raw_attrs:
            attrs.append((name_idx, body))
        out += struct.pack(">H", len(attrs))
        for name_idx, body in attrs:
            out += struct.pack(">HI", name_idx, len(body)) + body
        return bytes(out)

    # ---------------- mutation ----------------
    def insert(self, index, new_insns):
        """Insert new instructions before instruction `index`.

        Branch targets inside `new_insns` must already use *final* layout
        indices (continuation == index + len(new_insns))."""
        k = len(new_insns)
        if k == 0:
            return
        _shift_targets(self.insns, index, k)
        self.insns[index:index] = new_insns
        for i, f in enumerate(self.frames):
            if f.offset >= index:
                f.offset += k
            f.locals = [_shift_uninit(t, index, k) for t in f.locals]
            f.stack = [_shift_uninit(t, index, k) for t in f.stack]
        for h in self.handlers:
            if h.start >= index:
                h.start += k
            if h.end >= index:
                h.end += k
            if h.handler >= index:
                h.handler += k

    def append(self, new_insns):
        self.insert(len(self.insns), new_insns)

    def add_frame(self, index, locals_, stack):
        """Add/replace a stack map frame at instruction index (must keep sorted)."""
        for i, f in enumerate(self.frames):
            if f.offset == index:
                f.locals = list(locals_)
                f.stack = list(stack)
                return
            if f.offset > index:
                self.frames.insert(i, fr_mod.Frame(index, locals_, stack))
                return
        self.frames.append(fr_mod.Frame(index, locals_, stack))

    def sort_frames(self):
        self.frames.sort(key=lambda f: f.offset)

    def has_jsr(self):
        return any(insn.op in (MNEMONIC["jsr"], MNEMONIC["ret"], MNEMONIC["jsr_w"])
                   for insn in self.insns)

    def has_monitor(self):
        return any(insn.op in (MNEMONIC["monitorenter"], MNEMONIC["monitorexit"])
                   for insn in self.insns)

    def has_indy(self):
        return any(insn.op == MNEMONIC["invokedynamic"] for insn in self.insns)

    def insn_count(self):
        return len(self.insns)


def _fix_uninit(t, off2idx):
    if t[0] == "uninit":
        return ("uninit", off2idx.get(t[1], 0))
    return t


def _shift_uninit(t, index, k):
    if t[0] == "uninit" and t[1] >= index:
        return ("uninit", t[1] + k)
    return t


def _unfix_uninit(t, offsets):
    if t[0] == "uninit":
        idx = t[1]
        return ("uninit", offsets[idx] if idx < len(offsets) else 0)
    return t
