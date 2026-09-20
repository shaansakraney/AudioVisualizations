"""
nowplaying.py
-------------
What's playing right now, and what its cover art looks like.

This is the second input to the visuals, parallel to (and completely
independent of) the audio pipeline in audio.py/features.py:

    Spotify  ->  NowPlayingProvider  ->  NowPlaying  ->  Scene.now_playing
    (metadata)   (background thread)     (art+palette)

Two things worth knowing up front, because they shape the whole design:

1. Spotify's API cannot give you the audio. It returns metadata only, so
   *reactivity* still comes from a real input device (see audio.py and
   find_loopback_device()). This module only supplies art and color.
2. Spotify deprecated the Audio Analysis / Audio Features endpoints for new
   apps in Nov 2024, so there's no tempo or beat grid to fetch either.
   FeatureExtractor remains the only beat source.

Two interchangeable backends, both exposing `poll() -> dict | None`:

- AppleScriptBackend : talks to the local Spotify desktop app. No developer
                       account, no OAuth, no tokens. macOS only.
- WebAPIBackend     : OAuth PKCE against the Web API. Works cross-platform
                       and sees playback on any device (phone, Connect
                       speaker), at the cost of real setup.

`Features` deliberately stays audio-only -- it's the contract meant to be
reimplemented on a microcontroller -- so album art rides this separate
channel instead of being bolted onto it.
"""

import base64
import hashlib
import io
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass

import pygame

import fx

try:
    import requests
except Exception:  # the app must still run without the HTTP stack
    requests = None

ART_SIZE = 640          # cover art is scaled to this square once, on download
PALETTE_N = 6           # how many colors to pull out of each cover
PLAYING_STATES = ("playing",)


@dataclass
class NowPlaying:
    """A snapshot of the current track. Scenes read this off
    `self.now_playing`; it is None whenever nothing is known."""
    track_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    art: object = None                  # pygame.Surface (square) or None
    palette: tuple = ()                 # (r,g,b) tuples, most prominent first
    accent: tuple = (255, 255, 255)     # most vivid palette entry
    playing: bool = False

    def label(self):
        if not self.title:
            return ""
        return f"{self.title} - {self.artist}" if self.artist else self.title


# ---------------------------------------------------------------------------
# Backend: local Spotify desktop app via AppleScript (macOS)
# ---------------------------------------------------------------------------

_DELIM = "|:|"

# NOTE the System Events guard: a bare `tell application "Spotify"` LAUNCHES
# Spotify if it isn't running. Polling every few seconds must never do that,
# so we check for the process first and bail out before addressing the app.
_SCRIPT = f'''
tell application "System Events"
    if not (exists process "Spotify") then return "NOTRUNNING"
end tell
tell application "Spotify"
    if player state is stopped then return "STOPPED"
    set t to current track
    return (id of t) & "{_DELIM}" & (name of t) & "{_DELIM}" & ¬
        (artist of t) & "{_DELIM}" & (album of t) & "{_DELIM}" & ¬
        (artwork url of t) & "{_DELIM}" & (player state as text)
end tell
'''


class AppleScriptBackend:
    """Reads the local Spotify app's scripting interface. Zero setup, but
    macOS-only and blind to playback happening on other devices."""

    name = "applescript"
    poll_interval = 3.0

    def available(self):
        return os.path.exists("/Applications/Spotify.app")

    def poll(self):
        try:
            r = subprocess.run(
                ["osascript", "-e", _SCRIPT],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return None
        out = (r.stdout or "").strip()
        if not out or out in ("NOTRUNNING", "STOPPED"):
            return None
        parts = out.split(_DELIM)
        if len(parts) < 6:
            return None
        track_id, title, artist, album, art_url, state = (p.strip() for p in parts[:6])
        return {
            "track_id": track_id, "title": title, "artist": artist,
            "album": album, "art_url": art_url,
            "playing": state.lower() in PLAYING_STATES,
        }


# ---------------------------------------------------------------------------
# Backend: Spotify Web API (OAuth PKCE)
# ---------------------------------------------------------------------------

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
NOW_URL = "https://api.spotify.com/v1/me/player/currently-playing"
SCOPES = "user-read-currently-playing user-read-playback-state"
REDIRECT = "http://127.0.0.1:8888/callback"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".spotify_token.json")


