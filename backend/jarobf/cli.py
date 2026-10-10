"""Command line interface: python -m jarobf INPUT -o OUTPUT [options]."""

import argparse
import random

from .jar import Jar
from .jvm.gc import junk_dead_utf8
from .passes.rename import rename_jar
from .passes.strings import encrypt_strings
from .passes.flow import add_bogus_cf
from .passes.flatten import flatten_jar
from .passes.vmp import vmp_jar


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="jarobf", description="JVM jar obfuscator (rename + string encryption)")
    ap.add_argument("input", help="input jar")
    ap.add_argument("-o", "--output", required=True, help="output jar")
    ap.add_argument("--no-rename", action="store_true", help="skip renaming")
    ap.add_argument("--no-strings", action="store_true", help="skip string encryption")
    ap.add_argument("--rename-main", action="store_true",
                    help="rename the entry class too (Main-Class manifest is patched)")
    ap.add_argument("--aggressive", action="store_true",
                    help="rename instance methods even when the hierarchy exits the jar")
    ap.add_argument("--flow", action="store_true",
                    help="insert opaque-predicate bogus branches")
    ap.add_argument("--flatten", action="store_true",
                    help="flatten basic blocks via a dispatch loop")
    ap.add_argument("--vmp", action="store_true",
                    help="virtualize method bodies through an interpreter")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    def log(msg):
        if not args.quiet:
            print(msg)

    jar = Jar.read(args.input)
    jar.drop_signatures()
    jar.parse_classes(log=lambda n, e: log("warn: skip %s: %s" % (n, e)))

    main_old = _find_main(jar)
    stats = {"classes": len(jar.classes), "rename": None, "strings": 0}

    if not args.no_rename:
        st = rename_jar(jar, keep_main=not args.rename_main,
                        aggressive=args.aggressive, log=log)
        stats["rename"] = st
        if args.rename_main and main_old:
            new = st["class_map"].get(main_old, main_old)
            if new != main_old:
                if _patch_manifest(jar, main_old, new):
                    log("manifest: Main-Class %s -> %s" % (main_old, new))
                else:
                    log("warn: no manifest Main-Class to patch; "
                        "entry class is now %s" % new)

    if not args.no_strings:
        n = 0
        for _idx, cf in jar.classes.items():
            n += encrypt_strings(cf)
        stats["strings"] = n
        log("strings: %d encrypted" % n)

    if args.flatten:
        n = 0
        for _idx, cf in jar.classes.items():
            n += flatten_jar(cf, log=log)
        stats["flatten"] = n
        log("flatten: %d methods" % n)

    if args.flow:
        rng = random.Random()
        n = 0
        for _idx, cf in jar.classes.items():
            n += add_bogus_cf(cf, rng)
        log("flow: %d bogus branches" % n)

    if args.vmp:
        n = vmp_jar(jar, log=log)
        stats["vmp"] = n
        log("vmp: %d methods" % n)

    junked = 0
    for idx, cf in sorted(jar.classes.items()):
        r = junk_dead_utf8(cf)
        if r > 0:
            junked += r
        jar.set_class_bytes(idx, cf.to_bytes())
    log("utf8 junked: %d" % junked)

    jar.write(args.output)
    log("wrote %s (%d entries)" % (args.output, len(jar.entries)))
    return 0


def _find_main(jar):
    for _idx, cf in jar.classes.items():
        m = cf.method("main", "([Ljava/lang/String;)V")
        if m and (m.access & 0x0008) and (m.access & 0x0001):
            return cf.this_name
    return None


def _patch_manifest(jar, old, new):
    old_dot = old.replace("/", ".")
    new_dot = new.replace("/", ".")
    for i, (info, data) in enumerate(jar.entries):
        if info.filename == "META-INF/MANIFEST.MF":
            txt = data.decode("utf-8", "replace")
            if old_dot not in txt:
                return False
            jar.entries[i] = (info, txt.replace(old_dot, new_dot).encode("utf-8"))
            return True
    return False
