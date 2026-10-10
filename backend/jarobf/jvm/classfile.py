"""ClassFile parsing / serialization with structured attributes.

Only attributes we may edit or need for constant-pool reachability are parsed;
everything else is kept raw (and marks the class as 'opaque' which disables
constant-pool garbage collection for that class).
"""

import struct

from .pool import Pool, CLASS, UTF8, NAT, STRING
from .code import Code

# attribute names we fully parse
_PARSED = {
    "Code", "Signature", "Exceptions", "InnerClasses", "EnclosingMethod",
    "ConstantValue", "SourceFile", "BootstrapMethods", "MethodParameters",
    "NestHost", "NestMembers", "PermittedSubclasses", "Record",
    "RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations",
    "RuntimeVisibleParameterAnnotations", "RuntimeInvisibleParameterAnnotations",
    "AnnotationDefault", "RuntimeVisibleTypeAnnotations", "RuntimeInvisibleTypeAnnotations",
}
# attributes with no constant-pool references
_NO_CP = {"Synthetic", "Deprecated", "SourceDebugExtension", "LineNumberTable",
          "LocalVariableTable", "LocalVariableTypeTable"}
_DROP = {"LineNumberTable", "LocalVariableTable", "LocalVariableTypeTable"}


class Annotation:
    __slots__ = ("type_idx", "pairs")

    def __init__(self, type_idx, pairs):
        self.type_idx = type_idx      # utf8 index of descriptor
        self.pairs = pairs            # list[(name_idx, element_value)]


class Attribute:
    def __init__(self, name_idx, name):
        self.name_idx = name_idx
        self.name = name

    def body(self, pool):
        raise NotImplementedError

    def cp_refs(self):
        """All constant-pool indices referenced (for reachability)."""
        return []


class RawAttr(Attribute):
    def __init__(self, name_idx, name, data, cp_unknown=False):
        super().__init__(name_idx, name)
        self.data = data
        self.cp_unknown = cp_unknown

    def body(self, pool):
        return self.data


class CodeAttr(Attribute):
    def __init__(self, name_idx, code):
        super().__init__(name_idx, "Code")
        self.code = code

    def body(self, pool):
        return self.code.to_bytes(pool)

    def cp_refs(self):
        refs = [h.catch_type for h in self.code.handlers if h.catch_type]
        for f in self.code.frames:
            for t in f.locals + f.stack:
                if t[0] == "obj":
                    refs.append(("class_name", t[1]))
        for name_idx, _b in self.code.raw_attrs:
            refs.append(name_idx)
        return refs


class SignatureAttr(Attribute):
    def __init__(self, name_idx, sig_idx):
        super().__init__(name_idx, "Signature")
        self.sig_idx = sig_idx

    def body(self, pool):
        return struct.pack(">H", self.sig_idx)

    def cp_refs(self):
        return [self.sig_idx]


class ExceptionsAttr(Attribute):
    def __init__(self, name_idx, exc):
        super().__init__(name_idx, "Exceptions")
        self.exc = exc

    def body(self, pool):
        return struct.pack(">H", len(self.exc)) + b"".join(struct.pack(">H", i) for i in self.exc)

    def cp_refs(self):
        return list(self.exc)


class ConstantValueAttr(Attribute):
    def __init__(self, name_idx, idx):
        super().__init__(name_idx, "ConstantValue")
        self.idx = idx

    def body(self, pool):
        return struct.pack(">H", self.idx)

    def cp_refs(self):
        return [self.idx]


class SourceFileAttr(Attribute):
    def __init__(self, name_idx, idx):
        super().__init__(name_idx, "SourceFile")
        self.idx = idx

    def body(self, pool):
        return struct.pack(">H", self.idx)

    def cp_refs(self):
        return [self.idx]


class InnerClassesAttr(Attribute):
    def __init__(self, name_idx, entries):
        super().__init__(name_idx, "InnerClasses")
        self.entries = entries  # [(inner, outer, inner_name, access)]

    def body(self, pool):
        out = struct.pack(">H", len(self.entries))
        for e in self.entries:
            out += struct.pack(">HHHH", *e)
        return out

    def cp_refs(self):
        refs = []
        for inner, outer, iname, _acc in self.entries:
            refs.extend([inner, outer, iname])
        return refs


