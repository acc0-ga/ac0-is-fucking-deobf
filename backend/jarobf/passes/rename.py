"""Class / package / method / field renaming.

Strategy:
  * hierarchy clusters: methods (and fields) with the same name connected
    through inheritance inside the jar share one new name, so overrides and
    hiding stay consistent;
  * conservative keep rules (Object/serialization methods, native, main,
    methods of classes whose hierarchy exits the jar) preserve behaviour
    where we cannot see the external side;
  * references are rewritten structurally (member refs / indy / method types /
    descriptors / frames / attributes) and constant pool Utf8 entries are
    never mutated in place - renamed entities get fresh Utf8 slots.
"""

from ..jvm.pool import UTF8, CLASS, STRING, NAT, MTYPE, DYNAMIC, INDY
from ..jvm.classfile import (SignatureAttr, InnerClassesAttr, EnclosingMethodAttr,
                             SourceFileAttr, AnnotationsAttr, RecordAttr)
from .names import NameGen
from .desc import rewrite_desc, ret_type

ACC_STATIC = 0x0008
ACC_PRIVATE = 0x0002
ACC_NATIVE = 0x0100
ACC_PUBLIC = 0x0001
ACC_ENUM = 0x4000
ACC_MODULE = 0x8000

OBJECT_METHODS = {"toString", "equals", "hashCode", "getClass", "clone",
                  "finalize", "notify", "notifyAll", "wait"}
SERIAL_METHODS = {"writeObject", "readObject", "readResolve", "writeReplace"}


def rename_jar(jar, rename_classes=True, rename_methods=True, rename_fields=True,
               keep_main=True, aggressive=False, log=None):
    """Rename classes/methods/fields of all parsed classes in `jar`.

    Returns stats dict (also patches class entry file names)."""
    def say(msg):
        if log:
            log(msg)

    classes = {}      # old internal name -> (entry index, ClassFile)
    for idx, cf in jar.classes.items():
        name = cf.this_name
        if (cf.access & ACC_MODULE) or name == "module-info":
            continue
        classes[name] = (idx, cf)

    class_map = _plan_classes(classes, keep_main) if rename_classes else {}
    anc = {n: _ancestors(n, classes, {}) for n in classes}
    method_maps, method_decl = _plan_methods(classes, anc, keep_main, aggressive) \
        if rename_methods else ({n: {} for n in classes}, {})
    field_maps, field_decl = _plan_fields(classes, anc) if rename_fields else \
        ({n: {} for n in classes}, {})

    n_cls = sum(1 for k, v in class_map.items() if k != v)
    n_meth = sum(len(d) for d in method_decl.values())
    n_field = sum(len(d) for d in field_decl.values())
    say("rename: %d classes, %d methods, %d fields" % (n_cls, n_meth, n_field))

    dot_map = {k.replace("/", "."): v.replace("/", ".") for k, v in class_map.items()}
    for name, (idx, cf) in classes.items():
        _apply(cf, name, class_map, dot_map, method_maps, field_maps)

    # entry file names must follow the class names
    if class_map:
        for name, (idx, cf) in classes.items():
            new = class_map.get(name, name)
            if new != name:
                _rename_entry(jar, idx, name, new)

    return {"classes": n_cls, "methods": n_meth, "fields": n_field,
            "class_map": class_map}


# --------------------------------------------------------------- planning

def _is_entry_class(cf, keep_main):
    if not keep_main:
        return False
    m = cf.method("main", "([Ljava/lang/String;)V")
    return bool(m and (m.access & ACC_STATIC) and (m.access & ACC_PUBLIC))


