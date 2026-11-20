"""Score workspace backed by local SQLite or hosted PostgreSQL."""
from __future__ import annotations

from types import SimpleNamespace
from . import accounts
import argparse
from contextlib import contextmanager, nullcontext
import base64
import functools
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
import errno
import gzip
import io
import zipfile
import urllib.request
from xml.etree.ElementTree import ParseError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .document import (MAX_BYTES, append_bar, remove_tuplet, edit_symbol, move_part, rename_part, edit_note, insert_after_note, place_note, edit_meter, engrave, inspect,
                       new_score, read_xml, replace_bar, xml_bytes)

from PIL import Image
from .scan_preprocess import prepare_for_omr
from .pdf_meter import recover_opening_meter, recover_opening_tempo
from .pdf_resolution import dense_score_dpi
from .recognition_profile import recognition_flags, experiment_flags, page_evidence
from .scan_compare import compare, describe
from .scan_options import selected_pages, repair_satb_book, repair_empty_run_tables

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "static"


def scan_status(server, job):
    """Stage progress is real; recognition itself has no reliable percentage."""
    result = dict(server.jobs.get(job, {"status": "error", "error": "Job not found."}))
    if "started" in result:
        result["elapsed"] = max(0, int(result.get("finished", time.time()) - result["started"]))
    if result.get("status") == "running" and result.get("stage") == 1:
        log = server.library.path.parent / "scans" / job / "recognition.log"
        try:
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 12000))
                entries = re.findall(r"StepMonitoring[^\n]*\|\s*([A-Z_]+)", stream.read().decode("utf-8", errors="replace"))
            if entries:
                result["detail"] = "Recognizing: " + entries[-1].lower().replace("_", " ")
        except OSError:
            pass
    return result


def audiveris_path():
    configured = os.environ.get("AUDIVERIS_CMD")
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    private = ROOT / "build" / "studio-audiveris"
    if (private / "app/solfa-engine-v1").is_file() and (private / "Audiveris.exe").is_file():
        return str(private / "Audiveris.exe")
    return shutil.which("audiveris") or next((str(p) for p in [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Audiveris/Audiveris.exe"
    ] if p.is_file()), None)


