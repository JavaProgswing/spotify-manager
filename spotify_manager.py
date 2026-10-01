#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║              🎵  Spotify Manager  🎵                         ║
╠══════════════════════════════════════════════════════════════╣
║  1.  Export & Sync Liked Songs                               ║
║      – Newest first / Oldest first (your add-order)         ║
║      – Preserve custom playlist order                        ║
║  2.  Sort a Playlist                                         ║
║      – year · popularity · duration                         ║
║      – artist · title · BPM · energy                        ║
║      – danceability · valence (mood)                        ║
║  3.  Audio Features Dashboard                                ║
║  4.  Duplicate Detector          (within a playlist)         ║
║  5.  Mood Arc Creator                                        ║
║  6.  Playlist Backup & Restore   ← NEW                       ║
║  7.  Smart Filter Playlist       ← NEW                       ║
║  8.  Cross-Playlist Duplicate Finder ← NEW                   ║
║  9.  Playlist Merger             ← NEW                       ║
║  10. Time Machine Playlist       ← NEW                       ║
╚══════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import os
from datetime import datetime, timezone

import spotipy
import os
from spotipy.oauth2 import SpotifyOAuth

# ── Auth ───────────────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI  = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback")

SCOPE = (
    "user-library-read "
    "playlist-read-private "
    "playlist-modify-public "
    "playlist-modify-private"
)

sp = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
    )
)

# ── Shared helpers ─────────────────────────────────────────────────────────────

def fetch_all_liked_songs():
    """
    Returns list of dicts {uri, added_at, id, name, artist} newest-first.
    Reverse to get chronological add-order (oldest first = the order you liked them).
    """
    songs   = []
    results = sp.current_user_saved_tracks()
    while results:
        for item in results["items"]:
            t = item["track"]
            songs.append({
                "uri":      t["uri"],
                "id":       t["id"],
                "name":     t["name"],
                "artist":   t["artists"][0]["name"] if t["artists"] else "",
                "added_at": item["added_at"],
            })
        results = sp.next(results) if results["next"] else None
    return songs  # newest first


def fetch_all_playlists():
    playlists = []
    results   = sp.current_user_playlists(limit=50)
    while results:
        playlists.extend(results["items"])
        results = sp.next(results) if results["next"] else None
    return playlists


def fetch_playlist_tracks(playlist_id):
    """Return list of track dicts with rich metadata."""
    tracks  = []
    results = sp.playlist_items(
        playlist_id,
        fields="items(track(id,uri,name,artists,album(release_date),duration_ms,popularity)),next",
    )
    while results:
        for item in results["items"]:
            t = item.get("track")
            if not t or not t.get("id"):
                continue
            release = (t["album"].get("release_date") or "0000")
            tracks.append({
                "id":         t["id"],
                "uri":        t["uri"],
                "name":       t["name"],
                "artist":     t["artists"][0]["name"] if t["artists"] else "",
                "year":       int(release.split("-")[0]) if release[:4].isdigit() else 0,
                "popularity": t["popularity"],
                "duration":   t["duration_ms"],
            })
        results = sp.next(results) if results["next"] else None
    return tracks


def fetch_audio_features(track_ids):
    """Batch-fetch Spotify audio features. Returns dict {track_id: feature_dict}."""
    features = {}
    for i in range(0, len(track_ids), 100):
        batch = sp.audio_features(track_ids[i : i + 100]) or []
        for f in batch:
            if f:
                features[f["id"]] = f
    return features


def pick_playlist(prompt="Select a playlist: ", playlists=None):
    if playlists is None:
        playlists = fetch_all_playlists()
    print("\n📂 Your playlists:")
    for i, pl in enumerate(playlists, 1):
        track_count = pl.get("tracks", {}).get("total", "?")
        print(f"  {i:>3}. {pl['name']}  ({track_count} songs)")
    idx = int(input(f"\n{prompt}")) - 1
    return playlists[idx]


def pick_multiple_playlists(prompt="Select playlists (comma-separated numbers): "):
    playlists = fetch_all_playlists()
    print("\n📂 Your playlists:")
    for i, pl in enumerate(playlists, 1):
        track_count = pl.get("tracks", {}).get("total", "?")
        print(f"  {i:>3}. {pl['name']}  ({track_count} songs)")
    raw = input(f"\n{prompt}")
    indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
    return [playlists[i] for i in indices if 0 <= i < len(playlists)]


def replace_playlist_tracks(playlist_id, track_ids):
    """Wipe and rewrite a playlist with the given track IDs."""
    sp.playlist_replace_items(playlist_id, [])
    for i in range(0, len(track_ids), 100):
        sp.playlist_add_items(playlist_id, track_ids[i : i + 100])


def get_user():
    user = sp.current_user()
    return user["id"], user["display_name"]


# ══════════════════════════════════════════════════════════════════════════════
# Feature 1 — Export & Sync Liked Songs
# ══════════════════════════════════════════════════════════════════════════════

_EXPORT_HASH_SUFFIX = "_exported"


