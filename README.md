# Spotify Manager

A single-file CLI for managing a Spotify library: export and sync Liked Songs (newest- or
oldest-first, preserving add order) plus playlist tooling. Built on
[spotipy](https://spotipy.readthedocs.io/).

## Setup

1. Make an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and add
   a redirect URI (default `http://127.0.0.1:8000/callback`).
2. Set credentials via env vars:

```bash
pip install -r requirements.txt
cp .env.example .env     # fill in client id + secret
# or export SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / SPOTIFY_REDIRECT_URI
```

3. Run:

```bash
python spotify_manager.py
```

First run opens a browser to authorize and caches the token in `.cache` (git-ignored).

Scopes: `user-library-read`, `playlist-read-private`, `playlist-modify-public`,
`playlist-modify-private`.

## Notes

- Credentials come from the environment only; nothing is hardcoded. `.cache` and `.env` are
  git-ignored. Rotate a secret if you've exposed it.
