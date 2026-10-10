"""JAR reading / writing built on zipfile.

The JAR is held in memory as a dict {name: bytes} plus the ZipInfo list so
compression settings and timestamps are preserved.
"""

import io
import os
import zipfile

from .jvm.classfile import ClassFile

SIGNATURE_FILES = ("META-INF/*.SF", "META-INF/*.RSA", "META-INF/*.DSA", "META-INF/*.EC")


class Jar:
    def __init__(self):
        self.entries = []        # [(ZipInfo, bytes)]
        self.classes = {}        # entry index -> ClassFile (for .class entries)

    @classmethod
    def read(cls, path):
        j = cls()
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                data = zf.read(info)
                j.entries.append((info, data))
        return j

    def class_paths(self):
        out = []
        for i, (info, data) in enumerate(self.entries):
            n = info.filename
            if n.endswith(".class") and not n.endswith("/"):
                out.append((i, n))
        return out

    def parse_classes(self, log=None):
        for i, name in self.class_paths():
            info, data = self.entries[i]
            try:
                self.classes[i] = ClassFile.parse(data, name)
            except Exception as e:
                if log:
                    log("warn: failed to parse %s: %s" % (name, e))
                else:
                    raise

    def original_name_for(self, entry_index):
        return self.entries[entry_index][0].filename

    def set_class_bytes(self, entry_index, data):
        info, _old = self.entries[entry_index]
        self.entries[entry_index] = (info, data)

    def add_entry(self, name, data, after=None):
        info = zipfile.ZipInfo(name)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        self.entries.append((info, data))

    def drop_signatures(self):
        kept = []
        dropped = []
        for info, data in self.entries:
            n = info.filename.upper()
            if n.startswith("META-INF/") and (n.endswith(".SF") or n.endswith(".RSA")
                                              or n.endswith(".DSA") or n.endswith(".EC")
                                              or n == "META-INF/SIG-"):
                dropped.append(info.filename)
                continue
            kept.append((info, data))
        self.entries = kept
        return dropped

    def write(self, path):
        # remove existing entry with same name (duplicate avoidance)
        seen = set()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for info, data in self.entries:
                if info.filename in seen:
                    continue
                seen.add(info.filename)
                zf.writestr(info, data)
        with open(path, "wb") as f:
            f.write(buf.getvalue())

    def read_entry(self, name):
        for info, data in self.entries:
            if info.filename == name:
                return data
        return None

    def entry_names(self):
        return [i.filename for i, _d in self.entries]

    def stats(self):
        n_class = len(self.class_paths())
        total = sum(len(d) for _i, d in self.entries)
        return len(self.entries), n_class, total