def _plan_classes(classes, keep_main):
    kept = {n for n, (_i, cf) in classes.items() if _is_entry_class(cf, keep_main)}

    old_segs, old_simple = set(), set()
    for n in classes:
        parts = n.split("/")
        old_segs.update(parts[:-1])
        for s in parts:
            old_simple.update(s.split("$"))
    old_full = set(classes)

    seg_map = {}
    seg_gen = NameGen(avoid=old_segs)
    for n in sorted(classes):
        if n in kept:
            continue
        for seg in n.split("/")[:-1]:
            if seg not in seg_map:
                seg_map[seg] = seg_gen.take()

    used_full = set(old_full)
    simple_gen = NameGen(avoid=old_simple)
    class_map = {n: n for n in kept}
    for n in sorted(classes):
        if n in kept:
            continue
        if "$" in n:
            outer, rest = n.split("$", 1)
            if outer not in class_map:        # outer kept or unknown -> keep
                class_map[n] = n
                continue
            new = class_map[outer]
            for part in rest.split("$"):
                if part.isdigit():
                    new += "$" + part
                else:
                    new += "$" + _take_unique(simple_gen, new_prefix_check(new, used_full))
                    used_full.add(new)
            used_full.add(new)
            class_map[n] = new
        else:
            segs = n.split("/")[:-1]
            pkg = "/".join(seg_map[s] for s in segs)
            simple = _take_simple(simple_gen, pkg, used_full)
            new = pkg + "/" + simple if pkg else simple
            used_full.add(new)
            class_map[n] = new
    return class_map


def _take_simple(gen, pkg, used_full):
    while True:
        s = gen.take()
        full = (pkg + "/" + s) if pkg else s
        if full not in used_full:
            return s


def _take_unique(gen, check):
    while True:
        s = gen.take()
        if check(s):
            return s


def new_prefix_check(prefix, used_full):
    def f(s):
        return (prefix + "$" + s) not in used_full
    return f


def _ancestors(name, classes, cache):
    if name in cache:
        return cache[name]
    cache[name] = set()
    cf = classes[name][1]
    res = set()
    directs = []
    if cf.super_name in classes:
        directs.append(cf.super_name)
    for i in cf.interfaces:
        n = cf.pool.class_name(i)
        if n in classes:
            directs.append(n)
    for d in directs:
        res.add(d)
        res |= _ancestors(d, classes, cache)
    cache[name] = res
    return res


def _external_parents(cf, classes):
    out = []
    if cf.super_name and cf.super_name not in classes:
        out.append(cf.super_name)
    for i in cf.interfaces:
        n = cf.pool.class_name(i)
        if n not in classes:
            out.append(n)
    return out


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _plan_methods(classes, anc, keep_main, aggressive):
    decl = {}                       # class -> {old name -> [Member]}
    for c, (_i, cf) in classes.items():
        d = {}
        for m in cf.methods:
            mn = cf.pool.utf8_at(m.name_idx)
            if mn in ("<init>", "<clinit>"):
                continue
            d.setdefault(mn, []).append(m)
        decl[c] = d

    uf = _UF()
    for c, d in decl.items():
        for n in d:
            uf.find((c, n))
    for c in classes:
        for sup in anc[c]:
            for n in decl[c]:
                if n in decl.get(sup, ()):
                    uf.union((c, n), (sup, n))

    keep = {}
    for c, d in decl.items():
        cf = classes[c][1]
        ext = _external_parents(cf, classes)
        ext_deep = any(p != "java/lang/Object" for p in ext)
        entry = keep_main and _is_entry_class(cf, keep_main)
        for n, mems in d.items():
            r = uf.find((c, n))
            k = keep.get(r, False)
            if n in OBJECT_METHODS or n in SERIAL_METHODS:
                k = True
            # Enum.valueOf/getEnumConstants look up "values"/"valueOf" by name
            if cf.access & ACC_ENUM and n in ("values", "valueOf"):
                k = True
            if entry and n == "main":
                k = True
            for m in mems:
                desc = cf.pool.utf8_at(m.desc_idx)
                if m.access & ACC_NATIVE:
                    k = True
                if n == "main" and desc == "([Ljava/lang/String;)V" and (m.access & ACC_STATIC):
                    k = True
                if not aggressive and ext_deep and not (m.access & ACC_STATIC) \
                        and not (m.access & ACC_PRIVATE):
                    k = True
            keep[r] = k

    avoid = {cf.pool.utf8_at(m.name_idx)
             for _i, cf in classes.values() for m in cf.methods}
    gen = NameGen(avoid=avoid)
    newname = {}
    for c, d in decl.items():
        for n in d:
            r = uf.find((c, n))
            if not keep.get(r) and r not in newname:
                newname[r] = gen.take()

    decl_renames = {}
    for c, d in decl.items():
        rn = {}
        for n in d:
            r = uf.find((c, n))
            if not keep.get(r):
                rn[n] = newname[r]
        decl_renames[c] = rn

    maps = {}
    for c in classes:
        m = {}
        for a in [c] + sorted(anc[c]):
            m.update(decl_renames.get(a, {}))
        maps[c] = m
    return maps, decl_renames


