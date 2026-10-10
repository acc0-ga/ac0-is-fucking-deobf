#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <commdlg.h>
#include <shellapi.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <tchar.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <string>

#include "imgui.h"
#include "imgui_impl_win32.h"
#include "imgui_impl_dx11.h"

#include "pyembed.h"

#pragma comment(lib, "d3d11")
#pragma comment(lib, "dxgi")

extern "C" HRESULT WINAPI D3D11CreateDeviceAndSwapChain(
    IDXGIAdapter* pAdapter, D3D_DRIVER_TYPE DriverType, HMODULE Software, UINT Flags,
    const D3D_FEATURE_LEVEL* pFeatureLevels, UINT FeatureLevels, UINT SDKVersion,
    DXGI_SWAP_CHAIN_DESC* pSwapChainDesc, IDXGISwapChain** ppSwapChain,
    ID3D11Device** ppDevice, D3D_FEATURE_LEVEL* pFeatureLevel, ID3D11DeviceContext** ppImmediateContext);

static ID3D11Device* g_pd3dDevice = NULL;
static ID3D11DeviceContext* g_pd3dDeviceContext = NULL;
static IDXGISwapChain* g_pSwapChain = NULL;
static ID3D11RenderTargetView* g_mainRenderTargetView = NULL;

static void CreateRenderTarget() {
    ID3D11Texture2D* pBackBuffer;
    g_pSwapChain->GetBuffer(0, IID_PPV_ARGS(&pBackBuffer));
    g_pd3dDevice->CreateRenderTargetView(pBackBuffer, NULL, &g_mainRenderTargetView);
    pBackBuffer->Release();
}
static void CleanupRenderTarget() {
    if (g_mainRenderTargetView) { g_mainRenderTargetView->Release(); g_mainRenderTargetView = NULL; }
}
static bool CreateDeviceD3D(HWND hWnd) {
    DXGI_SWAP_CHAIN_DESC sd;
    ZeroMemory(&sd, sizeof(sd));
    sd.BufferCount = 2;
    sd.BufferDesc.Width = 0;
    sd.BufferDesc.Height = 0;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferDesc.RefreshRate.Numerator = 60;
    sd.BufferDesc.RefreshRate.Denominator = 1;
    sd.Flags = DXGI_SWAP_CHAIN_FLAG_ALLOW_MODE_SWITCH;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hWnd;
    sd.SampleDesc.Count = 1;
    sd.SampleDesc.Quality = 0;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    UINT createDeviceFlags = 0;
    D3D_FEATURE_LEVEL featureLevel;
    const D3D_FEATURE_LEVEL featureLevelArray[2] = { D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_0 };
    HRESULT res = D3D11CreateDeviceAndSwapChain(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, createDeviceFlags,
        featureLevelArray, 2, D3D11_SDK_VERSION, &sd, &g_pSwapChain, &g_pd3dDevice, &featureLevel, &g_pd3dDeviceContext);
    if (res == DXGI_ERROR_UNSUPPORTED)
        res = D3D11CreateDeviceAndSwapChain(NULL, D3D_DRIVER_TYPE_WARP, NULL, createDeviceFlags,
            featureLevelArray, 2, D3D11_SDK_VERSION, &sd, &g_pSwapChain, &g_pd3dDevice, &featureLevel, &g_pd3dDeviceContext);
    if (res != S_OK) return false;
    CreateRenderTarget();
    return true;
}
static void CleanupDeviceD3D() {
    CleanupRenderTarget();
    if (g_pSwapChain) { g_pSwapChain->Release(); g_pSwapChain = NULL; }
    if (g_pd3dDeviceContext) { g_pd3dDeviceContext->Release(); g_pd3dDeviceContext = NULL; }
    if (g_pd3dDevice) { g_pd3dDevice->Release(); g_pd3dDevice = NULL; }
}

// ---------------------------------------------------------------- app state

