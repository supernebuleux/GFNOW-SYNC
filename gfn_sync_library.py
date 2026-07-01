#!/usr/bin/env python3
"""
gfn_sync_library.py — Synchronisation de la bibliothèque GeForce NOW vers Steam.

Fonctionnalités :
- Détection automatique du backend GFN (officiel NVIDIA / communautaire)
- Extraction des jeux depuis le cache GFN (CacheStorage + LevelDB)
- Wizard 2 étapes : sélection par store, puis par jeu
- Écriture des raccourcis dans shortcuts.vdf avec tag "GeForce NOW"
- Lancement direct des jeux via --url-route (client officiel)
- Récupération automatique des artworks depuis le cache GFN et le CDN NVIDIA
- Redémarrage automatique de Steam

Prérequis : gfn_common.py dans le même dossier.
"""

import os
import re
import subprocess
import sys
import time

from gfn_common import (
    detect_gfn_backend,
    extract_games,
    get_active_steam_user_dir,
    get_steam_user_dirs,
    get_grid_dir,
    parse_binary_vdf,
    write_binary_vdf,
    generate_shortcut_appid,
    backup_file,
    gui_info,
    gui_error,
    gui_yesno,
    gui_input,
    gui_checklist_stores,
    gui_checklist_games,
    is_steam_running,
    restart_steam,
    fetch_native_artworks,
    HAS_KDIALOG,
)


def group_games_by_store(games):
    """Groupe les jeux par store. Retourne { store: [(cms_id, title), ...] }."""
    by_store = {}
    for cms_id, info in games.items():
        store = info["store"]
        if store not in by_store:
            by_store[store] = []
        by_store[store].append((cms_id, info["title"]))
    return by_store


def _build_launch_options(cms_id, info, flatpak_id):
    """
    Construit la commande de lancement en fonction du format de données.
    Client officiel (CacheStorage) : --url-route avec cmsId/shortName/parentGameId
    Clients communautaires (LevelDB) : --direct-start avec cmsId
    """
    if "shortName" in info and "parentGameId" in info:
        # Client officiel NVIDIA — lancement via url-route
        url_route = (
            f"#?cmsId={cms_id}"
            f"&launchSource=External"
            f"&shortName={info['shortName']}"
            f"&parentGameId={info['parentGameId']}"
        )
        return (
            f"run --command=sh {flatpak_id} -c "
            f"\"/app/cef/GeForceNOW --url-route='{url_route}'\""
        )
    else:
        # Client communautaire — lancement direct
        return f"run {flatpak_id} --direct-start {cms_id}"


def _extract_cms_id_from_shortcut(launch_opts):
    """
    Extrait le cmsId depuis les LaunchOptions d'un raccourci existant.
    Supporte les deux formats (url-route et direct-start).
    """
    # Format url-route (client officiel)
    match = re.search(r"cmsId=(\d+)", launch_opts)
    if match:
        return match.group(1)
    # Format direct-start (client communautaire)
    match = re.search(r"--direct-start\s+(\S+)", launch_opts)
    if match:
        return match.group(1)
    return None


