"""Constant pool garbage collection: junk out-of-reach Utf8 entries.

We never remove or reorder pool entries (attribute raw indices must stay
valid); instead dead Utf8 entries get their content replaced with junk so
plaintext strings do not survive string encryption.
"""

import os

from .pool import UTF8, CLASS, STRING, NAT, MHANDLE, MTYPE, DYNAMIC, INDY, MODULE, PACKAGE
from .classfile import RawAttr, CodeAttr, RecordAttr, AnnotationsAttr
from .opcodes import OPCODES


def _edges(e):
    tag = e[0]
    if tag in (CLASS, STRING, MTYPE, MODULE, PACKAGE):
        return (e[1],)
    if tag in (9, 10, 11):
        return (e[1], e[2])
    if tag == NAT:
        return (e[1], e[2])
    if tag == MHANDLE:
        return (e[2],)
    if tag in (DYNAMIC, INDY):
        return (e[2],)
    return ()


def _cp_operands(cf):
    from .opcodes import OPCODES as OP
    out = []
    for m in cf.fields + cf.methods:
        c = m.code()
        if not c:
            continue
        for insn in c.insns:
            fmt = OP[insn.op][1]
            if fmt in ("cp1", "cp2", "invokeinterface", "invokedynamic", "multianewarray"):
                out.append(insn.args[0])
        for h in c.handlers:
            if h.catch_type:
                out.append(h.catch_type)
    return out


def _attr_cp_roots(cf):
    """Returns None if the class is opaque (some attr we cannot analyze)."""
    roots = []
    groups = [cf.fields, cf.methods]
    for group in groups:
        for m in group:
            for a in m.attrs:
                if isinstance(a, RawAttr) and a.cp_unknown:
                    return None
                roots.append(a.name_idx)
                if isinstance(a, CodeAttr):
                    code = a.code
                    for _n, _b in code.raw_attrs:
                        roots.append(_n)
                    if code.frames:
                        smt = _find_utf8_idx(cf.pool, "StackMapTable")
                        if smt is not None:
                            roots.append(smt)
                    for f in code.frames:
                        for t in f.locals + f.stack:
                            if t[0] == "obj":
                                roots.append(("class", t[1]))
                    for h in code.handlers:
                        if h.catch_type:
                            roots.append(h.catch_type)
                    roots.extend(_insn_refs(code))
                else:
                    roots.extend(a.cp_refs())
    for a in cf.attrs:
        if isinstance(a, RawAttr) and a.cp_unknown:
            return None
        roots.append(a.name_idx)
        if isinstance(a, RecordAttr):
            for _n, _d, nested in a.components:
                for na in nested:
                    roots.append(na.name_idx)
                    roots.extend(na.cp_refs())
        else:
            roots.extend(a.cp_refs())
    return roots


def _insn_refs(code):
    out = []
    for insn in code.insns:
        fmt = OPCODES[insn.op][1]
        if fmt in ("cp1", "cp2", "invokeinterface", "invokedynamic", "multianewarray"):
            out.append(insn.args[0])
    return out


def _find_class_idx(pool, name):
    uidx = None
    for i, e in enumerate(pool.entries):
        if e and e[0] == UTF8 and e[1] == name:
            uidx = i
            break
    if uidx is None:
        return None
    for i, e in enumerate(pool.entries):
        if e and e[0] == CLASS and e[1] == uidx:
            return i
    return None


def _find_utf8_idx(pool, s):
    for i, e in enumerate(pool.entries):
        if e and e[0] == UTF8 and e[1] == s:
            return i
    return None


def junk_dead_utf8(cf):
    """Replace unreachable Utf8 entries with junk. Returns count junked.

    Utf8 slots used as descriptors (NameAndType descriptor / MethodType) are
    junked with a *valid* descriptor instead: HotSpot validates every
    NameAndType pair at class parse time, and an unparseable descriptor in a
    dead entry still raises ClassFormatError.

    Returns -1 when the class has an unanalyzable attribute (caller should
    skip pool-sensitive transforms for it)."""
    pool = cf.pool
    roots = _attr_cp_roots(cf)
    if roots is None:
        return -1
    roots = list(roots)
    roots.append(cf.this_class)
    if cf.super_class:
        roots.append(cf.super_class)
    roots.extend(cf.interfaces)
    for m in cf.fields + cf.methods:
        roots.append(m.name_idx)
        roots.append(m.desc_idx)
    desc_utf8s = set()
    for e in pool.entries:
        if e is None:
            continue
        if e[0] == NAT:
            desc_utf8s.add(e[2])
            desc_utf8s.add(e[1])   # NAT name too: pair must stay valid
        elif e[0] == 16:            # MethodType: single descriptor
            desc_utf8s.add(e[1])
    live = set()
    stack = []
    for r in roots:
        if isinstance(r, tuple) and r[0] == "class":
            idx = _find_class_idx(pool, r[1])
            if idx is not None:
                stack.append(idx)
        elif isinstance(r, int) and r > 0:
            stack.append(r)
    while stack:
        i = stack.pop()
        if i in live:
            continue
        if i >= pool.size() or pool.entries[i] is None:
            continue
        live.add(i)
        for e2 in _edges(pool.entries[i]):
            stack.append(e2)
    n = 0
    for i in range(1, pool.size()):
        e = pool.entries[i]
        if e is None:
            continue
        if e[0] == UTF8 and i not in live:
            if i in desc_utf8s:
                junk = "I"
            else:
                junk = "_%s" % os.urandom(6).hex()
            pool.entries[i] = (UTF8, junk)
            n += 1
    return n