class EnclosingMethodAttr(Attribute):
    def __init__(self, name_idx, cls, nat):
        super().__init__(name_idx, "EnclosingMethod")
        self.cls, self.nat = cls, nat

    def body(self, pool):
        return struct.pack(">HH", self.cls, self.nat)

    def cp_refs(self):
        return [self.cls, self.nat]


class BootstrapMethodsAttr(Attribute):
    def __init__(self, name_idx, entries):
        super().__init__(name_idx, "BootstrapMethods")
        self.entries = entries  # [(mh_idx, [arg_idx])]

    def body(self, pool):
        out = struct.pack(">H", len(self.entries))
        for mh, args in self.entries:
            out += struct.pack(">HH", mh, len(args))
            for a in args:
                out += struct.pack(">H", a)
        return out

    def cp_refs(self):
        refs = []
        for mh, args in self.entries:
            refs.append(mh)
            refs.extend(args)
        return refs


class MethodParametersAttr(Attribute):
    def __init__(self, name_idx, params):
        super().__init__(name_idx, "MethodParameters")
        self.params = params  # [(name_idx, access)]

    def body(self, pool):
        out = struct.pack(">B", len(self.params))
        for n, acc in self.params:
            out += struct.pack(">HH", n, acc)
        return out

    def cp_refs(self):
        return [n for n, _a in self.params]


class ClassListAttr(Attribute):
    """NestHost / NestMembers / PermittedSubclasses."""
    def __init__(self, name_idx, name, indices, single=False):
        super().__init__(name_idx, name)
        self.indices = indices
        self.single = single

    def body(self, pool):
        if self.single:
            return struct.pack(">H", self.indices[0])
        return struct.pack(">H", len(self.indices)) + b"".join(struct.pack(">H", i) for i in self.indices)

    def cp_refs(self):
        return list(self.indices)


class RecordAttr(Attribute):
    def __init__(self, name_idx, components):
        super().__init__(name_idx, "Record")
        self.components = components  # [(name_idx, desc_idx, [Attribute])]

    def body(self, pool):
        out = struct.pack(">H", len(self.components))
        for name_idx, desc_idx, attrs in self.components:
            out += struct.pack(">HH", name_idx, desc_idx)
            out += struct.pack(">H", len(attrs))
            for a in attrs:
                b = a.body(pool)
                out += struct.pack(">HI", a.name_idx, len(b)) + b
        return out

    def cp_refs(self):
        refs = []
        for name_idx, desc_idx, attrs in self.components:
            refs.extend([name_idx, desc_idx])
            for a in attrs:
                refs.extend(_refs_of(a))
        return refs


class AnnotationsAttr(Attribute):
    def __init__(self, name_idx, name, kind, value):
        super().__init__(name_idx, name)
        self.kind = kind        # 'ann' | 'param' | 'default' | 'typeann'
        self.value = value

    def body(self, pool):
        out = bytearray()
        if self.kind == "ann":
            out += _write_anns(self.value, pool)
        elif self.kind == "param":
            out += struct.pack(">B", len(self.value))
            for lst in self.value:
                out += _write_anns(lst, pool)
        elif self.kind == "default":
            out += _write_ev(self.value, pool)
        elif self.kind == "typeann":
            out += struct.pack(">H", len(self.value))
            for ann in self.value:
                out += ann[0]                     # raw target_info + type_path bytes
                out += struct.pack(">H", ann[1])  # type_index
                out += _write_ann_pairs(ann[2], pool)
        return bytes(out)

    def cp_refs(self):
        refs = []
        if self.kind == "ann":
            for a in self.value:
                refs.extend(_ann_refs(a))
        elif self.kind == "param":
            for lst in self.value:
                for a in lst:
                    refs.extend(_ann_refs(a))
        elif self.kind == "default":
            refs.extend(_ev_refs(self.value))
        elif self.kind == "typeann":
            for raw, t, pairs in self.value:
                refs.append(t)
                refs.extend(_ann_refs_pairs(pairs))
        return refs


