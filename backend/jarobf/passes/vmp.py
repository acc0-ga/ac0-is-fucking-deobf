"""Method virtualization: replace eligible method bodies with a stub that
interprets the original bytecode through VmpRuntime.exec.

Program string (each logical byte stored as char byte+1, whole body XOR'd
with a random key held in the first char):
    [key u1][version u1][u2 maxStack][code...]   (char offsets, code at 4)
The interpreter XOR-decodes p[1:] in place with key = p[0]-1 before running.
Consts passed as separate Object[] built by the stub:
    ('I', int32)->Integer  ('J', int64)->Long  ('S', str)->String
    ('C', name)->Class     ('M', owner, name, desc)->String[3]
Branch targets are absolute char offsets in the program.
The runtime class itself is obfuscated through this pipeline's passes
(rename + strings + flatten + flow) before injection.
Skips: <init>, F/D descriptors, handlers, jsr/monitor, unsupported ops.
"""

import os
import random
import string
import struct

from ..jvm.code import Code, ins
from ..jvm.classfile import CodeAttr
from ..jvm.pool import UTF8, INT, LONG, STRING, CLASS, METHODREF, _encode_utf8
from ..jvm.opcodes import MNEMONIC, OPCODES
from ..jar import Jar
from ..jvm.gc import junk_dead_utf8
from .rename import rename_jar
from .strings import encrypt_strings
from .flow import add_bogus_cf
from .flatten import flatten_jar

EXEC_DESC = "(Ljava/lang/String;[Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;"
_RUNTIME_PATH = os.path.join(os.path.dirname(__file__), "vmp_runtime.class")
_RT_SRC = b"x/VmpRuntime"


def _build_allowed():
    names = [
        "nop", "aconst_null",
        "iconst_m1", "iconst_0", "iconst_1", "iconst_2", "iconst_3",
        "iconst_4", "iconst_5", "lconst_0", "lconst_1",
        "bipush", "sipush", "ldc", "ldc_w", "ldc2_w",
        "iload", "lload", "aload",
        "iload_0", "iload_1", "iload_2", "iload_3",
        "lload_0", "lload_1", "lload_2", "lload_3",
        "aload_0", "aload_1", "aload_2", "aload_3",
        "iaload", "laload", "aaload", "baload", "caload", "saload",
        "istore", "lstore", "astore",
        "istore_0", "istore_1", "istore_2", "istore_3",
        "lstore_0", "lstore_1", "lstore_2", "lstore_3",
        "astore_0", "astore_1", "astore_2", "astore_3",
        "iastore", "lastore", "aastore", "bastore", "castore", "sastore",
        "pop", "pop2", "dup", "dup_x1", "dup_x2", "dup2", "dup2_x1", "dup2_x2", "swap",
        "iadd", "isub", "imul", "idiv", "irem", "ineg",
        "ladd", "lsub", "lmul", "ldiv", "lrem", "lneg",
        "ishl", "ishr", "iushr", "iand", "ior", "ixor",
        "lshl", "lshr", "lushr", "land", "lor", "lxor",
        "iinc", "i2l", "l2i", "i2b", "i2c", "i2s", "lcmp",
        "ifeq", "ifne", "iflt", "ifge", "ifgt", "ifle",
        "if_icmpeq", "if_icmpne", "if_icmplt", "if_icmpge", "if_icmpgt", "if_icmple",
        "if_acmpeq", "if_acmpne", "goto", "goto_w",
        "tableswitch", "lookupswitch",
        "ireturn", "lreturn", "areturn", "return",
        "getstatic", "putstatic", "getfield", "putfield",
        "invokevirtual", "invokestatic",
        "arraylength", "ifnull", "ifnonnull",
    ]
    return {MNEMONIC[n] for n in names}


_ALLOWED = _build_allowed()

# short-form local ops → (generic_op, index); all encoded as generic + u2
_N_FORMS = {}
for _base, _gen in (
    (26, 21), (30, 22), (42, 25),   # iload_0, lload_0, aload_0
    (59, 54), (63, 55), (76, 58),   # istore_0, lstore_0, astore_0
):
    for _i in range(4):
        _N_FORMS[_base + _i] = (_gen, _i)


