"""Basic block flattening: dispatch loop at method end + lookupswitch.

Final layout (instruction indices):

    0:  ...original block 0...      ; entered only by fall-through from entry
        push 1; istore L; goto D    ; end of block 0 (frame: gpad+[top])
        ...original block 1...      ; entered only via the dispatch switch
        push 2; istore L; goto D
        ...
        ...original block m-1...    ; ends with return/athrow itself
    D:  iload L                     ; frame: gpad+[int]
        lookupswitch -> block 1 .. block m-1  (default = block 1)

- L = max_locals (new int slot; max_locals += 1).  Original frames are left
  untouched: their locals arrays do not cover L, so L is implicitly top on
  every original path -- legal, since the end-insert stores into it first.
- cuts = {0} + offsets of stackmap frames with an empty stack; block j =
  [cuts[j], cuts[j+1]).  >= 2 cuts, state ids must fit a sipush.
- The padded locals of every cut frame j>=1 must be IDENTICAL (gpad): the
  switch jumps into them with exactly gpad+[int] (int is assignable to the
  implicit top at L, gpad is assignable to itself).
- Skips: major < 50, exception handlers, jsr/ret, monitorenter/exit,
  overflow, or non-uniform cut frames.
"""

from ..jvm.code import ins


def _pad(locals_, width):
    out = list(locals_)
    if len(out) > width:
        return out[:width]
    return out + [("top",)] * (width - len(out))


def _push_int(v):
    if -1 <= v <= 5:
        return [ins("iconst_m1" if v == -1 else "iconst_%d" % v)]
    if -128 <= v <= 127:
        return [ins("bipush", v)]
    if -32768 <= v <= 32767:
        return [ins("sipush", v)]
    return None


def _flatten_method(cf, m):
    code = m.code()
    if code is None:
        return False
    if getattr(cf, "major", 52) < 50:
        return False
    if code.has_jsr() or code.has_monitor() or code.handlers:
        return False
    ml = code.max_locals
    if ml >= 65535:
        return False

    cuts = sorted({0} | {f.offset for f in code.frames if not f.stack})
    if len(cuts) < 2:
        return False
    frame_at = {}
    for f in code.frames:
        frame_at.setdefault(f.offset, f)

    gset = {tuple(_pad(frame_at[c].locals, ml)) for c in cuts[1:]}
    if len(gset) != 1:
        return False
    gpad = list(next(iter(gset)))
    if any(_push_int(j) is None for j in range(1, len(cuts))):
        return False

    L = ml
    cut_insns = [code.insns[c] for c in cuts]
    gotos = []
    for j in range(len(cuts) - 1, 0, -1):
        pos = cuts[j]
        p = _push_int(j) + [ins("istore", L), ins("goto", 0)]
        gotos.append(p[-1])
        code.insert(pos, p)
        code.add_frame(pos, gpad + [("top",)], [])

    pairs = [(j, code.insns.index(cut_insns[j])) for j in range(1, len(cuts))]
    D = len(code.insns)
    code.insert(D, [ins("iload", L),
                    ins("lookupswitch", pairs[0][1], pairs)])
    for g in gotos:
        g.args = (D,)
    code.add_frame(D, gpad + [("int",)], [])

    code.max_locals = ml + 1
    code.max_stack = max(code.max_stack, 1)
    code.sort_frames()
    return True


def flatten_jar(cf, log=None):
    """Flatten every eligible method of `cf`; returns number flattened."""
    n = 0
    for m in cf.methods:
        try:
            if _flatten_method(cf, m):
                n += 1
        except Exception as e:                      # pragma: no cover
            if log:
                log("flatten: skip method: %r" % e)
    return n