struct ObfApp {
    char in_path[1024];
    char out_path[1024];
    bool do_rename;
    bool do_strings;
    bool rename_main;
    bool aggressive;
    bool do_flow;
    bool do_flatten;
    bool do_vmp;
    bool use_embedded;
    bool running;
    bool finished;
    int exit_code;
    HANDLE proc;
    HANDLE rd;
    // embedded-mode worker state
    HANDLE emb_thread;
    volatile bool emb_done;
    int emb_exit;
    std::string emb_log;
    std::string log;
    char status[128];
    bool auto_scroll;
    bool banner_done;

    ObfApp() : do_rename(true), do_strings(true), rename_main(false),
               aggressive(false), do_flow(false), do_flatten(false),
               do_vmp(false), use_embedded(false), running(false),
               finished(false), exit_code(-1), proc(NULL), rd(NULL),
               emb_thread(NULL), emb_done(true), emb_exit(-1),
               auto_scroll(true), banner_done(false) {
        in_path[0] = 0;
        out_path[0] = 0;
        status[0] = 0;
        snprintf(status, sizeof(status), "idle");
    }
};

static ObfApp g_app;

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

static void AppendLog(const char* data, size_t len) {
    g_app.log.append(data, len);
    if (g_app.log.size() > 512 * 1024)
        g_app.log.erase(0, g_app.log.size() / 2);
}

static void LogLine(const std::string& s) {
    AppendLog(s.c_str(), s.size());
    if (s.empty() || s[s.size() - 1] != '\n') AppendLog("\n", 1);
}

static void SetStatus(const char* s) {
    snprintf(g_app.status, sizeof(g_app.status), "%s", s);
}

static std::string DetectScript() {
    wchar_t mod[MAX_PATH];
    GetModuleFileNameW(NULL, mod, MAX_PATH);
    std::wstring exe(mod);
    size_t p = exe.find_last_of(L"\\/");
    std::wstring dir = (p == std::wstring::npos) ? L"" : exe.substr(0, p);
    const char* rel[] = { "\\obf.py", "\\..\\obf.py", "\\..\\..\\obf.py" };
    for (int i = 0; i < 3; i++) {
        std::wstring full = dir + Utf8ToWide(rel[i]);
        DWORD a = GetFileAttributesW(full.c_str());
        if (a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY))
            return WideToUtf8(full.c_str());
    }
    DWORD a = GetFileAttributesW(L"obf.py");
    if (a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY))
        return "obf.py";
    return "";
}

static std::string DetectPython() {
    const char* env = getenv("JAROBF_PYTHON");
    if (env && *env) return env;
    return "python";
}

static void DeriveOutput() {
    std::string in = g_app.in_path;
    std::string out = in;
    if (out.size() > 4) {
        std::string tail = out.substr(out.size() - 4);
        for (size_t i = 0; i < tail.size(); i++)
            tail[i] = (char)tolower((unsigned char)tail[i]);
        if (tail == ".jar") out = out.substr(0, out.size() - 4);
    }
    out += "_obf.jar";
    snprintf(g_app.out_path, sizeof(g_app.out_path), "%s", out.c_str());
}

static std::string BrowseDialog(bool save) {
    wchar_t file[1024];
    file[0] = 0;
    if (g_app.in_path[0]) {
        std::wstring w = Utf8ToWide(g_app.in_path);
        wcsncpy(file, w.c_str(), 1023);
        file[1023] = 0;
    }
    const wchar_t* filter =
        L"Jar files (*.jar)\0*.jar\0All files (*.*)\0*.*\0\0";
    OPENFILENAMEW of;
    ZeroMemory(&of, sizeof(of));
    of.lStructSize = sizeof(of);
    of.lpstrFilter = filter;
    of.lpstrFile = file;
    of.nMaxFile = 1024;
    of.Flags = OFN_OVERWRITEPROMPT | OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR;
    of.lpstrDefExt = L"jar";
    BOOL ok;
    if (save) {
        of.Flags = OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR;
        ok = GetSaveFileNameW(&of);
    } else {
        ok = GetOpenFileNameW(&of);
    }
    if (!ok) return std::string();
    return WideToUtf8(file);
}