def export_sync_liked_songs():
    print("\n══ Export & Sync Liked Songs ══════════════════════════════")
    print("""
How should the playlist be ordered?

  1. Newest first      — most recently liked song at the top
                         (default Spotify Liked Songs view)

  2. Oldest first      — your ORIGINAL ADD ORDER; the exact chronological
       (add-order) ★     sequence you liked songs over time.
                         Great for a personal timeline of your taste.

  3. Preserve custom   — keep your existing playlist arrangement as-is;
       order              only append new songs at the end and remove
                         any songs you've since unliked.
""")
    order_choice = input("Choose [1/2/3]: ").strip()

    user_id, username = get_user()

    liked     = fetch_all_liked_songs()          # newest → oldest
    liked_rev = list(reversed(liked))            # oldest → newest (add-order)

    liked_uris     = [s["uri"] for s in liked]
    liked_uris_rev = [s["uri"] for s in liked_rev]

    print(f"\n🎶 Found {len(liked)} liked songs as {username}")

    # ── Find or create the export playlist (keyed by description hash) ──────
    unique_hash    = hashlib.sha1(f"{user_id}{_EXPORT_HASH_SUFFIX}".encode()).hexdigest()
    pl_description = f"exported:{unique_hash}"

    existing_pl = None
    for pl in fetch_all_playlists():
        if pl.get("description") == pl_description:
            existing_pl = pl
            break

    # ── Update existing playlist ─────────────────────────────────────────────
    if existing_pl:
        pl = existing_pl
        print(f"📂 Found existing playlist: {pl['name']}  ({pl['id']})")

        existing_tracks = fetch_playlist_tracks(pl["id"])
        existing_uris   = [t["uri"] for t in existing_tracks]
        print(f"📊 Playlist currently has {len(existing_uris)} songs.")

        liked_set    = set(liked_uris)
        existing_set = set(existing_uris)
        to_add       = liked_set - existing_set
        to_remove    = existing_set - liked_set

        if order_choice == "3":
            if to_remove:
                print(f"➖ Removing {len(to_remove)} songs no longer in Liked…")
                chunks = list(to_remove)
                for i in range(0, len(chunks), 100):
                    sp.playlist_remove_all_occurrences_of_items(pl["id"], chunks[i : i + 100])
            if to_add:
                new_ordered = [u for u in liked_uris if u in to_add]
                print(f"➕ Appending {len(new_ordered)} new songs at the end…")
                for i in range(0, len(new_ordered), 100):
                    sp.playlist_add_items(pl["id"], new_ordered[i : i + 100])
            if not to_add and not to_remove:
                print("✅ Playlist already up to date.")
        else:
            target = liked_uris_rev if order_choice == "2" else liked_uris
            label  = "oldest→newest (your add-order ★)" if order_choice == "2" else "newest→oldest"
            print(f"🔄 Rewriting playlist in {label} order  ({len(target)} songs)…")
            replace_playlist_tracks(pl["id"], target)
            print(f"   ➕ Added {len(to_add)} new  |  ➖ Removed {len(to_remove)} unliked")

    # ── Create new playlist ──────────────────────────────────────────────────
    else:
        pl = sp.user_playlist_create(
            user_id,
            "Exported Liked Songs",
            public=True,
            description=pl_description,
        )
        print(f"🆕 Created new playlist: {pl['name']}  ({pl['id']})")
        target = liked_uris_rev if order_choice == "2" else liked_uris
        for i in range(0, len(target), 100):
            sp.playlist_add_items(pl["id"], target[i : i + 100])

    print(f"\n✅ Sync complete: '{pl['name']}'")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 2 — Sort a Playlist
# ══════════════════════════════════════════════════════════════════════════════

_SORT_FIELDS        = ["year", "popularity", "duration", "artist", "name",
                       "bpm", "energy", "danceability", "valence"]
_AUDIO_FEAT_FIELDS  = {"bpm", "energy", "danceability", "valence"}
_AUDIO_FEAT_MAP     = {"bpm": "tempo", "energy": "energy",
                       "danceability": "danceability", "valence": "valence"}


