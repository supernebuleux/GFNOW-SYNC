#!/usr/bin/env python3
"""
gfn_common.py — Module partagé pour la suite GeForce NOW SteamOS.

Contient :
- Parseur/Écrivain binaire VDF (shortcuts.vdf)
- Helpers GUI (kdialog avec fallback terminal)
- Détection automatique du backend GFN (Flatpak)
- Résolution des chemins Steam
"""

import binascii
import os
import re
import struct
try:
    import vdf as _vdf_lib
    HAS_VDF_LIB = True
except ImportError:
    HAS_VDF_LIB = False
import shutil
import subprocess
import time

# ──────────────────────────────────────────────
# Configuration des Flatpaks GFN supportés
# ──────────────────────────────────────────────
GFN_BACKENDS = [
    {
        "id": "com.nvidia.geforcenow",
        "name": "NVIDIA GeForce NOW (Officiel)",
        "cache_paths": [
            "~/.var/app/com.nvidia.geforcenow/.local/state/NVIDIA/GeForceNOW/CefCache/Default/Local Storage/leveldb",
            "~/.var/app/com.nvidia.geforcenow/config/GeForceNOW/Local Storage/leveldb",
            "~/.var/app/com.nvidia.geforcenow/config/geforcenow/Local Storage/leveldb",
        ],
    },
    {
        "id": "com.github.hmlendea.gfn-electron",
        "name": "GFN Electron (Communautaire)",
        "cache_paths": [
            "~/.var/app/com.github.hmlendea.gfn-electron/config/gfn-electron/Local Storage/leveldb",
            "~/.config/gfn-electron/Local Storage/leveldb",
        ],
    },
    {
        "id": "com.github.hmlendea.geforcenow-electron",
        "name": "GeForce NOW Electron (Communautaire ancien)",
        "cache_paths": [
            "~/.var/app/com.github.hmlendea.geforcenow-electron/config/geforcenow-electron/Local Storage/leveldb",
            "~/.config/geforcenow-electron/Local Storage/leveldb",
        ],
    },
]

STEAMGRIDDB_API_BASE = "https://www.steamgriddb.com/api/v2"
CONFIG_DIR = os.path.expanduser("~/.config/gfn-sync")


# ──────────────────────────────────────────────
# Détection du backend GFN
# ──────────────────────────────────────────────
def detect_gfn_backend():
    """Détecte le Flatpak GFN installé et retourne (flatpak_id, cache_dir) ou (None, None)."""
    for backend in GFN_BACKENDS:
        for cache_path in backend["cache_paths"]:
            expanded = os.path.expanduser(cache_path)
            if os.path.exists(expanded):
                return backend["id"], expanded, backend["name"]
    return None, None, None


# ──────────────────────────────────────────────
# Chemins Steam
# ──────────────────────────────────────────────
def get_steam_user_dirs():
    """Retourne la liste des dossiers utilisateur Steam."""
    candidates = [
        os.path.expanduser("~/.steam/steam/userdata"),
        os.path.expanduser("~/.local/share/Steam/userdata"),
    ]
    for steam_dir in candidates:
        if os.path.exists(steam_dir):
            return [
                os.path.join(steam_dir, d)
                for d in os.listdir(steam_dir)
                if d.isdigit()
            ]
    return []