def _plan_fields(classes, anc):
    decl = {}
    for c, (_i, cf) in classes.items():
        if any(isinstance(a, RecordAttr) for a in cf.attrs):
            decl[c] = {}            # record components keep their names
            continue
        d = {}
        for f in cf.fields:
            fn = cf.pool.utf8_at(f.name_idx)
            d.setdefault(fn, []).append(f)
        decl[c] = d

    uf = _UF()
    for c, d in decl.items():
        for n in d:
            uf.find((c, n))
    for c in classes:
        for sup in anc[c]:
            for n in decl[c]:
                if n in decl.get(sup, ()):
                    uf.union((c, n), (sup, n))

    keep = {}
    for c, d in decl.items():
        cf = classes[c][1]
        for n, mems in d.items():
            r = uf.find((c, n))
            k = keep.get(r, False)
            if n == "serialVersionUID" and any(
                    cf.pool.utf8_at(f.desc_idx) == "J" for f in mems):
                k = True
            keep[r] = k

    avoid = {cf.pool.utf8_at(f.name_idx)
             for _i, cf in classes.values() for f in cf.fields}
    gen = NameGen(avoid=avoid)
    newname = {}
    for c, d in decl.items():
        for n in d:
            r = uf.find((c, n))
            if not keep.get(r) and r not in newname:
                newname[r] = gen.take()

    decl_renames = {}
    for c, d in decl.items():
        decl_renames[c] = {n: newname[uf.find((c, n))]
                           for n in d if not keep.get(uf.find((c, n)))}

    maps = {}
    for c in classes:
        m = {}
        for a in [c] + sorted(anc[c]):
            m.update(decl_renames.get(a, {}))
        maps[c] = m
    return maps, decl_renames


# --------------------------------------------------------------- applying