def write_shortcuts(user_dir, selected_games, all_games, flatpak_id):
    """
    Écrit les raccourcis dans shortcuts.vdf.
    Retourne le nombre de jeux ajoutés et la liste des (appname, appid) créés.
    """
    config_dir = os.path.join(user_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    shortcuts_file = os.path.join(config_dir, "shortcuts.vdf")

    # Créer le fichier s'il n'existe pas
    if not os.path.exists(shortcuts_file):
        empty_vdf = write_binary_vdf({"shortcuts": {}})
        with open(shortcuts_file, "wb") as f:
            f.write(empty_vdf)

    # Backup
    backup_path = backup_file(shortcuts_file)
    print(f"[*] Sauvegarde : {backup_path}")

    # Lire
    with open(shortcuts_file, "rb") as f:
        data = f.read()

    vdf = parse_binary_vdf(data)
    if not vdf or "shortcuts" not in vdf:
        vdf = {"shortcuts": {}}

    shortcuts = vdf["shortcuts"]

    # Trouver le prochain index
    existing_indices = [int(k) for k in shortcuts.keys() if k.isdigit()]
    next_idx = max(existing_indices) + 1 if existing_indices else 0

    # Index des raccourcis GFN existants par cmsId
    existing_gfn = {}
    for idx, shortcut in shortcuts.items():
        launch_opts = shortcut.get("LaunchOptions", "")
        cms_id_found = _extract_cms_id_from_shortcut(launch_opts)
        if cms_id_found:
            existing_gfn[cms_id_found] = idx

    added_count = 0
    created_entries = []  # (appname, index_key)
    appid_map = {}  # app_name -> appid (unsigned)

    for cms_id in selected_games:
        if cms_id not in all_games:
            continue
        info = all_games[cms_id]
        app_name = info["title"]
        exe = '"/usr/bin/flatpak"'
        launch_options = _build_launch_options(cms_id, info, flatpak_id)

        # Générer un AppID déterministe via CRC32
        appid = generate_shortcut_appid(exe, app_name)

        if cms_id in existing_gfn:
            # Mise à jour
            idx = existing_gfn[cms_id]
            shortcuts[idx]["AppName"] = app_name
            shortcuts[idx]["Exe"] = exe
            shortcuts[idx]["StartDir"] = '"/usr/bin"'
            shortcuts[idx]["LaunchOptions"] = launch_options
            shortcuts[idx]["tags"] = {"0": "GeForce NOW"}
            # Récupérer l'appid existant ou généré
            existing_appid = shortcuts[idx].get("appid", 0)
            if existing_appid and existing_appid != 0:
                appid_map[app_name] = existing_appid & 0xFFFFFFFF
            else:
                shortcuts[idx]["appid"] = appid
                appid_map[app_name] = appid
            print(f"  [~] Mis à jour : {app_name}")
            created_entries.append((app_name, idx))
        else:
            # Nouveau raccourci
            new_shortcut = {
                "appid": appid,
                "AppName": app_name,
                "Exe": exe,
                "StartDir": '"/usr/bin"',
                "icon": "",
                "ShortcutPath": "",
                "LaunchOptions": launch_options,
                "IsHidden": 0,
                "AllowDesktopConfig": 1,
                "AllowOverlay": 1,
                "OpenVR": 0,
                "Devkit": 0,
                "DevkitGameID": "",
                "DevkitOverrideAppID": 0,
                "LastPlayTime": 0,
                "FlatpakAppID": flatpak_id,
                "tags": {"0": "GeForce NOW"},
            }
            idx_key = str(next_idx)
            shortcuts[idx_key] = new_shortcut
            appid_map[app_name] = appid
            print(f"  [+] Ajouté : {app_name}")
            created_entries.append((app_name, idx_key))
            next_idx += 1
            added_count += 1

    # Écrire
    binary_data = write_binary_vdf(vdf)
    with open(shortcuts_file, "wb") as f:
        f.write(binary_data)

    print(f"\n[+] {added_count} nouveaux raccourcis ajoutés dans {shortcuts_file}")

    return added_count, created_entries, appid_map




def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║  GeForce NOW — Synchronisation Bibliothèque     ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # ── Étape 0 : Détection du backend GFN ──
    flatpak_id, cache_dir, backend_name = detect_gfn_backend()
    if not flatpak_id:
        gui_error("Backend introuvable",
                  "Aucune application GeForce NOW détectée.\n"
                  "Installez le client officiel NVIDIA ou gfn-electron via Flatpak.")
        sys.exit(1)
    print(f"[✓] Backend détecté : {backend_name}")
    print(f"    Flatpak : {flatpak_id}\n")

    # ── Étape 1 : Extraction des jeux ──
    print("[*] Scan du cache GFN...")
    all_games = extract_games(flatpak_id)
    if not all_games:
        gui_error("Aucun jeu trouvé",
                  "Le cache GeForce NOW est vide.\n"
                  "Ouvrez l'application GFN, connectez-vous, parcourez votre Bibliothèque,\n"
                  "puis fermez-la et relancez ce script.")
        sys.exit(1)

    print(f"[✓] {len(all_games)} jeux trouvés.\n")

    # ── Étape 2 : Détection du profil Steam actif ──
    user_dir, steam3_id = get_active_steam_user_dir()
    if not user_dir:
        gui_error("Steam introuvable", "Aucun profil utilisateur Steam actif trouvé.")
        sys.exit(1)
    print(f"[*] Profil Steam actif : {steam3_id}\n")

    already_synced = set()
    shortcuts_file = os.path.join(user_dir, "config", "shortcuts.vdf")
    if os.path.exists(shortcuts_file):
        with open(shortcuts_file, "rb") as f:
            existing_vdf = parse_binary_vdf(f.read())
        if existing_vdf and "shortcuts" in existing_vdf:
            for _, shortcut in existing_vdf["shortcuts"].items():
                launch_opts = shortcut.get("LaunchOptions", "")
                found_id = _extract_cms_id_from_shortcut(launch_opts)
                if found_id:
                    already_synced.add(found_id)

    if already_synced:
        print(f"[*] {len(already_synced)} jeu(x) déjà synchronisé(s) dans Steam.\n")

    # ── Étape 3 : Sélection par Store ──
    by_store = group_games_by_store(all_games)
    store_counts = {store: len(games) for store, games in by_store.items()}

    selected_stores = gui_checklist_stores(store_counts)
    if not selected_stores:
        gui_info("Annulé", "Aucun store sélectionné. Opération annulée.")
        sys.exit(0)

    # Filtrer les jeux par stores sélectionnés
    filtered_by_store = {s: g for s, g in by_store.items() if s in selected_stores}
    total_filtered = sum(len(g) for g in filtered_by_store.values())
    print(f"\n[✓] {len(selected_stores)} store(s) sélectionné(s) — {total_filtered} jeux.\n")

    # ── Étape 4 : Sélection par Jeu ──
    selected_cms_ids = gui_checklist_games(filtered_by_store, already_synced)
    if not selected_cms_ids:
        gui_info("Annulé", "Aucun jeu sélectionné. Opération annulée.")
        sys.exit(0)

    print(f"\n[✓] {len(selected_cms_ids)} jeu(x) sélectionné(s) pour la synchronisation.\n")

    # ── Étape 5 : Fermeture de Steam (obligatoire avant écriture) ──
    steam_was_running = is_steam_running()
    if steam_was_running:
        print("[*] Fermeture de Steam (nécessaire pour écrire shortcuts.vdf)...")
        # Tentative d'arrêt propre
        subprocess.run(["steam", "-shutdown"], capture_output=True, timeout=5)
        time.sleep(3)
        # Forcer si Steam tourne toujours
        if is_steam_running():
            subprocess.run(["killall", "-9", "steam"], capture_output=True)
            time.sleep(2)
        # Attendre la fin complète
        for _ in range(20):
            if not is_steam_running():
                break
            time.sleep(0.5)
        time.sleep(2)  # Laisser le filesystem se synchroniser
        print("[✓] Steam fermé.\n")

    # ── Étape 6 : Écriture des raccourcis ──

    print(f"[*] Traitement du profil Steam : {steam3_id}")
    total_added, all_created, all_appid_maps = write_shortcuts(
        user_dir, selected_cms_ids, all_games, flatpak_id
    )

    # Vérification
    shortcuts_path = os.path.join(user_dir, "config", "shortcuts.vdf")
    if os.path.exists(shortcuts_path):
        file_size = os.path.getsize(shortcuts_path)
        print(f"[✓] Fichier vérifié : {shortcuts_path} ({file_size} octets)")
        # Relire pour vérifier l'intégrité
        with open(shortcuts_path, "rb") as f:
            verify_data = f.read()
        verify_vdf = parse_binary_vdf(verify_data)
        if verify_vdf and "shortcuts" in verify_vdf:
            n = len(verify_vdf["shortcuts"])
            print(f"[✓] {n} raccourci(s) total dans le fichier.")
        else:
            print("[!] ATTENTION : Le fichier VDF semble corrompu après écriture !")
    else:
        print(f"[!] ATTENTION : Le fichier n'a pas été créé : {shortcuts_path}")

    # ── Étape 7 : Artworks natifs GFN ──
    if all_created:
        print(f"\n[*] Récupération des artworks natifs GFN...")
        native_count, _ = fetch_native_artworks(
            user_dir, all_created, all_appid_maps, all_games, flatpak_id
        )
        print(f"[✓] {native_count} images récupérées.")

        # Patcher le champ 'icon' dans shortcuts.vdf avec l'image grid
        grid_dir = get_grid_dir(user_dir)
        with open(shortcuts_path, "rb") as f:
            vdf_data = parse_binary_vdf(f.read())
        if vdf_data and "shortcuts" in vdf_data:
            patched = 0
            for _idx, sc in vdf_data["shortcuts"].items():
                sc_appid = sc.get("appid", 0) & 0xFFFFFFFF
                if not sc.get("icon"):
                    # Chercher une image grid existante
                    for ext in [".jpg", ".png", ".webp"]:
                        icon_path = os.path.join(grid_dir, f"{sc_appid}{ext}")
                        if os.path.exists(icon_path):
                            sc["icon"] = icon_path
                            patched += 1
                            break
            if patched:
                with open(shortcuts_path, "wb") as f:
                    f.write(write_binary_vdf(vdf_data))
                print(f"[✓] {patched} icône(s) ajoutée(s) dans shortcuts.vdf.\n")
            else:
                print()

    # ── Étape 8 : Résumé + Relancement de Steam ──
    summary = (
        f"Synchronisation terminée !\n\n"
        f"• {len(selected_cms_ids)} jeux synchronisés\n"
        f"• {total_added} nouveaux raccourcis ajoutés\n"
        f"• Catégorie Steam : \"GeForce NOW\"\n\n"
        f"Steam va être relancé."
    )
    gui_info("Synchronisation terminée", summary)
    print(f"\n{'='*50}")
    print(summary)
    print(f"{'='*50}\n")

    # Relancer Steam et fermer le terminal
    print("[*] Relancement de Steam...")
    subprocess.Popen(
        ["steam"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1)
    # Fermer le terminal (kill du shell parent)
    try:
        os.kill(os.getppid(), 15)  # SIGTERM
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
