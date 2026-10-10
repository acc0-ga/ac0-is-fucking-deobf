"""JVM instruction table: (opcode, mnemonic, operand format).

Operand formats:
  None      no operands
  'b'       signed byte           's'   signed short
  'cp1'     u1 cp index           'cp2' u2 cp index
  'local'   u1 local index        'iinc' u1 local, s1 const
  'branch'  s2 branch offset      'branch4' s4 branch offset
  'newarray' u1 atype
  'invokeinterface'  cp2, u1 count
  'invokedynamic'    cp2
  'multianewarray'   cp2, u1 dims
  'tableswitch' / 'lookupswitch' / 'wide' handled specially
"""

OPCODES = {}


def _d(op, name, fmt=None):
    OPCODES[op] = (name, fmt)


_d(0x00, "nop")
_d(0x01, "aconst_null")
for i, n in enumerate(["iconst_m1", "iconst_0", "iconst_1", "iconst_2", "iconst_3", "iconst_4", "iconst_5"]):
    _d(0x02 + i, n)
_d(0x09, "lconst_0"); _d(0x0A, "lconst_1")
_d(0x0B, "fconst_0"); _d(0x0C, "fconst_1"); _d(0x0D, "fconst_2")
_d(0x0E, "dconst_0"); _d(0x0F, "dconst_1")
_d(0x10, "bipush", "b")
_d(0x11, "sipush", "s")
_d(0x12, "ldc", "cp1")
_d(0x13, "ldc_w", "cp2")
_d(0x14, "ldc2_w", "cp2")
for i, n in enumerate(["iload", "lload", "fload", "dload", "aload"]):
    _d(0x15 + i, n, "local")
for base, names in [(0x1A, ["iload_0", "iload_1", "iload_2", "iload_3"]),
                    (0x1E, ["lload_0", "lload_1", "lload_2", "lload_3"]),
                    (0x22, ["fload_0", "fload_1", "fload_2", "fload_3"]),
                    (0x26, ["dload_0", "dload_1", "dload_2", "dload_3"]),
                    (0x2A, ["aload_0", "aload_1", "aload_2", "aload_3"])]:
    for i, n in enumerate(names):
        _d(base + i, n)
for i, n in enumerate(["iaload", "laload", "faload", "daload", "aaload", "baload", "caload", "saload"]):
    _d(0x2E + i, n)
for i, n in enumerate(["istore", "lstore", "fstore", "dstore", "astore"]):
    _d(0x36 + i, n, "local")
for base, names in [(0x3B, ["istore_0", "istore_1", "istore_2", "istore_3"]),
                    (0x3F, ["lstore_0", "lstore_1", "lstore_2", "lstore_3"]),
                    (0x43, ["fstore_0", "fstore_1", "fstore_2", "fstore_3"]),
                    (0x47, ["dstore_0", "dstore_1", "dstore_2", "dstore_3"]),
                    (0x4B, ["astore_0", "astore_1", "astore_2", "astore_3"])]:
    for i, n in enumerate(names):
        _d(base + i, n)
for i, n in enumerate(["iastore", "lastore", "fastore", "dastore", "aastore", "bastore", "castore", "sastore"]):
    _d(0x4F + i, n)
for i, n in enumerate(["pop", "pop2", "dup", "dup_x1", "dup_x2", "dup2", "dup2_x1", "dup2_x2", "swap"]):
    _d(0x57 + i, n)
_arith = ["add", "sub", "mul", "div", "rem", "neg"]
_types = ["i", "l", "f", "d"]
op = 0x60
for a in _arith:
    for t in _types:
        _d(op, t + a); op += 1
op = 0x78
for s in ["shl", "shr", "ushr", "and", "or", "xor"]:
    for t in ["i", "l"]:
        _d(op, t + s); op += 1
_d(0x84, "iinc", "iinc")
op = 0x85
for c in ["i2l", "i2f", "i2d", "l2i", "l2f", "l2d", "f2i", "f2l", "f2d", "d2i", "d2l", "d2f",
          "i2b", "i2c", "i2s"]:
    _d(op, c); op += 1
_d(0x94, "lcmp"); _d(0x95, "fcmpl"); _d(0x96, "fcmpg"); _d(0x97, "dcmpl"); _d(0x98, "dcmpg")
op = 0x99
for c in ["ifeq", "ifne", "iflt", "ifge", "ifgt", "ifle",
          "if_icmpeq", "if_icmpne", "if_icmplt", "if_icmpge", "if_icmpgt", "if_icmple",
          "if_acmpeq", "if_acmpne", "goto", "jsr"]:
    _d(op, c, "branch"); op += 1
_d(0xA9, "ret", "local")
_d(0xAA, "tableswitch", "tableswitch")
_d(0xAB, "lookupswitch", "lookupswitch")
op = 0xAC
for c in ["ireturn", "lreturn", "freturn", "dreturn", "areturn", "return"]:
    _d(op, c); op += 1
op = 0xB2
for c in ["getstatic", "putstatic", "getfield", "putfield",
          "invokevirtual", "invokespecial", "invokestatic"]:
    _d(op, c, "cp2"); op += 1
_d(0xB9, "invokeinterface", "invokeinterface")
_d(0xBA, "invokedynamic", "invokedynamic")
_d(0xBB, "new", "cp2")
_d(0xBC, "newarray", "newarray")
_d(0xBD, "anewarray", "cp2")
_d(0xBE, "arraylength")
_d(0xBF, "athrow")
_d(0xC0, "checkcast", "cp2")
_d(0xC1, "instanceof", "cp2")
_d(0xC2, "monitorenter")
_d(0xC3, "monitorexit")
_d(0xC4, "wide", "wide")
_d(0xC5, "multianewarray", "multianewarray")
_d(0xC6, "ifnull", "branch")
_d(0xC7, "ifnonnull", "branch")
_d(0xC8, "goto_w", "branch4")
_d(0xC9, "jsr_w", "branch4")

MNEMONIC = {name: op for op, (name, _) in OPCODES.items()}

# branch opcodes (conditional + goto/jsr)
BRANCH_OPS = {op for op, (name, fmt) in OPCODES.items() if fmt in ("branch", "branch4")}

TABLESWITCH, LOOKUPSWITCH, WIDE = 0xAA, 0xAB, 0xC4