static void StopProcess() {
    if (g_app.proc) {
        TerminateProcess(g_app.proc, 1);
        CloseHandle(g_app.proc);
        g_app.proc = NULL;
    }
    if (g_app.rd) {
        CloseHandle(g_app.rd);
        g_app.rd = NULL;
    }
    if (g_app.emb_thread) {
        // Embedded python cannot be force-terminated safely; just abandon.
        LogLine("[warn] embedded python thread still running; ignoring cancel");
        CloseHandle(g_app.emb_thread);
        g_app.emb_thread = NULL;
        g_app.emb_done = true;
    }
    g_app.running = false;
}

// ---- embedded-python worker ----
static DWORD WINAPI EmbeddedWorker(LPVOID) {
    std::string log;
    int rc = pyembed::run_obf(
        g_app.in_path, g_app.out_path,
        g_app.do_rename, g_app.do_strings, g_app.rename_main,
        g_app.aggressive, g_app.do_flow, g_app.do_flatten, g_app.do_vmp,
        &log);
    g_app.emb_log = log;
    g_app.emb_exit = rc;
    g_app.emb_done = true;
    return 0;
}

static void PumpEmbedded() {
    if (!g_app.running || !g_app.emb_thread) return;
    if (!g_app.emb_done) return;
    WaitForSingleObject(g_app.emb_thread, 0);
    CloseHandle(g_app.emb_thread);
    g_app.emb_thread = NULL;
    if (!g_app.emb_log.empty())
        AppendLog(g_app.emb_log.c_str(), (DWORD)g_app.emb_log.size());
    char msg[80];
    snprintf(msg, sizeof(msg), "[exit code %d]\n", g_app.emb_exit);
    AppendLog(msg, (DWORD)strlen(msg));
    g_app.running = false;
    g_app.finished = true;
    g_app.exit_code = g_app.emb_exit;
    if (g_app.emb_exit == 0) SetStatus("done - output written");
    else SetStatus("failed - see log");
}

static void StartObf() {
    if (g_app.running) return;
    if (!g_app.in_path[0]) {
        SetStatus("select an input jar first");
        return;
    }
    if (!g_app.out_path[0])
        DeriveOutput();
    if (strcmp(g_app.in_path, g_app.out_path) == 0) {
        SetStatus("output must differ from input");
        return;
    }

    g_app.running = true;
    g_app.finished = false;
    g_app.exit_code = -1;
    SetStatus("running...");

    if (g_app.use_embedded) {
        if (!pyembed::is_available() && !pyembed::init()) {
            LogLine("error: embedded Python unavailable (python313.dll not found)");
            LogLine("hint: set JAROBF_PYTHON_HOME or use subprocess mode");
            g_app.running = false;
            SetStatus("embedded python unavailable");
            return;
        }
        LogLine("[embedded] running jarobf in-process");
        g_app.emb_done = false;
        g_app.emb_exit = -1;
        g_app.emb_log.clear();
        g_app.emb_thread = CreateThread(NULL, 0, EmbeddedWorker, NULL, 0, NULL);
        if (!g_app.emb_thread) {
            LogLine("error: CreateThread failed");
            g_app.running = false;
            SetStatus("thread create failed");
            return;
        }
        return;
    }

    // -------- subprocess mode --------
    std::string script = DetectScript();
    if (script.empty()) {
        LogLine("error: obf.py not found next to the executable");
        SetStatus("obf.py not found");
        return;
    }
    std::string py = DetectPython();

    std::string cmd = "\"" + py + "\" -X utf8 \"" + script + "\" \"" + g_app.in_path +
                      "\" -o \"" + g_app.out_path + "\"";
    if (!g_app.do_rename) cmd += " --no-rename";
    if (!g_app.do_strings) cmd += " --no-strings";
    if (g_app.rename_main) cmd += " --rename-main";
    if (g_app.aggressive) cmd += " --aggressive";
    if (g_app.do_flow) cmd += " --flow";
    if (g_app.do_flatten) cmd += " --flatten";
    if (g_app.do_vmp) cmd += " --vmp";

    LogLine("$ " + cmd);

    SECURITY_ATTRIBUTES sa;
    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    HANDLE rd = NULL, wr = NULL;
    if (!CreatePipe(&rd, &wr, &sa, 0)) {
        LogLine("error: CreatePipe failed");
        SetStatus("pipe error");
        return;
    }
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);

    std::wstring wcmd = Utf8ToWide(cmd.c_str());
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = wr;
    si.hStdError = wr;
    si.hStdInput = NULL;
    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));
    BOOL ok = CreateProcessW(NULL, &wcmd[0], NULL, NULL, TRUE, CREATE_NO_WINDOW,
                             NULL, NULL, &si, &pi);
    CloseHandle(wr);
    if (!ok) {
        CloseHandle(rd);
        LogLine("error: failed to start process");
        SetStatus("start failed");
        return;
    }
    CloseHandle(pi.hThread);
    g_app.proc = pi.hProcess;
    g_app.rd = rd;
    g_app.running = true;
    g_app.finished = false;
    g_app.exit_code = -1;
    SetStatus("running...");
}

