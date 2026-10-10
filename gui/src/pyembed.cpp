#include "pyembed.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdlib>
#include <vector>

// ---------------------------------------------------------------- python api
typedef void PyObject_;

typedef PyObject_* (*Py_IsInitialized_t)();
typedef void (*Py_Initialize_t)();
typedef void (*Py_Finalize_t)();
typedef void (*Py_SetProgramName_t)(const wchar_t*);
typedef PyObject_* (*PyImport_ImportModule_t)(const char*);
typedef PyObject_* (*PyModule_GetDict_t)(PyObject_*);
typedef PyObject_* (*PyRun_StringFlags_t)(const char*, int, PyObject_*,
                                          PyObject_*, void*);
typedef PyObject_* (*PyImport_AddModule_t)(const char*);
typedef PyObject_* (*PyEval_SaveThread_t)();
typedef void (*PyEval_RestoreThread_t)(PyObject_*);
typedef int (*PyGILState_Ensure_t)();
typedef void (*PyGILState_Release_t)(int);
typedef void (*PyErr_Print_t)();
typedef PyObject_* (*PyObject_GetAttrString_t)(PyObject_*, const char*);
typedef PyObject_* (*PyUnicode_FromString_t)(const char*);
typedef const char* (*PyUnicode_AsUTF8_t)(PyObject_*);
typedef PyObject_* (*PyObject_CallMethod_t)(PyObject_*, const char*,
                                            const char*);
typedef void (*Py_DecRef_t)(PyObject_*);
typedef PyObject_* (*PyDict_GetItemString_t)(PyObject_*, const char*);
typedef PyObject_* (*PyObject_Str_t)(PyObject_*);
typedef long (*PyLong_AsLong_t)(PyObject_*);
typedef PyObject_* (*PyLong_FromLong_t)(long);

#define PYFILE_INPUT 257

static HMODULE g_dll = nullptr;
static bool g_ready = false;

static Py_IsInitialized_t pPy_IsInitialized;
static Py_Initialize_t pPy_Initialize;
static Py_Finalize_t pPy_Finalize;
static Py_SetProgramName_t pPy_SetProgramName;
static PyImport_ImportModule_t pPyImport_ImportModule;
static PyModule_GetDict_t pPyModule_GetDict;
static PyRun_StringFlags_t pPyRun_StringFlags;
static PyImport_AddModule_t pPyImport_AddModule;
static PyEval_SaveThread_t pPyEval_SaveThread;
static PyEval_RestoreThread_t pPyEval_RestoreThread;
static PyGILState_Ensure_t pPyGILState_Ensure;
static PyGILState_Release_t pPyGILState_Release;
static PyErr_Print_t pPyErr_Print;
static PyObject_GetAttrString_t pPyObject_GetAttrString;
static PyUnicode_FromString_t pPyUnicode_FromString;
static PyUnicode_AsUTF8_t pPyUnicode_AsUTF8;
static PyObject_CallMethod_t pPyObject_CallMethod;
static Py_DecRef_t pPy_DecRef;
static PyDict_GetItemString_t pPyDict_GetItemString;
static PyObject_Str_t pPyObject_Str;
static PyLong_AsLong_t pPyLong_AsLong;

template <typename T>
static bool sym(T& fn, const char* name) {
    fn = reinterpret_cast<T>(GetProcAddress(g_dll, name));
    return fn != nullptr;
}

static bool resolve_all() {
    return sym(pPy_IsInitialized, "Py_IsInitialized") &&
           sym(pPy_Initialize, "Py_Initialize") &&
           sym(pPy_Finalize, "Py_Finalize") &&
           sym(pPy_SetProgramName, "Py_SetProgramName") &&
           sym(pPyImport_ImportModule, "PyImport_ImportModule") &&
           sym(pPyModule_GetDict, "PyModule_GetDict") &&
           sym(pPyRun_StringFlags, "PyRun_StringFlags") &&
           sym(pPyImport_AddModule, "PyImport_AddModule") &&
           sym(pPyEval_SaveThread, "PyEval_SaveThread") &&
           sym(pPyEval_RestoreThread, "PyEval_RestoreThread") &&
           sym(pPyGILState_Ensure, "PyGILState_Ensure") &&
           sym(pPyGILState_Release, "PyGILState_Release") &&
           sym(pPyErr_Print, "PyErr_Print") &&
           sym(pPyObject_GetAttrString, "PyObject_GetAttrString") &&
           sym(pPyUnicode_FromString, "PyUnicode_FromString") &&
           sym(pPyUnicode_AsUTF8, "PyUnicode_AsUTF8") &&
           sym(pPyObject_CallMethod, "PyObject_CallMethod") &&
           sym(pPy_DecRef, "Py_DecRef") &&
           sym(pPyDict_GetItemString, "PyDict_GetItemString") &&
           sym(pPyObject_Str, "PyObject_Str") &&
           sym(pPyLong_AsLong, "PyLong_AsLong");
}