def _ldc(pool, idx):
    return ins("ldc", idx) if idx <= 255 else ins("ldc_w", idx)


def _push_int_p(pool, v):
    if -1 <= v <= 5:
        return [ins("iconst_m1" if v == -1 else "iconst_%d" % v)]
    if -128 <= v <= 127:
        return [ins("bipush", v)]
    if -32768 <= v <= 32767:
        return [ins("sipush", v)]
    return [_ldc(pool, pool.int_const(v))]


def _can_vmp(cf, m):
    code = m.code()
    if code is None:
        return False
    pool = cf.pool
    name = pool.utf8_at(m.name_idx)
    desc = pool.utf8_at(m.desc_idx)
    if name == "<init>":
        return False
    if "F" in desc or "D" in desc:
        return False
    if code.handlers or code.has_jsr() or code.has_monitor():
        return False
    n = len(code.insns)
    for insn in code.insns:
        if insn.op not in _ALLOWED:
            return False
        opname = OPCODES[insn.op][0]
        fmt = OPCODES[insn.op][1]
        if opname in ("ldc", "ldc_w"):
            e = pool.entries[insn.args[0]]
            if e is None or e[0] not in (INT, STRING, CLASS):
                return False
        elif opname == "ldc2_w":
            e = pool.entries[insn.args[0]]
            if e is None or e[0] != LONG:
                return False
        elif fmt in ("branch", "branch4"):
            t = insn.args[0]
            if t < 0 or t > n:
                return False
        elif opname == "tableswitch":
            d, _low, offs = insn.args
            if d < 0 or d > n or any(o < 0 or o > n for o in offs):
                return False
        elif opname == "lookupswitch":
            d, pairs = insn.args
            if d < 0 or d > n or any(o < 0 or o > n for _k, o in pairs):
                return False
    return True


def _collect_consts(cf, code):
    pool = cf.pool
    consts = []
    cmap = {}

    def add(key):
        if key in cmap:
            return cmap[key]
        i = len(consts)
        consts.append(key)
        cmap[key] = i
        return i

    for insn in code.insns:
        opname = OPCODES[insn.op][0]
        if opname in ("ldc", "ldc_w"):
            e = pool.entries[insn.args[0]]
            if e[0] == INT:
                add(("I", e[1]))
            elif e[0] == STRING:
                add(("S", pool.utf8_at(e[1])))
            elif e[0] == CLASS:
                add(("C", pool.class_name(insn.args[0])))
        elif opname == "ldc2_w":
            add(("J", pool.entries[insn.args[0]][1]))
        elif opname in ("getstatic", "putstatic", "getfield", "putfield",
                        "invokevirtual", "invokestatic"):
            e = pool.entries[insn.args[0]]
            owner = pool.class_name(e[1])
            nat = pool.entries[e[2]]
            add(("M", owner, pool.utf8_at(nat[1]), pool.utf8_at(nat[2])))
    return consts, cmap


def _enc_size(insn):
    opname = OPCODES[insn.op][0]
    fmt = OPCODES[insn.op][1]
    if insn.op in _N_FORMS:
        return 3
    if opname == "goto_w":
        return 3
    if fmt == "local":
        return 3
    if fmt == "iinc":
        return 5
    if opname == "bipush":
        return 2
    if opname == "sipush":
        return 3
    if opname in ("ldc", "ldc_w", "ldc2_w"):
        return 3
    if opname in ("getstatic", "putstatic", "getfield", "putfield",
                  "invokevirtual", "invokestatic"):
        return 3
    if fmt in ("branch", "branch4"):
        return 3
    if opname == "tableswitch":
        return 9 + 2 * len(insn.args[2])
    if opname == "lookupswitch":
        return 5 + 6 * len(insn.args[1])
    return 1


def _u2(out, v):
    out.append((v >> 8) & 0xFF)
    out.append(v & 0xFF)


def _s2(out, v):
    v &= 0xFFFF
    out.append((v >> 8) & 0xFF)
    out.append(v & 0xFF)