def get_active_steam_user_dir():
    """
    Retourne le dossier du profil Steam actif (MostRecent=1).
    Parse loginusers.vdf pour trouver le SteamID64 actif,
    puis calcule le Steam3 ID correspondant.
    Retourne (user_dir, steam3_id) ou (None, None).
    """
    STEAM3_OFFSET = 76561197960265728

    config_candidates = [
        os.path.expanduser("~/.steam/steam/config/loginusers.vdf"),
        os.path.expanduser("~/.local/share/Steam/config/loginusers.vdf"),
    ]

    active_steam64 = None
    for config_path in config_candidates:
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r") as f:
                content = f.read()

            # Parse simple : chercher le SteamID64 suivi de MostRecent=1
            current_id = None
            for line in content.splitlines():
                stripped = line.strip().strip('"')
                # Ligne contenant un SteamID64 (17 chiffres)
                if stripped.isdigit() and len(stripped) >= 17:
                    current_id = stripped
                elif "MostRecent" in line and '"1"' in line and current_id:
                    active_steam64 = int(current_id)
                    break
        except Exception:
            continue

    if not active_steam64:
        return None, None

    steam3_id = str(active_steam64 - STEAM3_OFFSET)

    userdata_candidates = [
        os.path.expanduser("~/.steam/steam/userdata"),
        os.path.expanduser("~/.local/share/Steam/userdata"),
    ]
    for userdata_dir in userdata_candidates:
        user_dir = os.path.join(userdata_dir, steam3_id)
        if os.path.exists(user_dir):
            return user_dir, steam3_id

    return None, None


def get_grid_dir(user_dir):
    """Retourne le chemin du dossier grid pour un utilisateur Steam."""
    grid_dir = os.path.join(user_dir, "config", "grid")
    os.makedirs(grid_dir, exist_ok=True)
    return grid_dir


# ──────────────────────────────────────────────
# Extraction des jeux
# ──────────────────────────────────────────────
def extract_games(flatpak_id):
    """
    Extrait les jeux depuis le cache GFN.
    Essaie d'abord le CacheStorage (client officiel NVIDIA),
    puis le LevelDB (clients communautaires).
    Retourne un dict : { cmsId: {"title": str, "store": str, ...} }
    """
    # Tenter CacheStorage (client officiel)
    cachestorage_dirs = [
        f"~/.var/app/{flatpak_id}/.local/state/NVIDIA/GeForceNOW/CefCache/Default/Service Worker/CacheStorage",
    ]
    for cs_dir in cachestorage_dirs:
        expanded = os.path.expanduser(cs_dir)
        if os.path.exists(expanded):
            games = _extract_from_cachestorage(expanded)
            if games:
                return games

    # Fallback : LevelDB (clients communautaires)
    for backend in GFN_BACKENDS:
        if backend["id"] == flatpak_id:
            for cache_path in backend["cache_paths"]:
                expanded = os.path.expanduser(cache_path)
                if os.path.exists(expanded):
                    games = _extract_from_leveldb(expanded)
                    if games:
                        return games

    return {}


def _extract_from_cachestorage(cachestorage_dir):
    """
    Extrait les jeux depuis les fichiers Service Worker CacheStorage.
    Format du client officiel NVIDIA GeForce NOW.
    Retourne un dict : { variant_id: {"title", "store", "shortName", "parentGameId", "images"} }
    Seuls les jeux avec au moins une variante "selected: true" sont inclus.
    """
    games = {}

    for root, _, files in os.walk(cachestorage_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "rb") as f:
                    content = f.read()
                text = content.decode("utf-8", errors="ignore")

                # Skip files that don't contain game data
                if '"__typename":"GameItem"' not in text:
                    continue

                # Split by GameItem to isolate each game block
                parts = text.split('"__typename":"GameItem"')

                for part in parts[1:]:
                    # Extract game UUID (first UUID after "id":)
                    id_match = re.search(r'"id"\s*:\s*"([0-9a-f-]{36})"', part)
                    if not id_match:
                        continue
                    game_uuid = id_match.group(1)

                    # Extract title
                    title_match = re.search(r'"title"\s*:\s*"([^"]+)"', part)
                    if not title_match:
                        continue
                    title = title_match.group(1).strip()

                    # Extract image URLs
                    images = {}
                    hero_match = re.search(r'"HERO_IMAGE"\s*:\s*"([^"]+)"', part)
                    banner_match = re.search(r'"TV_BANNER"\s*:\s*"([^"]+)"', part)
                    if hero_match:
                        images["hero"] = hero_match.group(1)
                    if banner_match:
                        images["banner"] = banner_match.group(1)

                    # Find variants with selected=true
                    variant_pattern = re.compile(
                        r'"id"\s*:\s*"(\d+)"\s*,'
                        r'.*?"shortName"\s*:\s*"([^"]*)"'
                        r'.*?"appStore"\s*:\s*"([^"]+)"'
                        r'.*?"selected"\s*:\s*(true|false)',
                        re.DOTALL,
                    )

                    # Limit search to the variants section
                    variants_start = part.find('"variants"')
                    if variants_start == -1:
                        continue
                    variants_section = part[variants_start:]

                    for var_match in variant_pattern.finditer(variants_section):
                        variant_id = var_match.group(1)
                        short_name = var_match.group(2)
                        app_store = var_match.group(3)
                        selected = var_match.group(4) == "true"

                        if selected and variant_id not in games:
                            games[variant_id] = {
                                "title": title,
                                "store": _normalize_store_name(app_store),
                                "shortName": short_name,
                                "parentGameId": game_uuid,
                                "images": images,
                            }

            except Exception:
                continue

    return games


