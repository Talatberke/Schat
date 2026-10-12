@echo off
rem ============================================================
rem  SecretChat - SecretChat.exe derleme scripti (Windows)
rem  Kullanim: build_exe.bat  (once requirements.txt kurulu olmali)
rem ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] PyInstaller kontrol ediliyor...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo      PyInstaller kurulu degil, kuruluyor...
    python -m pip install pyinstaller || goto :error
)

echo [2/3] Temizlik...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist SecretChat.spec del /q SecretChat.spec

echo [3/3] Tek dosyalik exe uretiliyor...
python -m PyInstaller ^
    --name SecretChat ^
    --onefile ^
    --windowed ^
    --clean ^
    --noconfirm ^
    main.py

if errorlevel 1 goto :error

echo.
echo  BASARILI: dist\SecretChat.exe
echo  Cift tiklayarak calistirabilirsin.
goto :eof

:error
echo  HATA: Derleme basarisiz. Cikti yukarida.
exit /b 1
