@echo off
echo ============================================================
echo  Review Panel -- PyInstaller Build
echo ============================================================
echo.

:: Install/update dependencies
pip install -r requirements.txt

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
