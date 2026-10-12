#!/usr/bin/env bash
# ============================================================
#  SecretChat — tek dosyalık çalıştırılabilir derleme (Linux/macOS)
#  Kullanım: ./build_exe.sh
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] PyInstaller kontrol ediliyor..."
if ! python -m pip show pyinstaller >/dev/null 2>&1; then
    echo "      PyInstaller kurulu değil, kuruluyor..."
    python -m pip install pyinstaller
fi

echo "[2/3] Temizlik..."
rm -rf build dist SecretChat.spec

echo "[3/3] Tek dosyalık çalıştırılabilir üretiliyor..."
python -m PyInstaller \
    --name SecretChat \
    --onefile \
    --windowed \
    --clean \
    --noconfirm \
    main.py

echo
echo " BAŞARILI: dist/SecretChat"