def _ann_refs(ann):
    refs = [ann.type_idx]
    for n, ev in ann.pairs:
        refs.append(n)
        refs.extend(_ev_refs(ev))
    return refs


def _ann_refs_pairs(pairs):
    refs = []
    for n, ev in pairs:
        refs.append(n)
        refs.extend(_ev_refs(ev))
    return refs


def _ev_refs(ev):
    tag = ev[0]
    if tag == "const":
        return [ev[2]]
    if tag == "enum":
        return [ev[1], ev[2]]
    if tag == "cls":
        return [ev[1]]
    if tag == "ann":
        return _ann_refs(ev[1])
    if tag == "arr":
        refs = []
        for e in ev[1]:
            refs.extend(_ev_refs(e))
        return refs
    return []


def _write_anns(anns, pool):
    out = struct.pack(">H", len(anns))
    for a in anns:
        out += struct.pack(">H", a.type_idx)
        out += _write_ann_pairs(a.pairs, pool)
    return out


def _write_ann_pairs(pairs, pool):
    out = struct.pack(">H", len(pairs))
    for n, ev in pairs:
        out += struct.pack(">H", n)
        out += _write_ev(ev, pool)
    return out


def _write_ev(ev, pool):
    tag = ev[0]
    if tag == "const":
        return ev[1].encode() + struct.pack(">H", ev[2])
    if tag == "enum":
        return b"e" + struct.pack(">HH", ev[1], ev[2])
    if tag == "cls":
        return b"c" + struct.pack(">H", ev[1])
    if tag == "ann":
        a = ev[1]
        return b"@" + struct.pack(">H", a.type_idx) + _write_ann_pairs(a.pairs, pool)
    if tag == "arr":
        out = b"[" + struct.pack(">H", len(ev[1]))
        for e in ev[1]:
            out += _write_ev(e, pool)
        return out
    raise ValueError(tag)


def _refs_of(attr):
    if isinstance(attr, RawAttr):
        return []
    return attr.cp_refs()


# ----------------------------------------------------------------- parsing

def _parse_pool_refs_in_raw(name):
    return False


def _read_ev(data, off):
    tag = chr(data[off]); off += 1
    if tag in "BCDFIJSZs":
        (idx,) = struct.unpack_from(">H", data, off)
        return ("const", tag, idx), off + 2
    if tag == "e":
        t, c = struct.unpack_from(">HH", data, off)
        return ("enum", t, c), off + 4
    if tag == "c":
        (idx,) = struct.unpack_from(">H", data, off)
        return ("cls", idx), off + 2
    if tag == "@":
        ann, off = _read_ann(data, off)
        return ("ann", ann), off
    if tag == "[":
        (n,) = struct.unpack_from(">H", data, off)
        off += 2
        vals = []
        for _ in range(n):
            v, off = _read_ev(data, off)
            vals.append(v)
        return ("arr", vals), off
    raise ValueError("bad element_value tag %r" % tag)


def _read_ann(data, off):
    (t,) = struct.unpack_from(">H", data, off)
    off += 2
    (n,) = struct.unpack_from(">H", data, off)
    off += 2
    pairs = []
    for _ in range(n):
        (name,) = struct.unpack_from(">H", data, off)
        off += 2
        ev, off = _read_ev(data, off)
        pairs.append((name, ev))
    return Annotation(t, pairs), off


def _read_anns(data, off):
    (n,) = struct.unpack_from(">H", data, off)
    off += 2
    out = []
    for _ in range(n):
        a, off = _read_ann(data, off)
        out.append(a)
    return out, off


_TYPEANN_TARGET_SIZES = {}


