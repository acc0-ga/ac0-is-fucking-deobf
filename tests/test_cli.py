"""CLI matrix: every flag combination must produce a jar the JVM runs with
output identical to the original sample."""

import os
import re
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

TESTS = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(TESTS, "sample.jar")
OBF = os.path.join(TESTS, "..", "obf.py")

CASES = [
    ("default", []),
    ("no-rename", ["--no-rename"]),
    ("no-strings", ["--no-strings"]),
    ("no-both", ["--no-rename", "--no-strings"]),
    ("quiet", ["-q"]),
    ("aggressive", ["--aggressive"]),
    ("rename-main", ["--rename-main"]),
]


def run_jvm(jar_path, main_class, arg="abc"):
    r = subprocess.run(["java", "-Xverify:all", "-cp", jar_path, main_class, arg],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout


def find_main(out_jar, flags, proc_stdout, default):
    if "--rename-main" not in flags:
        return default
    if "META-INF/MANIFEST.MF" in zipfile.ZipFile(out_jar).namelist():
        mf = zipfile.ZipFile(out_jar).read("META-INF/MANIFEST.MF").decode()
        for line in mf.splitlines():
            if line.startswith("Main-Class:"):
                return line.split(":", 1)[1].strip()
    m = re.search(r"entry class is now (\S+)", proc_stdout)
    if not m:
        return None
    return m.group(1).replace(".", "/")


def main():
    base_rc, base_out = run_jvm(SAMPLE, "Sample")
    if base_rc != 0:
        print("BASELINE FAILED rc=%d" % base_rc)
        return 1
    print("baseline lines=%d" % base_out.count("\n"))

    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, flags in CASES:
            dst = os.path.join(tmp, name + ".jar")
            r = subprocess.run(
                [sys.executable, OBF, SAMPLE, "-o", dst] + flags,
                capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                print("%-12s OBF_FAIL rc=%d" % (name, r.returncode))
                fails += 1
                continue
            quiet_ok = ("-q" not in flags) or (not r.stdout.strip() and not r.stderr.strip())
            main_cls = find_main(dst, flags, r.stdout, "Sample")
            if main_cls is None:
                print("%-12s NO_NEW_MAIN" % name)
                fails += 1
                continue
            rc, out = run_jvm(dst, main_cls)
            same = (rc == base_rc and out == base_out)
            print("%-12s run=%s out=%s quiet=%s" % (
                name, "OK" if rc == 0 else "rc=%d" % rc,
                "SAME" if out == base_out else "DIFF", quiet_ok))
            if not (same and quiet_ok):
                fails += 1
                if out != base_out:
                    print("   obf out: %r" % out[:300])
    print("FAILS=%d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