def _s4(out, v):
    v &= 0xFFFFFFFF
    out.append((v >> 24) & 0xFF)
    out.append((v >> 16) & 0xFF)
    out.append((v >> 8) & 0xFF)
    out.append(v & 0xFF)


def _enc_insn(out, insn, offsets, cmap, pool):
    op = insn.op
    opname = OPCODES[op][0]
    fmt = OPCODES[op][1]
    if op in _N_FORMS:
        out.append(_N_FORMS[op][0])
        _u2(out, _N_FORMS[op][1])
        return
    if opname == "goto_w":
        op = MNEMONIC["goto"]
    out.append(op)
    if fmt == "local":
        _u2(out, insn.args[0])
    elif fmt == "iinc":
        _u2(out, insn.args[0])
        _s2(out, insn.args[1])
    elif opname == "bipush":
        out.append(insn.args[0] & 0xFF)
    elif opname == "sipush":
        _s2(out, insn.args[0])
    elif opname in ("ldc", "ldc_w"):
        e = pool.entries[insn.args[0]]
        if e[0] == INT:
            ci = cmap[("I", e[1])]
        elif e[0] == STRING:
            ci = cmap[("S", pool.utf8_at(e[1]))]
        else:
            ci = cmap[("C", pool.class_name(insn.args[0]))]
        _u2(out, ci)
    elif opname == "ldc2_w":
        _u2(out, cmap[("J", pool.entries[insn.args[0]][1])])
    elif opname in ("getstatic", "putstatic", "getfield", "putfield",
                    "invokevirtual", "invokestatic"):
        e = pool.entries[insn.args[0]]
        owner = pool.class_name(e[1])
        nat = pool.entries[e[2]]
        _u2(out, cmap[("M", owner, pool.utf8_at(nat[1]), pool.utf8_at(nat[2]))])
    elif fmt in ("branch", "branch4"):
        _u2(out, offsets[insn.args[0]])
    elif opname == "tableswitch":
        d, low, offs = insn.args
        _u2(out, offsets[d])
        _s4(out, low)
        _u2(out, len(offs))
        for o in offs:
            _u2(out, offsets[o])
    elif opname == "lookupswitch":
        d, pairs = insn.args
        _u2(out, offsets[d])
        _u2(out, len(pairs))
        for k, o in pairs:
            _s4(out, k)
            _u2(out, offsets[o])


def _encode_program(code, cmap, pool):
    insns = code.insns
    offsets = []
    pos = 4                      # key + version + maxStack hi/lo
    for insn in insns:
        offsets.append(pos)
        pos += _enc_size(insn)
    if pos >= 65536:
        return None
    out = bytearray()
    out.append(1)  # version (raw; char = version+1 after XOR decode)
    ms = code.max_stack
    out.append((ms >> 8) & 0xFF)
    out.append(ms & 0xFF)
    for insn in insns:
        _enc_insn(out, insn, offsets, cmap, pool)
    key = os.urandom(1)[0] % 255 + 1
    return chr(key + 1) + "".join(chr((b ^ key) + 1) for b in out)


_INT_VOF = "(I)Ljava/lang/Integer;"
_LONG_VOF = "(J)Ljava/lang/Long;"
_INT_VAL = "()I"
_LONG_VAL = "()J"


def _box_const(pool, c):
    """Bytecode that pushes one boxed const value (for aastore into consts[])."""
    kind = c[0]
    if kind == "I":
        return _push_int_p(pool, c[1]) + [
            ins("invokestatic", pool.member_ref(
                METHODREF, "java/lang/Integer", "valueOf", _INT_VOF))]
    if kind == "J":
        if c[1] == 0:
            body = [ins("lconst_0")]
        elif c[1] == 1:
            body = [ins("lconst_1")]
        else:
            body = [ins("ldc2_w", pool.long_const(c[1]))]
        return body + [ins("invokestatic", pool.member_ref(
            METHODREF, "java/lang/Long", "valueOf", _LONG_VOF))]
    if kind == "S":
        return [_ldc(pool, pool.string_idx(c[1]))]
    if kind == "C":
        return [_ldc(pool, pool.class_idx(c[1]))]
    owner, name, desc = c[1], c[2], c[3]
    arr = pool.class_idx("java/lang/String")
    return ([ins("iconst_3"), ins("anewarray", arr),
             ins("dup"), ins("iconst_0"), _ldc(pool, pool.string_idx(owner)),
             ins("aastore"),
             ins("dup"), ins("iconst_1"), _ldc(pool, pool.string_idx(name)),
             ins("aastore"),
             ins("dup"), ins("iconst_2"), _ldc(pool, pool.string_idx(desc)),
             ins("aastore")])


