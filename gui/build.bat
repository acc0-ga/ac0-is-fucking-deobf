@echo off
setlocal
set GXX=C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\g++.exe
cd /d "%~dp0"
for %%I in ("C:\Program Files (x86)\Dev-Cpp\MinGW64\x86_64-w64-mingw32\lib") do set LIB64=%%~sI
if not exist bin mkdir bin
"%GXX%" -std=c++11 -O2 -mwindows -I imgui -I imgui\backends -I src ^
  src\main.cpp src\pyembed.cpp ^
  imgui\imgui.cpp imgui\imgui_draw.cpp imgui\imgui_tables.cpp imgui\imgui_widgets.cpp ^
  imgui\backends\imgui_impl_win32.cpp imgui\backends\imgui_impl_dx11.cpp ^
  -o bin\jarobf-gui.exe ^
  -L. ^
  -L"%LIB64%" ^
  -ld3d11 -ld3dcompiler -ldxgi -lcomdlg32 -lshell32 -lgdi32 -limm32 -lole32 -luuid -ldwmapi ^
  -static-libgcc -static-libstdc++
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
echo BUILD OK: bin\jarobf-gui.exe
