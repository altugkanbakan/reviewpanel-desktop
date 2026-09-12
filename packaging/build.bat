@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Review Panel -- PyInstaller Build (Windows)
echo ============================================================
echo.

:: Install/update dependencies (requirements.txt lives at the repo root)
pip install -r ..\requirements.txt

:: Download the llmfit hardware-check binary if missing (kept next to the
:: spec; gitignored). Mirrors build_mac.sh / build_linux.sh.
if not exist llmfit.exe (
    echo Downloading llmfit ^(windows^)...
    curl -L "https://github.com/AlexsJones/llmfit/releases/download/v0.8.0/llmfit-v0.8.0-x86_64-pc-windows-msvc.zip" -o llmfit_tmp.zip
    tar -xf llmfit_tmp.zip
    if exist llmfit-v0.8.0-x86_64-pc-windows-msvc\llmfit.exe move /Y llmfit-v0.8.0-x86_64-pc-windows-msvc\llmfit.exe llmfit.exe >nul
    if exist llmfit-v0.8.0-x86_64-pc-windows-msvc rmdir /S /Q llmfit-v0.8.0-x86_64-pc-windows-msvc
    del /Q llmfit_tmp.zip
)
if not exist llmfit.exe (
    echo [ERROR] llmfit.exe missing -- download it manually and place it
    echo         next to ReviewPanel.spec. See README ^(llmfit section^).
    pause
    exit /b 1
)

echo.
echo Building executable...
echo.

python -m PyInstaller ReviewPanel.spec --noconfirm

echo.
if exist dist\ReviewPanel.exe (
    echo ============================================================
    echo  SUCCESS: dist\ReviewPanel.exe is ready
    echo  You can now run Inno Setup with installer.iss to build
    echo  a proper Windows installer.
    echo ============================================================
) else (
    echo [ERROR] Build failed. Check output above.
)
echo.
pause