class WebAPIBackend:
    """OAuth PKCE against the Web API. Needs a client ID from
    developer.spotify.com (free): register an app, add
    http://127.0.0.1:8888/callback as a redirect URI, then export
    SPOTIFY_CLIENT_ID. The refresh token is cached in .spotify_token.json
    (gitignored) so the browser consent only happens once."""

    name = "web"
    poll_interval = 5.0

    def __init__(self, client_id=None):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "")
        self._access = ""
        self._expires = 0.0
        self._refresh = ""
        self._backoff_until = 0.0
        self._load_cache()

    def available(self):
        return bool(self.client_id) and requests is not None

    # -- token handling ----------------------------------------------------
    def _load_cache(self):
        try:
            with open(TOKEN_FILE) as fh:
                self._refresh = json.load(fh).get("refresh_token", "")
        except Exception:
            self._refresh = ""

    def _save_cache(self):
        try:
            with open(TOKEN_FILE, "w") as fh:
                json.dump({"refresh_token": self._refresh}, fh)
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass

    def _authorize(self):
        """One-time browser consent. Spins up a throwaway local server just
        long enough to catch the redirect carrying the auth code."""
        import http.server
        import webbrowser

        verifier = secrets.token_urlsafe(64)[:96]
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id, "response_type": "code",
            "redirect_uri": REDIRECT, "scope": SCOPES, "state": state,
            "code_challenge_method": "S256", "code_challenge": challenge,
        }
        holder = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                holder.update({k: v[0] for k, v in q.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>audioviz connected. You can close this tab.</h2>")

            def log_message(self, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
        url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
        print("[spotify] opening browser for one-time authorization...")
        webbrowser.open(url)
        server.timeout = 120
        server.handle_request()
        server.server_close()

        if holder.get("state") != state or "code" not in holder:
            print("[spotify] authorization failed or timed out")
            return False
        r = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": holder["code"],
            "redirect_uri": REDIRECT, "client_id": self.client_id,
            "code_verifier": verifier,
        }, timeout=10)
        if r.status_code != 200:
            print(f"[spotify] token exchange failed: {r.status_code}")
            return False
        d = r.json()
        self._access = d.get("access_token", "")
        self._expires = time.time() + d.get("expires_in", 3600) - 60
        self._refresh = d.get("refresh_token", "")
        self._save_cache()
        return True

    def _refresh_token(self):
        r = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": self._refresh,
            "client_id": self.client_id,
        }, timeout=10)
        if r.status_code != 200:
            self._refresh = ""      # stale -> fall back to full consent
            return False
        d = r.json()
        self._access = d.get("access_token", "")
        self._expires = time.time() + d.get("expires_in", 3600) - 60
        if d.get("refresh_token"):
            self._refresh = d["refresh_token"]
            self._save_cache()
        return True

    def _ensure_token(self):
        if self._access and time.time() < self._expires:
            return True
        if self._refresh and self._refresh_token():
            return True
        return self._authorize()

    # -- polling -----------------------------------------------------------
    def poll(self):
        if not self.available() or time.time() < self._backoff_until:
            return None
        try:
            if not self._ensure_token():
                self._backoff_until = time.time() + 60
                return None
            r = requests.get(NOW_URL, timeout=8, headers={
                "Authorization": f"Bearer {self._access}"})
            if r.status_code == 204:        # nothing playing
                return None
            if r.status_code == 401:        # token died early
                self._access = ""
                return None
            if r.status_code == 429:        # rate limited -- respect the header
                self._backoff_until = time.time() + float(
                    r.headers.get("Retry-After", 5)) + 1
                return None
            if r.status_code != 200:
                self._backoff_until = time.time() + 15
                return None
            d = r.json()
            item = d.get("item") or {}
            if not item:
                return None
            images = (item.get("album") or {}).get("images") or []
            artists = item.get("artists") or []
            return {
                "track_id": item.get("id", ""),
                "title": item.get("name", ""),
                "artist": artists[0].get("name", "") if artists else "",
                "album": (item.get("album") or {}).get("name", ""),
                "art_url": images[0].get("url", "") if images else "",
                "playing": bool(d.get("is_playing")),
            }
        except Exception:
            self._backoff_until = time.time() + 15
            return None


def build_backend(kind="applescript"):
    """Pick a backend, falling back to the other when the preferred one
    isn't usable on this machine."""
    applescript, web = AppleScriptBackend(), WebAPIBackend()
    order = [applescript, web] if kind == "applescript" else [web, applescript]
    for b in order:
        if b.available():
            return b
    return None