static void PumpProcess() {
    if (!g_app.running || !g_app.rd) return;
    char buf[4096];
    DWORD avail = 0, got = 0;
    while (PeekNamedPipe(g_app.rd, NULL, 0, NULL, &avail, NULL) && avail > 0) {
        DWORD want = avail < sizeof(buf) ? avail : (DWORD)sizeof(buf);
        if (!ReadFile(g_app.rd, buf, want, &got, NULL) || got == 0) break;
        AppendLog(buf, got);
    }
    DWORD code = 0;
    if (GetExitCodeProcess(g_app.proc, &code) && code != STILL_ACTIVE) {
        while (PeekNamedPipe(g_app.rd, NULL, 0, NULL, &avail, NULL) && avail > 0) {
            DWORD want = avail < sizeof(buf) ? avail : (DWORD)sizeof(buf);
            if (!ReadFile(g_app.rd, buf, want, &got, NULL) || got == 0) break;
            AppendLog(buf, got);
        }
        char msg[80];
        snprintf(msg, sizeof(msg), "[exit code %u]\n", (unsigned)code);
        AppendLog(msg, strlen(msg));
        CloseHandle(g_app.proc);
        CloseHandle(g_app.rd);
        g_app.proc = NULL;
        g_app.rd = NULL;
        g_app.running = false;
        g_app.finished = true;
        g_app.exit_code = (int)code;
        if (code == 0) SetStatus("done - output written");
        else SetStatus("failed - see log");
    }
}

// ------------------------------------------------------------------ UI

