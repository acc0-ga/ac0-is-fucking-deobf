"""Descriptor parsing / rewriting (class names inside descriptors)."""


def rewrite_desc(desc, class_map):
    """Replace mapped class names inside a field/method/annotation descriptor.

    Works on descriptors (and simple signature strings): walks the text, and
    every `Lname;` component is looked up in class_map.
    """
    if not class_map:
        return desc
    out = []
    i = 0
    n = len(desc)
    while i < n:
        c = desc[i]
        if c == "L":
            j = desc.find(";", i)
            if j < 0:
                out.append(desc[i:])
                break
            name = desc[i + 1:j]
            out.append("L" + class_map.get(name, name) + ";")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def ret_type(desc):
    """Class name of a descriptor's return type, or None (primitive/array)."""
    r = desc[desc.rindex(")") + 1:]
    if r.startswith("L") and r.endswith(";"):
        return r[1:-1]
    if r.startswith("["):
        while r.startswith("["):
            r = r[1:]
        if r.startswith("L") and r.endswith(";"):
            return r[1:-1]
    return None
