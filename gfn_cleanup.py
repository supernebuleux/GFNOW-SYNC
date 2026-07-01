#!/usr/bin/env python3
"""
gfn_cleanup.py — Nettoyage des raccourcis GeForce NOW dans Steam.

Fonctionnalités :
- Identifie tous les raccourcis tagués "GeForce NOW" dans shortcuts.vdf
- Sélection interactive (individuel ou bulk) via kdialog ou terminal
- Supprime les raccourcis sélectionnés
- Supprime les artworks associés dans le dossier grid/
- Sauvegarde automatique avant modification

Prérequis : gfn_common.py dans le même dossier.
"""

import os
import sys

from gfn_common import (
    get_steam_user_dirs,
    get_grid_dir,
    parse_binary_vdf,
    write_binary_vdf,
    backup_file,
    gui_info,
    gui_error,
    gui_yesno,
    gui_checklist_cleanup,
    is_steam_running,
    restart_steam,
)


def find_gfn_shortcuts(shortcuts):
    """
    Trouve tous les raccourcis JEUX avec le tag "GeForce NOW".
    Exclut le lanceur GFN lui-même (pas de cmsId / --direct-start).
    Retourne une liste de (index_key, app_name, appid).
    """
    gfn_shortcuts = []
    for idx, shortcut in shortcuts.items():
        tags = shortcut.get("tags", {})
        is_gfn = False
        if isinstance(tags, dict):
            for _, tag_val in tags.items():
                if isinstance(tag_val, str) and tag_val.lower() == "geforce now":
                    is_gfn = True
                    break
        # Fallback : vérifier les LaunchOptions
        launch_opts = shortcut.get("LaunchOptions", "")
        if not is_gfn:
            if "--direct-start" in launch_opts and "flatpak" in shortcut.get("exe", ""):
                is_gfn = True

        if is_gfn:
            # Protéger le lanceur GFN lui-même (pas de cmsId = c'est l'app, pas un jeu)
            has_game_id = "cmsId=" in launch_opts or "--direct-start" in launch_opts
            if not has_game_id:
                continue
            app_name = shortcut.get("AppName", f"Inconnu ({idx})")
            appid = shortcut.get("appid", 0)
            gfn_shortcuts.append((idx, app_name, appid))

    return gfn_shortcuts


def delete_artworks(grid_dir, appid):
    """Supprime les fichiers d'artwork associés à un appid."""
    if not appid or appid == 0:
        return 0
    appid_unsigned = appid & 0xFFFFFFFF
    patterns = [
        f"{appid_unsigned}.png",
        f"{appid_unsigned}.jpg",
        f"{appid_unsigned}.webp",
        f"{appid_unsigned}_hero.png",
        f"{appid_unsigned}_hero.jpg",
        f"{appid_unsigned}_hero.webp",
        f"{appid_unsigned}_logo.png",
        f"{appid_unsigned}_logo.jpg",
        f"{appid_unsigned}_logo.webp",
        f"{appid_unsigned}_icon.png",
        f"{appid_unsigned}_icon.jpg",
        f"{appid_unsigned}_icon.webp",
        f"{appid_unsigned}p.png",
        f"{appid_unsigned}p.jpg",
        f"{appid_unsigned}p.webp",
    ]
    deleted = 0
    for pattern in patterns:
        filepath = os.path.join(grid_dir, pattern)
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted += 1
    return deleted


def process_user_dir(user_dir):
    """Traite un dossier utilisateur Steam."""
    shortcuts_file = os.path.join(user_dir, "config", "shortcuts.vdf")
    if not os.path.exists(shortcuts_file):
        print(f"  [!] Aucun shortcuts.vdf dans {user_dir}")
        return 0

    # Lire le fichier
    with open(shortcuts_file, "rb") as f:
        data = f.read()

    vdf = parse_binary_vdf(data)
    if not vdf or "shortcuts" not in vdf:
        print(f"  [!] Fichier shortcuts.vdf vide ou invalide")
        return 0

    shortcuts = vdf["shortcuts"]

    # Trouver les raccourcis GFN
    gfn_list = find_gfn_shortcuts(shortcuts)
    if not gfn_list:
        print(f"  [✓] Aucun raccourci GeForce NOW trouvé.")
        return 0

    print(f"  [*] {len(gfn_list)} raccourci(s) GeForce NOW trouvé(s).\n")

    # Sélection interactive
    checklist_items = [(idx, name) for idx, name, _ in gfn_list]
    selected_keys = gui_checklist_cleanup(checklist_items)

    if not selected_keys:
        print("  [!] Aucun raccourci sélectionné. Annulé.")
        return 0

    # Confirmation
    if not gui_yesno("Confirmation",
                     f"Supprimer {len(selected_keys)} raccourci(s) GeForce NOW ?\n"
                     "Les artworks associés seront aussi supprimés."):
        print("  [!] Opération annulée.")
        return 0

    # Backup
    backup_path = backup_file(shortcuts_file)
    print(f"  [*] Sauvegarde : {backup_path}")

    # Suppression des raccourcis
    grid_dir = get_grid_dir(user_dir)
    deleted_count = 0
    art_deleted = 0

    for idx_key in selected_keys:
        if idx_key in shortcuts:
            app_name = shortcuts[idx_key].get("AppName", "?")
            appid = shortcuts[idx_key].get("appid", 0)

            # Supprimer les artworks
            art_count = delete_artworks(grid_dir, appid)
            art_deleted += art_count

            # Supprimer le raccourci
            del shortcuts[idx_key]
            print(f"  [-] Supprimé : {app_name} (+ {art_count} artwork(s))")
            deleted_count += 1

    # Renuméroter les clés pour garder un index continu
    new_shortcuts = {}
    for new_idx, (_, shortcut) in enumerate(sorted(shortcuts.items(), key=lambda x: x[0])):
        new_shortcuts[str(new_idx)] = shortcut
    vdf["shortcuts"] = new_shortcuts

    # Écrire
    binary_data = write_binary_vdf(vdf)
    with open(shortcuts_file, "wb") as f:
        f.write(binary_data)

    print(f"\n  [✓] {deleted_count} raccourci(s) supprimé(s), {art_deleted} artwork(s) nettoyé(s).")
    return deleted_count


def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║  GeForce NOW — Nettoyage des Raccourcis          ║")
    print("╚══════════════════════════════════════════════════╝\n")

    user_dirs = get_steam_user_dirs()
    if not user_dirs:
        gui_error("Steam introuvable", "Aucun profil utilisateur Steam trouvé.")
        sys.exit(1)

    total_deleted = 0
    for user_dir in user_dirs:
        profile_id = os.path.basename(user_dir)
        print(f"[*] Profil Steam : {profile_id}")
        total_deleted += process_user_dir(user_dir)
        print()

    if total_deleted > 0:
        # Redémarrage de Steam
        if is_steam_running():
            if gui_yesno("Redémarrer Steam ?",
                         "Redémarrer Steam pour appliquer les suppressions ?"):
                print("[*] Redémarrage de Steam...")
                if restart_steam():
                    print("[✓] Steam redémarré.")
                else:
                    print("[!] Échec. Relancez Steam manuellement.")
        else:
            print("[!] Pensez à relancer Steam pour appliquer les changements.")

        gui_info("Nettoyage terminé",
                 f"{total_deleted} raccourci(s) GeForce NOW supprimé(s).")
    else:
        gui_info("Nettoyage terminé",
                 "Aucun raccourci supprimé.")

    print("\n[✓] Terminé.")


if __name__ == "__main__":
    main()
