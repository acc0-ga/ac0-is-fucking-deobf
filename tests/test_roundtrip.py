"""Roundtrip test: parse -> serialize -> reparse -> serialize stability,
then repack the jar from re-serialized (and dead-utf8-junked) bytes and
make sure the JVM runs it with identical output to the original."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from jarobf.jar import Jar
from jarobf.jvm.gc import junk_dead_utf8

TESTS = os.path.dirname(os.path.abspath(__file__))


def run_jvm(jar_path, main_class, arg):
    r = subprocess.run(["java", "-cp", jar_path, main_class, arg],
                       capture_output=True, text=True, timeout=120)
    return r


def check_jar(path, main_class=None, arg=None):
    jar = Jar.read(path)
    jar.parse_classes()
    print("entries=%d classes=%d" % (len(jar.entries), len(jar.classes)))
    bad = 0
    for idx, cf in sorted(jar.classes.items()):
        try:
            b1 = cf.to_bytes()
            cf2 = type(cf).parse(b1)
            b2 = cf2.to_bytes()
            if b1 != b2:
                print("UNSTABLE: %s (%s)" % (jar.original_name_for(idx), cf.this_name))
                bad += 1
                continue
            n = junk_dead_utf8(cf)
            b3 = cf.to_bytes()
            type(cf).parse(b3)  # must still parse
            jar.set_class_bytes(idx, b3)
        except Exception as e:
            print("FAIL %s: %r" % (jar.original_name_for(idx), e))
            bad += 1
    print("unstable/failed: %d" % bad)

    if main_class:
        base = run_jvm(path, main_class, arg)
        print("baseline rc=%d" % base.returncode)
        if base.returncode != 0:
            print(base.stderr[-2000:])
            bad += 1
        fd, out_path = tempfile.mkstemp(suffix=".jar")
        os.close(fd)
        try:
            jar.write(out_path)
            r = run_jvm(out_path, main_class, arg)
            print("repacked rc=%d" % r.returncode)
            print(r.stdout[-2000:])
            if r.returncode != 0:
                print(r.stderr[-2000:])
                bad += 1
            elif r.stdout != base.stdout:
                print("OUTPUT MISMATCH")
                b_lines = base.stdout.splitlines()
                o_lines = r.stdout.splitlines()
                for i in range(max(len(b_lines), len(o_lines))):
                    bb = b_lines[i] if i < len(b_lines) else "<missing>"
                    oo = o_lines[i] if i < len(o_lines) else "<missing>"
                    if bb != oo:
                        print("  line %d: %r != %r" % (i, bb, oo))
                bad += 1
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass
    return bad


if __name__ == "__main__":
    src = TESTS + "/sample.jar"
    if not os.path.exists(src):
        print("sample.jar missing - compile first")
        sys.exit(1)
    bad = check_jar(src, main_class="Sample", arg="abc")
    sys.exit(1 if bad else 0)
