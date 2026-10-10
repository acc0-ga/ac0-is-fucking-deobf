"""String constant encryption.

Every LDC of a CONSTANT_String is replaced by LDC of Base64(XOR(utf8, key))
followed by an injected static decryptor call. The decryptor is branchless
except for a simple XOR loop, with hand-built StackMapTable frames.
"""

import base64
import os

from ..jvm.code import Code, ins
from ..jvm.classfile import Member, CodeAttr
from ..jvm.opcodes import MNEMONIC
from ..jvm.pool import STRING, METHODREF
from ..jvm import frames as fr_mod

LDC = MNEMONIC["ldc"]
LDC_W = MNEMONIC["ldc_w"]


def encrypt_strings(cf, key=None):
    """Encrypt LDC strings of one class; injects the decryptor if needed.

    Returns number of encrypted constants."""
    pool = cf.pool
    targets = {}                       # Code -> [(insn index, plaintext)]
    for m in cf.methods:
        c = m.code()
        if not c:
            continue
        for i, insn in enumerate(c.insns):
            if insn.op not in (LDC, LDC_W):
                continue
            e = pool.entries[insn.args[0]]
            if not e or e[0] != STRING:
                continue
            s = pool.utf8_at(e[1])
            if not s:
                continue
            try:
                s.encode("utf-8")
            except UnicodeEncodeError:
                continue
            targets.setdefault(c, []).append((i, s))
    if not targets:
        return 0

    if key is None:
        key = os.urandom(1)[0] % 127 + 1
    dec_name = _pick_name(cf)
    dec_ref = pool.member_ref(METHODREF, cf.this_name, dec_name,
                              "(Ljava/lang/String;)Ljava/lang/String;")

    n = 0
    for c, items in targets.items():
        for i, s in sorted(items, reverse=True):
            new_idx = pool.string_idx(_encrypt(s, key))
            insn = c.insns[i]
            if new_idx <= 255:
                insn.op = LDC
                insn.args = (new_idx,)
            else:
                insn.op = LDC_W
                insn.args = (new_idx,)
            c.insert(i + 1, [ins("invokestatic", dec_ref)])
            n += 1

    cf.methods.append(_decryptor(cf, dec_name, key))
    return n


def _encrypt(s, key):
    raw = s.encode("utf-8")
    return base64.b64encode(bytes(b ^ key for b in raw)).decode("ascii")


def _pick_name(cf):
    existing = {cf.pool.utf8_at(m.name_idx) for m in cf.methods}
    while True:
        n = "$d" + os.urandom(3).hex()
        if n not in existing:
            return n


def _decryptor(cf, name, key):
    pool = cf.pool
    S = "java/lang/String"
    insns = [
        ins("invokestatic", pool.member_ref(
            METHODREF, "java/util/Base64", "getDecoder",
            "()Ljava/util/Base64$Decoder;")),
        ins("aload", 0),
        ins("invokevirtual", pool.member_ref(
            METHODREF, "java/util/Base64$Decoder", "decode",
            "(Ljava/lang/String;)[B")),
        ins("astore", 1),
        ins("iconst_0"),
        ins("istore", 2),
        # L1 (loop head) @ index 6
        ins("iload", 2),
        ins("aload", 1),
        ins("arraylength"),
        ins("if_icmpge", 0),            # -> L2
        ins("aload", 1),
        ins("iload", 2),
        ins("aload", 1),
        ins("iload", 2),
        ins("baload"),
        ins("bipush", key),
        ins("ixor"),
        ins("i2b"),
        ins("bastore"),
        ins("iinc", 2, 1),
        ins("goto", 0),                 # -> L1
        # L2 @ index 19
        ins("new", pool.class_idx(S)),
        ins("dup"),
        ins("aload", 1),
        ins("getstatic", pool.member_ref(
            9, "java/nio/charset/StandardCharsets", "UTF_8",
            "Ljava/nio/charset/Charset;")),
        ins("invokespecial", pool.member_ref(
            METHODREF, S, "<init>", "([BLjava/nio/charset/Charset;)V")),
        ins("areturn"),
    ]
    l1, l2 = 6, 21
    assert len(insns) == 27 and insns[l1].name == "iload" and insns[l2].name == "new"
    insns[9] = ins("if_icmpge", l2)
    insns[20] = ins("goto", l1)

    init_locals = [("obj", S)]
    loop_locals = [("obj", S), ("obj", "[B"), ("int",)]
    frames = [fr_mod.Frame(l1, loop_locals, []),
              fr_mod.Frame(l2, loop_locals, [])]
    code = Code(4, 3, insns, [], frames=frames, raw_attrs=[],
                init_locals=init_locals)
    name_idx = pool.utf8(name)
    desc_idx = pool.utf8("(Ljava/lang/String;)Ljava/lang/String;")
    return Member(0x0001 | 0x0008, name_idx, desc_idx,
                  [CodeAttr(pool.utf8("Code"), code)])
