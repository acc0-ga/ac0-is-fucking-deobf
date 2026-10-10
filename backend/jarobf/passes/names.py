"""Obfuscated name generation (unique, collision-free short identifiers)."""

CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ$_"

RESERVED = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
    "var", "record", "yield", "permits", "sealed", "non-sealed",
}


class NameGen:
    """Generates names a, b, ..., z, A, ..., $, _, aa, ab, ... avoiding a set."""

    def __init__(self, avoid=()):
        self.used = set(avoid)
        self.i = 0

    def take(self):
        while True:
            n = _gen(self.i)
            self.i += 1
            if n in self.used or n in RESERVED:
                continue
            self.used.add(n)
            return n


def _gen(i):
    n = len(CHARS)
    if i < n:
        return CHARS[i]
    parts = []
    while True:
        parts.append(CHARS[i % n])
        i = i // n - 1
        if i < 0:
            break
        # keep leading position non-zero
    return "".join(reversed(parts))