static std::wstring ExeDir() {
    wchar_t buf[MAX_PATH];
    GetModuleFileNameW(NULL, buf, MAX_PATH);
    std::wstring s(buf);
    size_t p = s.find_last_of(L"\\/");
    return (p == std::wstring::npos) ? L"." : s.substr(0, p);
}

static std::string WideToUtf8(const wchar_t* w) {
    if (!w || !*w) return std::string();
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    if (n <= 1) return std::string();
    std::string s((size_t)(n - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w, -1, &s[0], n, NULL, NULL);
    return s;
}

static std::wstring Utf8ToWide(const char* s) {
    if (!s || !*s) return std::wstring();
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, NULL, 0);
    if (n <= 1) return std::wstring();
    std::wstring w((size_t)(n - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s, -1, &w[0], n);
    return w;
}

// stdout capture shim (python side)
static const char* kCaptureSrc =
    "class _JarobfOut:\n"
    "    def __init__(self):\n"
    "        self.buf = []\n"
    "    def write(self, s):\n"
    "        self.buf.append(s)\n"
    "        return len(s)\n"
    "    def flush(self):\n"
    "        pass\n"
    "    def getvalue(self):\n"
    "        return ''.join(self.buf)\n"
    "_jarobf_out = _JarobfOut()\n";

// GIL helpers ------------------------------------------------------------
struct GilGuard {
    int state;
    GilGuard() { state = pPyGILState_Ensure(); }
    ~GilGuard() { pPyGILState_Release(state); }
};

// Get __main__.__dict__ (borrowed reference, do NOT DecRef).
static PyObject_* MainDict() {
    PyObject_* mod = pPyImport_AddModule("__main__");
    if (!mod) return nullptr;
    return pPyModule_GetDict(mod);
}

// --------------------------------------------------------------- public api

bool pyembed::init() {
    if (g_ready) return true;

    const char* env = getenv("JAROBF_PYTHON_HOME");
    std::vector<std::wstring> candidates;
    if (env && *env) {
        std::wstring h = Utf8ToWide(env);
        candidates.push_back(h + L"\\python313.dll");
    }
    std::wstring exe = ExeDir();
    candidates.push_back(exe + L"\\python313.dll");
    candidates.push_back(L"C:\\Users\\Alex\\AppData\\Local\\Programs\\Python\\"
                         L"Python313\\python313.dll");

    for (auto& c : candidates) {
        g_dll = LoadLibraryW(c.c_str());
        if (g_dll) break;
    }
    if (!g_dll) return false;
    if (!resolve_all()) {
        FreeLibrary(g_dll);
        g_dll = nullptr;
        return false;
    }

    if (pPy_IsInitialized()) {
        g_ready = true;
        return true;
    }

    // locate python home for stdlib
    std::wstring home;
    if (env && *env) {
        home = Utf8ToWide(env);
    } else {
        home = L"C:\\Users\\Alex\\AppData\\Local\\Programs\\Python\\Python313";
    }
    std::wstring prog = home + L"\\python.exe";
    pPy_SetProgramName(prog.c_str());
    pPy_Initialize();

    // bootstrap: put backend on sys.path, install capture shim
    std::wstring backend_w = exe + L"\\..\\..\\backend";
    std::string backend = WideToUtf8(backend_w.c_str());
    for (auto& ch : backend)
        if (ch == '\\') ch = '/';

    std::string boot;
    boot += "import sys\n";
    boot += "p = r'" + backend + "'\n";
    boot += "if p not in sys.path: sys.path.insert(0, p)\n";
    boot += kCaptureSrc;

    // After Py_Initialize the calling thread already holds the GIL,
    // so run the bootstrap directly (no GilGuard).
    PyObject_* dict = MainDict();
    PyObject_* r = pPyRun_StringFlags(boot.c_str(), PYFILE_INPUT, dict,
                                      dict, nullptr);
    if (!r) {
        pPyErr_Print();
        pPy_Finalize();
        FreeLibrary(g_dll);
        g_dll = nullptr;
        return false;
    }
    pPy_DecRef(r);

    // Release the GIL so worker threads can acquire it via PyGILState_Ensure.
    pPyEval_SaveThread();

    g_ready = true;
    return true;
}

void pyembed::shutdown() {
    if (!g_ready) return;
    if (g_dll && pPy_IsInitialized && pPy_IsInitialized()) {
        // Acquire the GIL then finalize. Py_Finalize destroys all thread
        // states, so we must NOT call PyGILState_Release afterwards.
        pPyGILState_Ensure();
        pPy_Finalize();
    }
    if (g_dll) {
        FreeLibrary(g_dll);
        g_dll = nullptr;
    }
    g_ready = false;
}

bool pyembed::is_available() { return g_ready; }

// Escape a C string for embedding inside a Python single-quoted literal.
static std::string PyQuote(const char* s) {
    std::string out = "'";
    for (const char* p = s; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (c == '\\' || c == '\'') {
            out += '\\';
            out += (char)c;
        } else if (c == '\n') {
            out += "\\n";
        } else if (c == '\r') {
            out += "\\r";
        } else if (c == '\t') {
            out += "\\t";
        } else if (c < 0x20 || c == 0x7f) {
            char buf[8];
            snprintf(buf, sizeof(buf), "\\x%02x", c);
            out += buf;
        } else {
            out += (char)c;
        }
    }
    out += "'";
    return out;
}

int pyembed::run_obf(const char* input, const char* output, bool rename,
                     bool strings, bool rename_main, bool aggressive,
                     bool flow, bool flatten, bool vmp,
                     std::string* log_out) {
    if (!g_ready) return 127;

    // build argv python literal with proper escaping
    std::string args_lit = "[" + PyQuote("jarobf") + ", " + PyQuote(input) +
                           ", " + PyQuote("-o") + ", " + PyQuote(output);
    if (!rename) args_lit += ", " + PyQuote("--no-rename");
    if (!strings) args_lit += ", " + PyQuote("--no-strings");
    if (rename_main) args_lit += ", " + PyQuote("--rename-main");
    if (aggressive) args_lit += ", " + PyQuote("--aggressive");
    if (flow) args_lit += ", " + PyQuote("--flow");
    if (flatten) args_lit += ", " + PyQuote("--flatten");
    if (vmp) args_lit += ", " + PyQuote("--vmp");
    args_lit += "]";

    std::string src;
    src += "import sys\n";
    src += "sys.argv = " + args_lit + "\n";
    src += "sys.stdout = _jarobf_out\n";
    src += "try:\n";
    src += "    from jarobf import cli as _cli\n";
    src += "    _cli.main(sys.argv[1:])\n";
    src += "    _jarobf_exit = 0\n";
    src += "except SystemExit as _e:\n";
    src += "    _jarobf_exit = _e.code if isinstance(_e.code, int) else 1\n";
    src += "except BaseException:\n";
    src += "    import traceback\n";
    src += "    _jarobf_out.write(traceback.format_exc())\n";
    src += "    _jarobf_exit = 1\n";
    src += "finally:\n";
    src += "    sys.stdout = sys.__stdout__\n";

    int exit_code = 1;
    GilGuard gil;
    PyObject_* dict = MainDict();
    PyObject_* result =
        pPyRun_StringFlags(src.c_str(), PYFILE_INPUT, dict, dict, nullptr);
    if (!result) {
        pPyErr_Print();
        if (log_out) log_out->append("pyembed: unhandled python error\n");
    } else {
        pPy_DecRef(result);
    }

    // read exit code + captured log from __main__
    PyObject_* main_mod = pPyImport_ImportModule("__main__");
    if (main_mod) {
        PyObject_* dict = pPyModule_GetDict(main_mod);
        PyObject_* ec = pPyDict_GetItemString(dict, "_jarobf_exit");
        if (ec) {
            PyObject_* s = pPyObject_Str(ec);
            if (s) {
                const char* cs = pPyUnicode_AsUTF8(s);
                if (cs) exit_code = atoi(cs);
                pPy_DecRef(s);
            }
        }
        PyObject_* out = pPyObject_GetAttrString(main_mod, "_jarobf_out");
        if (out) {
            PyObject_* val = pPyObject_CallMethod(out, "getvalue", nullptr);
            if (val) {
                const char* s = pPyUnicode_AsUTF8(val);
                if (s && log_out) log_out->append(s);
                pPy_DecRef(val);
            }
            pPy_DecRef(out);
        }
        pPy_DecRef(main_mod);
    }
    return exit_code;
}