def _read_type_ann(data, off):
    # JVMS SE8 Tables 4.7.20-A / 4.7.20-B
    start = off
    target_type = data[off]; off += 1
    if target_type in (0x00, 0x01, 0x16):
        off += 1                       # type_parameter / formal_parameter: u1
    elif target_type in (0x10, 0x17, 0x42, 0x43, 0x44, 0x45, 0x46,
                         0x47, 0x48, 0x49, 0x4A, 0x4B):
        off += 2                       # supertype / throws / catch /
                                       # offset / type_argument: u2
    elif target_type in (0x11, 0x12):
        off += 2                       # type_parameter_bound: u1 + u1
    elif target_type in (0x13, 0x14, 0x15):
        pass                           # empty_target: no bytes
    elif target_type in (0x40, 0x41):
        (ln,) = struct.unpack_from(">H", data, off)
        off += 2 + 6 * ln              # localvar: u2 count + count * (3 * u2)
    else:
        raise ValueError("type annotation target 0x%02x" % target_type)
    (plen,) = struct.unpack_from(">B", data, off); off += 1 + 2 * plen   # type_path
    raw = data[start:off]
    (t,) = struct.unpack_from(">H", data, off); off += 2                # type_index
    pairs, off = (lambda p, o: (p, o))(*_read_ann_pairs(data, off))
    return (raw, t, pairs), off


def _read_ann_pairs(data, off):
    (n,) = struct.unpack_from(">H", data, off)
    off += 2
    pairs = []
    for _ in range(n):
        (name,) = struct.unpack_from(">H", data, off)
        off += 2
        ev, off = _read_ev(data, off)
        pairs.append((name, ev))
    return pairs, off


def parse_attribute(name_idx, name, data, pool):
    if name == "Code":
        raise AssertionError("Code handled by member parser")
    if name == "Signature":
        (idx,) = struct.unpack_from(">H", data, 0)
        return SignatureAttr(name_idx, idx)
    if name == "Exceptions":
        (n,) = struct.unpack_from(">H", data, 0)
        exc = list(struct.unpack_from(">%dH" % n, data, 2))
        return ExceptionsAttr(name_idx, exc)
    if name == "ConstantValue":
        (idx,) = struct.unpack_from(">H", data, 0)
        return ConstantValueAttr(name_idx, idx)
    if name == "SourceFile":
        (idx,) = struct.unpack_from(">H", data, 0)
        return SourceFileAttr(name_idx, idx)
    if name == "InnerClasses":
        (n,) = struct.unpack_from(">H", data, 0)
        entries = []
        off = 2
        for _ in range(n):
            entries.append(struct.unpack_from(">HHHH", data, off)); off += 8
        return InnerClassesAttr(name_idx, entries)
    if name == "EnclosingMethod":
        c, nat = struct.unpack_from(">HH", data, 0)
        return EnclosingMethodAttr(name_idx, c, nat)
    if name == "BootstrapMethods":
        (n,) = struct.unpack_from(">H", data, 0)
        off = 2
        entries = []
        for _ in range(n):
            mh, argc = struct.unpack_from(">HH", data, off); off += 4
            args = list(struct.unpack_from(">%dH" % argc, data, off)); off += 2 * argc
            entries.append((mh, args))
        return BootstrapMethodsAttr(name_idx, entries)
    if name == "MethodParameters":
        (n,) = struct.unpack_from(">B", data, 0)
        off = 1
        params = []
        for _ in range(n):
            nm, acc = struct.unpack_from(">HH", data, off); off += 4
            params.append((nm, acc))
        return MethodParametersAttr(name_idx, params)
    if name == "NestHost":
        (idx,) = struct.unpack_from(">H", data, 0)
        return ClassListAttr(name_idx, name, [idx], single=True)
    if name in ("NestMembers", "PermittedSubclasses"):
        (n,) = struct.unpack_from(">H", data, 0)
        idxs = list(struct.unpack_from(">%dH" % n, data, 2))
        return ClassListAttr(name_idx, name, idxs)
    if name == "Record":
        (n,) = struct.unpack_from(">H", data, 0)
        off = 2
        comps = []
        for _ in range(n):
            ni, di, an = struct.unpack_from(">HHH", data, off); off += 6
            attrs = []
            for _j in range(an):
                (ani,) = struct.unpack_from(">H", data, off)
                (alen,) = struct.unpack_from(">I", data, off + 2)
                abody = data[off + 6:off + 6 + alen]
                off += 6 + alen
                aname = pool.utf8_at(ani)
                attrs.append(parse_attribute(ani, aname, abody, pool))
            comps.append((ni, di, attrs))
        return RecordAttr(name_idx, comps)
    if name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
        anns, _off = _read_anns(data, 0)
        return AnnotationsAttr(name_idx, name, "ann", anns)
    if name in ("RuntimeVisibleParameterAnnotations", "RuntimeInvisibleParameterAnnotations"):
        (np,) = struct.unpack_from(">B", data, 0)
        off = 1
        lists = []
        for _ in range(np):
            lst, off = _read_anns(data, off)
            lists.append(lst)
        return AnnotationsAttr(name_idx, name, "param", lists)
    if name == "AnnotationDefault":
        ev, _off = _read_ev(data, 0)
        return AnnotationsAttr(name_idx, name, "default", ev)
    if name in ("RuntimeVisibleTypeAnnotations", "RuntimeInvisibleTypeAnnotations"):
        (n,) = struct.unpack_from(">H", data, 0)
        off = 2
        anns = []
        for _ in range(n):
            a, off = _read_type_ann(data, off)
            anns.append(a)
        return AnnotationsAttr(name_idx, name, "typeann", anns)
    if name in _NO_CP:
        return RawAttr(name_idx, name, data)
    if name in _DROP:
        return None
    # unknown attribute: keep raw but flag pool as opaque
    return RawAttr(name_idx, name, data, cp_unknown=True)