def _parse_params(desc, is_static):
    """Yield (slot, kind) for each param. kind in 'I','J','L'."""
    slot = 0 if is_static else 1
    i = 1
    while desc[i] != ")":
        c = desc[i]
        if c == "J":
            yield slot, "J"
            slot += 2
            i += 1
        elif c in "BCISZ":
            yield slot, "I"
            slot += 1
            i += 1
        elif c == "L":
            yield slot, "L"
            slot += 1
            i = desc.index(";", i) + 1
        elif c == "[":
            yield slot, "L"
            slot += 1
            i += 1
            while desc[i] == "[":
                i += 1
            if desc[i] == "L":
                i = desc.index(";", i) + 1
            else:
                i += 1
        else:
            raise ValueError("bad param %r" % c)


def _make_stub(cf, m, prog, consts, rt_name, exec_name, orig_ml):
    pool = cf.pool
    desc = pool.utf8_at(m.desc_idx)
    is_static = bool(m.access & 0x0008)
    ml = orig_ml
    L_loc, L_cst, L_res = ml, ml + 1, ml + 2
    obj = pool.class_idx("java/lang/Object")

    insns = []
    insns += _push_int_p(pool, ml)
    insns.append(ins("anewarray", obj))
    insns.append(ins("astore", L_loc))
    insns += _push_int_p(pool, len(consts))
    insns.append(ins("anewarray", obj))
    insns.append(ins("astore", L_cst))
    for i, c in enumerate(consts):
        insns.append(ins("aload", L_cst))
        insns += _push_int_p(pool, i)
        insns += _box_const(pool, c)
        insns.append(ins("aastore"))
    if not is_static:
        insns.append(ins("aload", L_loc))
        insns.append(ins("iconst_0"))
        insns.append(ins("aload_0"))
        insns.append(ins("aastore"))
    for slot, kind in _parse_params(desc, is_static):
        insns.append(ins("aload", L_loc))
        insns += _push_int_p(pool, slot)
        if kind == "J":
            insns.append(ins("lload", slot))
            insns.append(ins("invokestatic", pool.member_ref(
                METHODREF, "java/lang/Long", "valueOf", _LONG_VOF)))
        elif kind == "I":
            insns.append(ins("iload", slot))
            insns.append(ins("invokestatic", pool.member_ref(
                METHODREF, "java/lang/Integer", "valueOf", _INT_VOF)))
        else:
            insns.append(ins("aload", slot))
        insns.append(ins("aastore"))
    insns.append(_ldc(pool, pool.string_idx(prog)))
    insns.append(ins("aload", L_cst))
    insns.append(ins("aload", L_loc))
    insns.append(ins("invokestatic", pool.member_ref(
        METHODREF, rt_name, exec_name, EXEC_DESC)))
    insns.append(ins("astore", L_res))
    ret = desc[desc.index(")") + 1:]
    insns.append(ins("aload", L_res))
    if ret == "V":
        insns.append(ins("pop"))
        insns.append(ins("return"))
    elif ret == "J":
        insns.append(ins("checkcast", pool.class_idx("java/lang/Long")))
        insns.append(ins("invokevirtual", pool.member_ref(
            METHODREF, "java/lang/Long", "longValue", _LONG_VAL)))
        insns.append(ins("lreturn"))
    elif ret in "IZBCS":
        insns.append(ins("checkcast", pool.class_idx("java/lang/Integer")))
        insns.append(ins("invokevirtual", pool.member_ref(
            METHODREF, "java/lang/Integer", "intValue", _INT_VAL)))
        insns.append(ins("ireturn"))
    else:
        if ret.startswith("L"):
            cls = ret[1:-1]
        else:
            cls = ret
        insns.append(ins("checkcast", pool.class_idx(cls)))
        insns.append(ins("areturn"))
    return Code(8, ml + 3, insns, [], frames=[], raw_attrs=[])