def sort_playlist():
    print("\n══ Sort a Playlist ════════════════════════════════════════")
    pl     = pick_playlist("Select a playlist to sort: ")
    tracks = fetch_playlist_tracks(pl["id"])
    print(f"\n▶ '{pl['name']}'  —  {len(tracks)} songs")

    print(f"\nAvailable fields: {', '.join(_SORT_FIELDS)}")
    print("  (bpm, energy, danceability, valence require an extra API call)")
    fields_input = input("Sort fields in priority order (comma-separated): ").lower()
    dirs_input   = input("Sort directions (asc/desc, comma-separated):      ").lower()

    fields = [f.strip() for f in fields_input.split(",")]
    dirs   = [d.strip() for d in dirs_input.split(",")]

    if len(fields) != len(dirs):
        print("❌ Number of fields and directions must match."); return
    for f in fields:
        if f not in _SORT_FIELDS:
            print(f"❌ Unknown field: '{f}'"); return

    if any(f in _AUDIO_FEAT_FIELDS for f in fields):
        print("\n🔍 Fetching audio features…")
        af = fetch_audio_features([t["id"] for t in tracks])
        for t in tracks:
            feat = af.get(t["id"], {})
            t["bpm"]          = feat.get("tempo",        0.0)
            t["energy"]       = feat.get("energy",       0.0)
            t["danceability"] = feat.get("danceability", 0.0)
            t["valence"]      = feat.get("valence",      0.0)

    def sort_key(track):
        key = []
        for f, d in zip(fields, dirs):
            val = track.get(f) or 0
            if d == "desc":
                val = -val if isinstance(val, (int, float)) else val[::-1]
            key.append(val)
        return tuple(key)

    sorted_tracks = sorted(tracks, key=sort_key)

    print("\n📊 Preview (first 20 songs):")
    af_cols = [f for f in fields if f in _AUDIO_FEAT_FIELDS]
    for i, t in enumerate(sorted_tracks[:20], 1):
        extra = f" | {t['year']}"
        extra += f" | pop {t['popularity']}"
        if "bpm"          in af_cols: extra += f" | {t.get('bpm',0):.0f} BPM"
        if "energy"       in af_cols: extra += f" | nrg {t.get('energy',0):.2f}"
        if "danceability" in af_cols: extra += f" | dn {t.get('danceability',0):.2f}"
        if "valence"      in af_cols: extra += f" | vl {t.get('valence',0):.2f}"
        print(f"  {i:>3}. {t['name'][:36]:36} — {t['artist'][:20]:20}{extra}")

    confirm = input("\nApply this sort to the playlist? [y/N]: ").strip().lower()
    if confirm == "y":
        replace_playlist_tracks(pl["id"], [t["id"] for t in sorted_tracks])
        print(f"✅ '{pl['name']}' sorted and updated.")
    else:
        print("↩ Cancelled — playlist unchanged.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 3 — Audio Features Dashboard
# ══════════════════════════════════════════════════════════════════════════════

def audio_dashboard():
    print("\n══ Audio Features Dashboard ═══════════════════════════════")
    pl     = pick_playlist("Select a playlist to analyse: ")
    tracks = fetch_playlist_tracks(pl["id"])
    if not tracks:
        print("No tracks found."); return

    print(f"\n🔍 Fetching audio features for {len(tracks)} songs…")
    af    = fetch_audio_features([t["id"] for t in tracks])
    feats = list(af.values())
    if not feats:
        print("No audio features returned."); return

    def avg(key): return sum(f.get(key, 0) for f in feats) / len(feats)
    def pct(key): return f"{avg(key) * 100:.1f}%"

    avg_bpm     = avg("tempo")
    avg_energy  = avg("energy")
    avg_dance   = avg("danceability")
    avg_valence = avg("valence")

    if   avg_valence > 0.6 and avg_energy > 0.6:   mood = "🔥 Upbeat & Happy"
    elif avg_valence > 0.6 and avg_energy <= 0.6:  mood = "😊 Chill & Positive"
    elif avg_valence <= 0.4 and avg_energy > 0.6:  mood = "😤 Intense & Dark"
    elif avg_valence <= 0.4 and avg_energy <= 0.4: mood = "😔 Melancholic"
    else:                                           mood = "😐 Mixed / Neutral"

    print(f"""
╔══════════════════════════════════════════════════╗
║  🎵  {pl['name'][:44]:<44}  ║
╠══════════════════════════════════════════════════╣
║  Songs analysed   : {len(feats):<29}║
║  Overall mood     : {mood:<29}║
╠══════════════════════════════════════════════════╣
║  Avg BPM          : {avg_bpm:<29.1f}║
║  Energy           : {pct('energy'):<29}║
║  Danceability     : {pct('danceability'):<29}║
║  Valence (mood)   : {pct('valence'):<29}║
║  Acousticness     : {pct('acousticness'):<29}║
║  Instrumentalness : {pct('instrumentalness'):<29}║
║  Speechiness      : {pct('speechiness'):<29}║
║  Liveness         : {pct('liveness'):<29}║
╚══════════════════════════════════════════════════╝""")

    e_buckets = {"Low  (0 – 0.33)": 0, "Mid  (0.33 – 0.66)": 0, "High (0.66 – 1)": 0}
    for f in feats:
        e = f.get("energy", 0)
        if   e < 0.33: e_buckets["Low  (0 – 0.33)"] += 1
        elif e < 0.66: e_buckets["Mid  (0.33 – 0.66)"] += 1
        else:          e_buckets["High (0.66 – 1)"] += 1
    print("\nEnergy distribution:")
    for label, count in e_buckets.items():
        bar = "█" * int(count / len(feats) * 32)
        print(f"  {label:18} {bar:<32} {count}")

    bpm_buckets = {"< 80": 0, "80 – 100": 0, "100 – 120": 0, "120 – 140": 0, "140 +": 0}
    for f in feats:
        b = f.get("tempo", 0)
        if   b < 80:  bpm_buckets["< 80"] += 1
        elif b < 100: bpm_buckets["80 – 100"] += 1
        elif b < 120: bpm_buckets["100 – 120"] += 1
        elif b < 140: bpm_buckets["120 – 140"] += 1
        else:         bpm_buckets["140 +"] += 1
    print("\nBPM distribution:")
    for label, count in bpm_buckets.items():
        bar = "█" * int(count / len(feats) * 32)
        print(f"  {label:10} {bar:<32} {count}")

    sorted_by_energy = sorted(feats, key=lambda f: f.get("energy", 0), reverse=True)
    top_ids   = [f["id"] for f in sorted_by_energy[:5]]
    top_names = {t["id"]: t["name"] for t in tracks if t["id"] in top_ids}
    print("\n⚡ Top 5 most energetic tracks:")
    for rank, f in enumerate(sorted_by_energy[:5], 1):
        name = top_names.get(f["id"], f["id"])
        print(f"  {rank}. {name[:50]}  — energy {f['energy']:.2f} | {f.get('tempo',0):.0f} BPM")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 4 — Duplicate Detector (within a playlist)
# ══════════════════════════════════════════════════════════════════════════════

def detect_duplicates():
    print("\n══ Duplicate Detector ═════════════════════════════════════")
    pl     = pick_playlist("Select a playlist to scan: ")
    tracks = fetch_playlist_tracks(pl["id"])
    if not tracks:
        print("Playlist is empty."); return

    seen_ids   = {}
    seen_names = {}
    dupes_exact = []
    dupes_fuzzy = []

    for idx, t in enumerate(tracks):
        tid      = t["id"]
        name_key = f"{t['name'].lower().strip()}||{t['artist'].lower().strip()}"

        if tid in seen_ids:
            dupes_exact.append(
                {"track": t, "original_idx": seen_ids[tid] + 1, "dupe_idx": idx + 1}
            )
        else:
            seen_ids[tid] = idx

        if name_key in seen_names and seen_names[name_key] != tid:
            dupes_fuzzy.append(
                {"track": t, "dupe_idx": idx + 1,
                 "note": "same title & artist — possibly a different version/release"}
            )
        else:
            seen_names[name_key] = tid

    print(f"\n🔍 Scan complete for '{pl['name']}':")
    print(f"   Exact duplicates : {len(dupes_exact)}")
    print(f"   Fuzzy duplicates : {len(dupes_fuzzy)}")

    if not dupes_exact and not dupes_fuzzy:
        print("✅ No duplicates found!"); return

    if dupes_exact:
        print("\n‼  Exact duplicates  (same Spotify track ID):")
        for d in dupes_exact:
            t = d["track"]
            print(f"     Position {d['dupe_idx']:>4}  →  '{t['name']}' — {t['artist']}"
                  f"  (first seen at position {d['original_idx']})")

    if dupes_fuzzy:
        print("\n≈  Fuzzy duplicates  (same song, possibly different release):")
        for d in dupes_fuzzy:
            t = d["track"]
            print(f"     Position {d['dupe_idx']:>4}  →  '{t['name']}' — {t['artist']}")

    if dupes_exact:
        action = input(
            "\nRemove exact duplicates and keep the first occurrence? [y/N]: "
        ).strip().lower()
        if action == "y":
            seen = set()
            deduped_ids = []
            for t in tracks:
                if t["id"] not in seen:
                    deduped_ids.append(t["id"])
                    seen.add(t["id"])
            replace_playlist_tracks(pl["id"], deduped_ids)
            removed = len(tracks) - len(deduped_ids)
            print(f"✅ Removed {removed} exact duplicate(s). Playlist now has {len(deduped_ids)} tracks.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 5 — Mood Arc Creator
# ══════════════════════════════════════════════════════════════════════════════

def mood_arc():
    print("\n══ Mood Arc Creator ═══════════════════════════════════════")
    print(
        "Reorder a playlist so it follows an emotional journey.\n"
        "\n"
        "  1. Build-up    — calm & mellow → high energy bangers\n"
        "  2. Wind-down   — high energy → calm & reflective\n"
        "  3. Valley      — starts energetic, dips low in the middle, peaks again\n"
        "  4. Pyramid     — builds to peak energy in the middle, then fades out\n"
    )
    arc_type = input("Choose arc [1/2/3/4]: ").strip()
    if arc_type not in {"1", "2", "3", "4"}:
        print("Invalid choice."); return

    pl     = pick_playlist("Select a playlist to reorder: ")
    tracks = fetch_playlist_tracks(pl["id"])
    if not tracks:
        print("Playlist is empty."); return

    print(f"\n🔍 Fetching audio features for {len(tracks)} songs…")
    af = fetch_audio_features([t["id"] for t in tracks])
    for t in tracks:
        feat      = af.get(t["id"], {})
        t["energy"]  = feat.get("energy",  0.5)
        t["valence"] = feat.get("valence", 0.5)

    asc  = sorted(tracks, key=lambda t: (t["energy"], t["valence"]))
    desc = list(reversed(asc))

    if arc_type == "1":
        sorted_tracks = asc
    elif arc_type == "2":
        sorted_tracks = desc
    elif arc_type == "3":
        mid  = len(tracks) // 2
        top  = desc[:mid]
        bot  = asc[:len(tracks) - mid]
        sorted_tracks = list(reversed(top)) + bot
    elif arc_type == "4":
        mid  = len(tracks) // 2
        up   = asc[:mid + len(tracks) % 2]
        down = desc[:len(tracks) - mid - len(tracks) % 2]
        sorted_tracks = up + down

    arc_labels = {"1": "Build-up", "2": "Wind-down", "3": "Valley", "4": "Pyramid"}
    print(f"\n📊 '{arc_labels[arc_type]}' arc preview:")
    preview_indices = list(range(min(8, len(sorted_tracks))))
    if len(sorted_tracks) > 10:
        preview_indices += ["…"] + [len(sorted_tracks) - 3,
                                     len(sorted_tracks) - 2,
                                     len(sorted_tracks) - 1]

    for pos in preview_indices:
        if pos == "…":
            print("       …")
            continue
        t   = sorted_tracks[pos]
        bar = "█" * int(t["energy"] * 12)
        mood = "🙂" if t["valence"] > 0.5 else "😔"
        print(f"  {pos+1:>4}. {t['name'][:38]:38} — {bar:<12} nrg {t['energy']:.2f} {mood}")

    confirm = input("\nApply this arc to the playlist? [y/N]: ").strip().lower()
    if confirm == "y":
        replace_playlist_tracks(pl["id"], [t["id"] for t in sorted_tracks])
        print(f"✅ '{arc_labels[arc_type]}' arc applied to '{pl['name']}'.")
    else:
        print("↩ Cancelled — playlist unchanged.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 6 — Playlist Backup & Restore   ★ NEW
# ══════════════════════════════════════════════════════════════════════════════

_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spotify_backups")


def _ensure_backup_dir():
    os.makedirs(_BACKUP_DIR, exist_ok=True)


def playlist_backup_restore():
    print("\n══ Playlist Backup & Restore ══════════════════════════════")
    print(
        "  1. Back up a playlist to a local JSON file\n"
        "  2. Restore a playlist from a local JSON backup\n"
        "  3. List available backups\n"
    )
    choice = input("Choose [1/2/3]: ").strip()

    _ensure_backup_dir()

    # ── Backup ───────────────────────────────────────────────────────────────
    if choice == "1":
        pl     = pick_playlist("Select a playlist to back up: ")
        tracks = fetch_playlist_tracks(pl["id"])

        backup = {
            "playlist_id":   pl["id"],
            "playlist_name": pl["name"],
            "description":   pl.get("description", ""),
            "backed_up_at":  datetime.now(timezone.utc).isoformat(),
            "track_count":   len(tracks),
            "tracks": [
                {
                    "id":         t["id"],
                    "uri":        t["uri"],
                    "name":       t["name"],
                    "artist":     t["artist"],
                    "year":       t["year"],
                    "popularity": t["popularity"],
                    "duration":   t["duration"],
                }
                for t in tracks
            ],
        }

        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in pl["name"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = os.path.join(_BACKUP_DIR, f"{safe_name}_{timestamp}.json")

        with open(filename, "w", encoding="utf-8") as fh:
            json.dump(backup, fh, ensure_ascii=False, indent=2)

        print(f"\n✅ Backed up {len(tracks)} tracks to:")
        print(f"   {filename}")

    # ── Restore ──────────────────────────────────────────────────────────────
    elif choice == "2":
        backups = sorted(
            [f for f in os.listdir(_BACKUP_DIR) if f.endswith(".json")]
        )
        if not backups:
            print("No backups found in:", _BACKUP_DIR); return

        print("\n📂 Available backups:")
        for i, f in enumerate(backups, 1):
            print(f"  {i:>3}. {f}")
        idx  = int(input("\nSelect a backup: ")) - 1
        path = os.path.join(_BACKUP_DIR, backups[idx])

        with open(path, encoding="utf-8") as fh:
            backup = json.load(fh)

        print(f"\n📄 Backup: '{backup['playlist_name']}'  ({backup['track_count']} tracks)")
        print(f"   Backed up: {backup['backed_up_at']}")
        print(
            "\nRestore options:\n"
            "  1. Overwrite the original playlist\n"
            "  2. Create a new playlist from this backup\n"
        )
        restore_choice = input("Choose [1/2]: ").strip()

        track_uris = [t["uri"] for t in backup["tracks"]]
        skipped    = 0

        if restore_choice == "1":
            pl_id = backup["playlist_id"]
            print(f"🔄 Restoring {len(track_uris)} tracks to original playlist…")
            try:
                replace_playlist_tracks(pl_id, [t["id"] for t in backup["tracks"]])
                print(f"✅ Restored to original playlist  ({pl_id})")
            except Exception as e:
                print(f"❌ Could not write to original playlist: {e}")
                print("   (It may have been deleted. Try option 2 to create a new one.)")

        elif restore_choice == "2":
            user_id, _ = get_user()
            new_name   = f"{backup['playlist_name']} (Restored)"
            new_pl     = sp.user_playlist_create(
                user_id, new_name, public=True,
                description=f"Restored from backup {backup['backed_up_at'][:10]}"
            )
            print(f"🆕 Created '{new_name}'")

            # Add in batches; skip unavailable URIs gracefully
            valid_uris = [t["uri"] for t in backup["tracks"]]
            for i in range(0, len(valid_uris), 100):
                try:
                    sp.playlist_add_items(new_pl["id"], valid_uris[i : i + 100])
                except Exception:
                    skipped += 100  # rough estimate

            print(f"✅ Restored {len(valid_uris) - skipped} tracks to '{new_name}'")
            if skipped:
                print(f"   ⚠ ~{skipped} tracks may have been unavailable.")

    # ── List backups ─────────────────────────────────────────────────────────
    elif choice == "3":
        backups = sorted(
            [f for f in os.listdir(_BACKUP_DIR) if f.endswith(".json")]
        )
        if not backups:
            print("No backups found in:", _BACKUP_DIR); return
        print(f"\n📂 Backups in {_BACKUP_DIR}:")
        for f in backups:
            path = os.path.join(_BACKUP_DIR, f)
            size = os.path.getsize(path) // 1024
            print(f"  {f}  ({size} KB)")
    else:
        print("Invalid choice.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 7 — Smart Filter Playlist Creator   ★ NEW
# ══════════════════════════════════════════════════════════════════════════════

def smart_filter_playlist():
    print("\n══ Smart Filter Playlist Creator ══════════════════════════")
    print(
        "Build a new playlist by filtering your Liked Songs (or any playlist)\n"
        "using audio features and metadata.\n"
        "\n"
        "Source:\n"
        "  1. My Liked Songs\n"
        "  2. An existing playlist\n"
    )
    source_choice = input("Choose source [1/2]: ").strip()

    if source_choice == "1":
        print("\n⬇ Fetching your Liked Songs…")
        raw    = fetch_all_liked_songs()   # newest first
        tracks = []
        for s in raw:
            tracks.append({
                "id":     s["id"],
                "uri":    s["uri"],
                "name":   s["name"],
                "artist": s["artist"],
                "year":   0,
                "popularity": 0,
                "duration":   0,
            })
        # Enrich with playlist-style metadata
        ids    = [t["id"] for t in tracks]
        # Fetch full track info in batches for year / popularity / duration
        for i in range(0, len(ids), 50):
            batch = sp.tracks(ids[i : i + 50])["tracks"]
            for j, full_t in enumerate(batch):
                if not full_t:
                    continue
                idx = i + j
                release = (full_t["album"].get("release_date") or "0000")
                tracks[idx]["year"]       = int(release.split("-")[0]) if release[:4].isdigit() else 0
                tracks[idx]["popularity"] = full_t["popularity"]
                tracks[idx]["duration"]   = full_t["duration_ms"]
        print(f"   Found {len(tracks)} liked songs.")
    elif source_choice == "2":
        pl     = pick_playlist("Select a source playlist: ")
        tracks = fetch_playlist_tracks(pl["id"])
        print(f"   Loaded {len(tracks)} songs from '{pl['name']}'.")
    else:
        print("Invalid choice."); return

    # ── Fetch audio features ─────────────────────────────────────────────────
    print("\n🔍 Fetching audio features (needed for BPM / energy / mood filters)…")
    af = fetch_audio_features([t["id"] for t in tracks])
    for t in tracks:
        feat = af.get(t["id"], {})
        t["bpm"]          = feat.get("tempo",        0.0)
        t["energy"]       = feat.get("energy",       0.0)
        t["danceability"] = feat.get("danceability", 0.0)
        t["valence"]      = feat.get("valence",      0.0)
        t["acousticness"] = feat.get("acousticness", 0.0)

    # ── Build filters interactively ─────────────────────────────────────────
    print("""
Filter options (press Enter to skip any filter):

  Year range        e.g.  2015-2022   or  2020
  Artist keyword    e.g.  kendrick    (partial match, case-insensitive)
  BPM range         e.g.  100-130
  Min energy        e.g.  0.6         (0.0 – 1.0)
  Max energy        e.g.  0.8
  Min valence       e.g.  0.5         (0.0 = sad, 1.0 = happy)
  Max valence       e.g.  0.9
  Min danceability  e.g.  0.7
  Min popularity    e.g.  40          (0 – 100)
""")

    def _range(prompt):
        raw = input(f"  {prompt}: ").strip()
        if not raw:
            return None, None
        if "-" in raw:
            parts = raw.split("-", 1)
            return (float(parts[0]) if parts[0] else None,
                    float(parts[1]) if parts[1] else None)
        v = float(raw)
        return v, v

    year_lo, year_hi   = _range("Year range (e.g. 2015-2022 or 2020)")
    artist_kw          = input("  Artist keyword:      ").strip().lower()
    bpm_lo,  bpm_hi    = _range("BPM range   (e.g. 100-130)")
    e_lo               = input("  Min energy  (0-1):   ").strip()
    e_hi               = input("  Max energy  (0-1):   ").strip()
    v_lo               = input("  Min valence (0-1):   ").strip()
    v_hi               = input("  Max valence (0-1):   ").strip()
    d_lo               = input("  Min danceability:    ").strip()
    pop_lo             = input("  Min popularity (0-100): ").strip()

    def _f(s): return float(s) if s else None

    filters = {
        "year_lo":  year_lo,  "year_hi":  year_hi,
        "bpm_lo":   bpm_lo,   "bpm_hi":   bpm_hi,
        "e_lo":     _f(e_lo), "e_hi":     _f(e_hi),
        "v_lo":     _f(v_lo), "v_hi":     _f(v_hi),
        "d_lo":     _f(d_lo),
        "pop_lo":   _f(pop_lo),
        "artist":   artist_kw,
    }

    def passes(t):
        if filters["year_lo"] is not None and t["year"] < filters["year_lo"]: return False
        if filters["year_hi"] is not None and t["year"] > filters["year_hi"]: return False
        if filters["bpm_lo"]  is not None and t["bpm"] < filters["bpm_lo"]:  return False
        if filters["bpm_hi"]  is not None and t["bpm"] > filters["bpm_hi"]:  return False
        if filters["e_lo"]    is not None and t["energy"] < filters["e_lo"]:  return False
        if filters["e_hi"]    is not None and t["energy"] > filters["e_hi"]:  return False
        if filters["v_lo"]    is not None and t["valence"] < filters["v_lo"]: return False
        if filters["v_hi"]    is not None and t["valence"] > filters["v_hi"]: return False
        if filters["d_lo"]    is not None and t["danceability"] < filters["d_lo"]: return False
        if filters["pop_lo"]  is not None and t["popularity"] < filters["pop_lo"]:  return False
        if filters["artist"]  and filters["artist"] not in t["artist"].lower(): return False
        return True

    matched = [t for t in tracks if passes(t)]
    print(f"\n🎯 {len(matched)} tracks match your filters.")

    if not matched:
        print("No tracks matched. Try loosening your filters."); return

    print("\nFirst 15 matches:")
    for i, t in enumerate(matched[:15], 1):
        print(f"  {i:>3}. {t['name'][:38]:38} — {t['artist'][:20]:20}"
              f" | {t['year']} | {t['bpm']:.0f} BPM | nrg {t['energy']:.2f}"
              f" | vl {t['valence']:.2f}")

    default_name = f"Filtered — {datetime.now().strftime('%b %Y')}"
    pl_name = input(f"\nNew playlist name [{default_name}]: ").strip() or default_name
    confirm = input(f"Create '{pl_name}' with {len(matched)} tracks? [y/N]: ").strip().lower()

    if confirm == "y":
        user_id, _ = get_user()
        new_pl = sp.user_playlist_create(
            user_id, pl_name, public=True,
            description=f"Smart Filter playlist — {datetime.now().strftime('%Y-%m-%d')}"
        )
        for i in range(0, len(matched), 100):
            sp.playlist_add_items(new_pl["id"], [t["uri"] for t in matched[i : i + 100]])
        print(f"✅ Created '{pl_name}' with {len(matched)} tracks!")
    else:
        print("↩ Cancelled.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 8 — Cross-Playlist Duplicate Finder   ★ NEW
# ══════════════════════════════════════════════════════════════════════════════

def cross_playlist_duplicates():
    print("\n══ Cross-Playlist Duplicate Finder ════════════════════════")
    print(
        "Scans all your playlists and surfaces songs that appear in more than one.\n"
        "Useful for cleaning up overlapping collections.\n"
    )

    playlists = fetch_all_playlists()
    print(f"📂 Found {len(playlists)} playlists. Fetching tracks…")

    # Map: track_id → {name, artist, playlists: [pl_name, …]}
    track_map = {}

    for pl in playlists:
        print(f"   ↳ '{pl['name']}'…", end="", flush=True)
        tracks = fetch_playlist_tracks(pl["id"])
        print(f"  {len(tracks)} tracks")
        for t in tracks:
            tid = t["id"]
            if tid not in track_map:
                track_map[tid] = {"name": t["name"], "artist": t["artist"], "playlists": []}
            if pl["name"] not in track_map[tid]["playlists"]:
                track_map[tid]["playlists"].append(pl["name"])

    # Only keep tracks that appear in 2+ playlists
    dupes = {
        tid: info for tid, info in track_map.items()
        if len(info["playlists"]) >= 2
    }

    print(f"\n🔍 Cross-playlist duplicates: {len(dupes)} tracks appear in multiple playlists.")

    if not dupes:
        print("✅ Your playlists are clean — no cross-playlist duplicates!"); return

    # Group by number of playlists (most duplicated first)
    sorted_dupes = sorted(dupes.items(), key=lambda x: -len(x[1]["playlists"]))

    print(f"\n{'Track':<42} {'Artist':<22} In playlists")
    print("─" * 100)
    for tid, info in sorted_dupes[:50]:
        pl_list = ", ".join(info["playlists"])
        if len(pl_list) > 55:
            pl_list = pl_list[:52] + "…"
        print(f"  {info['name'][:40]:40}  {info['artist'][:20]:20}  {pl_list}")

    if len(dupes) > 50:
        print(f"  … and {len(dupes) - 50} more.")

    # Optional: export full report to JSON
    export = input("\nExport full report to JSON? [y/N]: ").strip().lower()
    if export == "y":
        _ensure_backup_dir()
        filename = os.path.join(
            _BACKUP_DIR,
            f"cross_playlist_dupes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(filename, "w", encoding="utf-8") as fh:
            json.dump(
                [{"id": tid, **info} for tid, info in sorted_dupes],
                fh, ensure_ascii=False, indent=2
            )
        print(f"✅ Report saved to:\n   {filename}")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 9 — Playlist Merger   ★ NEW
# ══════════════════════════════════════════════════════════════════════════════

def playlist_merger():
    print("\n══ Playlist Merger ═════════════════════════════════════════")
    print("Combine two or more playlists into a single new playlist.\n")

    selected = pick_multiple_playlists(
        "Enter playlist numbers to merge (comma-separated, e.g. 1,3,5): "
    )
    if len(selected) < 2:
        print("Please select at least 2 playlists."); return

    print(f"\n📦 Merging {len(selected)} playlists:")
    for pl in selected:
        print(f"   • {pl['name']}")

    print(
        "\nDuplicate handling:\n"
        "  1. Keep all tracks (including duplicates)\n"
        "  2. Remove exact duplicates (keep first occurrence)\n"
    )
    dedup_choice = input("Choose [1/2]: ").strip()

    print(
        "\nOrder:\n"
        "  1. Playlist by playlist (all of playlist 1, then 2, …)\n"
        "  2. Interleave (round-robin: 1 song from each playlist in turn)\n"
    )
    order_choice = input("Choose [1/2]: ").strip()

    # Fetch tracks from each playlist
    all_tracks = []
    for pl in selected:
        tracks = fetch_playlist_tracks(pl["id"])
        print(f"   ↳ '{pl['name']}'  →  {len(tracks)} tracks")
        all_tracks.append(tracks)

    # Build merged list
    if order_choice == "2":
        merged = []
        max_len = max(len(t) for t in all_tracks)
        for i in range(max_len):
            for pl_tracks in all_tracks:
                if i < len(pl_tracks):
                    merged.append(pl_tracks[i])
    else:
        merged = [t for pl_tracks in all_tracks for t in pl_tracks]

    if dedup_choice == "2":
        seen = set()
        deduped = []
        for t in merged:
            if t["id"] not in seen:
                deduped.append(t)
                seen.add(t["id"])
        print(f"\n🔧 Removed {len(merged) - len(deduped)} duplicates.")
        merged = deduped

    print(f"\n✅ Merged playlist will have {len(merged)} tracks.")

    names    = " + ".join(pl["name"][:15] for pl in selected[:3])
    if len(selected) > 3:
        names += f" + {len(selected) - 3} more"
    default_name = f"Merged: {names}"
    pl_name  = input(f"\nNew playlist name [{default_name}]: ").strip() or default_name
    confirm  = input(f"Create '{pl_name}'? [y/N]: ").strip().lower()

    if confirm == "y":
        user_id, _ = get_user()
        new_pl = sp.user_playlist_create(
            user_id, pl_name, public=True,
            description=f"Merged playlist created {datetime.now().strftime('%Y-%m-%d')}"
        )
        for i in range(0, len(merged), 100):
            sp.playlist_add_items(new_pl["id"], [t["uri"] for t in merged[i : i + 100]])
        print(f"✅ '{pl_name}' created with {len(merged)} tracks!")
    else:
        print("↩ Cancelled.")


# ══════════════════════════════════════════════════════════════════════════════
# Feature 10 — Time Machine Playlist   ★ NEW
# ══════════════════════════════════════════════════════════════════════════════

def time_machine_playlist():
    print("\n══ Time Machine Playlist ══════════════════════════════════")
    print(
        "Creates a playlist from your Liked Songs added during a specific\n"
        "time window — a snapshot of what you were listening to back then.\n"
    )
    print("Date format: YYYY-MM-DD  (e.g. 2022-01-01)")
    start_str = input("  Start date: ").strip()
    end_str   = input("  End date:   ").strip()

    try:
        start_dt = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
        end_dt   = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)
    except ValueError:
        print("❌ Invalid date format. Use YYYY-MM-DD."); return

    if start_dt > end_dt:
        print("❌ Start date must be before end date."); return

    print(f"\n⬇ Fetching all liked songs…")
    liked = fetch_all_liked_songs()   # newest first = also most efficient to short-circuit

    matched = []
    for s in liked:
        added = datetime.fromisoformat(s["added_at"].replace("Z", "+00:00"))
        if start_dt <= added <= end_dt:
            matched.append(s)
        elif added < start_dt:
            # Since liked is newest-first, once we pass the start boundary we're done
            break

    print(f"\n🕰 Found {len(matched)} songs liked between {start_str} and {end_str}")

    if not matched:
        print("No songs found in this date range."); return

    # Show a preview
    print("\nSample (up to 10):")
    for s in matched[:10]:
        added_fmt = s["added_at"][:10]
        print(f"  {added_fmt}  {s['name'][:40]:40} — {s['artist']}")
    if len(matched) > 10:
        print(f"  … and {len(matched) - 10} more.")

    print(
        "\nOrder:\n"
        "  1. Oldest first  — the exact order you liked them (your add-order ★)\n"
        "  2. Newest first  — most recently liked at the top\n"
    )
    order = input("Choose [1/2, default 1]: ").strip() or "1"
    if order == "2":
        pass  # already newest first
    else:
        matched = list(reversed(matched))   # oldest first = add-order

    label_start = start_str.replace("-", ".")
    label_end   = end_str.replace("-", ".")
    default_name = f"Time Machine: {label_start} → {label_end}"
    pl_name  = input(f"\nNew playlist name [{default_name}]: ").strip() or default_name
    confirm  = input(f"Create '{pl_name}' with {len(matched)} tracks? [y/N]: ").strip().lower()

    if confirm == "y":
        user_id, _ = get_user()
        new_pl = sp.user_playlist_create(
            user_id, pl_name, public=True,
            description=(
                f"Time Machine: liked songs from {start_str} to {end_str}. "
                f"Order: {'oldest→newest (add-order)' if order != '2' else 'newest→oldest'}"
            )
        )
        uris = [s["uri"] for s in matched]
        for i in range(0, len(uris), 100):
            sp.playlist_add_items(new_pl["id"], uris[i : i + 100])
        print(f"✅ '{pl_name}' created with {len(matched)} tracks!")
        print(f"   Covering {start_str} → {end_str}")
    else:
        print("↩ Cancelled.")


# ══════════════════════════════════════════════════════════════════════════════
# Main menu
# ══════════════════════════════════════════════════════════════════════════════

MENU = {
    "1":  ("Export & Sync Liked Songs",         export_sync_liked_songs),
    "2":  ("Sort a Playlist",                   sort_playlist),
    "3":  ("Audio Features Dashboard",          audio_dashboard),
    "4":  ("Duplicate Detector",                detect_duplicates),
    "5":  ("Mood Arc Creator",                  mood_arc),
    "6":  ("Playlist Backup & Restore  ★",      playlist_backup_restore),
    "7":  ("Smart Filter Playlist      ★",      smart_filter_playlist),
    "8":  ("Cross-Playlist Duplicates  ★",      cross_playlist_duplicates),
    "9":  ("Playlist Merger            ★",      playlist_merger),
    "10": ("Time Machine Playlist      ★",      time_machine_playlist),
    "q":  ("Quit",                              None),
}


def main():
    print(
        "\n╔══════════════════════════════════════════════════════╗"
        "\n║           🎵  Spotify Manager  🎵                    ║"
        "\n╚══════════════════════════════════════════════════════╝"
    )
    while True:
        print()
        for key, (label, _) in MENU.items():
            print(f"  [{key:>2}]  {label}")
        choice = input("\nChoose an option: ").strip().lower()
        if choice == "q":
            print("👋 Bye!"); break
        if choice in MENU:
            _, fn = MENU[choice]
            try:
                fn()
            except KeyboardInterrupt:
                print("\n↩  Interrupted — returning to menu.")
            except Exception as e:
                print(f"❌ Error: {e}")
        else:
            print("Invalid choice — enter 1–10 or q.")


if __name__ == "__main__":
    main()