def _extract_from_leveldb(leveldb_dir):
    """
    Scanne les fichiers LevelDB pour extraire les jeux GFN.
    Format des clients communautaires (gfn-electron).
    Retourne un dict : { cmsId: {"title": str, "store": str} }
    """
    games = {}

    cms_pattern = re.compile(br'"cmsId"\s*:\s*"?([^",}\s]+)"?')
    title_pattern = re.compile(br'"title"\s*:\s*"([^"]+)"')
    store_patterns = [
        re.compile(br'"store"\s*:\s*"([^"]+)"'),
        re.compile(br'"storeName"\s*:\s*"([^"]+)"'),
        re.compile(br'"platform"\s*:\s*"([^"]+)"'),
        re.compile(br'"storeFrontName"\s*:\s*"([^"]+)"'),
    ]

    for root, _, files in os.walk(leveldb_dir):
        for filename in files:
            if not filename.endswith((".ldb", ".log")):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "rb") as f:
                    content = f.read()

                for cms_match in cms_pattern.finditer(content):
                    cms_id = cms_match.group(1).decode("utf-8", errors="ignore").strip('"\'')
                    if not cms_id or len(cms_id) < 3:
                        continue

                    start = max(0, cms_match.start() - 500)
                    end = min(len(content), cms_match.end() + 500)
                    window = content[start:end]

                    title_match = title_pattern.search(window)
                    title = title_match.group(1).decode("utf-8", errors="ignore") if title_match else None

                    store = "Inconnu"
                    for sp in store_patterns:
                        store_match = sp.search(window)
                        if store_match:
                            store = store_match.group(1).decode("utf-8", errors="ignore")
                            break

                    store = _normalize_store_name(store)

                    if title and cms_id not in games:
                        games[cms_id] = {"title": title, "store": store}

            except Exception:
                continue

    return games


def _normalize_store_name(store):
    """Normalise les noms de store pour un affichage cohérent."""
    store_lower = store.lower().strip()
    if "steam" in store_lower:
        return "Steam"
    elif "epic" in store_lower:
        return "Epic Games"
    elif "ubisoft" in store_lower or "uplay" in store_lower:
        return "Ubisoft Connect"
    elif "xbox" in store_lower or "microsoft" in store_lower:
        return "Xbox / Microsoft"
    elif "gog" in store_lower:
        return "GOG"
    elif store_lower in ("ea", "ea app", "ea play") or "origin" in store_lower:
        return "EA App"
    return store if store != "Inconnu" else "Autre"


