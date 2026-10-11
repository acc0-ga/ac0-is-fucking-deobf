# jarobf

A JVM jar obfuscator with a pure-Python backend and an optional Dear ImGui
GUI. It rewrites class files directly (constant pool, bytecode, stack map
frames) without ASM or any other Java tooling.

## Passes

| Pass       | Flag            | What it does |
|------------|-----------------|--------------|
| rename     | on by default (`--no-rename`) | Renames classes, packages, methods, fields. Override/hiding groups stay consistent through hierarchy clustering. Patches `Main-Class` in the manifest with `--rename-main`. |
| strings    | on by default (`--no-strings`) | Encrypts every `ldc` string constant; injects a per-class decryptor. Dead plaintext is then junked out of the constant pool. |
| flatten    | `--flatten`     | Splits methods into basic blocks and re-enters them through a dispatch loop + `lookupswitch`. |
| flow       | `--flow`        | Inserts opaque-predicate bogus branches at method entry and every stack map frame point. |
| vmp        | `--vmp`         | Virtualizes eligible method bodies: the original bytecode is encoded into an XOR-encrypted program string interpreted at run time by an injected runtime class. |
| gc         | always          | Constant-pool garbage collection: unreachable Utf8 entries are overwritten so plaintext cannot survive string encryption. |

Pipeline order: `rename -> strings -> flatten -> flow -> vmp -> gc`.

## Requirements

- Python 3.x (tested on 3.13)
- No third-party Python packages
- JDK only needed to run the tests / verify output
- MinGW-w64 g++ only needed to build the GUI

## CLI

```
python -m jarobf INPUT.jar -o OUTPUT.jar [options]
```

or `python obf.py INPUT.jar -o OUTPUT.jar [options]` (same thing, sets up
`sys.path` for you).

Options:

```
--no-rename       skip renaming
--no-strings      skip string encryption
--rename-main     rename the entry class too (manifest Main-Class is patched)
--aggressive      rename instance methods even when the hierarchy exits the jar
--flow            insert opaque-predicate bogus branches
--flatten         flatten basic blocks via a dispatch loop
--vmp             virtualize method bodies through an interpreter
-q, --quiet       suppress progress output
```

Example:

```
python -m jarobf app.jar -o app-obf.jar --aggressive --flow --flatten --vmp
```

Verify the result with the JVM verifier:

```
java -Xverify:all -jar app-obf.jar
```

## Method virtualization (VMP)

- Only methods whose opcodes are all in the interpreter's whitelist are
  virtualized (no `F`/`D` locals, no exception handlers, no `jsr`/`monitor`).
- The stub that replaces the method body just builds a `locals`/`consts`
  array and calls `<runtime>.exec(program, consts, locals)`.
- The program string stores one bytecode byte per char (`byte + 1`) and the
  whole stream is XOR-encrypted with a per-method random key held in the
  first char; the interpreter decodes in place before running.
- Constants (ints, longs, strings, classes, member refs) are passed as a
  separate boxed `Object[]`, so the program string never contains them.
- The runtime class is built by the obfuscator itself: it is put through
  strings + flatten + flow + rename and gets a randomized `x/...` name and
  method names before injection. If that self-obfuscation fails for any
  reason, a plain (still XOR-capable) runtime is injected instead.

## GUI

`gui/` contains a Dear ImGui (DX11) front-end that embeds CPython and calls
the same backend. It loads `python313.dll` dynamically at runtime, so no
MSVC import library is required.

Build with MinGW-w64 (paths in `gui/build.bat` assume Dev-C++ layout):

```
cd gui
build.bat
```

The output is `gui/bin/jarobf-gui.exe`. At startup it puts
`<exe dir>/../../backend` (the repo-root `backend/` directory) on
`sys.path`, so the repository layout must be kept intact.

## Tests

```
python tests/test_cli.py       # every flag combination, output must match the original
python tests/test_roundtrip.py # obfuscate -> run -> compare behaviour
python tests/test_stress.py    # larger input
```

Tests use `tests/sample.jar` and expect `java` on `PATH`.

## Layout

```
backend/jarobf/
  cli.py            command line entry point
  jar.py            zip-level jar reading/writing
  jvm/              class file model: constant pool, code, frames, gc
  passes/           rename, strings, flatten, flow, vmp (+ VmpRuntime.java)
gui/                ImGui front-end, pyembed (embedded CPython)
tests/              regression suite and sample jar
obf.py              convenience runner
```

## Limitations

- Classes with attributes the parser cannot analyse are left untouched by
  pool-sensitive passes.
- Flattening skips methods with exception handlers, `jsr`/`ret`, or
  `monitorenter`/`monitorexit`.
- VMP skips `<init>`, native methods, and any method using unsupported
  opcodes (floating point, `invokedynamic`, `athrow`, ...).
- Renaming is conservative by default: methods of classes whose hierarchy
  leaves the jar keep their names unless `--aggressive` is given.
