#!/usr/bin/env python3
"""
gfn_steam_input_fix.py — Fix des permissions Steam Input pour GeForce NOW.

Permet l'utilisation de périphériques non supportés nativement par GFN
(ex: Yoke Turtle Beach) via la traduction Steam Input → XInput.

Fonctionnalités :
- Auto-détection du Flatpak GFN installé
- Application des permissions udev
- GUI (kdialog) avec fallback terminal
- Rappel des étapes manuelles restantes

Prérequis : gfn_common.py dans le même dossier.
"""

import subprocess
import sys

from gfn_common import (
    detect_gfn_backend,
    gui_info,
    gui_error,
    gui_yesno,
)


def apply_udev_permission(flatpak_id):
    """Applique la permission udev au Flatpak GFN."""
    try:
        subprocess.run(
            ["flatpak", "override", "--user", "--filesystem=/run/udev:ro", flatpak_id],
            check=True,
            capture_output=True,
        )
        return True
    except Exception as e:
        return False


def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║  GeForce NOW — Fix Steam Input / Yoke           ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # Détection du backend
    flatpak_id, _, backend_name = detect_gfn_backend()
    if not flatpak_id:
        gui_error("Backend introuvable",
                  "Aucune application GeForce NOW détectée.\n"
                  "Installez le client officiel NVIDIA ou gfn-electron via Flatpak.")
        sys.exit(1)

    print(f"[✓] Backend détecté : {backend_name}")
    print(f"    Flatpak : {flatpak_id}\n")

    # Confirmation
    if not gui_yesno(
        "Appliquer le fix Steam Input ?",
        f"Ce script va accorder les permissions d'accès aux périphériques\n"
        f"(udev) au Flatpak '{flatpak_id}'.\n\n"
        f"Cela permet à Steam Input de traduire les entrées de\n"
        f"périphériques spéciaux (Yoke, HOTAS, volants...)\n"
        f"en manette Xbox standard pour GeForce NOW.\n\n"
        f"Appliquer ?",
    ):
        print("[!] Opération annulée.")
        sys.exit(0)

    # Application
    print("[*] Application des permissions udev...")
    if apply_udev_permission(flatpak_id):
        print("[✓] Permissions appliquées avec succès !\n")

        next_steps = (
            "Permissions appliquées avec succès !\n\n"
            "Étapes restantes (dans Steam, Gaming Mode) :\n\n"
            "1. Sélectionnez un jeu GFN dans votre bibliothèque\n"
            "2. Cliquez sur l'icône Manette (à côté du bouton Jouer)\n"
            "3. Appliquez le modèle \"Manette classique\" (Gamepad)\n"
            "4. Mappez les axes de votre Yoke / HOTAS sur les\n"
            "   sticks et boutons virtuels\n\n"
            "Steam traduira vos entrées en XInput pour GFN."
        )
        gui_info("Fix appliqué", next_steps)
        print(next_steps)
    else:
        error_msg = (
            f"Impossible d'appliquer les permissions.\n\n"
            f"Essayez manuellement dans un terminal :\n"
            f"flatpak override --user --filesystem=/run/udev:ro {flatpak_id}"
        )
        gui_error("Erreur", error_msg)
        print(f"[✗] {error_msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
