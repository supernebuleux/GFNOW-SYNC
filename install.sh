#!/bin/bash
# ═══════════════════════════════════════════════
#  GFN Sync — Installer for SteamOS
# ═══════════════════════════════════════════════
# Installs GFN Sync to ~/gfn-sync/ and creates
# a menu shortcut in KDE.
#
# Usage:
#   git clone https://github.com/supernebuleux/GFNOW-SYNC.git
#   cd GFNOW-SYNC
#   bash install.sh
# ═══════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/gfn-sync"
DESKTOP_DIR="$HOME/.local/share/applications"

# ── Check: Linux / SteamOS ──
if [[ "$(uname)" != "Linux" ]]; then
    echo "❌ This installer is designed for SteamOS / Linux."
    exit 1
fi

# ── Check: required files present ──
REQUIRED_FILES=("gfn_common.py" "gfn_sync_library.py" "gfn_cleanup.py" "gfn_steam_input_fix.py" "gfn-sync.sh" "gfn-sync.desktop")
for f in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$SCRIPT_DIR/$f" ]]; then
        echo "❌ Missing file: $f"
        echo "   Make sure you run this script from the GFNOW-SYNC directory."
        exit 1
    fi
done

# ── Confirmation ──
if command -v kdialog &>/dev/null; then
    kdialog --title "GFN Sync — Install" \
        --yesno "Install GFN Sync?\n\nThis will:\n• Copy files to ~/gfn-sync/\n• Add a 'GFN Sync' shortcut to the app menu\n\nContinue?" 2>/dev/null || exit 0
else
    echo ""
    echo "  ╔═══════════════════════════════════╗"
    echo "  ║   GFN Sync — Installation         ║"
    echo "  ╚═══════════════════════════════════╝"
    echo ""
    echo "  This will:"
    echo "  • Copy files to ~/gfn-sync/"
    echo "  • Add a 'GFN Sync' shortcut to the app menu"
    echo ""
    read -p "  Install GFN Sync? (y/n): " reply
    [[ "$reply" =~ ^[yYoO] ]] || exit 0
fi

# ── Install files ──
echo "[*] Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/vdf"

if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
    # Copy Python scripts
    cp "$SCRIPT_DIR/gfn_common.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gfn_sync_library.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gfn_cleanup.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gfn_steam_input_fix.py" "$INSTALL_DIR/"

    # Copy VDF module
    cp "$SCRIPT_DIR/vdf/__init__.py" "$INSTALL_DIR/vdf/"
    cp "$SCRIPT_DIR/vdf/vdict.py" "$INSTALL_DIR/vdf/"

    # Copy launcher and desktop entry
    cp "$SCRIPT_DIR/gfn-sync.sh" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gfn-sync.desktop" "$INSTALL_DIR/"
else
    echo "  [~] Already in $INSTALL_DIR, skipping copy."
fi

# Make scripts executable
chmod +x "$INSTALL_DIR/gfn-sync.sh"
chmod +x "$INSTALL_DIR/"*.py 2>/dev/null || true

# ── Install desktop shortcut ──
echo "[*] Installing menu shortcut ..."
mkdir -p "$DESKTOP_DIR"
cp "$INSTALL_DIR/gfn-sync.desktop" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/gfn-sync.desktop"
# Refresh KDE menu cache
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# ── Success ──
echo ""
echo "  ✅ GFN Sync installed successfully!"
echo ""
echo "  📁 Files: $INSTALL_DIR/"
echo "  🖥️  Menu:  Search for 'GFN Sync' in your app launcher"
echo ""
echo "  ⚠️  Prerequisites:"
echo "     • GeForce NOW (NVIDIA Flatpak) must be installed"
echo "     • Open GFN, log in, browse your Library, then close it"
echo ""

if command -v kdialog &>/dev/null; then
    kdialog --title "GFN Sync — Installed!" \
        --msgbox "Installation complete!\n\n✅ Files: ~/gfn-sync/\n✅ Menu shortcut added\n\nSearch for 'GFN Sync' in your app menu.\n\n⚠️ Make sure GeForce NOW (Flatpak)\nis installed and configured." 2>/dev/null
fi

exit 0