static void DrawUI() {
    ImGui::SetNextWindowPos(ImVec2(0, 0), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(920, 640), ImGuiCond_FirstUseEver);
    ImGui::Begin("JarObf - JVM obfuscator");

    ImGui::AlignTextToFramePadding();
    ImGui::Text("Input jar");
    ImGui::SameLine(90);
    ImGui::SetNextItemWidth(-110);
    ImGui::InputText("##in", g_app.in_path, sizeof(g_app.in_path));
    ImGui::SameLine();
    if (ImGui::Button("Browse...")) {
        std::string p = BrowseDialog(false);
        if (!p.empty()) {
            snprintf(g_app.in_path, sizeof(g_app.in_path), "%s", p.c_str());
            if (!g_app.out_path[0] || g_app.finished) DeriveOutput();
        }
    }

    ImGui::AlignTextToFramePadding();
    ImGui::Text("Output jar");
    ImGui::SameLine(90);
    ImGui::SetNextItemWidth(-110);
    ImGui::InputText("##out", g_app.out_path, sizeof(g_app.out_path));
    ImGui::SameLine();
    if (ImGui::Button("Browse...##out")) {
        std::string p = BrowseDialog(true);
        if (!p.empty())
            snprintf(g_app.out_path, sizeof(g_app.out_path), "%s", p.c_str());
    }

    ImGui::Separator();
    ImGui::Checkbox("Rename classes/methods/fields", &g_app.do_rename);
    ImGui::SameLine();
    ImGui::Checkbox("Encrypt strings", &g_app.do_strings);
    ImGui::SameLine();
    ImGui::Checkbox("Rename main class", &g_app.rename_main);
    ImGui::SameLine();
    ImGui::Checkbox("Aggressive", &g_app.aggressive);

    ImGui::Checkbox("Opaque branches (flow)", &g_app.do_flow);
    ImGui::SameLine();
    ImGui::Checkbox("Flatten blocks", &g_app.do_flatten);
    ImGui::SameLine();
    ImGui::Checkbox("Virtualize (VMP)", &g_app.do_vmp);
    ImGui::SameLine();
    ImGui::Checkbox("Embedded Python", &g_app.use_embedded);
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Run jarobf in-process via embedded CPython.\n"
                          "Faster startup, no subprocess. Requires python313.dll.");

    bool can_run = !g_app.running && g_app.in_path[0];
    if (!can_run) ImGui::BeginDisabled();
    if (ImGui::Button("Run obfuscation", ImVec2(160, 0)))
        StartObf();
    if (!can_run) ImGui::EndDisabled();

    ImGui::SameLine();
    if (g_app.running) {
        if (ImGui::Button("Cancel")) {
            StopProcess();
            LogLine("[cancelled]");
            SetStatus("cancelled");
        }
    } else if (g_app.finished) {
        ImGui::TextColored(g_app.exit_code == 0 ? ImVec4(0.4f, 1.0f, 0.5f, 1.0f)
                                                : ImVec4(1.0f, 0.45f, 0.4f, 1.0f),
                           "exit code %d", g_app.exit_code);
        if (g_app.exit_code == 0) {
            ImGui::SameLine();
            if (ImGui::Button("Open output folder")) {
                std::wstring w = Utf8ToWide(g_app.out_path);
                size_t p = w.find_last_of(L"\\/");
                std::wstring dir = (p == std::wstring::npos) ? L"." : w.substr(0, p);
                ShellExecuteW(NULL, L"open", dir.c_str(), NULL, NULL, SW_SHOWNORMAL);
            }
        }
    } else {
        ImGui::TextUnformatted(g_app.status);
    }

    ImGui::SameLine();
    ImGui::Checkbox("Autoscroll", &g_app.auto_scroll);

    ImGui::TextDisabled("or drop a .jar onto this window   |   engine: %s",
                        DetectPython().c_str());
    ImGui::Separator();

    ImGui::BeginChild("log", ImVec2(0, 0), true);
    const char* begin = g_app.log.c_str();
    const char* p = begin;
    const char* end = begin + g_app.log.size();
    while (p <= end) {
        const char* nl = (const char*)memchr(p, '\n', (size_t)(end - p));
        if (nl) {
            ImGui::TextUnformatted(p, nl);
            p = nl + 1;
        } else {
            if (end > p) ImGui::TextUnformatted(p, end);
            break;
        }
    }
    if (g_app.auto_scroll && ImGui::GetScrollY() >= ImGui::GetScrollMaxY() - 4.0f)
        ImGui::SetScrollHereY(1.0f);
    ImGui::EndChild();

    ImGui::End();
}

// ----------------------------------------------------------------- window

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam);