# ---------------------------------------------------------------------------
# Provider: polls a backend on its own thread, publishes NowPlaying snapshots
# ---------------------------------------------------------------------------

class NowPlayingProvider:
    """Owns a daemon thread that polls the backend and, whenever the track
    changes, downloads the cover and extracts its palette.

    The render thread only ever calls read(), which returns the last
    published snapshot and never touches the network. That separation is the
    whole point: this codebase is tuned around not stalling the render loop
    (see the perf notes in fx.scratch_surface and PulseScene.draw), and a
    blocking HTTP call in draw() would blow the audio callback's real-time
    deadline every time a track changed.

    Same push-from-one-thread / read-from-another + lock arrangement that
    FeatureExtractor already uses.
    """

    def __init__(self, backend, poll_interval=None):
        self.backend = backend
        self.interval = poll_interval or getattr(backend, "poll_interval", 3.0)
        self._lock = threading.Lock()
        self._current = None
        self._thread = None
        self._stop = threading.Event()
        self._conv_id = None     # track whose art has been display-converted

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        if self.backend is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def read(self):
        """Called once per frame from the render thread. Cheap and never
        blocks on I/O."""
        with self._lock:
            np_ = self._current
        if np_ is None:
            return None
        # Surfaces are decoded on the worker thread, but .convert() needs the
        # display context and so must happen here, on the main thread. Once
        # per track; harmless to leave unconverted if there's no display yet
        # (headless tests).
        if np_.art is not None and np_.track_id != self._conv_id:
            try:
                np_.art = np_.art.convert()
                self._conv_id = np_.track_id
            except pygame.error:
                pass
        return np_

    # -- worker ------------------------------------------------------------
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass  # a backend hiccup must never kill the thread
            # sleep in slices so stop() stays responsive
            self._stop.wait(self.interval)

    def _tick(self):
        info = self.backend.poll()
        if info is None:
            # Nothing playing / Spotify closed: keep the last known track but
            # mark it paused, so the visuals hold their colors instead of
            # snapping back to the default palette on every pause.
            with self._lock:
                if self._current is not None:
                    self._current.playing = False
            return

        with self._lock:
            prev = self._current
        if prev is not None and prev.track_id == info["track_id"]:
            with self._lock:
                self._current.playing = info["playing"]
            return

        art, palette, accent = None, (), (255, 255, 255)
        if info.get("art_url"):
            art = self._fetch_art(info["art_url"])
            if art is not None:
                palette = fx.palette_from_surface(art, n=PALETTE_N)
                accent = fx.most_vivid(palette)

        np_ = NowPlaying(
            track_id=info["track_id"], title=info["title"],
            artist=info["artist"], album=info["album"],
            art_url=info["art_url"], art=art, palette=palette,
            accent=accent, playing=info["playing"],
        )
        with self._lock:
            self._current = np_

    def _fetch_art(self, url):
        if requests is None:
            return None
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                return None
            surf = pygame.image.load(io.BytesIO(r.content))
            # decode+scale here on the worker; only .convert() needs the
            # main thread (see read())
            return pygame.transform.smoothscale(surf, (ART_SIZE, ART_SIZE))
        except Exception:
            return None


def build_provider(kind="applescript"):
    """Convenience: backend + provider in one call. Returns None when no
    backend is usable, which callers treat as 'no Spotify integration'."""
    backend = build_backend(kind)
    if backend is None:
        return None
    return NowPlayingProvider(backend)


if __name__ == "__main__":
    # Standalone check: prints the current track and its palette without
    # opening a window.  python nowplaying.py [applescript|web]
    import sys

    pygame.init()
    kind = sys.argv[1] if len(sys.argv) > 1 else "applescript"
    backend = build_backend(kind)
    if backend is None:
        raise SystemExit("no usable backend (Spotify.app missing, or set SPOTIFY_CLIENT_ID)")
    print(f"backend: {backend.name}")
    info = backend.poll()
    if info is None:
        raise SystemExit("nothing playing (is Spotify running and unpaused?)")
    print(f"track   : {info['title']} - {info['artist']}")
    print(f"album   : {info['album']}")
    print(f"playing : {info['playing']}")
    prov = NowPlayingProvider(backend)
    art = prov._fetch_art(info["art_url"]) if info.get("art_url") else None
    if art is None:
        raise SystemExit("no art")
    pal = fx.palette_from_surface(art, n=PALETTE_N)
    print(f"palette : {pal}")
    print(f"accent  : {fx.most_vivid(pal)}")