def available_title(db, requested, exclude=None):
    title = requested.strip() or "Untitled score"
    rows = db.execute("SELECT meta FROM scores WHERE id <> ?", (exclude or "",))
    records = (json.loads(row["meta"]) for row in rows)
    occupied = {meta["title"].strip().casefold() for meta in records if not meta.get("trashed")}
    if title.casefold() not in occupied:
        return title
    stem, extension = os.path.splitext(title)
    if extension.lower() not in {".pdf", ".musicxml", ".mxl", ".xml", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        stem, extension = title, ""
    stem = re.sub(r" \(\d+\)$", "", stem)
    number = 1
    while f"{stem} ({number}){extension}".casefold() in occupied:
        number += 1
    return f"{stem} ({number}){extension}"


class PostgresQueries:
    """The shared library queries use SQLite-style parameter markers."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        return self.connection.execute(query.replace("?", "%s"), params)


class Library:
    def __init__(self, path, database_url=None, schema="public"):
        self.path = Path(path)
        self.database_url = database_url
        self.schema = schema
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = "BYTEA" if database_url else "BLOB"
        identity = "BIGSERIAL" if database_url else "INTEGER"
        with self.connect() as db:
            if database_url and schema != "public":
                from psycopg import sql
                db.connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            if database_url and schema == "public":
                db.execute("CREATE TABLE IF NOT EXISTS studio_users (name TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL, space TEXT UNIQUE NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS studio_invites (hash TEXT PRIMARY KEY, expires DOUBLE PRECISION NOT NULL)")
            db.execute(f"""CREATE TABLE IF NOT EXISTS redo_history (
                id {identity} PRIMARY KEY, score TEXT, xml {blob}, meta TEXT)""")
            db.execute(f"""CREATE TABLE IF NOT EXISTS scores (
                id TEXT PRIMARY KEY, xml {blob} NOT NULL, meta TEXT NOT NULL,
                source {blob}, source_type TEXT, updated DOUBLE PRECISION NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1)""")
            db.execute(f"""CREATE TABLE IF NOT EXISTS history (
                id {identity} PRIMARY KEY, score TEXT, xml {blob}, meta TEXT)""")

    @contextmanager
    def connect(self):
        if self.database_url:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=12) as conn:
                conn.execute("SELECT set_config('search_path', %s, true)", (self.schema,))
                yield PostgresQueries(conn)
        else:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def lock_writes(self, db):
        if self.database_url:
            db.execute("LOCK TABLE scores IN SHARE ROW EXCLUSIVE MODE")
        else:
            db.execute("BEGIN IMMEDIATE")

    def list(self):
        with self.connect() as db:
            return [{"id": r["id"], **json.loads(r["meta"]), "updated": r["updated"], "revision": r["revision"]}
                    for r in db.execute("SELECT id,meta,updated,revision FROM scores ORDER BY updated DESC")]

    def get(self, sid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scores WHERE id=?", (sid,)).fetchone()
            if row is None: raise ValueError("Score not found.")
            result = dict(row)
            result["meta"] = json.loads(result["meta"])
            return result

    def add(self, data, meta=None, source=None, source_type=None):
        root = read_xml(data)
        info = inspect(root)
        sid = uuid.uuid4().hex
        meta = {"title": info["title"], "composer": info["composer"], "group": "Ungrouped",
                "bookmarks": [], "reviewed": False, "origin": "MusicXML", **(meta or {})}
        with self.connect() as db:
            self.lock_writes(db)
            meta["title"] = available_title(db, meta["title"])
            meta["created"] = time.time()
            db.execute("INSERT INTO scores VALUES (?,?,?,?,?,?,1)",
                       (sid, xml_bytes(root), json.dumps(meta), source, source_type, meta["created"]))
        return sid

    def update(self, sid, revision, data=None, metadata=None, undo=False, redo=False):
        with self.connect() as db:
            self.lock_writes(db)
            row = db.execute("SELECT * FROM scores WHERE id=?", (sid,)).fetchone()
            if row is None: raise ValueError("Score not found.")
            if row["revision"] != revision:
                raise ValueError("This score changed in another window. Reopen it before editing.")
            meta = json.loads(row["meta"])
            if undo or redo:
                source, target = ("history", "redo_history") if undo else ("redo_history", "history")
                old = db.execute(f"SELECT * FROM {source} WHERE score=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
                if old is None: raise ValueError("No more changes in this direction.")
                db.execute(f"INSERT INTO {target}(score,xml,meta) VALUES (?,?,?)", (sid,row["xml"],row["meta"]))
                data, meta = old["xml"], json.loads(old["meta"])
                db.execute(f"DELETE FROM {source} WHERE id=?", (old["id"],))
            else:
                self.remember(db, sid, row)
                if metadata is not None:
                    for field in ("group", "bookmarks", "reviewed", "mixer", "practice", "annotations", "playbackReady", "scanError", "title", "trashed"):
                        if field in metadata: meta[field] = metadata[field]
                if data is not None:
                    info = inspect(read_xml(data))
                    meta.update(title=meta.get("title", info["title"]), composer=info["composer"], reviewed=False)
            if row["revision"] == 1:
                meta.setdefault("created", row["updated"])
            if not meta.get("trashed") and (undo or redo or (metadata and ("title" in metadata or "trashed" in metadata))):
                meta["title"] = available_title(db, meta["title"], sid)
            db.execute("UPDATE scores SET xml=?,meta=?,updated=?,revision=revision+1 WHERE id=?",
                       (data if data is not None else row["xml"], json.dumps(meta), time.time(), sid))
        return self.get(sid)

    @staticmethod
    def remember(db, sid, row):
        db.execute("DELETE FROM redo_history WHERE score=?", (sid,))
        db.execute("INSERT INTO history(score,xml,meta) VALUES (?,?,?)", (sid, row["xml"], row["meta"]))
        db.execute("DELETE FROM history WHERE score=? AND id NOT IN (SELECT id FROM history WHERE score=? ORDER BY id DESC LIMIT 50)", (sid, sid))


def pdf_dimensions(row):
    if row["source_type"] != "application/pdf" or not row["source"]:
        return []
    import pymupdf
    try:
        with pymupdf.open(stream=row["source"], filetype="pdf") as doc:
            return [[round(page.rect.width,2),round(page.rect.height,2)] for page in doc]
    except (ValueError, RuntimeError):
        return []


@functools.lru_cache(maxsize=6)
def rendered(data, mode, minor_do, solfa, paper=None, compact=False, tenor_part="auto"):
    return engrave(data, mode, minor_do, solfa, paper, compact, tenor_part)


def seed(library):
    if library.list(): return
    data = new_score("Morning light", "A practice sketch · Solfa Studio", bars=8)
    phrases = [
        ["C5/q D5/q E5/q G5/q", "A5/h G5/h", "F5/q E5/q D5/h", "E5/w", "G5/q A5/q G5/q E5/q", "F5/h D5/h", "E5/q D5/q C5/q B4/q", "C5/w"],
        ["G4/h C5/h", "C5/w", "A4/h B4/h", "C5/w", "C5/h B4/h", "A4/h B4/h", "G4/h G4/h", "G4/w"],
        ["E4/w", "E4/h D4/h", "F4/h G4/h", "G4/w", "E4/h G4/h", "F4/w", "E4/h D4/h", "E4/w"],
        ["C3/w", "A2/h E3/h", "F3/h G3/h", "C3/w", "C3/h E3/h", "D3/h G2/h", "C3/h G2/h", "C3/w"]]
    for pi, bars in enumerate(phrases):
        for mi, phrase in enumerate(bars): data = replace_bar(data, pi, mi, phrase)
    library.add(data, {"group": "Practice room", "origin": "Demo", "reviewed": True,
                       "bookmarks": [{"measure": 4, "label": "Second phrase"}]})


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows permits two listeners with SO_REUSEADDR; never shadow another app.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, library):
        super().__init__(address, Handler)
        self.workspaces = {}
        self.workspace_lock = threading.Lock()
        self.login_slots = threading.BoundedSemaphore(2)
        self.scan_lock = threading.Lock()
        self.public_host = None
        self.workspace_password = None
        self.library, self.token, self.jobs = library, secrets.token_urlsafe(32), {}


class Handler(BaseHTTPRequestHandler):
    server_version = "SolfaStudio/1.0"

    def log_message(self, *_):
        pass

    def respond(self, data, kind="application/json", status=200, etag=None, cookie=None):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode() if kind == "application/json" else data.encode()
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
            self.end_headers()
            return
        compressed = len(data) > 4096 and "gzip" in self.headers.get("Accept-Encoding", "") and (
            "json" in kind or kind.startswith("text/") or "javascript" in kind)
        if compressed:
            data = gzip.compress(data, compresslevel=3)
        self.send_response(status)
        if cookie: self.send_header("Set-Cookie",cookie)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate" if etag else "no-store")
        if etag: self.send_header("ETag", etag)
        self.send_header("Vary", "Accept-Encoding")
        if compressed: self.send_header("Content-Encoding", "gzip")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; media-src 'self' blob:; object-src 'self'; frame-src 'self'; connect-src 'self'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.server.public_host:
            return self.headers.get("Host") == self.server.public_host and self.headers.get("Origin") in (
                None, "https://" + self.server.public_host)
        return self.headers.get("Host") in allowed and (
            not self.headers.get("Origin") or self.headers["Origin"] in {f"http://{h}" for h in allowed})

    def authenticated(self):
        self.workspace = self.server
        self.username = None
        if self.server.public_host is None:
            return True
        identity = accounts.session_identity(self.headers.get("Cookie"), self.server.workspace_password)
        if identity is None:
            if urlparse(self.path).path == "/":
                self.respond((STATIC/"login.html").read_bytes(),"text/html")
            else:
                self.respond({"error":"Sign in to your workspace."},status=401)
            return False
        self.username, schema = identity
        if schema != "public":
            with self.server.workspace_lock:
                if schema not in self.server.workspaces:
                    library = self.server.library
                    self.server.workspaces[schema] = SimpleNamespace(
                        library=Library(library.path,library.database_url,schema),
                        jobs={},token=secrets.token_urlsafe(32),public_host=self.server.public_host,
                        scan_lock=self.server.scan_lock)
                self.workspace = self.server.workspaces[schema]
        return True

    def sign_in(self, registering):
        if not self.server.login_slots.acquire(blocking=False):
            return self.respond({"error":"Please retry in a moment."},status=429)
        try:
            length = int(self.headers.get("Content-Length",0))
            if not 0 < length <= 4096: raise ValueError("Invalid sign-in request.")
            payload = json.loads(self.rfile.read(length))
            identity = accounts.authenticate(self.server.library,self.server.workspace_password,payload,registering)
            self.respond({"ok":True},cookie=accounts.session_cookie(identity,self.server.workspace_password))
        except (ValueError,TypeError):
            self.respond({"error":"Check your username and password, or request a fresh invitation."},status=400)
        finally:
            self.server.login_slots.release()

    def do_GET(self):
        if self.path == "/healthz":
            return self.respond({"status": "ok"})
        if not self.allowed(): return self.respond({"error": "Local access only."}, status=403)
        path = urlparse(self.path)
        public_assets = {
            "/login.js": "text/javascript", "/login.css": "text/css",
            "/wordmark.css": "text/css", "/fonts/pinyon/PinyonScript-Regular.ttf": "font/ttf",
        }
        if path.path in public_assets:
            file = STATIC / path.path[1:]
            return self.respond(file.read_bytes(),public_assets[path.path],etag=f'"{file.stat().st_mtime_ns:x}"')
        if not self.authenticated(): return
        try:
            if path.path == "/api/library":
                return self.respond({"scores": self.workspace.library.list(), "scanner": bool(audiveris_path()),
                                     "storage": "Neon" if self.server.public_host else str(self.workspace.library.path), "build": "2026-11-18-personal-libraries",
                                     "scanJobs": [{"job": job, **scan_status(self.workspace, job)} for job in list(self.workspace.jobs)]})
            if path.path.startswith("/api/job/"):
                return self.respond(scan_status(self.workspace, path.path.split("/")[-1]))
            if path.path.startswith("/api/score/"):
                row = self.workspace.library.get(path.path.split("/")[-1])
                q = parse_qs(path.query)
                mode = q.get("mode", ["movable"])[0]
                if mode not in ("movable", "fixed", "pitch"): raise ValueError("Invalid sol-fa mode.")
                sizes = pdf_dimensions(row)
                chosen = [int(n) for n in row["meta"].get("scanPages",[]) if 1 <= int(n) <= len(sizes)]
                paper = tuple(sizes[(chosen or [1])[0]-1]) if sizes else None
                result = rendered(row["xml"], mode, q.get("minor", ["false"])[0] == "true", q.get("solfa", ["true"])[0] == "true", paper, q.get("compact")==["true"], q.get("tenor", ["auto"])[0])
                return self.respond({**result, "sourceSizes": sizes, "sourcePages": chosen, "id": row["id"], "meta": row["meta"], "revision": row["revision"], "hasSource": row["source"] is not None, "sourceType": row["source_type"], "title": row["meta"].get("title", result["title"])})
            if path.path.startswith("/api/bundle/"):
                row = self.workspace.library.get(path.path.split("/")[-1])
                title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", row["meta"]["title"]).strip(" .")[:120] or "Score"
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                    bundle.writestr(f"{title}/{title}.musicxml", row["xml"])
                    if row["source"] is not None:
                        extension = mimetypes.guess_extension(row["source_type"] or "") or ".bin"
                        bundle.writestr(f"{title}/Original{extension}", row["source"])
                return self.respond(archive.getvalue(), "application/zip")
            if path.path.startswith("/api/xml/"):
                row = self.workspace.library.get(path.path.split("/")[-1])
                return self.respond(row["xml"], "application/vnd.recordare.musicxml+xml")
            if path.path.startswith("/api/source/"):
                row = self.workspace.library.get(path.path.split("/")[-1])
                if row["source"] is None: raise ValueError("No source scan is attached.")
                return self.respond(row["source"], row["source_type"])
            if path.path == "/api/session": return self.respond({"token": self.workspace.token, "username": self.username})
            relative = "index.html" if path.path == "/" else path.path.lstrip("/")
            file = (STATIC / relative).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                return self.respond({"error": "Not found"}, status=404)
            kind = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix, mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            stat = file.stat()
            return self.respond(file.read_bytes(), kind, etag=f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"')
        except (ValueError, KeyError, IndexError, RuntimeError, OSError) as exc:
            self.respond({"error": str(exc)}, status=400)
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond({"error": "Could not process this score. Check its MusicXML structure."}, status=422)

    def do_POST(self):
        if not self.allowed(): return self.respond({"error":"Invalid request origin."},status=403)
        if self.server.public_host and self.path in ("/api/login","/api/register"):
            if self.headers.get_content_type() != "application/json": return self.respond({"error":"JSON required."},status=400)
            return self.sign_in(self.path == "/api/register")
        if not self.authenticated(): return
        if not self.allowed() or self.headers.get("X-Studio-Token") != self.workspace.token:
            return self.respond({"error": "Reload the local app to continue."}, status=403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BYTES * 1.4: raise ValueError("Request is empty or too large (40 MB file limit).")
            payload = json.loads(self.rfile.read(length))
            route = urlparse(self.path).path
            lib = self.workspace.library
            if route == "/api/page-trial":
                row = lib.get(payload["id"])
                if row["source_type"] != "application/pdf" or not row["meta"].get("playbackReady", True) or row["meta"].get("pageTrial"):
                    raise ValueError("Choose a recognized score with its original PDF.")
                page = int(payload["page"])
                pages = list(map(int, row["meta"].get("scanPages") or range(1, len(pdf_dimensions(row))+1)))
                if page not in pages:
                    raise ValueError("Choose a page included in the baseline scan.")
                profile = payload.get("profile")
                if profile not in ("evidence", "poor", "synthetic", "leland", "leland-synthetic", "bravura"):
                    raise ValueError("Choose a trial profile.")
                command = audiveris_path()
                if not command:
                    raise ValueError("Audiveris is unavailable.")
                job = uuid.uuid4().hex
                name = f'{row["meta"]["title"]} · page {page} trial'
                with self.server.workspace_lock:
                    if any(j.get("parent") == row["id"] and j["status"] == "running" for j in self.workspace.jobs.values()):
                        raise ValueError("A page trial is already running for this score.")
                    self.workspace.jobs[job] = {"status":"running", "parent":row["id"], "stage":0,
                                                "started":time.time(), "name":name, "message":"Preparing one-page trial"}
                threading.Thread(target=page_trial, args=(self.workspace, job, command, row, page, pages, profile), daemon=True).start()
                return self.respond({"job":job, "name":name})
            if route == "/api/invite" and self.username == "studio":
                return self.respond({"invite":accounts.invite(lib)})
            if route == "/api/logout":
                return self.respond({"ok":True},cookie="solfa_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax")
            if route == "/api/new":
                return self.respond({"id": lib.add(new_score(**payload), {"origin": "Composition"})})
            if route == "/api/import-pair":
                pdf = base64.b64decode(payload["pdf"], validate=True)
                notation = base64.b64decode(payload["data"], validate=True)
                if not pdf.startswith(b"%PDF-") or len(pdf)+len(notation)>MAX_BYTES:
                    raise ValueError("Choose a PDF and matching MusicXML under 40 MB combined.")
                name = payload["name"]
                meta = {"title": name, "sourceFileName": name, "origin": "Paired MusicXML", "playbackReady": True}
                return self.respond({"id": lib.add(notation, meta, pdf, "application/pdf")})
            if route == "/api/import":
                data = base64.b64decode(payload["data"], validate=True)
                return self.respond({"id": lib.add(data, {"title": payload["name"], "sourceFileName": payload["name"]})})
            if route in ("/api/scan", "/api/rescan"):
                options = payload.get("options", {})
                pages = selected_pages(options.get("pages"))
                language = options.get("language", "default")
                if language not in ("default","eng","chi_tra+eng","chi_sim+eng"): raise ValueError("Unsupported text language.")
                cue_mode = options.get("cueNotes", "auto")
                if cue_mode not in ("auto", "on", "off"): raise ValueError("Unknown cue-note setting.")
                layout = options.get("layout", "auto")
                if layout not in ("auto", "satb-piano", "satb", "piano"): raise ValueError("Unknown ensemble preset.")
                rescan_row = lib.get(payload["id"]) if route == "/api/rescan" else None
                if rescan_row:
                    if rescan_row["source"] is None: raise ValueError("No original scan is attached.")
                    if any(j.get("id") == payload["id"] and j.get("status") == "running" for j in self.workspace.jobs.values()): raise ValueError("This score is already scanning.")
                    payload["name"] = rescan_row["meta"].get("sourceFileName", rescan_row["meta"]["title"])
                command = audiveris_path()
                data = rescan_row["source"] if rescan_row else base64.b64decode(payload["data"], validate=True)
                ext = Path(payload["name"]).suffix.lower()
                if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff") or len(data) > MAX_BYTES:
                    raise ValueError("Choose a PDF, PNG, JPEG or TIFF under 40 MB.")
                sid = payload["id"] if rescan_row else lib.add(new_score(title=Path(payload["name"]).stem, template="melody", bars=1), {"origin": "Scan", "playbackReady": False, "title": payload["name"], "sourceFileName": payload["name"]}, data, "application/pdf" if ext == ".pdf" else mimetypes.guess_type(payload["name"])[0])
                if not command: return self.respond({"id": sid, "job": None})
                job = uuid.uuid4().hex
                self.workspace.jobs[job] = {"status": "running", "stage": 0, "started": time.time(), "id": sid,
                                         "name": payload["name"], "message": "Preparing scan"}
                threading.Thread(target=run_scan, args=(self.workspace, job, command, data, ext, sid, {"pages": pages, "layout": layout, "cueNotes": cue_mode, "language": language}), daemon=True).start()
                return self.respond({"job": job, "id": sid})
            sid, revision = payload["id"], int(payload["revision"])
            row = lib.get(sid)
            if route == "/api/duplicate":
                meta = dict(row["meta"])
                meta.update(trashed=False)
                return self.respond({"id": lib.add(row["xml"], meta, row["source"], row["source_type"])})
            if route == "/api/meta":
                result = lib.update(sid, revision, metadata=payload["meta"])
            elif route in ("/api/undo","/api/redo"): result = lib.update(sid,revision,undo=route=="/api/undo",redo=route=="/api/redo")
            elif route == "/api/edit":
                action = payload["action"]
                metadata = None
                if action == "note": data = edit_note(row["xml"], **payload["values"])
                elif action == "place": data = place_note(row["xml"], **payload["values"])
                elif action == "insert-note": data = insert_after_note(row["xml"], **payload["values"])
                elif action == "remove-tuplet": data = remove_tuplet(row["xml"], **payload["values"])
                elif action == "symbol": data = edit_symbol(row["xml"], **payload["values"])
                elif action == "move-part":
                    values = payload["values"]
                    data = move_part(row["xml"], **values)
                    first = values["part"]
                    second = first + values["direction"]
                    mixer = list(row["meta"].get("mixer") or [])
                    if mixer:
                        while len(mixer) <= max(first, second):
                            mixer.append({})
                        mixer[first], mixer[second] = mixer[second], mixer[first]
                        metadata = {"mixer": mixer}
                elif action == "rename-part": data = rename_part(row["xml"], **payload["values"])
                elif action == "bar": data = replace_bar(row["xml"], **payload["values"])
                elif action == "append": data = append_bar(row["xml"])
                elif action == "meter": data = edit_meter(row["xml"], **payload["values"])
                elif action == "xml": data = xml_bytes(read_xml(payload["xml"].encode()))
                else: raise ValueError("Unknown edit action.")
                # Validate engraving before making the new document durable.
                rendered(data, "movable", False, True)
                result = lib.update(sid, revision, data=data, metadata=metadata)
            else: raise ValueError("Unknown operation.")
            self.respond({"id": sid, "revision": result["revision"], "meta": result["meta"]})
        except Exception as exc:
            self.respond({"error": str(exc) or "Could not save the score."}, status=400)


def run_scan(server, job, *args):
    if server.public_host:
        with server.scan_lock:
            scan(server, job, *args)
    else:
        scan(server, job, *args)


def page_trial(server, job, command, row, page, pages, profile):
    """Keep an independent full-page candidate and its source coordinates. Never splice bars."""
    import pymupdf
    state = server.jobs[job]
    def progress(stage, message):
        state.update(stage=stage, message=message)
    try:
        with server.scan_lock if server.public_host else nullcontext():
            with pymupdf.open(stream=row["source"], filetype="pdf") as original, pymupdf.open() as subset:
                subset.insert_pdf(original, from_page=page-1, to_page=page-1)
                data = subset.tobytes()
                font, quality = page_evidence(subset[0]) if profile == "evidence" else {
                    "poor": (None, "Poor"), "synthetic": (None,"Synthetic"),
                    "leland": ("Leland", None), "leland-synthetic": ("Leland", "Synthetic"),
                    "bravura": ("Bravura", None)}[profile]
            flags = experiment_flags(font, quality)
            if not flags:
                raise ValueError("No reliable profile evidence on this page. Choose a manual trial profile.")
            folder = server.library.path.parent / "scans" / job
            folder.mkdir(parents=True)
            source = folder / "page.pdf"
            source.write_bytes(data)
            progress(1, "Recognizing one complete page")
            prior = row["meta"].get("scanOptions") or {}
            flags += recognition_flags(prior.get("cueNotes", "auto"), data, ".pdf", [1])
            if prior.get("language", "default") != "default":
                flags.extend(["-constant", "org.audiveris.omr.text.Language.defaultSpecification="+prior["language"]])
            if server.public_host:
                flags.extend(["-constant", "org.audiveris.omr.util.OmrExecutors.useParallelism=false"])
            with (folder / "recognition.log").open("w", encoding="utf8") as log:
                prepared = prepare_for_omr(source)
                dpi = dense_score_dpi(data, [1], 12_000_000 if server.public_host else 16_000_000) if source == prepared else None
                if dpi:
                    flags.extend(["-constant", f"org.audiveris.omr.image.ImageLoading.pdfResolution={dpi}"])
                output, _ = recognize_book(command, prepared, folder, flags, [], prior.get("layout","auto"), log, progress)
            if page == pages[0]:
                output = recover_opening_tempo(output, data, 1)
                output, _ = recover_opening_meter(output, data, 1)
            baseline = describe(row["xml"], pages.index(page)+1, len(pages))
            candidate = describe(output)
            evidence = {"parent":row["id"], "revision":row["revision"], "page":page,
                        "sourceSHA256":hashlib.sha256(row["source"]).hexdigest(),
                        "box":[0, 0, 1000, 1000], "font":font, "quality":quality,
                        "candidateParts":candidate[0], "comparison":compare(baseline, candidate) if baseline else None}
            sid = server.library.add(output, {"title":state["name"], "origin":"Scan", "pageTrial":evidence,
                                     "playbackReady":True, "reviewed":False}, data, "application/pdf")
            state.update(status="done", stage=4, message="Page trial ready to compare", id=sid, finished=time.time())
    except Exception as exc:
        state.update(status="error", error=str(exc), message="Page trial could not finish", finished=time.time())


def recognize_book(command, source, folder, settings, sheet_args, layout, log, progress):
    """Transcribe, then export the persisted book to preserve cross-page part assembly."""
    def run(args, check):
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        subprocess.run([command, "-batch", *args], stdout=log, stderr=subprocess.STDOUT,
                       timeout=1200, check=check, **flags)

    print("Recognition settings:", settings or "engine default", file=log, flush=True)
    run(["-step", "PAGE", "-save", *settings, "-output", str(folder), *sheet_args, "--", str(source)], True)
    book = next(folder.rglob("*.omr"), None)
    if book is None:
        raise ValueError("Audiveris did not produce a score book. Inspect the recognition log.")
    repair_empty_run_tables(book)
    layout_warning = None
    if layout != "auto":
        try:
            repair_satb_book(book, layout)
        except ValueError as exc:
            layout_warning = f"Used automatic grouping. {exc}"
            print(layout_warning, file=log)
    progress(2, "Exporting recognized notation")
    for _ in range(2):
        run(["-export", *settings, *sheet_args, "--", str(book)], False)
        exports = sorted(folder.rglob("*.mxl")) or sorted(folder.rglob("*.musicxml"))
        if exports:
            output = exports[0].read_bytes()
            if read_xml(output).find("part/measure/note") is None:
                raise ValueError("Recognition found no readable notes or rests.")
            return output, layout_warning
    raise ValueError("Recognition produced no MusicXML. Review the book in Audiveris.")


def scan(server, job, command, data, ext, sid=None, options=None):
    options = options or {}
    sheet_args = ["-sheets", *options["pages"]] if options.get("pages") else []
    server.jobs.setdefault(job, {"status": "running", "stage": 0, "started": time.time(), "id": sid, "name": "Score scan"})
    def progress(stage, message, **extra):
        server.jobs[job] = {**server.jobs[job], "stage": stage, "message": message, **extra}
    folder = server.library.path.parent / "scans" / job
    source = folder / f"scan{ext}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        with (folder / "recognition.log").open("w", encoding="utf-8") as log:
            progress(1, "Checking page orientation and staff alignment")
            try:
                recognition_source = prepare_for_omr(source, options.get("pages") or ())
            except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
                print(f"Page preparation unavailable; continuing with original: {exc}", file=log)
                recognition_source = source
            progress(1, "Recognizing music · large scores can take several minutes")
            flags_for_book = recognition_flags(options.get("cueNotes", "auto"), data, ext, options.get("pages"))
            if getattr(server, "public_host", None):
                flags_for_book.extend(["-constant", "org.audiveris.omr.util.OmrExecutors.useParallelism=false"])
            language = options.get("language","default")
            if language != "default":
                flags_for_book.extend(["-constant", "org.audiveris.omr.text.Language.defaultSpecification=" + language])
            # Vector inspection only applies to the original engraving. A raster
            # preparation has already been rendered at its available resolution.
            dpi = None
            if ext == ".pdf" and recognition_source == source:
                pixel_budget = 12_000_000 if getattr(server, "public_host", None) else 16_000_000
                dpi = dense_score_dpi(data, options.get("pages"), pixel_budget)
            settings = flags_for_book
            if dpi:
                progress(1, f"Recognizing closely spaced staves at {dpi} DPI")
                settings = [*settings, "-constant", f"org.audiveris.omr.image.ImageLoading.pdfResolution={dpi}"]
            layout = options.get("layout", "auto")
            try:
                output, layout_warning = recognize_book(command, recognition_source, folder, settings,
                                                        sheet_args, layout, log, progress)
            except (subprocess.CalledProcessError, ValueError, zipfile.BadZipFile, ParseError) as exc:
                if not dpi and recognition_source == source:
                    raise
                print(f"Enhanced scan failed: {exc}", file=log, flush=True)
                progress(1, "Retrying the original at standard resolution")
                fallback = folder / "standard"
                fallback.mkdir()
                output, layout_warning = recognize_book(command, source, fallback, flags_for_book,
                                                        sheet_args, layout, log, progress)
        progress(3, "Checking and saving the result")
        meter = None
        if ext == ".pdf":
            pages = options.get("pages") or [1]
            output = recover_opening_tempo(output, data, int(pages[0]))
            output, meter = recover_opening_meter(output, data, int(pages[0]))
        if meter:
            server.jobs[job]["meterEvidence"] = f"Opening {meter[0]}/{meter[1]} recovered from matching printed meter symbols."
        # A readable export is still unverified; keep its source for comparison.
        inspect(read_xml(output))
        if sid is None:
            sid = server.library.add(output, {"origin": "Scan", "reviewed": False, "playbackReady": True,
                                     "scanOptions": options, "scanPages":options.get("pages") or []}, data,
                                     "application/pdf" if ext == ".pdf" else mimetypes.guess_type(source.name)[0])
        else:
            # Scan completion must not overwrite concurrent annotation edits.
            with server.library.connect() as db:
                server.library.lock_writes(db)
                row = db.execute("SELECT xml,meta FROM scores WHERE id=?", (sid,)).fetchone()
                meta = json.loads(row["meta"])
                if meta.get("playbackReady", True):
                    server.library.remember(db, sid, row)
                else:
                    db.execute("DELETE FROM redo_history WHERE score=?", (sid,))
                meta.update(playbackReady=True, reviewed=False, reviewNote=layout_warning or "", scanOptions=options, scanPages=options.get("pages") or [])
                db.execute("UPDATE scores SET xml=?,meta=?,updated=?,revision=revision+1 WHERE id=?", (xml_bytes(read_xml(output)),json.dumps(meta),time.time(),sid))
        progress(4, "Scan ready · check the result against the original", status="done", id=sid, finished=time.time())
    except Exception as exc:
        progress(server.jobs[job].get("stage", 0), "Scanning failed · your original is still available", status="error",
                 finished=time.time(), error=f"{exc} Log: {folder / 'recognition.log'}")


def start_or_reuse(port, library, open_browser=True):
    """Reuse only a verified Studio serving this same library."""
    url = f"http://127.0.0.1:{port}"
    try:
        return StudioServer(("127.0.0.1", port), library)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE and getattr(exc, "winerror", None) != 10048:
            raise
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url + "/api/library", timeout=2) as response:
                is_studio = response.headers.get("Server", "").startswith("SolfaStudio/")
                info = json.load(response)
            same_library = Path(info.get("storage", "")).resolve() == library.path.resolve()
            if is_studio and same_library and info.get("build") != "2026-11-18-personal-libraries":
                print("An older Studio is running; opening the updated version on the next port.", flush=True)
                return start_or_reuse(port + 1, library, open_browser)
            if is_studio and same_library:
                print(f"Solfa Studio is already running: {url}\nOpening the existing workspace.", flush=True)
                if open_browser:
                    webbrowser.open(url)
                return None
        except (OSError, ValueError, TypeError):
            pass
        raise RuntimeError(
            f"Port {port} is already in use by another app or a different Studio library. "
            f"Start Studio with --port {port + 1}, or close the app using that port."
        ) from None


def main():
    parser = argparse.ArgumentParser(description="Solfa Studio — local music workspace")
    parser.add_argument("--port", type=int, default=8873)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    public_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    database_url = os.environ.get("DATABASE_URL") if public_host else None
    password = os.environ.get("STUDIO_PASSWORD")
    if public_host and not (database_url and password):
        parser.error("Hosted Studio requires DATABASE_URL and STUDIO_PASSWORD.")
    if public_host:
        print("Initializing hosted Postgres library", flush=True)
    lib = Library(args.data_dir / "library.sqlite3", database_url)
    seed(lib)
    try:
        if public_host:
            server = StudioServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), lib)
            server.public_host, server.workspace_password = public_host, password
        else:
            server = start_or_reuse(args.port, lib, open_browser=not args.no_browser)
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"Could not start Studio: {exc}\n")
    if server is None:
        return
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Solfa Studio: {url}\nLibrary: {lib.path}\nPress Ctrl+C to stop.", flush=True)
    if not args.no_browser and not public_host: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