# ──────────────────────────────────────────────
# Parseur / Écrivain VDF binaire (via lib vdf)
# ──────────────────────────────────────────────
def parse_binary_vdf(data):
    """Parse un fichier VDF binaire en dict Python."""
    if HAS_VDF_LIB:
        try:
            return _vdf_lib.binary_loads(data)
        except Exception:
            return {}
    # Fallback maison
    pos = 0

    def read_string():
        nonlocal pos
        end = data.find(b"\x00", pos)
        if end == -1:
            return ""
        val = data[pos:end].decode("utf-8", errors="ignore")
        pos = end + 1
        return val

    def parse_map():
        nonlocal pos
        res = {}
        while pos < len(data):
            t = data[pos]
            pos += 1
            if t == 8:
                break
            key = read_string()
            if t == 0:
                res[key] = parse_map()
            elif t == 1:
                res[key] = read_string()
            elif t == 2:
                if pos + 4 <= len(data):
                    val = struct.unpack("<i", data[pos : pos + 4])[0]
                    pos += 4
                    res[key] = val
        return res

    if len(data) < 2 or data[0] != 0:
        return {}
    pos = 1
    root_key = read_string()
    return {root_key: parse_map()}


def write_binary_vdf(vdf_dict):
    """Sérialise un dict Python en VDF binaire."""
    if HAS_VDF_LIB:
        return _vdf_lib.binary_dumps(vdf_dict)
    # Fallback maison (signed int32)
    out = bytearray()

    def write_string(s):
        out.extend(s.encode("utf-8"))
        out.append(0)

    def write_map(m):
        for k, v in m.items():
            if isinstance(v, dict):
                out.append(0)
                write_string(k)
                write_map(v)
            elif isinstance(v, str):
                out.append(1)
                write_string(k)
                write_string(v)
            elif isinstance(v, int):
                out.append(2)
                write_string(k)
                out.extend(struct.pack("<i", _to_signed32(v)))
        out.append(8)

    root_key = list(vdf_dict.keys())[0]
    out.append(0)
    write_string(root_key)
    write_map(vdf_dict[root_key])
    return bytes(out)


def _to_signed32(val):
    """Convertit un entier en signed int32."""
    val = val & 0xFFFFFFFF
    if val >= 0x80000000:
        val -= 0x100000000
    return val


def generate_shortcut_appid(exe, app_name):
    """
    Génère un AppID déterministe pour un raccourci non-Steam.
    Formule standard : crc32(exe + app_name) | 0x80000000
    Retourne un signed int32 (requis par Steam).
    """
    key = (exe + app_name).encode("utf-8")
    crc = binascii.crc32(key) & 0xFFFFFFFF
    unsigned_id = crc | 0x80000000
    return _to_signed32(unsigned_id)


def backup_file(filepath):
    """Crée une copie de sauvegarde d'un fichier."""
    backup_path = filepath + ".bak"
    shutil.copyfile(filepath, backup_path)
    return backup_path