class Member:
    __slots__ = ("access", "name_idx", "desc_idx", "attrs")

    def __init__(self, access, name_idx, desc_idx, attrs):
        self.access = access
        self.name_idx = name_idx
        self.desc_idx = desc_idx
        self.attrs = attrs

    def attr(self, name):
        for a in self.attrs:
            if a.name == name:
                return a
        return None

    def code(self):
        a = self.attr("Code")
        return a.code if a else None


class ClassFile:
    def __init__(self):
        self.minor = 0
        self.major = 52
        self.pool = Pool()
        self.access = 0
        self.this_class = 0
        self.super_class = 0
        self.interfaces = []
        self.fields = []
        self.methods = []
        self.attrs = []
        self.opaque = False       # has attribute we can't analyze
        self.source_name = None   # original file name for logging

    # -- convenience --
    @property
    def this_name(self):
        return self.pool.class_name(self.this_class)

    @property
    def super_name(self):
        return self.pool.class_name(self.super_class) if self.super_class else None

    def method(self, name, desc=None):
        for m in self.methods:
            if self.pool.utf8_at(m.name_idx) == name and (desc is None or
               self.pool.utf8_at(m.desc_idx) == desc):
                return m
        return None

    def field(self, name, desc=None):
        for f in self.fields:
            if self.pool.utf8_at(f.name_idx) == name and (desc is None or
               self.pool.utf8_at(f.desc_idx) == desc):
                return f
        return None

    @classmethod
    def parse(cls, data, source_name=None):
        if data[:4] != b"\xca\xfe\xba\xbe":
            raise ValueError("not a class file")
        cf = cls()
        cf.source_name = source_name
        cf.minor, cf.major = struct.unpack_from(">HH", data, 4)
        cf.pool, off = Pool.parse(data, 8)
        cf.access, cf.this_class, cf.super_class = struct.unpack_from(">HHH", data, off)
        off += 6
        (ifn,) = struct.unpack_from(">H", data, off); off += 2
        for _ in range(ifn):
            (i,) = struct.unpack_from(">H", data, off); off += 2
            cf.interfaces.append(i)
        (fn,) = struct.unpack_from(">H", data, off); off += 2
        for _ in range(fn):
            cf.fields.append(_parse_member(data, off, cf.pool, cf.this_name))
            off = _member_end(data, off, cf.pool)
        (mn,) = struct.unpack_from(">H", data, off); off += 2
        for _ in range(mn):
            cf.methods.append(_parse_member(data, off, cf.pool, cf.this_name))
            off = _member_end(data, off, cf.pool)
        (an,) = struct.unpack_from(">H", data, off); off += 2
        for _ in range(an):
            (name_idx,) = struct.unpack_from(">H", data, off)
            (alen,) = struct.unpack_from(">I", data, off + 2)
            body = data[off + 6:off + 6 + alen]
            off += 6 + alen
            aname = cf.pool.utf8_at(name_idx)
            attr = parse_attribute(name_idx, aname, body, cf.pool)
            if attr is None:
                continue
            cf.attrs.append(attr)
            if isinstance(attr, RawAttr) and attr.cp_unknown:
                cf.opaque = True
        return cf

    def to_bytes(self):
        p = self.pool
        # Serialize members first: attribute bodies may intern new pool
        # entries; the pool header (count) must be written after that so the
        # declared count covers every referenced index.
        body = bytearray()
        body += struct.pack(">HHH", self.access, self.this_class, self.super_class)
        body += struct.pack(">H", len(self.interfaces))
        for i in self.interfaces:
            body += struct.pack(">H", i)
        for group in (self.fields, self.methods):
            body += struct.pack(">H", len(group))
            for m in group:
                body += struct.pack(">HHH", m.access, m.name_idx, m.desc_idx)
                body += _serialize_attrs(m.attrs, p)
        body += _serialize_attrs(self.attrs, p)
        out = bytearray(b"\xca\xfe\xba\xbe")
        out += struct.pack(">HH", self.minor, self.major)
        out += p.to_bytes()
        out += body
        return bytes(out)