def _vmp_method(cf, m, rt_name, exec_name, log):
    if not _can_vmp(cf, m):
        return False
    code = m.code()
    consts, cmap = _collect_consts(cf, code)
    prog = _encode_program(code, cmap, cf.pool)
    if prog is None:
        return False
    if len(_encode_utf8(prog)) > 65535:
        return False
    stub = _make_stub(cf, m, prog, consts, rt_name, exec_name, code.max_locals)
    for i, a in enumerate(m.attrs):
        if a.name == "Code":
            m.attrs[i] = CodeAttr(a.name_idx, stub)
            return True
    return False


def _rand_ident(n):
    letters = string.ascii_letters + "_$"
    alnum = letters + string.digits
    return (random.choice(letters)
            + "".join(random.choice(alnum) for _ in range(n - 1)))


def _patch_runtime(data):
    new = ("x/" + _rand_ident(10)).encode("ascii")
    assert len(new) == len(_RT_SRC)
    return data.replace(_RT_SRC, new), new.decode("ascii")


def _force_class_name(cf, new_name):
    """Rewrite in place every pool Utf8 mentioning the class' current name."""
    pool = cf.pool
    old = cf.this_name
    if old == new_name:
        return
    for i, e in enumerate(pool.entries):
        if e is not None and e[0] == UTF8 and old in e[1]:
            pool.entries[i] = (UTF8, e[1].replace(old, new_name))


def _obfuscate_runtime(log):
    """Build the runtime through this pipeline: strings/flatten/flow/rename.

    Returns (class bytes, runtime class name, exec method name)."""
    raw = open(_RUNTIME_PATH, "rb").read()
    mini = Jar()
    mini.add_entry(_RT_SRC.decode("ascii") + ".class", raw)
    mini.parse_classes()
    idx = next(iter(mini.classes))
    cf = mini.classes[idx]
    exec_m = cf.method("exec", EXEC_DESC)
    if exec_m is None:
        raise RuntimeError("vmp: runtime class has no exec()")
    forced = "x/" + _rand_ident(10)
    _force_class_name(cf, forced)
    encrypt_strings(cf)
    flatten_jar(cf, log=log)
    add_bogus_cf(cf, random.Random())
    rename_jar(mini, rename_classes=False, keep_main=False,
               aggressive=True, log=log)
    exec_name = cf.pool.utf8_at(exec_m.name_idx)
    junk_dead_utf8(cf)
    return cf.to_bytes(), forced, exec_name


def _build_runtime(log):
    """Obfuscated runtime; falls back to a plain (still XOR-capable) one."""
    try:
        return _obfuscate_runtime(log)
    except Exception as e:
        if log:
            log("vmp: runtime obfuscation failed, plain runtime: %r" % e)
        data, name = _patch_runtime(open(_RUNTIME_PATH, "rb").read())
        return data, name, "exec"


def vmp_jar(jar, log=None):
    rt = None                # (data, rt_name, exec_name), built on first need
    n = 0
    for _idx, cf in sorted(jar.classes.items()):
        for m in cf.methods:
            try:
                if rt is None and _can_vmp(cf, m):
                    rt = _build_runtime(log)
                if rt is None:
                    continue
                if _vmp_method(cf, m, rt[1], rt[2], log):
                    n += 1
            except Exception as e:
                if log:
                    log("vmp: skip %s.%s: %r" % (
                        cf.this_name, cf.pool.utf8_at(m.name_idx), e))
    if n > 0 and rt is not None:
        jar.add_entry(rt[1] + ".class", rt[0])
    return n
