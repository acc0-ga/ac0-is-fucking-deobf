#pragma once
#include <string>

// Embedded Python interpreter for jarobf backend.
// Loads python313.dll dynamically (works with MinGW, no MSVC .lib needed).
namespace pyembed {

// Locate python313.dll and resolve API. Safe to call multiple times.
// Search order: JAROBF_PYTHON_HOME env, exe dir, PATH.
bool init();

void shutdown();

bool is_available();

// Run jarobf.cli.main in-process. Returns process exit code (0 = ok).
// Log output (stdout) is appended to *log_out.
// Flags mirror the CLI: pass false to disable a pass.
int run_obf(const char* input, const char* output,
            bool rename, bool strings, bool rename_main, bool aggressive,
            bool flow, bool flatten, bool vmp,
            std::string* log_out);

}  // namespace pyembed