static LRESULT WINAPI WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (ImGui_ImplWin32_WndProcHandler(hWnd, msg, wParam, lParam)) return true;
    switch (msg) {
    case WM_SIZE:
        if (g_pd3dDevice != NULL && wParam != SIZE_MINIMIZED) {
            CleanupRenderTarget();
            g_pSwapChain->ResizeBuffers(0, (UINT)LOWORD(lParam), (UINT)HIWORD(lParam), DXGI_FORMAT_UNKNOWN, 0);
            CreateRenderTarget();
        }
        return 0;
    case WM_SYSCOMMAND:
        if ((wParam & 0xfff0) == SC_KEYMENU) return 0;
        break;
    case WM_DROPFILES: {
        HDROP h = (HDROP)wParam;
        wchar_t path[MAX_PATH];
        if (DragQueryFileW(h, 0, path, MAX_PATH)) {
            std::string p = WideToUtf8(path);
            snprintf(g_app.in_path, sizeof(g_app.in_path), "%s", p.c_str());
            DeriveOutput();
            snprintf(g_app.status, sizeof(g_app.status), "dropped: %s",
                     p.c_str() + (p.size() > 30 ? p.size() - 30 : 0));
        }
        DragFinish(h);
        return 0;
    }
    case WM_DESTROY:
        StopProcess();
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProc(hWnd, msg, wParam, lParam);
}

int main(int, char**) {
    WNDCLASSEX wc = { sizeof(wc), CS_CLASSDC, WndProc, 0L, 0L, GetModuleHandle(NULL), NULL, NULL, NULL, NULL, _T("JarObf"), NULL };
    RegisterClassEx(&wc);
    HWND hwnd = CreateWindow(wc.lpszClassName, _T("JarObf"), WS_OVERLAPPEDWINDOW,
                             100, 100, 960, 680, NULL, NULL, wc.hInstance, NULL);
    DragAcceptFiles(hwnd, TRUE);
    if (!CreateDeviceD3D(hwnd)) { CleanupDeviceD3D(); UnregisterClass(wc.lpszClassName, wc.hInstance); return 1; }
    ShowWindow(hwnd, SW_SHOWDEFAULT);
    UpdateWindow(hwnd);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui::StyleColorsDark();
    const char* fonts[] = { "C:\\Windows\\Fonts\\msyh.ttc",
                            "C:\\Windows\\Fonts\\simhei.ttf",
                            "C:\\Windows\\Fonts\\simsun.ttc" };
    for (int i = 0; i < 3; i++) {
        FILE* f = fopen(fonts[i], "rb");
        if (!f) continue;
        fclose(f);
        if (io.Fonts->AddFontFromFileTTF(fonts[i], 18.0f, NULL,
                                         io.Fonts->GetGlyphRangesChineseFull()))
            break;
    }
    ImGui_ImplWin32_Init(hwnd);
    ImGui_ImplDX11_Init(g_pd3dDevice, g_pd3dDeviceContext);

    bool done = false;
    while (!done) {
        MSG msg;
        while (PeekMessage(&msg, NULL, 0U, 0U, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessage(&msg);
            if (msg.message == WM_QUIT) done = true;
        }
        if (done) break;

        PumpProcess();
        PumpEmbedded();
        if (!g_app.banner_done) {
            g_app.banner_done = true;
            std::string sc = DetectScript();
            LogLine("JarObf GUI");
            if (sc.empty()) LogLine("warning: obf.py not found next to executable");
            else LogLine("script: " + sc);
            LogLine("python: " + DetectPython());
            LogLine("drop a jar or browse, set options, press Run.");
        }

        ImGui_ImplDX11_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();

        DrawUI();

        ImGui::Render();
        const float clear_color[4] = { 0.10f, 0.11f, 0.13f, 1.00f };
        g_pd3dDeviceContext->OMSetRenderTargets(1, &g_mainRenderTargetView, NULL);
        g_pd3dDeviceContext->ClearRenderTargetView(g_mainRenderTargetView, clear_color);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
        g_pSwapChain->Present(1, 0);
    }

    StopProcess();
    ImGui_ImplDX11_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();
    CleanupDeviceD3D();
    DestroyWindow(hwnd);
    UnregisterClass(wc.lpszClassName, wc.hInstance);
    return 0;
}
