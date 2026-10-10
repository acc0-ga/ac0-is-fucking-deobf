"""Stability + GC roundtrip stress test over real jars (no execution)."""
import sys, time, traceback, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from jarobf.jar import Jar
from jarobf.jvm.gc import junk_dead_utf8


def stress(path):
    t0 = time.time()
    jar = Jar.read(path)
    jar.parse_classes()
    bad = 0
    for idx, cf in sorted(jar.classes.items()):
        try:
            b1 = cf.to_bytes()
            cf2 = type(cf).parse(b1)
            b2 = cf2.to_bytes()
            if b1 != b2:
                print("UNSTABLE", jar.original_name_for(idx))
                bad += 1
                continue
            junk_dead_utf8(cf)
            b3 = cf.to_bytes()
            type(cf).parse(b3)
            jar.set_class_bytes(idx, b3)
        except Exception as e:
            bad += 1
            if bad <= 5:
                tb = traceback.format_exc().splitlines()
                print("FAIL", jar.original_name_for(idx), repr(e), "|", tb[-3] if len(tb) > 2 else "")
    print("%s: classes=%d bad=%d time=%.1fs" % (
        os.path.basename(path), len(jar.classes), bad, time.time() - t0))
    return bad


if __name__ == "__main__":
    total = 0
    for p in sys.argv[1:]:
        total += stress(p)
    sys.exit(1 if total else 0)