def _apply(cf, this_old, class_map, dot_map, method_maps, field_maps):
    pool = cf.pool

    # 1. member refs / indy / method types (owner lookups use OLD names)
    for i, e in enumerate(list(pool.entries)):
        if e is None:
            continue
        tag = e[0]
        if tag in (9, 10, 11):                     # Fieldref / Methodref / ...
            owner = pool.class_name(e[1])
            _rewrite_ref(pool, i, e, owner, method_maps, field_maps, class_map)
        elif tag in (INDY, DYNAMIC):               # call site / condy
            nat = pool.entries[e[2]]
            name = pool.utf8_at(nat[1])
            desc = pool.utf8_at(nat[2])
            owner = ret_type(desc)
            new_desc = rewrite_desc(desc, class_map)
            new_name = method_maps.get(owner, {}).get(name, name)
            if new_name != name or new_desc != desc:
                pool.entries[i] = (tag, e[1], pool.nat(new_name, new_desc))
        elif tag == MTYPE:                         # MethodType descriptor
            desc = pool.utf8_at(e[1])
            nd = rewrite_desc(desc, class_map)
            if nd != desc:
                pool.entries[i] = (MTYPE, pool.utf8(nd))

    # 2. EnclosingMethod nat
    for a in cf.attrs:
        if isinstance(a, EnclosingMethodAttr) and a.nat:
            _rewrite_enclosing(pool, a, method_maps, class_map)

    # 3. member declarations
    ren_m = method_maps.get(this_old, {})
    ren_f = field_maps.get(this_old, {})
    for m in cf.methods:
        _rename_member(pool, m, ren_m, class_map)
    for f in cf.fields:
        _rename_member(pool, f, ren_f, class_map)

    # 4. drop Signature attributes (generic metadata, cosmetic only)
    _drop_signatures(cf)

    # 5. InnerClasses simple names
    for a in cf.attrs:
        if isinstance(a, InnerClassesAttr):
            _rewrite_inner_names(pool, a, class_map)

    # 6. SourceFile
    for a in cf.attrs:
        if isinstance(a, SourceFileAttr):
            new_full = class_map.get(this_old, this_old)
            simple = new_full.split("$")[-1].split("/")[-1]
            a.idx = pool.utf8(simple + ".java")

    # 7. annotation descriptors
    for a in list(cf.attrs):
        if isinstance(a, AnnotationsAttr):
            _rewrite_ann_attr(pool, a, class_map)
    for m in cf.fields + cf.methods:
        for a in m.attrs:
            if isinstance(a, AnnotationsAttr):
                _rewrite_ann_attr(pool, a, class_map)
            elif isinstance(a, RecordAttr):
                for _n, _d, nested in a.components:
                    for na in nested:
                        if isinstance(na, AnnotationsAttr):
                            _rewrite_ann_attr(pool, na, class_map)

    # 8. StackMapTable object types + init locals
    for m in cf.methods:
        c = m.code()
        if not c:
            continue
        c.init_locals = [_map_t(t, class_map) for t in c.init_locals]
        for f in c.frames:
            f.locals = [_map_t(t, class_map) for t in f.locals]
            f.stack = [_map_t(t, class_map) for t in f.stack]

    # 9. Record components
    for a in cf.attrs:
        if isinstance(a, RecordAttr):
            _rewrite_record(pool, a, ren_f, class_map)

    # 10. CLASS + STRING constant repoint (LAST: all old-name lookups done)
    for i, e in enumerate(list(pool.entries)):
        if e is None:
            continue
        if e[0] == CLASS:
            name = pool.utf8_at(e[1])
            new = _map_class_name(name, class_map)
            if new:
                pool.entries[i] = (CLASS, pool.utf8(new))
        elif e[0] == STRING:
            s = pool.utf8_at(e[1])
            new = _map_class_name(s, class_map) or _map_class_name(s, dot_map)
            if new:
                pool.entries[i] = (STRING, pool.utf8(new))


def _rewrite_ref(pool, i, e, owner, method_maps, field_maps, class_map):
    nat = pool.entries[e[2]]
    name = pool.utf8_at(nat[1])
    desc = pool.utf8_at(nat[2])
    if e[0] == 9:
        new_name = field_maps.get(owner, {}).get(name, name)
    else:
        new_name = method_maps.get(owner, {}).get(name, name)
    new_desc = rewrite_desc(desc, class_map)
    if new_name != name or new_desc != desc:
        pool.entries[i] = (e[0], e[1], pool.nat(new_name, new_desc))


def _rewrite_enclosing(pool, a, method_maps, class_map):
    owner = pool.class_name(a.cls)
    nat = pool.entries[a.nat]
    name = pool.utf8_at(nat[1])
    desc = pool.utf8_at(nat[2])
    new_name = method_maps.get(owner, {}).get(name, name)
    new_desc = rewrite_desc(desc, class_map)
    if new_name != name or new_desc != desc:
        a.nat = pool.nat(new_name, new_desc)


def _rename_member(pool, mem, ren, class_map):
    name = pool.utf8_at(mem.name_idx)
    desc = pool.utf8_at(mem.desc_idx)
    new_name = ren.get(name, name)
    new_desc = rewrite_desc(desc, class_map)
    if new_name != name:
        mem.name_idx = pool.utf8(new_name)
    if new_desc != desc:
        mem.desc_idx = pool.utf8(new_desc)


