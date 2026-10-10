"""Opaque-predicate bogus control flow.

At the method entry and at every StackMapTable frame point insert:

    <push constants>     ; net stack effect 0, no locals touched
    ifXX L_live          ; predicate is ALWAYS true -> branch always taken
    nop ...              ; dead block (verifier-checked, never executed)
L_live:                  ; == original frame, shifted here by insert()

Every path (branch, dead fall-through, shifted jumps, original fall-through)
arrives at L_live with exactly the state the original frame declares, so the
shifted original frame serves as the merge point.  A copy of that frame is
also kept at the prefix start: HotSpot demands a stackmap frame on the
instruction following an unconditional transfer (goto/return/athrow/switch)
even when it is unreachable.  For the method entry (no frame at offset 0) an
explicit frame equal to init_locals is added.

Only classes with major >= 50 (type-checked verification) are touched; jsr
methods are skipped.  Runs on Code instruction indices, so branch targets,
frames, and exception handlers are maintained by Code.insert().
"""

import random

from ..jvm.code import ins


def _prefix(rng, index):
    """Build the bogus block for insertion at `index`; returns insns.

    The branch is always taken at runtime (opaque predicate), net stack
    effect 0, locals untouched, no exception can be thrown."""
    n_dead = rng.randrange(1, 7)
    form = rng.randrange(6)
    if form == 0:
        push, br_op = [ins("iconst_1")], "ifne"
    elif form == 1:
        push, br_op = [ins("iconst_0")], "ifeq"
    elif form == 2:
        k = rng.choice([k for k in range(-128, 128) if k != 0])
        push, br_op = [ins("bipush", k)], "ifne"
    elif form == 3:
        k = rng.choice([k for k in range(-32768, 32768) if k != 0])
        push, br_op = [ins("sipush", k)], "ifne"
    elif form == 4:
        a = rng.randrange(0, 128)
        b = rng.randrange(0, a + 1)          # a >= b -> if_icmpge taken
        push, br_op = [ins("bipush", a), ins("bipush", b)], "if_icmpge"
    else:
        a = rng.randrange(1, 64)
        b = rng.randrange(-63, 64)
        while a + b == 0:
            b = rng.randrange(-63, 64)
        push, br_op = [ins("bipush", a), ins("bipush", b), ins("iadd")], "ifne"
    k = len(push) + 1 + n_dead               # branch + dead block length
    br = ins(br_op, index + k)
    return push + [br] + [ins("nop")] * n_dead


def add_bogus_cf(cf, rng=None, log=None):
    """Insert bogus branches into every eligible method of `cf`.

    Returns number of insertions performed."""
    if getattr(cf, "major", 52) < 50:
        return 0
    rng = rng or random.Random()
    n = 0
    for m in cf.methods:
        code = m.code()
        if code is None:
            continue
        if code.has_jsr():
            continue
        if code.max_stack > 65533:
            continue
        points = sorted({0} | {f.offset for f in code.frames}, reverse=True)
        for i in points:
            if i > len(code.insns):
                continue
            prefix = _prefix(rng, i)
            has_frame = any(f.offset == i for f in code.frames)
            code.insert(i, prefix)
            if i == 0:
                if not has_frame:
                    code.add_frame(len(prefix), list(code.init_locals), [])
            else:
                # HotSpot requires a stackmap frame on the instruction that
                # follows an unconditional transfer (goto/return/athrow/switch),
                # even when unreachable: keep a frame at the prefix start too.
                shifted = next(f for f in code.frames
                               if f.offset == i + len(prefix))
                code.add_frame(i, list(shifted.locals), list(shifted.stack))
            n += 1
        if code.frames:
            code.sort_frames()
        code.max_stack += 2
    return n