def _attr_roots(attr):
    if isinstance(attr, RawAttr):
        if attr.cp_unknown:
            return None      # signal: opaque
        return []
    if isinstance(attr, CodeAttr):
        refs = [h.catch_type for h in attr.code.handlers if h.catch_type]
        refs.extend(a for a in attr.code.raw_attrs)
        for f in attr.code.frames:
            for t in f.locals + f.stack:
                if t[0] == "obj":
                    refs.append(("class_name", t[1]))
        return refs
    return attr.cp_refs()


def _init_locals(desc, access, name, this_name):
    """Initial verification locals of a method: this (uninit for <init>)
    plus parameters, expanded per-slot (long/double take two)."""
    locs = []
    if not (access & 0x0008):  # ACC_STATIC
        if name == "<init>":
            locs.append(("uninit_this",))
        else:
            locs.append(("obj", this_name))
    i = 1  # skip '('
    while i < len(desc) and desc[i] != ')':
        c = desc[i]
        if c == "J":
            locs.append(("long",)); locs.append(("top",)); i += 1
        elif c == "D":
            locs.append(("double",)); locs.append(("top",)); i += 1
        elif c == "L":
            j = desc.index(";", i)
            locs.append(("obj", desc[i + 1:j])); i = j + 1
        elif c == "[":
            j = i
            while desc[j] == "[":
                j += 1
            if desc[j] == "L":
                j = desc.index(";", j) + 1
            else:
                j += 1
            locs.append(("obj", desc[i:j])); i = j
        else:
            if c in "BCISZ":
                locs.append(("int",))
            elif c == "F":
                locs.append(("float",))
            i += 1
    return locs


def _parse_member(data, off, pool, this_name=None):
    access, name_idx, desc_idx, attr_n = struct.unpack_from(">HHHH", data, off)
    off += 8
    attrs = []
    for _ in range(attr_n):
        (ani,) = struct.unpack_from(">H", data, off)
        (alen,) = struct.unpack_from(">I", data, off + 2)
        body = data[off + 6:off + 6 + alen]
        off += 6 + alen
        aname = pool.utf8_at(ani)
        if aname == "Code":
            desc = pool.utf8_at(desc_idx)
            name = pool.utf8_at(name_idx)
            init_locals = _init_locals(desc, access, name, this_name)
            attrs.append(CodeAttr(ani, Code.parse(body, 0, pool,
                                                   init_locals=init_locals)))
        else:
            attr = parse_attribute(ani, aname, body, pool)
            if attr is not None:
                attrs.append(attr)
    return Member(access, name_idx, desc_idx, attrs)


def _member_end(data, off, pool):
    access, name_idx, desc_idx, attr_n = struct.unpack_from(">HHHH", data, off)
    off += 8
    for _ in range(attr_n):
        (alen,) = struct.unpack_from(">I", data, off + 2)
        off += 6 + alen
    return off


def _serialize_attrs(attrs, pool):
    out = struct.pack(">H", len(attrs))
    for a in attrs:
        body = a.body(pool)
        out += struct.pack(">HI", a.name_idx, len(body)) + body
    return out