def _drop_signatures(cf):
    cf.attrs = [a for a in cf.attrs if not isinstance(a, SignatureAttr)]
    for m in cf.fields + cf.methods:
        m.attrs = [a for a in m.attrs if not isinstance(a, SignatureAttr)]
        for a in m.attrs:
            if isinstance(a, RecordAttr):
                for _n, _d, nested in a.components:
                    a_components_filter(nested)


def a_components_filter(nested):
    nested[:] = [a for a in nested if not isinstance(a, SignatureAttr)]


def _rewrite_inner_names(pool, a, class_map):
    out = []
    for inner, outer, iname, acc in a.entries:
        if iname:
            old_full = pool.class_name(inner)
            new_full = class_map.get(old_full)
            if new_full and new_full != old_full:
                simple = new_full.split("$")[-1].split("/")[-1]
                iname = pool.utf8(simple)
        out.append((inner, outer, iname, acc))
    a.entries = out


def _map_t(t, class_map):
    if t[0] == "obj":
        new = _map_class_name(t[1], class_map)
        return ("obj", new or t[1])
    return t


def _map_class_name(name, class_map):
    """Map a plain class name or an array class descriptor ([Lold;, [[Lold;)."""
    new = class_map.get(name)
    if new:
        return new
    if name.startswith("["):
        i = 0
        while i < len(name) and name[i] == "[":
            i += 1
        if i < len(name) and name[i] == "L" and name.endswith(";"):
            inner = class_map.get(name[i + 1:-1])
            if inner:
                return name[:i + 1] + inner + ";"
    return None


def _rewrite_ann_attr(pool, a, class_map):
    if a.kind == "ann":
        a.value = [_rewrite_ann(pool, x, class_map) for x in a.value]
    elif a.kind == "param":
        a.value = [[_rewrite_ann(pool, x, class_map) for x in lst] for lst in a.value]
    elif a.kind == "default":
        a.value = _rewrite_ev(pool, a.value, class_map)
    elif a.kind == "typeann":
        a.value = [(raw, _rw_utf8_desc(pool, t, class_map),
                    _rewrite_pairs(pool, pairs, class_map))
                   for raw, t, pairs in a.value]


def _rw_utf8_desc(pool, idx, class_map):
    d = pool.utf8_at(idx)
    nd = rewrite_desc(d, class_map)
    return pool.utf8(nd) if nd != d else idx


def _rewrite_ann(pool, x, class_map):
    from ..jvm.classfile import Annotation
    t = _rw_utf8_desc(pool, x.type_idx, class_map)
    return Annotation(t, _rewrite_pairs(pool, x.pairs, class_map))


def _rewrite_pairs(pool, pairs, class_map):
    return [(n, _rewrite_ev(pool, ev, class_map)) for n, ev in pairs]


def _rewrite_ev(pool, ev, class_map):
    tag = ev[0]
    if tag == "enum":
        return ("enum", _rw_utf8_desc(pool, ev[1], class_map), ev[2])
    if tag == "ann":
        return ("ann", _rewrite_ann(pool, ev[1], class_map))
    if tag == "arr":
        return ("arr", [_rewrite_ev(pool, e, class_map) for e in ev[1]])
    return ev


def _rewrite_record(pool, a, ren_f, class_map):
    out = []
    for ni, di, nested in a.components:
        n_old = pool.utf8_at(ni)
        d_old = pool.utf8_at(di)
        n_new = ren_f.get(n_old, n_old)
        d_new = rewrite_desc(d_old, class_map)
        if n_new != n_old:
            ni = pool.utf8(n_new)
        if d_new != d_old:
            di = pool.utf8(d_new)
        out.append((ni, di, nested))
    a.components = out


def _rename_entry(jar, idx, old, new):
    info, data = jar.entries[idx]
    fn = info.filename
    suffix = old + ".class"
    if fn.endswith(suffix):
        info.filename = fn[:len(fn) - len(suffix)] + new + ".class"
