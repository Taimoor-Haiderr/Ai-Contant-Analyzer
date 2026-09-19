"""
Minimal HTTP wrapper around the Phase 1 engine.

This file adds NO processing logic. Every route is a thin translation between
HTTP and a function that already exists in `api.py`:

    POST /api/analyze/text     -> api.analyze_text
    POST /api/rewrite/text     -> api.rewrite_text
    POST /api/analyze/file     -> api.analyze_file
    POST /api/rewrite/file     -> api.rewrite_file
    POST /api/export/<job_id>  -> api.export_result

State lives in two process-memory dictionaries that vanish on restart. There is
no database, no user accounts and no persistence layer.

Run:  python server.py     ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import mimetypes
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

import api
from config import BASE_DIR, INPUT_DIR, OUTPUT_DIR, ensure_directories, get_settings
from processors import SUPPORTED_EXTENSIONS

FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = INPUT_DIR / "uploads"
MAX_UPLOAD_MB = 25

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# In-memory session state. Cleared whenever the server restarts.
JOBS: dict[str, dict] = {}      # job_id  -> engine result
UPLOADS: dict[str, dict] = {}   # file_id -> {"path": Path, "name": original name}
DOWNLOADS: dict[str, Path] = {}  # token  -> file on disk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _token_for(path: str | Path) -> str:
    """Register a file for download and return an opaque token."""
    token = secrets.token_urlsafe(12)
    DOWNLOADS[token] = Path(path).resolve()
    return token


def _label_for(key: str) -> str:
    labels = {
        "rewritten_txt": "Rewritten text (.txt)",
        "rewritten_document": "Rewritten document",
        "result_json": "Full result (JSON)",
        "report_txt": "Analysis report (.txt)",
        "report_json": "Analysis report (JSON)",
        "report_html": "Analysis report (HTML)",
        "report_pdf": "Analysis report (PDF)",
        "original": "Original file (untouched)",
    }
    return labels.get(key, key.replace("_", " ").capitalize())


def _attach_job(result: dict, original_path: Path | None = None) -> dict:
    """Give a successful result a job id plus ready-to-use download tokens."""
    if not result.get("ok"):
        return result

    job_id = secrets.token_urlsafe(10)
    result["job_id"] = job_id
    result["created_at"] = datetime.now().isoformat(timespec="seconds")

    downloads = []
    if original_path and Path(original_path).exists():
        downloads.append(
            {
                "key": "original",
                "label": _label_for("original"),
                "filename": Path(original_path).name,
                "token": _token_for(original_path),
            }
        )
    if result.get("output_file"):
        downloads.append(
            {
                "key": "rewritten_document",
                "label": _label_for("rewritten_document"),
                "filename": Path(result["output_file"]).name,
                "token": _token_for(result["output_file"]),
            }
        )
    result["downloads"] = downloads
    JOBS[job_id] = result
    return result


def _error(code: str, message: str, status: int = 400, detail: str | None = None):
    return jsonify({"ok": False, "error": {"code": code, "message": message,
                                           "detail": detail}}), status


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:asset>")
def static_asset(asset: str):
    target = (FRONTEND_DIR / asset).resolve()
    if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.exists():
        return _error("not_found", "Asset not found.", 404)
    return send_from_directory(FRONTEND_DIR, asset)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """Safe configuration summary. The API key itself is never included."""
    settings = get_settings()
    return jsonify(
        {
            "ok": True,
            "engine": "ready",
            "mode": "mock" if settings.use_mock else "model",
            "provider": settings.provider,
            "model_name": settings.model_name or None,
            "api_key_configured": settings.has_api_key,
            "test_mode": settings.test_mode,
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_chunk_chars": settings.max_chunk_chars,
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS.keys()),
            "session_jobs": len(JOBS),
        }
    )


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
@app.post("/api/analyze/text")
def analyze_text():
    text = _json_body().get("text", "")
    if not str(text).strip():
        return _error("empty_content", "Please enter some text to analyze.")
    return jsonify(_attach_job(api.analyze_text(text)))


@app.post("/api/rewrite/text")
def rewrite_text():
    body = _json_body()
    text = body.get("text", "")
    if not str(text).strip():
        return _error("empty_content", "Please enter some text to rewrite.")
    result = api.rewrite_text(text, include_analysis=bool(body.get("include_analysis", True)))
    return jsonify(_attach_job(result))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
@app.post("/api/upload")
def upload():
    if "file" not in request.files:
        return _error("no_file", "No file was included in the request.")

    upload_file = request.files["file"]
    if not upload_file.filename:
        return _error("no_file", "No file was selected.")

    safe_name = secure_filename(upload_file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return _error(
            "unsupported_file_type",
            f"'{suffix or 'this file'}' is not supported.",
            400,
            "Supported: " + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = UPLOAD_DIR / f"{stamp}_{safe_name}"
    upload_file.save(destination)

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        return _error("empty_content", "That file is empty.")

    file_id = secrets.token_urlsafe(10)
    UPLOADS[file_id] = {"path": destination, "name": upload_file.filename}
    return jsonify(
        {
            "ok": True,
            "file_id": file_id,
            "name": upload_file.filename,
            "stored_name": destination.name,
            "size": destination.stat().st_size,
            "extension": suffix,
            "kind": SUPPORTED_EXTENSIONS[suffix],
        }
    )


def _resolve_upload(file_id: str) -> dict | None:
    entry = UPLOADS.get(file_id or "")
    return entry if entry and entry["path"].exists() else None


def _use_original_name(result: dict, entry: dict) -> dict:
    """
    Show the name the user recognises.

    Uploads are stored under a timestamped name; an engine error would quote
    that internal name, so it is swapped back for the original before the
    message reaches the browser.
    """
    error = result.get("error")
    if error:
        stored = entry["path"].name
        for field in ("message", "detail"):
            if isinstance(error.get(field), str):
                error[field] = error[field].replace(stored, entry["name"])
    return result


@app.post("/api/analyze/file")
def analyze_file():
    entry = _resolve_upload(_json_body().get("file_id", ""))
    if not entry:
        return _error("file_not_found", "That upload is no longer available. "
                                        "Please upload the file again.", 404)
    result = _use_original_name(api.analyze_file(entry["path"]), entry)
    return jsonify(_attach_job(result, original_path=entry["path"]))


@app.post("/api/rewrite/file")
def rewrite_file():
    body = _json_body()
    entry = _resolve_upload(body.get("file_id", ""))
    if not entry:
        return _error("file_not_found", "That upload is no longer available. "
                                        "Please upload the file again.", 404)
    result = api.rewrite_file(
        entry["path"], include_analysis=bool(body.get("include_analysis", True))
    )
    return jsonify(_attach_job(_use_original_name(result, entry),
                               original_path=entry["path"]))


# ---------------------------------------------------------------------------
# Export / download
# ---------------------------------------------------------------------------
@app.post("/api/export/<job_id>")
def export(job_id: str):
    result = JOBS.get(job_id)
    if not result:
        return _error("job_not_found", "That result is no longer in this session. "
                                       "Run the analysis again.", 404)

    formats = _json_body().get("formats") or ["txt", "json", "html", "pdf"]
    exported = api.export_result(result, formats=tuple(formats))
    if not exported.get("ok"):
        return jsonify(exported), 500

    files = []
    for key, path in exported["files"].items():
        if key.endswith("_error"):
            continue
        files.append(
            {
                "key": key,
                "label": _label_for(key),
                "filename": Path(path).name,
                "token": _token_for(path),
            }
        )

    existing = {d["key"] for d in result.get("downloads", [])}
    result.setdefault("downloads", []).extend(
        item for item in files if item["key"] not in existing
    )
    return jsonify({"ok": True, "files": files, "downloads": result["downloads"]})


@app.get("/api/download/<token>")
def download(token: str):
    path = DOWNLOADS.get(token)
    if not path or not path.exists():
        return _error("file_not_found", "That download has expired.", 404)
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype=guessed)


@app.post("/api/session/clear")
def clear_session():
    """Forget this session's in-memory results. Files on disk are left alone."""
    JOBS.clear()
    UPLOADS.clear()
    DOWNLOADS.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Error handling - nothing internal is ever leaked to the browser
# ---------------------------------------------------------------------------
@app.errorhandler(RequestEntityTooLarge)
def too_large(_exc):
    return _error("file_too_large",
                  f"That file is larger than the {MAX_UPLOAD_MB} MB limit.", 413)


@app.errorhandler(404)
def not_found(_exc):
    return _error("not_found", "Not found.", 404)


@app.errorhandler(Exception)
def unexpected(exc):
    app.logger.exception("Unhandled error", exc_info=exc)   # full detail to the console only
    return _error("server_error", "Something went wrong on the server.", 500)


if __name__ == "__main__":
    ensure_directories()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    print("=" * 62)
    print("  AI Content Analyzer & Natural Rewriter")
    print("=" * 62)
    print(f"  Engine mode : {'OFFLINE TEST MODE' if settings.use_mock else 'model'}")
    print(f"  Model       : {settings.model_name or '(not set)'}")
    print(f"  Output      : {OUTPUT_DIR}")
    print("  Open        : http://127.0.0.1:5000")
    print("=" * 62)
    app.run(host="127.0.0.1", port=5000, debug=False)
