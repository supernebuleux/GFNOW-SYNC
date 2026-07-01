#!/bin/bash
# ═══════════════════════════════════════════════
#  GFN Sync — Launcher Menu
# ═══════════════════════════════════════════════
# This script provides a menu to run the different
# GFN Sync tools. Called by the .desktop entry.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# ── Check Python 3 ──
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 is required but not found."
    echo "   On SteamOS, it should be pre-installed."
    exit 1
fi

# ── Check GeForce NOW Flatpak ──
GFN_INSTALLED=false
for app_id in com.nvidia.geforcenow com.github.hmlendea.gfn-electron com.github.hmlendea.geforcenow-electron; do
    if flatpak info "$app_id" &>/dev/null; then
        GFN_INSTALLED=true
        break
    fi
done

if [ "$GFN_INSTALLED" = false ]; then
    echo "⚠️  No GeForce NOW client detected."
    echo "   Install it via Flatpak before using GFN Sync."
    echo ""
fi

# ── Menu ──
if command -v kdialog &>/dev/null; then
    # KDE dialog menu
    CHOICE=$(kdialog --title "GFN Sync" --menu "Choose an action:" \
        1 "🔄 Sync Library — Add GFN games to Steam" \
        2 "🧹 Cleanup — Remove GFN shortcuts from Steam" \
        3 "🎮 Fix Steam Input — (coming soon)" \
        4 "❌ Quit" 2>/dev/null)

    case "$CHOICE" in
        1) python3 "$SCRIPT_DIR/gfn_sync_library.py" ;;
        2) python3 "$SCRIPT_DIR/gfn_cleanup.py" ;;
        3) kdialog --title "GFN Sync" --sorry "Steam Input fix is not available yet.\nThis feature is coming in a future update." 2>/dev/null ;;
        *) exit 0 ;;
    esac
else
    # Terminal fallback
    echo ""
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║          GFN Sync — Menu             ║"
    echo "  ╚══════════════════════════════════════╝"
    echo ""
    echo "  [1] 🔄 Sync Library — Add GFN games to Steam"
    echo "  [2] 🧹 Cleanup — Remove GFN shortcuts from Steam"
    echo "  [3] 🎮 Fix Steam Input — (coming soon)"
    echo "  [4] ❌ Quit"
    echo ""
    read -p "  Your choice [1-4]: " choice

    case "$choice" in
        1) python3 "$SCRIPT_DIR/gfn_sync_library.py" ;;
        2) python3 "$SCRIPT_DIR/gfn_cleanup.py" ;;
        3) echo "  ⚠️  Steam Input fix is not available yet. Coming in a future update." ;;
        *) echo "  Bye!"; exit 0 ;;
    esac
fi