# ──────────────────────────────────────────────
# GUI Helpers (kdialog + fallback terminal)
# ──────────────────────────────────────────────
def _has_kdialog():
    """Vérifie si kdialog est disponible."""
    try:
        subprocess.run(["kdialog", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


HAS_KDIALOG = _has_kdialog()


def gui_info(title, message):
    """Affiche un message d'information."""
    if HAS_KDIALOG:
        subprocess.run(["kdialog", "--title", title, "--msgbox", message])
    else:
        print(f"\n✅ {title}")
        print(f"   {message}\n")


def gui_error(title, message):
    """Affiche un message d'erreur."""
    if HAS_KDIALOG:
        subprocess.run(["kdialog", "--title", title, "--error", message])
    else:
        print(f"\n❌ {title}")
        print(f"   {message}\n")


def gui_yesno(title, question):
    """Pose une question oui/non. Retourne True si oui."""
    if HAS_KDIALOG:
        result = subprocess.run(
            ["kdialog", "--title", title, "--yesno", question],
            capture_output=True,
        )
        return result.returncode == 0
    else:
        print(f"\n❓ {title}")
        reply = input(f"   {question} (o/n) : ").strip().lower()
        return reply in ("o", "oui", "y", "yes")


def gui_input(title, label, default=""):
    """Demande une saisie texte. Retourne la valeur ou None si annulé."""
    if HAS_KDIALOG:
        result = subprocess.run(
            ["kdialog", "--title", title, "--inputbox", label, default],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    else:
        print(f"\n📝 {title}")
        val = input(f"   {label} [{default}] : ").strip()
        return val if val else (default if default else None)


def gui_checklist_stores(stores_with_counts):
    """
    Affiche une checklist de stores.
    stores_with_counts: dict { store_name: count }
    Retourne la liste des stores sélectionnés.
    """
    store_names = list(stores_with_counts.keys())

    if HAS_KDIALOG:
        args = ["kdialog", "--title", "Sélection des Stores", "--checklist",
                "Sélectionnez les stores à synchroniser :"]
        for i, store in enumerate(store_names):
            count = stores_with_counts[store]
            args.extend([str(i), f"{store}  ({count} jeux)", "off"])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            return []  # Annulé
        selected_indices = result.stdout.strip().replace('"', '').split()
        return [store_names[int(idx)] for idx in selected_indices if idx.isdigit()]
    else:
        # Terminal fallback
        print("\n╔══════════════════════════════════════╗")
        print("║     SÉLECTION DES STORES             ║")
        print("╚══════════════════════════════════════╝")
        for i, store in enumerate(store_names):
            count = stores_with_counts[store]
            print(f"  [{i+1}] {store}  ({count} jeux)")
        print(f"\n  Commandes : all | none | numéros séparés par des espaces")
        reply = input("  Votre sélection : ").strip().lower()
        if reply == "all":
            return store_names
        elif reply == "" or reply == "none":
            return []
        else:
            indices = []
            for token in reply.split():
                if token.isdigit():
                    idx = int(token) - 1
                    if 0 <= idx < len(store_names):
                        indices.append(idx)
            return [store_names[i] for i in indices]


def gui_checklist_games(games_by_store, already_synced=None):
    """
    Affiche une checklist de jeux groupés par store.
    games_by_store: dict { store_name: [ (cms_id, title), ... ] }
    already_synced: set de cms_id déjà présents dans Steam (optionnel)
    Retourne la liste des cms_id sélectionnés.
    """
    if already_synced is None:
        already_synced = set()

    # Construire la liste plate avec séparateurs visuels
    flat_items = []  # (cms_id, display_label, store, is_synced)
    for store, game_list in games_by_store.items():
        for cms_id, title in sorted(game_list, key=lambda x: x[1].lower()):
            is_synced = cms_id in already_synced
            flat_items.append((cms_id, title, store, is_synced))

    synced_count = sum(1 for _, _, _, s in flat_items if s)
    new_count = len(flat_items) - synced_count

    if HAS_KDIALOG:
        header = "Sélectionnez les jeux à synchroniser :"
        if synced_count > 0:
            header += (f"\n\n({synced_count} jeu(x) déjà synchronisé(s), "
                       f"{new_count} nouveau(x))\n"
                       "Décocher un jeu [déjà sync] ne le supprime pas.\n"
                       "Utilisez gfn_cleanup.py pour retirer des raccourcis.")
        args = ["kdialog", "--title", "Sélection des Jeux", "--checklist", header]
        for cms_id, title, store, is_synced in flat_items:
            if is_synced:
                label = f"[{store}]  {title}  [déjà sync]"
            else:
                label = f"[{store}]  {title}"
            args.extend([cms_id, label, "off"])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            return []  # Annulé
        selected = result.stdout.strip().replace('"', '').split()
        return selected
    else:
        # Terminal fallback
        print("\n╔══════════════════════════════════════╗")
        print("║     SÉLECTION DES JEUX               ║")
        print("╚══════════════════════════════════════╝")
        if synced_count > 0:
            print(f"\n  ℹ️  {synced_count} jeu(x) déjà synchronisé(s) (marqués ✓)")
            print("  ℹ️  Décocher un jeu déjà sync ne le supprime pas.")
            print("      Utilisez gfn_cleanup.py pour retirer des raccourcis.")
        current_store = None
        idx_map = {}
        new_ids = []
        i = 1
        for cms_id, title, store, is_synced in flat_items:
            if store != current_store:
                current_store = store
                print(f"\n  ── {store} ──")
            suffix = "  ✓ déjà sync" if is_synced else ""
            print(f"  [{i}] {title}{suffix}")
            idx_map[i] = cms_id
            if not is_synced:
                new_ids.append(cms_id)
            i += 1
        print(f"\n  Commandes : all | none | new (nouveaux uniquement) | numéros séparés par des espaces")
        reply = input(f"  Votre sélection : ").strip().lower()
        if reply == "all":
            return [item[0] for item in flat_items]
        elif reply == "" or reply == "none":
            return []
        else:
            selected = []
            for token in reply.split():
                if token.isdigit():
                    num = int(token)
                    if num in idx_map:
                        selected.append(idx_map[num])
            return selected


def gui_checklist_cleanup(shortcuts_list):
    """
    Affiche une checklist pour le nettoyage.
    shortcuts_list: [ (index_key, app_name), ... ]
    Retourne la liste des index_key sélectionnés.
    """
    if HAS_KDIALOG:
        args = ["kdialog", "--title", "Nettoyage des raccourcis GFN", "--checklist",
                "Sélectionnez les raccourcis à supprimer :"]
        for idx_key, app_name in shortcuts_list:
            args.extend([idx_key, app_name, "on"])
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        return result.stdout.strip().replace('"', '').split()
    else:
        print("\n╔══════════════════════════════════════╗")
        print("║     NETTOYAGE RACCOURCIS GFN         ║")
        print("╚══════════════════════════════════════╝")
        num_map = {}
        for i, (idx_key, app_name) in enumerate(shortcuts_list, 1):
            print(f"  [{i}] {app_name}")
            num_map[i] = idx_key
        print(f"\n  Commandes : all | none | numéros séparés par des espaces")
        reply = input("  Raccourcis à supprimer [all] : ").strip().lower()
        if reply == "" or reply == "all":
            return [item[0] for item in shortcuts_list]
        elif reply == "none":
            return []
        else:
            selected = []
            for token in reply.split():
                if token.isdigit():
                    num = int(token)
                    if num in num_map:
                        selected.append(num_map[num])
            return selected


# ──────────────────────────────────────────────
# Gestion de Steam (kill / restart)
# ──────────────────────────────────────────────
def is_steam_running():
    """Vérifie si Steam est en cours d'exécution."""
    try:
        result = subprocess.run(["pgrep", "-x", "steam"], capture_output=True)
        return result.returncode == 0
    except Exception:
        return False


def restart_steam():
    """Tue et relance Steam."""
    try:
        subprocess.run(["killall", "steam"], capture_output=True)
        time.sleep(3)
        subprocess.Popen(["steam"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────
# SteamGridDB (optionnel)
# ──────────────────────────────────────────────
def load_steamgriddb_key():
    """Charge la clé API SteamGridDB depuis le fichier de config."""
    key_file = os.path.join(CONFIG_DIR, "steamgriddb_api_key")
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            key = f.read().strip()
            if key:
                return key
    return None


def save_steamgriddb_key(key):
    """Sauvegarde la clé API SteamGridDB."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    key_file = os.path.join(CONFIG_DIR, "steamgriddb_api_key")
    with open(key_file, "w") as f:
        f.write(key)


def steamgriddb_request(endpoint, api_key):
    """Effectue une requête GET sur l'API SteamGridDB."""
    import urllib.request
    import json

    url = f"{STEAMGRIDDB_API_BASE}{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success"):
                return data.get("data", [])
    except Exception:
        pass
    return None


def download_file(url, dest_path):
    """Télécharge un fichier depuis une URL."""
    import urllib.request

    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception:
        return False
