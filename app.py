from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, send_from_directory, jsonify, g, session
)
from pathlib import Path
from functools import wraps
from io import BytesIO
import sqlite3, time, os, base64, json, ast, re, collections

from PIL import Image, ImageOps, ExifTags

import config

"""Artifact/Site capture app

A webapp to allow field workers and others to take and annotate photos with
suitable metadata in the field and elsewhere.

It supports multiple object types (e.g., artifacts, sites) defined in
config.py as `object_types`. Each object type maps to its own SQLite table and
its own set of fields. Images for all types live in the same UPLOAD_DIR.

Multiple images can be attached to the same record: when a user uploads another
image with identical non-timestamp metadata for the same object type, we append
the new image filenames to JSON lists stored on that record.
"""

import config as app_config

object_types = app_config.object_types
APP_BRAND = getattr(app_config, 'APP_BRAND', 'Artifact Capture')
APP_SUBTITLE = getattr(app_config, 'APP_SUBTITLE', '')
APP_LOGO = getattr(app_config, 'APP_LOGO', 'logo.svg')
ADMIN_LABEL = getattr(app_config, 'ADMIN_LABEL', 'Admin')
DATE_FORMAT = getattr(app_config, 'DATE_FORMAT', '%Y-%m-%d')
TIMESTAMP_FORMAT = getattr(app_config, 'TIMESTAMP_FORMAT', DATE_FORMAT + 'T%H:%M:%S')

APP_ROOT = Path(__file__).parent.resolve()

# Runtime-writable directories / files should be configurable in production.
UPLOAD_DIR = Path(
    os.environ.get("ARTCAP_UPLOAD_DIR", str(APP_ROOT / "uploads"))
).expanduser().resolve()

DB_PATH = Path(
    os.environ.get("ARTCAP_DB_PATH", str(APP_ROOT / "data" / "artifacts.db"))
).expanduser().resolve()

ADMIN_USER = os.getenv("ARTCAP_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ARTCAP_ADMIN_PASS", "change-me")
APP_SECRET = os.getenv("ARTCAP_SECRET", "change-me")

MAX_DIM = int(os.getenv("ARTCAP_MAX_DIM", "3000"))
THUMB_DIM = int(os.getenv("ARTCAP_THUMB_DIM", "400"))
JPEG_QUALITY = int(os.getenv("ARTCAP_JPEG_QUALITY", "92"))
WEBP_QUALITY = int(os.getenv("ARTCAP_WEBP_QUALITY", "85"))


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean env var.

    Accepts: 1/0, true/false, yes/no, on/off (case-insensitive).
    Missing or empty values fall back to `default`.
    """
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    raw = str(raw).strip().lower()
    if raw == "":
        return bool(default)
    return raw in ("1", "true", "yes", "y", "on")


# GPS feature flag.
#
# Precedence:
#   1) If ARTCAP_GPS_ENABLED is set in the environment, it wins.
#   2) Otherwise fall back to config.GPS_ENABLED (if present), else False.
GPS_ENABLED = _env_bool("ARTCAP_GPS_ENABLED", default=getattr(config, "GPS_ENABLED", False))
app = Flask(__name__)

# Grid view sizing (can be overridden in config.py)
GRID_MAX_WIDTH = int(getattr(config, "GRID_MAX_WIDTH", getattr(config, "grid_max_width", 500)))


@app.context_processor
def inject_ui_globals():
    # Make a few UI globals available to all templates
    return {
        "grid_max_width": GRID_MAX_WIDTH,
    }


app.secret_key = APP_SECRET


@app.before_request
def _log_all_posts_to_wsgi():
    """Log all POSTs (including form fields) so they appear in Apache/mod_wsgi logs.

    Note: Apache access logs do not include request bodies by default; this logs to
    the application logger (typically the Apache error log under mod_wsgi).
    """
    try:
        if request.method == "POST":
            form_dict = {k: request.form.getlist(k) if len(request.form.getlist(k)) > 1 else request.form.get(k)
                         for k in request.form.keys()}
            files_dict = {k: (v.filename if v else "") for k, v in (request.files or {}).items()}
            app.logger.info("POST %s form=%s files=%s", request.path, form_dict, files_dict)
    except Exception:
        # Never break requests due to logging.
        pass


def _parse_widget(widget_raw: str):
    """Parse config widget descriptors.

    Supports:
      - DROPDOWN('A','B',...)
      - RADIO('A','B',...)   # rendered as a multi-select checkbox group (0+ selections)
    """
    widget_raw = widget_raw or ""
    if not isinstance(widget_raw, str):
        return "auto", None

    up = widget_raw.strip().upper()
    if up.startswith("DROPDOWN"):
        kind = "dropdown"
    elif up.startswith("RADIO"):
        kind = "radio"
    else:
        return "auto", None

    try:
        start = widget_raw.index("(")
        inside = widget_raw[start:]
        vals = ast.literal_eval(inside)
        if isinstance(vals, (list, tuple)):
            options = [str(v) for v in vals]
        else:
            options = [str(vals)]
        return kind, options
    except Exception:
        print(f"[FATAL] Could not parse widget spec {widget_raw!r} in config.py")
        raise


# Normalize and validate object_types config.
OBJECT_TYPES = object_types or {}
if not isinstance(OBJECT_TYPES, dict) or not OBJECT_TYPES:
    raise RuntimeError("config.py must define a non-empty dict named object_types")

TYPE_META = {}

# Columns that are managed by the server and should not be treated like
# user-configured input fields (e.g., to avoid duplicate display).
# Columns managed by the server (or otherwise "system/reserved").
# These may be hidden by default in some views, but **must be allowed** to appear
# if explicitly referenced in config.py layout_rows/result_rows.
SYSTEM_COLUMNS = {
    "id",
    "gps_lat", "gps_lon", "gps_alt", "gps_acc",
    "thumbs_json", "images_json", "webps_json", "json_files_json",
    "date_last_saved", "date_recorded", "date_updated",
}

for otype, cfg in OBJECT_TYPES.items():
    if not isinstance(cfg, dict):
        raise RuntimeError(f"object_types[{otype!r}] must be a dict")
    label = cfg.get("label") or otype.title()
    input_fields = cfg.get("input_fields") or []
    layout_rows = cfg.get("layout_rows") or []
    result_rows = cfg.get("result_rows") or []  # layout for Recent/Edit results
    # Required fields should only refer to user-configured columns.
    required_fields = tuple([c for c in (cfg.get("required_fields") or ()) if c not in SYSTEM_COLUMNS])
    filename_format = cfg.get("filename_format") or cfg.get("filename_format")
    if not input_fields:
        raise RuntimeError(f"object_types[{otype!r}] has no input_fields")

    field_meta = {}
    for f in input_fields:
        flabel, col, sql_type = f[0], f[1], (f[2] if len(f) > 2 else "TEXT")
        sql_type_str = str(sql_type or "TEXT")
        st_up = sql_type_str.strip().upper()

        constant_value = None
        server_now = False
        if st_up == "CONSTANT":
            # A CONSTANT field is rendered read-only with a fixed value, and stored as TEXT in SQLite.
            widget = "constant"
            options = None
            constant_value = str(f[3]) if len(f) > 3 else ""
            sqlite_type = "TEXT"
            sql_type_str = "TEXT"
        elif st_up == "UPPERCASE":
            # UPPERCASE is a TEXT field rendered with CSS text-transform: uppercase.
            widget = "uppercase"
            options = None
            sqlite_type = "TEXT"
            sql_type_str = "TEXT"
        else:
            widget_raw = f[3] if len(f) > 3 else ""
            widget, options = _parse_widget(widget_raw)
            sqlite_type = sql_type_str
        # Special server-managed timestamps.
        # - date_updated: if the user defines it as TIMESTAMP, manage it as NOW() on save.
        # - date_recorded: if the user defines it as TIMESTAMP, manage it as NOW() on BOTH create and update.
        if str(col).lower() == "date_updated" and st_up.startswith("TIMESTAMP"):
            server_now = True
        if str(col).lower() == "date_recorded" and (st_up.startswith("TIMESTAMP") or st_up == "TIMESTAMP"):
            server_now = True

        field_meta[col] = {
            "label": flabel,
            "col": col,
            "sql_type": sql_type_str,  # for UI decisions
            "sqlite_type": sqlite_type,  # for schema creation
            "widget": widget,
            "options": options,
            "constant_value": constant_value,
            "server_now": server_now,
            "required": col in required_fields,
        }

    # result_rows controls which fields appear (and how they are arranged) in Recent and Edit views.
    # If not provided, we fall back to layout_rows; if still empty, show one field per row.
    result_rows_effective = result_rows or layout_rows or [[f[1]] for f in input_fields if
                                                           (len(f) > 1 and f[1] not in SYSTEM_COLUMNS)]
    # Allow "system/reserved" columns to be displayed if explicitly referenced in
    # layout_rows/result_rows by adding minimal metadata for them.
    referenced_cols = set()
    for _r in (layout_rows or []):
        for _c in (_r or []):
            referenced_cols.add(_c)
    for _r in (result_rows or []):
        for _c in (_r or []):
            referenced_cols.add(_c)

    RESERVED_DEFAULTS = {
        "id": {"label": "ID", "sqlite_type": "INTEGER", "sql_type": "INTEGER", "widget": "readonly", "options": None,
               "constant_value": None, "server_now": False, "required": False},
        "date_last_saved": {"label": "Date last saved", "sqlite_type": "TEXT", "sql_type": "TIMESTAMP",
                            "widget": "text", "options": None,
                            "constant_value": None, "server_now": True, "required": False},
        "date_recorded": {"label": "Date recorded", "sqlite_type": "TEXT", "sql_type": "TIMESTAMP", "widget": "text",
                          "options": None,
                          "constant_value": None, "server_now": True, "required": False},
        "date_updated": {"label": "Date updated", "sqlite_type": "TEXT", "sql_type": "TIMESTAMP", "widget": "text",
                         "options": None,
                         "constant_value": None, "server_now": True, "required": False},
        "gps_lat": {"label": "GPS lat", "sqlite_type": "REAL", "sql_type": "FLOAT", "widget": "text", "options": None,
                    "constant_value": None, "server_now": False, "required": False},
        "gps_lon": {"label": "GPS lon", "sqlite_type": "REAL", "sql_type": "FLOAT", "widget": "text", "options": None,
                    "constant_value": None, "server_now": False, "required": False},
        "gps_alt": {"label": "GPS alt", "sqlite_type": "REAL", "sql_type": "FLOAT", "widget": "text", "options": None,
                    "constant_value": None, "server_now": False, "required": False},
        "gps_acc": {"label": "GPS acc", "sqlite_type": "REAL", "sql_type": "FLOAT", "widget": "text", "options": None,
                    "constant_value": None, "server_now": False, "required": False},
        "images_json": {"label": "Images", "sqlite_type": "TEXT", "sql_type": "TEXT", "widget": "text", "options": None,
                        "constant_value": None, "server_now": False, "required": False},
        "thumbs_json": {"label": "Thumbs", "sqlite_type": "TEXT", "sql_type": "TEXT", "widget": "text", "options": None,
                        "constant_value": None, "server_now": False, "required": False},
        "webps_json": {"label": "WebPs", "sqlite_type": "TEXT", "sql_type": "TEXT", "widget": "text", "options": None,
                       "constant_value": None, "server_now": False, "required": False},
        "json_files_json": {"label": "JSON files", "sqlite_type": "TEXT", "sql_type": "TEXT", "widget": "text",
                            "options": None,
                            "constant_value": None, "server_now": False, "required": False},
    }

    for _c in referenced_cols:
        if _c not in field_meta and _c in RESERVED_DEFAULTS:
            d = RESERVED_DEFAULTS[_c]
            field_meta[_c] = {
                "label": d["label"],
                "col": _c,
                "sql_type": d["sql_type"],
                "sqlite_type": d["sqlite_type"],
                "widget": d["widget"],
                "options": d["options"],
                "constant_value": d["constant_value"],
                "server_now": d["server_now"],
                "required": d["required"],
            }

    cleaned = []
    for row in (result_rows_effective or []):
        cols = []
        for col in (row or []):
            if col in field_meta:
                cols.append(col)
        if cols:
            cleaned.append(cols)
    result_rows_effective = cleaned

    fields_to_reset = list(cfg.get('fields_to_reset') or [])
    copy_from = (cfg.get('copy_from') or '').strip()
    index_fields = list(cfg.get('index') or [])
    result_grid = list(cfg.get('result_grid') or cfg.get('result_gird') or [])
    # Keep only known columns (user fields or system columns).
    _rg_clean = []
    for _c in result_grid:
        if _c in field_meta or _c in SYSTEM_COLUMNS:
            _rg_clean.append(_c)
    result_grid = _rg_clean
    # Flattened unique list of layout field names (used by client-side helpers)
    layout_fields = []
    seen = set()
    for _row in (layout_rows or []):
        for _col in (_row or []):
            if _col in field_meta and _col not in seen:
                layout_fields.append(_col)
                seen.add(_col)
    TYPE_META[otype] = {
        "label": label,
        "input_fields": input_fields,
        # Convenience list for templates: all user-configured fields except
        # system-managed columns. (TIMESTAMP fields are allowed.)
        "display_fields": [f for f in input_fields if (len(f) > 1 and f[1] not in SYSTEM_COLUMNS)],
        "layout_rows": layout_rows,
        "layout_fields": layout_fields,
        "result_rows": result_rows_effective,
        "result_fields": [col for row in result_rows_effective for col in row],
        "required_fields": required_fields,
        "filename_format": filename_format,
        "fields_to_reset": fields_to_reset,
        "copy_from": copy_from,
        "index_fields": index_fields,
        "result_grid": result_grid,
        "field_meta": field_meta,
    }

# Expose to templates.
app.jinja_env.globals["OBJECT_TYPES"] = TYPE_META


# Template helpers
@app.template_filter("mmddyyyy")
def _filter_mmddyyyy(val):
    return _mmddyyyy_from_iso(val)


def make_banner_title(*parts: str) -> str:
    base = APP_BRAND
    if APP_SUBTITLE:
        base = f"{base} · {APP_SUBTITLE}"
    parts = [p for p in parts if p]
    if parts:
        return " · ".join(parts)
    return base


def _get_current_type() -> str:
    """Best-effort object type for navbar URLs."""
    # Prefer explicit value set by routes that render templates.
    try:
        if getattr(g, "current_type", None):
            ct = str(g.current_type)
            if ct in TYPE_META:
                return ct
    except Exception:
        pass

    # Try URL params
    for k in ("type", "object_type"):
        v = (request.view_args or {}).get(k) if hasattr(request, "view_args") else None
        if v and str(v) in TYPE_META:
            return str(v)
        v = request.args.get(k) if hasattr(request, "args") else None
        if v and str(v) in TYPE_META:
            return str(v)

    # Fallback: first configured type
    return next(iter(TYPE_META.keys()))


@app.context_processor
def inject_globals():
    ct = _get_current_type()
    endpoint = (request.endpoint or '').lower() if hasattr(request, 'endpoint') else ''
    # Treat all admin_* endpoints as 'edit' for navbar highlighting.
    active = {
        'upload': endpoint in ('form',),
        'recent': endpoint in ('recent',),
        'edit': endpoint.startswith('admin_'),
        'review': endpoint in ('review', 'index',),
        'info': endpoint in ('info',),
        'user': endpoint in ('user',),
    }

    nav_links = [
        {'key': 'upload', 'label': 'Upload', 'url': url_for('form', type=ct), 'active': active['upload']},
        {'key': 'recent', 'label': 'Recent', 'url': url_for('recent', type=ct), 'active': active['recent']},
        {'key': 'edit', 'label': 'Edit', 'url': url_for('admin_list', type=ct), 'active': active['edit']},
        {'key': 'review', 'label': 'Review', 'url': url_for('review', type=ct), 'active': active['review']},
        {'key': 'info', 'label': 'Info', 'url': url_for('info'), 'active': active['info']},
        # {'key': 'user', 'label': 'Account', 'url': url_for('user'), 'active': active['user']},
    ]

    return {
        'APP_BRAND': getattr(config, 'APP_BRAND', 'Artifact Capture'),
        'APP_SUBTITLE': getattr(config, 'APP_SUBTITLE', ''),
        'APP_LOGO': getattr(config, 'APP_LOGO', 'logo.svg'),
        'ADMIN_LABEL': getattr(config, 'ADMIN_LABEL', 'Admin'),
        'GPS_ENABLED': GPS_ENABLED,

        'BANNER_BG': getattr(config, 'BANNER_BG', '#1f2937'),
        'BANNER_FG': getattr(config, 'BANNER_FG', '#ffffff'),
        'BANNER_ACCENT': getattr(config, 'BANNER_ACCENT', '#60a5fa'),
        'SHOW_LOGO': getattr(config, 'SHOW_LOGO', True),
        'NAV_LINKS': nav_links,
        # Default banner subtitle: current object type (overridden by routes that pass banner_title)
        'banner_title': make_banner_title(ct.capitalize()) if ct else '',
    }


app.jinja_env.globals["GPS_ENABLED"] = GPS_ENABLED


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create/upgrade DB tables for each configured object type."""

    # Columns common to all object-type tables.
    # Image fields are JSON-encoded lists so multiple images can attach to a record.
    base_cols = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("images_json", "TEXT"),
        ("thumbs_json", "TEXT"),
        ("webps_json", "TEXT"),
        ("json_files_json", "TEXT"),
        ("meta_signature", "TEXT"),
        ("date_last_saved", "TEXT"),
        ("width", "INTEGER"),
        ("height", "INTEGER"),
        ("timestamp", "INTEGER"),
        ("ip", "TEXT"),
        ("user_agent", "TEXT"),
        ("exif_datetime", "TEXT"),
        ("exif_make", "TEXT"),
        ("exif_model", "TEXT"),
        ("exif_orientation", "INTEGER"),
        ("gps_lat", "REAL"),
        ("gps_lon", "REAL"),
        ("gps_alt", "REAL"),
    ]

    with get_db() as conn:
        for otype, meta in TYPE_META.items():
            table = otype
            meta_cols = [(f[1], meta["field_meta"][f[1]]["sqlite_type"]) for f in meta["input_fields"]]

            cols_sql = ",\n                ".join(
                [f"{name} {ctype}" for name, ctype in [base_cols[0]] + meta_cols + base_cols[1:]]
            )
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols_sql});")

            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, ctype in meta_cols + base_cols:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}")

            # Helpful index for record matching by metadata signature.
            try:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_meta_signature ON {table}(meta_signature)")
            except Exception:
                pass


def ensure_runtime_paths():
    """Create runtime directories (uploads/ and DB parent) and initialize DB schema.

    This runs at import time under mod_wsgi, so failures here surface immediately and
    clearly in the Apache error log.
    """
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Touch the DB file (directory must exist). SQLite will create it if missing.
        conn = sqlite3.connect(str(DB_PATH))
        conn.close()

        # Ensure schema exists / evolves.
        init_db()
    except Exception as e:
        # Avoid a silent failure: make the path and error obvious.
        print(f"[FATAL] Cannot initialize runtime paths. UPLOAD_DIR={UPLOAD_DIR} DB_PATH={DB_PATH} error={e}")
        raise


ensure_runtime_paths()


def check_auth(auth_header: str) -> bool:
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        user, pw = decoded.split(":", 1)
        return (user == ADMIN_USER and pw == ADMIN_PASS)
    except Exception:
        return False


def requires_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if check_auth(request.headers.get("Authorization")):
            return f(*args, **kwargs)
        # Return a 401 with WWW-Authenticate so the browser re-prompts.
        # Also disable caching to avoid a stale 401 being reused.
        body = (
            "<html><head><title>Authentication required</title></head>"
            "<body style='font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;'>"
            "<h3>Authentication required</h3>"
            "<p>Please enter your admin username/password to continue.</p>"
            "</body></html>"
        )
        return Response(
            body,
            401,
            {
                "WWW-Authenticate": 'Basic realm="Artifact Admin", charset="UTF-8"',
                "Cache-Control": "no-store",
            },
            mimetype="text/html",
        )

    return wrapper


TAGS = {v: k for k, v in ExifTags.TAGS.items()}
GPS_TAG_ID = TAGS.get("GPSInfo")


def _to_decimal(dms, ref):
    def _r(v):
        try:
            return v[0] / v[1]
        except Exception:
            return float(v)

    deg = _r(dms[0]);
    minutes = _r(dms[1]);
    seconds = _r(dms[2])
    val = deg + minutes / 60.0 + seconds / 3600.0
    if ref in ("S", "W"):
        val = -val
    return val


def extract_exif_and_autorotate(image_bytes: bytes):
    img = Image.open(BytesIO(image_bytes))
    exif_raw = img.info.get("exif", None)
    exifdata = img.getexif()

    out = {
        "exif_datetime": None,
        "exif_make": None,
        "exif_model": None,
        "exif_orientation": None,
    }

    if exifdata:
        dtid = TAGS.get("DateTimeOriginal") or TAGS.get("DateTime")
        if dtid and dtid in exifdata:
            out["exif_datetime"] = str(exifdata.get(dtid))
        mkid = TAGS.get("Make")
        mdid = TAGS.get("Model")
        orid = TAGS.get("Orientation")
        if mkid and mkid in exifdata:
            out["exif_make"] = str(exifdata.get(mkid))
        if mdid and mdid in exifdata:
            out["exif_model"] = str(exifdata.get(mdid))
        if orid and orid in exifdata:
            out["exif_orientation"] = int(exifdata.get(orid))

    gps_lat = gps_lon = gps_alt = None
    if exifdata and GPS_TAG_ID in exifdata:
        gps_ifd = exifdata.get(GPS_TAG_ID)
        try:
            lat_ref = gps_ifd.get(1)
            lat = gps_ifd.get(2)
            lon_ref = gps_ifd.get(3)
            lon = gps_ifd.get(4)
            alt = gps_ifd.get(6)
            if lat and lon and lat_ref and lon_ref:
                lat_ref = lat_ref.decode() if hasattr(lat_ref, "decode") else lat_ref
                lon_ref = lon_ref.decode() if hasattr(lon_ref, "decode") else lon_ref
                gps_lat = _to_decimal(lat, lat_ref)
                gps_lon = _to_decimal(lon, lon_ref)
            if alt:
                gps_alt = (alt[0] / alt[1]) if isinstance(alt, tuple) else float(alt)
        except Exception:
            pass

    img = ImageOps.exif_transpose(img)
    return img, exif_raw, out, gps_lat, gps_lon, gps_alt


def resize_if_needed(img):
    w, h = img.size
    if max(w, h) <= MAX_DIM:
        return img, w, h
    if w >= h:
        new_w = MAX_DIM
        new_h = int(h * (MAX_DIM / float(w)))
    else:
        new_h = MAX_DIM
        new_w = int(w * (MAX_DIM / float(h)))
    return img.resize((new_w, new_h), Image.LANCZOS), new_w, new_h


def make_thumbnail(img):
    thumb = img.copy()
    thumb.thumbnail((THUMB_DIM, THUMB_DIM), Image.LANCZOS)
    return thumb


def slug(s: str) -> str:
    s = (s or "").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch in " .":
            out.append("_")
        else:
            out.append("_")
    return "".join(out) or "NA"


def _mmddyyyy_from_iso(val: str) -> str:
    v = (val or "").strip()
    if not v:
        return ""
    # Already MM/DD/YYYY?
    if re.match(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}$", v):
        return v
    # ISO YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", v)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{mo}/{d}/{y}"
    return v


def _normalize_date_input(val: str) -> str:
    """Parse flexible user-entered dates and store in a single configured format.

    Accepts common inputs such as:
      - MM/DD/YYYY or M/D/YYYY
      - YYYY-MM-DD or YYYY/M/D
      - DD/MM/YYYY (only when unambiguous: day > 12)
    Stores using DATE_FORMAT (default %Y-%m-%d).
    """
    v = (val or "").strip()
    if not v:
        return ""

    # Normalize separators
    vv = re.sub(r"[.\-]", "/", v)

    # Try explicit formats first
    fmts = [
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
        "%Y/%m/%d",
    ]
    # We'll also attempt some relaxed parsing below.
    from datetime import datetime

    # Allow compact numeric dates: MMDDYY and MMDDYYYY (e.g., 020286 or 02021986)
    digits = re.sub(r"\D+", "", v)
    if len(digits) == 8:
        try:
            mo = int(digits[0:2]);
            d = int(digits[2:4]);
            y = int(digits[4:8])
            dt = datetime(y, mo, d)
            return dt.strftime(DATE_FORMAT)
        except Exception:
            pass
    if len(digits) == 6:
        try:
            mo = int(digits[0:2]);
            d = int(digits[2:4]);
            yy = int(digits[4:6])
            y = (2000 + yy) if yy <= 49 else (1900 + yy)
            dt = datetime(y, mo, d)
            return dt.strftime(DATE_FORMAT)
        except Exception:
            pass

    # Direct attempts
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%-d", "%Y/%-m/%d", "%Y/%-m/%-d"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.strftime(DATE_FORMAT)
        except Exception:
            pass

    # Handle M/D/YYYY without zero padding
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", vv)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(y, mo, d)
            return dt.strftime(DATE_FORMAT)
        except Exception:
            return v

    # Handle YYYY/M/D
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(y, mo, d)
            return dt.strftime(DATE_FORMAT)
        except Exception:
            return v

    # Handle DD/MM/YYYY when day is > 12 (avoids ambiguity with MM/DD/YYYY)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", vv)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            try:
                dt = datetime(y, b, a)
                return dt.strftime(DATE_FORMAT)
            except Exception:
                return v

    return v


def _normalize_timestamp_input(val: str) -> str:
    """Parse flexible user-entered datetimes and store in a single configured format.

    Accepts:
      - YYYY-MM-DD HH:MM[:SS]
      - YYYY-MM-DDTHH:MM[:SS]
      - MM/DD/YYYY HH:MM[:SS] (and M/D/YYYY)
    Stores using TIMESTAMP_FORMAT (default DATE_FORMAT + 'T%H:%M:%S').
    """
    v = (val or "").strip()
    if not v:
        return ""

    from datetime import datetime

    # Common canonical forms
    for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.strftime(TIMESTAMP_FORMAT)
        except Exception:
            pass

    # Handle M/D/YYYY with times
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$", v)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm = int(m.group(4)), int(m.group(5))
        ss = int(m.group(6) or 0)
        try:
            dt = datetime(y, mo, d, hh, mm, ss)
            return dt.strftime(TIMESTAMP_FORMAT)
        except Exception:
            return v

    # If it's just a date, normalize as date at midnight
    d = _normalize_date_input(v)
    if d and d != v:
        try:
            dt = datetime.strptime(d, DATE_FORMAT)
            return datetime(dt.year, dt.month, dt.day, 0, 0, 0).strftime(TIMESTAMP_FORMAT)
        except Exception:
            return v

    return v


def _safe_format_filename(fmt: str, meta_values: dict, record_id: int) -> str:
    """Safely render a filename using a Python format string.

    - Placeholders must match SQL column names from config (e.g. {unit}, {lot}, {record_id}).
    - All substituted values are slugged for filesystem safety.
    - Missing placeholders resolve to empty string.
    """
    fmt = (fmt or "").strip()
    if not fmt:
        return ""

    class _Default(dict):
        def __missing__(self, key):
            return ""

    ctx = {k: slug(str(v)) for k, v in (meta_values or {}).items()}
    ctx.setdefault("record_id", record_id)

    try:
        out = fmt.format_map(_Default(ctx))
    except Exception:
        # Do not crash uploads because of a bad format string.
        out = fmt

    out = slug(out)
    out = re.sub(r"_+", "_", out).strip("_")
    return out


def maps_links(lat, lon):
    if lat is None or lon is None:
        return None, None
    osm = (
        f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}"
        f"#map=18/{lat:.6f}/{lon:.6f}"
    )
    gmaps = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    return osm, gmaps


app.jinja_env.globals["maps_links"] = maps_links
app.jinja_env.filters["fromjson"] = lambda s: json.loads(s) if s else []


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.static_folder,
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route("/", methods=["GET"])
def form():
    last_id = request.args.get("last_id", type=int)
    last_type = request.args.get("last_type", type=str)
    last_row = None
    last_meta = None
    if last_id and last_type and last_type in TYPE_META:
        with get_db() as conn:
            last_row = conn.execute(
                f"SELECT * FROM {last_type} WHERE id=?", (last_id,)
            ).fetchone()
            last_meta = TYPE_META[last_type]
    # Default selected tab
    selected = request.args.get("type") or (last_type if last_type in TYPE_META else None)
    if selected not in TYPE_META:
        selected = next(iter(TYPE_META.keys()))
    g.current_type = selected
    prefill_by_type = session.get('prefill_by_type', {})
    return render_template("upload.html",
                           last_row=last_row, last_type=last_type, last_meta=last_meta,
                           selected_type=selected,
                           banner_title=make_banner_title(selected.capitalize()),
                           prefill_by_type=prefill_by_type,
                           current_record_by_type=session.get('current_record_by_type', {}))


def _apply_postprocess_values(otype: str, values: dict) -> dict:
    """Optional post-processing hook.
    It should return a dict (may be the same object) containing values compatible
    with the database schema. Unknown keys are dropped.
    """

    def extract_values(otype, dico):
        context = dico['context']
        parts = context.split(',')
        if len(parts) < 3:
            raise TypeError("need 3 and only 3 comma-separated values for context: Unit,Area,Level")
        dico['excavation_unit'] = parts[0].upper().strip()
        dico['area'] = parts[1].upper().strip()
        dico['level'] = parts[2].upper().strip()
        return dico

    out = extract_values(otype, dict(values))

    if not isinstance(out, dict):
        raise TypeError("postprocess_values must return a dict (or None)")

    allowed = set(TYPE_META.get(otype, {}).get("field_meta", {}).keys())
    cleaned = {}
    for k in allowed:
        cleaned[k] = out.get(k)
    return cleaned


@app.route("/exists", methods=["POST"])
def exists():
    """Return whether a record exists for the current metadata values.

    Returns JSON: {exists: bool, id: int|null}
    """
    otype = (request.form.get("object_type") or "").strip().lower()
    if otype not in TYPE_META:
        return jsonify({"exists": False, "id": None})

    meta = TYPE_META[otype]

    # Coerce values the same way as /submit does (but without requiring a photo).
    meta_values = {}
    ts = int(time.time())
    now = __import__("datetime").datetime.fromtimestamp(ts)
    ts_str = now.strftime(TIMESTAMP_FORMAT)

    for fdef in meta["input_fields"]:
        _label, col, coltype = fdef[0], fdef[1], (fdef[2] if len(fdef) > 2 else "TEXT")
        t = (str(coltype or "TEXT")).upper().strip()
        fm = meta["field_meta"].get(col, {})

        if t == "CONSTANT" or fm.get("widget") == "constant":
            meta_values[col] = str(fm.get("constant_value") or "")
            continue

        if fm.get("widget") == "radio":
            selected = [str(v).strip() for v in request.form.getlist(col) if str(v).strip()]
            meta_values[col] = json.dumps(selected, ensure_ascii=False, separators=(",", ":")) if selected else None
            continue

        # Server-managed timestamp/date (e.g., date_last_saved)

        if fm.get('server_now'):
            from datetime import datetime

            now = datetime.now()

            meta_values[col] = now.strftime(DATE_FORMAT) if t == 'DATE' else now.strftime(TIMESTAMP_FORMAT)

            continue

        raw = (request.form.get(col) or "").strip()
        if fm.get("widget") == "uppercase" and raw:
            raw = raw.upper()

        if not raw:
            meta_values[col] = None
            continue

        if t.startswith("INT"):
            try:
                meta_values[col] = int(raw)
            except ValueError:
                meta_values[col] = None
        elif t.startswith("FLOAT") or t.startswith("REAL") or t.startswith("DOUBLE"):
            try:
                meta_values[col] = float(raw)
            except ValueError:
                meta_values[col] = None
        elif t == "DATE":
            meta_values[col] = _normalize_date_input(raw)
        elif t == "TIMESTAMP":
            meta_values[col] = _normalize_timestamp_input(raw)
        else:
            meta_values[col] = raw

    # Optional server-side postprocessing; on failure, return the values to the client
    # and ask them to correct.
    try:
        meta_values = _apply_postprocess_values(otype, meta_values)
    except Exception:
        flash("post processing failed, please correct.")
        try:
            prefill_by_type = session.get('prefill_by_type', {}) or {}
            prefill_by_type[otype] = dict(meta_values)
            session['prefill_by_type'] = prefill_by_type
        except Exception:
            pass
        return redirect(url_for('form', type=otype))

    signature_values = {}
    for fdef in meta["input_fields"]:
        col, coltype = fdef[1], (fdef[2] if len(fdef) > 2 else "TEXT")
        t = (str(coltype or "TEXT")).upper().strip()
        if t.startswith("TIMESTAMP"):
            continue
        signature_values[col] = meta_values.get(col)

    meta_signature = json.dumps(signature_values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    with get_db() as conn:
        row = conn.execute(
            f"SELECT id FROM {otype} WHERE meta_signature=? ORDER BY id DESC LIMIT 1",
            (meta_signature,),
        ).fetchone()

    if row:
        return jsonify({"exists": True, "id": int(row["id"])})
    return jsonify({"exists": False, "id": None})


@app.route("/submit", methods=["POST"])
def submit():
    otype = (request.form.get("object_type") or "").strip().lower()
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("form"))
    meta = TYPE_META[otype]
    # submit_mode may be supplied by either a submit button (name/value) or a hidden input.
    submit_mode = (request.form.get("submit_mode") or "image").strip().lower()
    action = (request.form.get("action") or "").strip().lower()
    ts = int(time.time())
    now = __import__("datetime").datetime.fromtimestamp(ts)
    ts_str = now.strftime(TIMESTAMP_FORMAT)

    # Coerce metadata values from request.form according to config.
    meta_values = {}

    for fdef in meta["input_fields"]:
        _label, col, coltype = fdef[0], fdef[1], (fdef[2] if len(fdef) > 2 else "TEXT")
        t = (str(coltype or "TEXT")).upper().strip()
        fm = meta["field_meta"].get(col, {})

        # CONSTANT fields are server-controlled (clients may submit, but we overwrite).
        if t == "CONSTANT" or fm.get("widget") == "constant":
            meta_values[col] = str(fm.get("constant_value") or "")
            continue

        # RADIO fields are multi-select (0+), stored as a JSON list in a TEXT column.
        if fm.get("widget") == "radio":
            selected = [str(v).strip() for v in request.form.getlist(col) if str(v).strip()]
            if selected:
                meta_values[col] = json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
            else:
                meta_values[col] = None
            continue

        # Server-managed timestamp/date (e.g., date_last_saved)

        if fm.get('server_now'):
            from datetime import datetime

            now = datetime.now()

            meta_values[col] = now.strftime(DATE_FORMAT) if t == 'DATE' else now.strftime(TIMESTAMP_FORMAT)

            continue

        raw = (request.form.get(col) or "").strip()
        if fm.get("widget") == "uppercase" and raw:
            raw = raw.upper()

        if not raw:
            meta_values[col] = None
            continue

        if t.startswith("INT"):
            try:
                meta_values[col] = int(raw)
            except ValueError:
                meta_values[col] = None
        elif t.startswith("FLOAT") or t.startswith("REAL") or t.startswith("DOUBLE"):
            try:
                meta_values[col] = float(raw)
            except ValueError:
                meta_values[col] = None
        elif t == 'DATE':
            meta_values[col] = _normalize_date_input(raw)
        elif t == 'TIMESTAMP':
            meta_values[col] = _normalize_timestamp_input(raw)
        else:
            meta_values[col] = raw

    # Remember the user's most recent inputs per object type (for POST-to-POST continuity).
    # Do this BEFORE post-processing so that even if post-processing fails we can
    # return the form with the user's inputs intact.
    prefill_by_type = session.get('prefill_by_type', {})
    prefill = {}
    for fdef in meta['input_fields']:
        col = fdef[1]
        fm = meta['field_meta'].get(col, {})
        if fm.get('widget') == 'radio':
            prefill[col] = [str(v).strip() for v in request.form.getlist(col) if str(v).strip()]
        elif fm.get('widget') == 'constant':
            prefill[col] = str(fm.get('constant_value') or '')
        else:
            prefill[col] = request.form.get(col, '')
    prefill_by_type[otype] = prefill
    session['prefill_by_type'] = prefill_by_type

    # Allow optional post-processing of the collected form values.
    try:
        meta_values = _apply_postprocess_values(otype, meta_values)
    except Exception:
        flash('post processing failed, please correct.')
        return redirect(url_for('form', type=otype))

    # Record matching signature: use non-timestamp values only.
    signature_values = {}
    for fdef in meta["input_fields"]:
        col, coltype = fdef[1], (fdef[2] if len(fdef) > 2 else "TEXT")
        t = (str(coltype or "TEXT")).upper().strip()
        if t.startswith("TIMESTAMP"):
            continue
        signature_values[col] = meta_values.get(col)
    for col in meta["required_fields"]:
        if not meta_values.get(col):
            label = meta["field_meta"].get(col, {}).get("label", col.replace("_", " ").title())
            flash(f"Please fill in required field: {label}.")
            return redirect(url_for("form", type=otype))

    # GPS handling: we still accept browser GPS as a fallback when EXIF has none.
    require_gps = False
    if GPS_ENABLED:
        require_gps = request.form.get("require_gps") == "on"

    # Metadata-only submission (New Record / Update Record)
    if submit_mode == "metadata":
        meta_signature = json.dumps(signature_values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        meta_cols = [fdef[1] for fdef in meta["input_fields"]]
        current_by_type = session.get('current_record_by_type', {})

        with get_db() as conn:
            if action == 'update_record':
                rid = current_by_type.get(otype)
                if not rid:
                    flash('No current record to update. Click New Record first.')
                    return redirect(url_for('form', type=otype))

                sets = ",".join(
                    [f"{c}=?" for c in meta_cols] + ["meta_signature=?", "timestamp=?", "date_last_saved=?"] + (
                        ["date_updated=?"] if meta.get('field_meta', {}).get('date_updated', {}).get(
                            'server_now') else []))
                vals = [meta_values.get(c) for c in meta_cols] + [meta_signature, ts,
                                                                  now.strftime(TIMESTAMP_FORMAT)] + (
                           [now.strftime(TIMESTAMP_FORMAT)] if meta.get('field_meta', {}).get('date_updated', {}).get(
                               'server_now') else [])
                conn.execute(f"UPDATE {otype} SET {sets} WHERE id=?", vals + [rid])
                flash(f"Record {rid} updated.")
                return redirect(url_for('form', type=otype, last_id=rid, last_type=otype))

            # Default (and 'new_record'): always insert a fresh row
            db_cols = meta_cols + ["meta_signature", "images_json", "thumbs_json", "webps_json", "json_files_json",
                                   "timestamp", "date_last_saved"] + (
                          ["date_updated"] if meta.get('field_meta', {}).get('date_updated', {}).get(
                              'server_now') else [])
            vals = [meta_values.get(c) for c in meta_cols] + [
                meta_signature,
                json.dumps([]), json.dumps([]), json.dumps([]), json.dumps([]),
                ts,
                now.strftime(TIMESTAMP_FORMAT),
            ] + ([now.strftime(TIMESTAMP_FORMAT)] if meta.get('field_meta', {}).get('date_updated', {}).get(
                'server_now') else [])
            placeholders = ",".join(["?"] * len(db_cols))
            cur = conn.execute(f"INSERT INTO {otype} ({','.join(db_cols)}) VALUES ({placeholders})", vals)
            rid = int(cur.lastrowid)

        current_by_type[otype] = rid
        session['current_record_by_type'] = current_by_type
        flash(f"New record created: {rid}.")
        return redirect(url_for('form', type=otype, last_id=rid, last_type=otype))

    f = request.files.get("photo")
    if not f or f.filename == "":
        flash("Please take or choose a photo.")
        return redirect(url_for("form", type=otype))

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")

    data = f.read()
    img, exif_raw, exif_small, gps_lat, gps_lon, gps_alt = extract_exif_and_autorotate(data)

    if GPS_ENABLED:
        try:
            if gps_lat is None or gps_lon is None:
                form_lat = request.form.get("gps_lat")
                form_lon = request.form.get("gps_lon")
                if form_lat and form_lon:
                    gps_lat = float(form_lat)
                    gps_lon = float(form_lon)
                    gps_alt = None
        except Exception:
            pass
        if require_gps and (gps_lat is None or gps_lon is None):
            flash(
                "GPS is required, but no GPS was found in EXIF or browser location. "
                "Please enable location and try again."
            )
            return redirect(url_for("form", type=otype))

    img, width, height = resize_if_needed(img)
    thumb = make_thumbnail(img)

    exif_datetime = exif_small["exif_datetime"]
    exif_make = exif_small["exif_make"]
    exif_model = exif_small["exif_model"]
    exif_orientation = exif_small["exif_orientation"]

    meta_signature = json.dumps(signature_values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _load_list(val):
        if not val:
            return []
        try:
            x = json.loads(val)
            return x if isinstance(x, list) else []
        except Exception:
            return []

    def _make_base(record_id: int) -> str:
        fmt = (meta.get("filename_format") or "").strip()
        out = _safe_format_filename(fmt, meta_values, record_id)
        if out:
            return out
        # If no format is provided, fall back to a simple deterministic name.
        return slug(f"{otype.upper()}_ID{record_id}")

    with get_db() as conn:
        # Prefer the current record (created by New Record) when it matches the current form values.
        row = None
        current_by_type = session.get('current_record_by_type', {})
        cur_id = current_by_type.get(otype)
        if cur_id:
            try:
                cand = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (cur_id,)).fetchone()
                if cand and cand['meta_signature'] == meta_signature:
                    row = cand
            except Exception:
                row = None

        # Otherwise, try to match an existing record by metadata signature.
        if row is None:
            row = conn.execute(
                f"SELECT * FROM {otype} WHERE meta_signature=? ORDER BY id DESC LIMIT 1",
                (meta_signature,),
            ).fetchone()

        if row:
            record_id = int(row["id"])
            images = _load_list(row["images_json"])
            thumbs = _load_list(row["thumbs_json"])
            webps = _load_list(row["webps_json"])
            jfiles = _load_list(row["json_files_json"])
        else:
            # Create a new record first.
            meta_cols = [f[1] for f in meta["input_fields"]]
            db_cols = meta_cols + [
                "meta_signature",
                "images_json", "thumbs_json", "webps_json", "json_files_json",
                "width", "height", "timestamp", "ip", "user_agent",
                "exif_datetime", "exif_make", "exif_model", "exif_orientation",
                "gps_lat", "gps_lon", "gps_alt",
            ]
            values = [meta_values.get(c) for c in meta_cols] + [
                meta_signature,
                json.dumps([]), json.dumps([]), json.dumps([]), json.dumps([]),
                width, height, ts, ip, ua,
                exif_datetime, exif_make, exif_model, exif_orientation,
                gps_lat, gps_lon, gps_alt,
            ]
            placeholders = ",".join(["?"] * len(db_cols))
            cur = conn.execute(
                f"INSERT INTO {otype} ({','.join(db_cols)}) VALUES ({placeholders})",
                values,
            )
            record_id = cur.lastrowid
            images, thumbs, webps, jfiles = [], [], [], []

        # Remember / update current record for this object type
        try:
            current_by_type = session.get('current_record_by_type', {})
            current_by_type[otype] = int(record_id)
            session['current_record_by_type'] = current_by_type
        except Exception:
            pass

        img_idx = len(images) + 1
        base = _make_base(record_id) + f"_IMG{img_idx}"
        jpg_name = f"{base}.jpg"
        thumb_name = f"{base}_thumb.jpg"
        webp_name = f"{base}.webp"
        json_name = f"{base}.json"

        save_kwargs = {"format": "JPEG", "quality": JPEG_QUALITY}
        if exif_raw:
            save_kwargs["exif"] = exif_raw
        img.convert("RGB").save(UPLOAD_DIR / jpg_name, **save_kwargs)
        thumb.convert("RGB").save(UPLOAD_DIR / thumb_name, format="JPEG", quality=85)
        img.save(UPLOAD_DIR / webp_name, "WEBP", quality=WEBP_QUALITY, method=6)

        # Per-image JSON sidecar (one file per captured image)
        json_payload = {
            "object_type": otype,
            "record_id": record_id,
            "image_index": img_idx,
            "filename_base": base,
            "filename": jpg_name,
            "thumb_filename": thumb_name,
            "webp_filename": webp_name,
            "timestamp": ts,
            "client_ip": ip,
            "user_agent": ua,
            "gps": {"lat": gps_lat, "lon": gps_lon, "alt": gps_alt},
            "exif": {
                "datetime": exif_datetime,
                "make": exif_make,
                "model": exif_model,
                "orientation": exif_orientation,
            },
            "fields": meta_values,
        }
        # Append new files to the record lists first so we can embed the full list
        # in both the record-level JSON and the per-image JSON (useful for downstream tooling).
        images.append(jpg_name)
        thumbs.append(thumb_name)
        webps.append(webp_name)
        jfiles.append(json_name)

        # Embed the full record image lists into the per-image JSON sidecar.
        json_payload["record_images"] = list(images)
        json_payload["record_thumbs"] = list(thumbs)
        json_payload["record_webps"] = list(webps)
        json_payload["record_image_json_files"] = list(jfiles)

        (UPLOAD_DIR / json_name).write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

        # Record-level JSON sidecar (one file per record, updated on every capture)
        record_json_name = f"{_make_base(record_id)}_record.json"
        record_payload = {
            "object_type": otype,
            "record_id": record_id,
            "timestamp": ts,
            "client_ip": ip,
            "user_agent": ua,
            "gps": {"lat": gps_lat, "lon": gps_lon, "alt": gps_alt},
            "exif": {
                "datetime": exif_datetime,
                "make": exif_make,
                "model": exif_model,
                "orientation": exif_orientation,
            },
            "fields": meta_values,
            "images": list(images),
            "thumbs": list(thumbs),
            "webps": list(webps),
            "image_json_files": list(jfiles),
        }
        (UPLOAD_DIR / record_json_name).write_text(json.dumps(record_payload, indent=2), encoding="utf-8")

        # Record-level JSON sidecar (updated on every submission; includes ALL images)
        record_json_name = f"{_make_base(record_id)}_record.json"
        record_payload = {
            "object_type": otype,
            "record_id": record_id,
            "timestamp": ts,
            "client_ip": ip,
            "user_agent": ua,
            "gps": {"lat": gps_lat, "lon": gps_lon, "alt": gps_alt},
            "exif": {
                "datetime": exif_datetime,
                "make": exif_make,
                "model": exif_model,
                "orientation": exif_orientation,
            },
            "fields": meta_values,
            "images": images,
            "thumbs": thumbs,
            "webps": webps,
            "image_json_files": jfiles,
        }
        (UPLOAD_DIR / record_json_name).write_text(
            json.dumps(record_payload, indent=2),
            encoding="utf-8",
        )
        # Update record with new image lists and latest capture context.
        # Always bump date_last_saved; bump date_updated if configured (TIMESTAMP + field name date_updated).
        from datetime import datetime
        now2 = datetime.now()
        dls = now2.strftime(TIMESTAMP_FORMAT)
        du_sql = ''
        du_val = None
        if meta.get('field_meta', {}).get('date_updated', {}).get('server_now'):
            du_sql = 'date_updated=?, '
            du_val = now2.strftime(TIMESTAMP_FORMAT)

        sql = (
            f"UPDATE {otype} SET {du_sql}date_last_saved=?, images_json=?, thumbs_json=?, webps_json=?, json_files_json=?, "
            "width=?, height=?, timestamp=?, ip=?, user_agent=?, exif_datetime=?, exif_make=?, exif_model=?, exif_orientation=?, gps_lat=?, gps_lon=?, gps_alt=? "
            "WHERE id=?"
        )
        params = []
        if du_sql:
            params.append(du_val)
        params.append(dls)
        params += [
            json.dumps(images), json.dumps(thumbs), json.dumps(webps), json.dumps(jfiles),
            width, height, ts, ip, ua,
            exif_datetime, exif_make, exif_model, exif_orientation,
            gps_lat, gps_lon, gps_alt,
            record_id,
        ]

        conn.execute(sql, tuple(params))

    return redirect(url_for("form", last_id=record_id, last_type=otype, type=otype))


@app.route("/recent")
def recent():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    g.current_type = otype

    view = (request.args.get("view") or "para").strip().lower()
    if view not in ("para", "table", "grid"):
        view = "para"

    # Pagination (Recent)
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(page, 1)

    try:
        per_page = int(request.args.get("per_page") or "25")
    except ValueError:
        per_page = 25
    per_page_choices = [10, 25, 50, 100]
    if per_page not in per_page_choices:
        per_page = 25

    offset = (page - 1) * per_page

    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM {otype}").fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM {otype} ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

    start_n = offset + 1 if total and rows else 0
    end_n = offset + len(rows) if total and rows else 0
    has_prev = page > 1
    has_next = (offset + per_page) < total

    def _q(**kw):
        base = {"type": otype, "view": view, "page": page, "per_page": per_page}
        base.update(kw)
        return base

    return render_template(
        "recent.html",
        rows=rows,
        otype=otype,
        meta=TYPE_META[otype],
        view=view,
        page=page,
        per_page=per_page,
        per_page_choices=per_page_choices,
        total=total,
        start_n=start_n,
        end_n=end_n,
        has_prev=has_prev,
        has_next=has_next,
        prev_q=_q(page=page - 1),
        next_q=_q(page=page + 1),
        banner_title=make_banner_title("Recent", TYPE_META[otype]["label"]),
    )


def _index_groups_for_field(otype: str, field: str):
    """Return grouped records for Index view.

    For normal TEXT fields, groups by exact value.
    For RADIO fields (stored as JSON list), groups by each selected value.
    """
    meta = TYPE_META[otype]
    fm = meta.get('field_meta', {}).get(field, {})
    widget = (fm.get('widget') or '').lower()
    is_radio = widget == 'radio'

    # Pull only needed columns.
    cols = set(['id', 'thumbs_json', 'images_json', field])
    # Add any fields used in result_rows so we can show tidy metadata.
    for c in meta.get('result_fields', []):
        cols.add(c)
    cols = [c for c in cols if c]
    col_sql = ", ".join([f'"{c}"' for c in cols])

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {col_sql} FROM {otype} ORDER BY id DESC"
        ).fetchall()

    groups = {}  # value -> list[dict]

    def _add_to_group(val, rdict):
        key = (val or '').strip()
        if not key:
            key = '(blank)'
        groups.setdefault(key, []).append(rdict)

    for r in rows:
        r = dict(r)
        thumbs = json.loads(r.get('thumbs_json') or '[]')
        images = json.loads(r.get('images_json') or '[]')
        pairs = []
        # Prefer thumbs, but still link to matching full images by index.
        for i, t in enumerate(thumbs):
            full = images[i] if i < len(images) else t
            pairs.append({'thumb': t, 'full': full})
        # If no thumbs, fall back to full images.
        if not pairs and images:
            for img in images:
                pairs.append({'thumb': img, 'full': img})
        r['_img_pairs'] = pairs

        raw = r.get(field)
        if is_radio:
            try:
                vals = json.loads(raw) if raw else []
                if not isinstance(vals, list):
                    vals = [str(vals)]
            except Exception:
                vals = [str(raw)] if raw else []
            if not vals:
                _add_to_group('', r)
            else:
                for v in vals:
                    _add_to_group(str(v), r)
        else:
            _add_to_group(str(raw) if raw is not None else '', r)

    # Sort keys alphabetically, but keep (blank) last.
    keys = sorted([k for k in groups.keys() if k != '(blank)'], key=lambda s: s.casefold())
    if '(blank)' in groups:
        keys.append('(blank)')

    return [(k, groups[k]) for k in keys]


@app.route("/review")
def review():
    """Review / concordance page (formerly Index)."""
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    g.current_type = otype

    meta = TYPE_META[otype]
    index_fields = [f for f in (meta.get("index_fields") or []) if f in meta.get("field_meta", {})]
    field = (request.args.get("field") or (index_fields[0] if index_fields else "")).strip()
    if field not in index_fields and index_fields:
        field = index_fields[0]

    view = (request.args.get("view") or "para").strip().lower()
    if view not in ("para", "table", "grid"):
        view = "para"

    # Pagination (applies to the record set selected by the index-field buttons)
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(page, 1)

    try:
        per_page = int(request.args.get("per_page") or "25")
    except ValueError:
        per_page = 25
    per_page_choices = [10, 25, 50, 100]
    if per_page not in per_page_choices:
        per_page = 25

    rows = []
    total = 0
    start_n = end_n = 0
    has_prev = has_next = False

    if field:
        offset = (page - 1) * per_page
        # Basic "has data" filter for the chosen field. Also excludes the empty JSON list string for multi-select fields.
        where = f'("{field}" IS NOT NULL AND TRIM(CAST("{field}" AS TEXT)) != "" AND CAST("{field}" AS TEXT) != ?)'
        with get_db() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM {otype} WHERE {where}", ("[]",)).fetchone()["n"]
            rows = conn.execute(
                f'SELECT * FROM {otype} WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?',
                ("[]", per_page, offset),
            ).fetchall()

        start_n = offset + 1 if total and rows else 0
        end_n = offset + len(rows) if total and rows else 0
        has_prev = page > 1
        has_next = (offset + per_page) < total

    # Group rows by the selected field value (within the current page) so the Review display
    # can show headers for each value group without changing pagination semantics.
    groups = []
    if field and rows:
        tmp = collections.defaultdict(list)
        for r in rows:
            v = r[field] if field in r.keys() else ""
            key = ""
            if v is None:
                key = ""
            else:
                s = str(v).strip()
                # If this is a JSON list (multi-select), show it as a comma-separated string.
                if s.startswith("[") and s.endswith("]"):
                    try:
                        arr = json.loads(s)
                        if isinstance(arr, list):
                            key = ", ".join([str(x) for x in arr if str(x).strip()])
                        else:
                            key = s
                    except Exception:
                        key = s
                else:
                    key = s
            if not key:
                key = "(no value)"
            tmp[key].append(r)
        for k in sorted(tmp.keys(), key=lambda x: x.lower()):
            groups.append((k, tmp[k]))

    def _q(**kw):
        base = {"type": otype, "field": field, "view": view, "page": page, "per_page": per_page}
        base.update(kw)
        return base

    return render_template(
        "index.html",
        page_mode="review",
        otype=otype,
        meta=meta,
        index_fields=index_fields,
        field=field,
        view=view,
        rows=rows,
        groups=groups,
        page=page,
        per_page=per_page,
        per_page_choices=per_page_choices,
        total=total,
        start_n=start_n,
        end_n=end_n,
        has_prev=has_prev,
        has_next=has_next,
        prev_q=_q(page=page - 1),
        next_q=_q(page=page + 1),
        banner_title=make_banner_title("Review", meta["label"]),
    )


@app.route("/index")
def index():
    """Backward compatible route; redirect to /review."""
    return redirect(url_for('review', **request.args))


@app.route("/info")
def info():
    # Render Info inside index.html so it inherits the same <head>/layout/styles.
    return render_template(
        "index.html",
        banner_title=make_banner_title("Info", ""),
        page_mode="info",
        # Safe defaults for index template variables (unused in info mode)
        otype=(list(TYPE_META.keys())[0] if TYPE_META else ""),
        index_types=(list(TYPE_META.keys()) if TYPE_META else []),
        field_name="",
        field_label="",
        values=[],
        groupings={},
    )


@app.route("/user")
def user():
    """Stub page for future user/profile/auth UI."""
    return render_template(
        "user.html",
        banner_title=make_banner_title("Account"),
    )


@app.route("/uploads/<path:fname>")
def serve_upload(fname):
    return send_from_directory(UPLOAD_DIR, fname, as_attachment=False)


@app.route("/admin")
@requires_admin
def admin_list():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    g.current_type = otype
    meta = TYPE_META[otype]

    q = request.args.get("q", "").strip()
    view = (request.args.get("view") or "para").strip().lower()
    if view not in ("para", "table", "grid"):
        view = "para"

    # Sorting (server-side) - applies across all pages.
    sort = (request.args.get("sort") or "id").strip()
    direction = (request.args.get("dir") or "desc").strip().lower()
    if direction not in ("asc", "desc"):
        direction = "desc"

    # Allowed columns: id + configured result_fields + a few reserved timestamp fields if present.
    allowed_cols = ["id"] + list(meta.get("result_fields") or [])
    for extra in ("date_last_saved", "date_updated", "date_recorded"):
        if extra not in allowed_cols and extra in meta.get("all_cols", allowed_cols):
            allowed_cols.append(extra)

    if sort not in allowed_cols:
        sort = "id"

    # Pagination
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    page = max(page, 1)

    try:
        per_page = int(request.args.get("per_page", "50"))
    except ValueError:
        per_page = 50
    # Keep bounds reasonable
    per_page = max(10, min(per_page, 200))

    base_sql = f"FROM {otype}"
    params = []
    if q:
        text_cols = [f[1] for f in meta["input_fields"] if (str(f[2] or "")).upper().startswith("TEXT")]
        if text_cols:
            where_clauses = [f"{c} LIKE ?" for c in text_cols]
            base_sql += " WHERE " + " OR ".join(where_clauses)
            like = f"%{q}%"
            params = [like] * len(text_cols)

    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) {base_sql}", params).fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page

        rows = conn.execute(
            f"SELECT * {base_sql} ORDER BY {sort} {direction}, id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

    return render_template(
        "admin_list.html",
        rows=rows,
        q=q,
        view=view,
        sort=sort,
        direction=direction,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        otype=otype,
        meta=meta,
        banner_title=make_banner_title("Edit", meta["label"]),
    )


@app.post("/admin/<otype>/<int:aid>/add_image")
@requires_admin
def admin_add_image(otype, aid):
    otype = (otype or '').strip().lower()
    if otype not in TYPE_META:
        flash('Unknown object type.')
        return redirect(url_for('admin_list', type=otype))
    meta = TYPE_META[otype]

    f = request.files.get('photo')
    if not f or f.filename == '':
        flash('Please take or choose a photo.')
        return redirect(url_for('admin_edit', otype=otype, aid=aid))

    ts = int(time.time())
    from datetime import datetime
    now = datetime.now()
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua = request.headers.get('User-Agent', '')

    def _load_list(val):
        if not val:
            return []
        try:
            x = json.loads(val)
            return x if isinstance(x, list) else []
        except Exception:
            return []

    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
        if not row:
            flash('Record not found.')
            return redirect(url_for('admin_list', type=otype))

        # sqlite3.Row does not support .get(); convert to dict for convenience
        row = dict(row)

        images = _load_list(row.get('images_json'))
        thumbs = _load_list(row.get('thumbs_json'))
        webps = _load_list(row.get('webps_json'))
        jfiles = _load_list(row.get('json_files_json'))

        # Use existing record metadata values for filename formatting.
        meta_values = {}
        for fdef in meta['input_fields']:
            col = fdef[1]
            fm = meta['field_meta'].get(col, {})
            if fm.get('widget') == 'constant':
                meta_values[col] = str(fm.get('constant_value') or '')
            else:
                meta_values[col] = row.get(col)

        # Read & process image
        data = f.read()
        img, exif_raw, exif_small, gps_lat, gps_lon, gps_alt = extract_exif_and_autorotate(data)
        img, width, height = resize_if_needed(img)
        thumb = make_thumbnail(img)

        exif_datetime = exif_small.get('exif_datetime')
        exif_make = exif_small.get('exif_make')
        exif_model = exif_small.get('exif_model')
        exif_orientation = exif_small.get('exif_orientation')

        def _make_base(record_id: int) -> str:
            fmt = (meta.get('filename_format') or '').strip()
            out = _safe_format_filename(fmt, meta_values, record_id)
            if out:
                return out
            return slug(f"{otype.upper()}_ID{record_id}")

        img_idx = len(images) + 1
        base = _make_base(int(aid)) + f"_IMG{img_idx}"
        jpg_name = f"{base}.jpg"
        thumb_name = f"{base}_thumb.jpg"
        webp_name = f"{base}.webp"
        json_name = f"{base}.json"

        save_kwargs = {"format": "JPEG", "quality": JPEG_QUALITY}
        if exif_raw:
            save_kwargs['exif'] = exif_raw
        img.convert('RGB').save(UPLOAD_DIR / jpg_name, **save_kwargs)
        thumb.convert('RGB').save(UPLOAD_DIR / thumb_name, format='JPEG', quality=85)
        img.save(UPLOAD_DIR / webp_name, 'WEBP', quality=WEBP_QUALITY, method=6)

        images.append(jpg_name)
        thumbs.append(thumb_name)
        webps.append(webp_name)
        jfiles.append(json_name)

        json_payload = {
            'object_type': otype,
            'record_id': int(aid),
            'image_index': img_idx,
            'filename_base': base,
            'filename': jpg_name,
            'thumb_filename': thumb_name,
            'webp_filename': webp_name,
            'timestamp': ts,
            'client_ip': ip,
            'user_agent': ua,
            'gps': {'lat': gps_lat, 'lon': gps_lon, 'alt': gps_alt},
            'exif': {
                'datetime': exif_datetime,
                'make': exif_make,
                'model': exif_model,
                'orientation': exif_orientation,
            },
            'fields': meta_values,
            'record_images': list(images),
            'record_thumbs': list(thumbs),
            'record_webps': list(webps),
            'record_image_json_files': list(jfiles),
        }
        (UPLOAD_DIR / json_name).write_text(json.dumps(json_payload, indent=2), encoding='utf-8')

        # Update record lists and timestamps
        du_sql = ''
        du_params = []
        if meta.get('field_meta', {}).get('date_updated', {}).get('server_now'):
            du_sql = 'date_updated=?, '
            du_params.append(now.strftime(TIMESTAMP_FORMAT))

        sql = (
            f"UPDATE {otype} SET {du_sql}date_last_saved=?, images_json=?, thumbs_json=?, webps_json=?, json_files_json=?, "
            "width=?, height=?, timestamp=?, ip=?, user_agent=?, exif_datetime=?, exif_make=?, exif_model=?, exif_orientation=?, gps_lat=?, gps_lon=?, gps_alt=? "
            "WHERE id=?"
        )
        params = du_params + [
            now.strftime(TIMESTAMP_FORMAT),
            json.dumps(images), json.dumps(thumbs), json.dumps(webps), json.dumps(jfiles),
            width, height, ts, ip, ua,
            exif_datetime, exif_make, exif_model, exif_orientation,
            gps_lat, gps_lon, gps_alt,
            int(aid),
        ]
        conn.execute(sql, params)

    flash(f"Added image to record {aid}.")
    return redirect(url_for('admin_edit', otype=otype, aid=aid))


@app.post('/admin/<otype>/<int:aid>/delete_image/<int:img_idx>')
@requires_admin
def admin_delete_image(otype, aid, img_idx):
    otype = (otype or '').strip().lower()
    if otype not in TYPE_META:
        flash('Unknown object type.')
        return redirect(url_for('admin_list', type=otype))
    meta = TYPE_META[otype]

    from datetime import datetime
    now = datetime.now()

    def _load_list(val):
        if not val:
            return []
        try:
            x = json.loads(val)
            return x if isinstance(x, list) else []
        except Exception:
            return []

    def _safe_delete_upload(fname: str):
        if not fname:
            return
        try:
            p = (UPLOAD_DIR / fname).resolve()
            root = UPLOAD_DIR.resolve()
            if str(p).startswith(str(root)) and p.exists():
                p.unlink()
        except Exception:
            pass

    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
        if not row:
            flash('Record not found.')
            return redirect(url_for('admin_list', type=otype))
        row = dict(row)

        images = _load_list(row.get('images_json'))
        thumbs = _load_list(row.get('thumbs_json'))
        webps = _load_list(row.get('webps_json'))
        jfiles = _load_list(row.get('json_files_json'))

        # img_idx is 0-based index from the template
        max_len = max(len(images), len(thumbs), len(webps), len(jfiles), 0)
        if img_idx < 0 or img_idx >= max_len:
            flash('Image index out of range.')
            return redirect(url_for('admin_edit', otype=otype, aid=aid))

        if img_idx < len(images):
            _safe_delete_upload(images[img_idx])
            images.pop(img_idx)
        if img_idx < len(thumbs):
            _safe_delete_upload(thumbs[img_idx])
            thumbs.pop(img_idx)
        if img_idx < len(webps):
            _safe_delete_upload(webps[img_idx])
            webps.pop(img_idx)
        if img_idx < len(jfiles):
            _safe_delete_upload(jfiles[img_idx])
            jfiles.pop(img_idx)

        du_sql = ''
        du_params = []
        if meta.get('field_meta', {}).get('date_updated', {}).get('server_now'):
            du_sql = 'date_updated=?, '
            du_params.append(now.strftime(TIMESTAMP_FORMAT))

        sql = (
            f"UPDATE {otype} SET {du_sql}date_last_saved=?, images_json=?, thumbs_json=?, webps_json=?, json_files_json=? "
            "WHERE id=?"
        )
        params = du_params + [
            now.strftime(TIMESTAMP_FORMAT),
            json.dumps(images), json.dumps(thumbs), json.dumps(webps), json.dumps(jfiles),
            int(aid),
        ]
        conn.execute(sql, params)

    flash('Deleted image.')
    return redirect(url_for('admin_edit', otype=otype, aid=aid))


@app.route("/admin/edit/<otype>/<int:aid>", methods=["GET", "POST"])
@requires_admin
def admin_edit(otype, aid):
    otype = (otype or "").strip().lower()
    if otype not in TYPE_META:
        flash("Unknown object type")
        return redirect(url_for("admin_list"))
    meta = TYPE_META[otype]
    g.current_type = otype
    with get_db() as conn:
        if request.method == "POST":
            from datetime import datetime
            now = datetime.now()
            coerced: dict = {}
            for f in meta["input_fields"]:
                label, col, coltype = f[0], f[1], (f[2] if len(f) > 2 else "TEXT")
                t = (str(coltype or "TEXT")).upper().strip()
                fm = meta["field_meta"].get(col, {})

                # Server-managed timestamp/date (e.g., date_updated/date_recorded)
                if fm.get("server_now"):
                    coerced[col] = now.strftime(DATE_FORMAT) if t == "DATE" else now.strftime(TIMESTAMP_FORMAT)
                    continue

                # Enforce CONSTANT fields as server-controlled values.
                if t == "CONSTANT" or fm.get("widget") == "constant":
                    coerced[col] = str(fm.get("constant_value") or "")
                    continue

                # RADIO fields are multi-select, stored as JSON list (TEXT).
                if fm.get("widget") == "radio":
                    selected = [str(v).strip() for v in request.form.getlist(col) if str(v).strip()]
                    coerced[col] = json.dumps(selected, ensure_ascii=False, separators=(",", ":")) if selected else None
                    continue

                raw = (request.form.get(col) or "").strip()
                if fm.get("widget") == "uppercase" and raw:
                    raw = raw.upper()
                if not raw:
                    coerced[col] = None
                elif t.startswith("INT"):
                    try:
                        coerced[col] = int(raw)
                    except ValueError:
                        coerced[col] = None
                elif t.startswith("FLOAT") or t.startswith("REAL") or t.startswith("DOUBLE"):
                    try:
                        coerced[col] = float(raw)
                    except ValueError:
                        coerced[col] = None
                elif t == "DATE":
                    coerced[col] = _normalize_date_input(raw)
                elif t == "TIMESTAMP":
                    coerced[col] = _normalize_timestamp_input(raw)
                else:
                    coerced[col] = raw

            # Apply optional server-side postprocessing to Edit updates.
            try:
                coerced = _apply_postprocess_values(otype, coerced)
            except Exception:
                flash("post processing failed, please correct.")
                row0 = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
                r0 = dict(row0) if row0 else {}
                r0.update(coerced or {})
                return render_template(
                    "admin_edit.html",
                    r=r0,
                    otype=otype,
                    meta=meta,
                    banner_title=make_banner_title("Edit", meta["label"], f"ID {aid}"),
                )

            updates = dict(coerced or {})
            # App-internal save timestamp always bumps on edit.
            updates["date_last_saved"] = now.strftime(TIMESTAMP_FORMAT)
            if meta.get("field_meta", {}).get("date_updated", {}).get("server_now"):
                updates["date_updated"] = now.strftime(TIMESTAMP_FORMAT)
            # Special: date_recorded also bumps on every save if defined.
            if meta.get("field_meta", {}).get("date_recorded", {}).get("server_now"):
                updates["date_recorded"] = now.strftime(TIMESTAMP_FORMAT)

            if updates:
                set_clause = ", ".join([f"{c}=?" for c in updates.keys()])
                params = list(updates.values()) + [aid]
                conn.execute(f"UPDATE {otype} SET {set_clause} WHERE id=?", params)
                flash(f"Updated {otype} {aid}")
            return redirect(url_for("admin_list", type=otype))

        row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        flash("Not found")
        return redirect(url_for("admin_list", type=otype))
    g.current_type = otype
    # Jinja templates often use mapping methods like .get(); sqlite3.Row does not provide .get.
    # Normalize to a plain dict for template friendliness.
    return render_template(
        "admin_edit.html",
        r=dict(row),
        otype=otype,
        meta=meta,
        banner_title=make_banner_title("Edit", meta["label"], f"ID {aid}"),
    )


@app.route("/admin/delete/<otype>/<int:aid>", methods=["POST"])
@requires_admin
def admin_delete(otype, aid):
    otype = (otype or "").strip().lower()
    if otype not in TYPE_META:
        flash("Unknown object type")
        return redirect(url_for("admin_list"))
    with get_db() as conn:
        row = conn.execute(
            f"SELECT images_json, thumbs_json, webps_json, json_files_json FROM {otype} WHERE id=?",
            (aid,),
        ).fetchone()
        conn.execute(f"DELETE FROM {otype} WHERE id=?", (aid,))
    if row:
        try:
            files = []
            for col in ["images_json", "thumbs_json", "webps_json", "json_files_json"]:
                files.extend(json.loads(row[col] or "[]") or [])
        except Exception:
            files = []
        for fn in files:
            if fn:
                try:
                    (UPLOAD_DIR / fn).unlink(missing_ok=True)
                except Exception:
                    pass
    flash(f"Deleted {otype} {aid}")
    return redirect(url_for("admin_list", type=otype))


@app.route("/admin/export.csv")
@requires_admin
def admin_export_csv():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM {otype} ORDER BY id ASC"
        ).fetchall()
        headers = rows[0].keys() if rows else []

    def generate():
        yield ",".join(headers) + "\n"
        with get_db() as conn2:
            for r in conn2.execute(f"SELECT * FROM {otype} ORDER BY id ASC"):
                vals = []
                for h in headers:
                    v = r[h]
                    if v is None:
                        vals.append("")
                    else:
                        s = str(v)
                        if any(c in s for c in [",", "\n", '"']):
                            s = '"' + s.replace('"', '""') + '"'
                        vals.append(s)
                yield ",".join(vals) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={otype}.csv"},
    )


@app.route("/admin/record/<otype>/<int:aid>.json")
@requires_admin
def admin_record_json(otype: str, aid: int):
    """Return a single record as JSON, including *all* attached images."""
    otype = (otype or "").strip().lower()
    if otype not in TYPE_META:
        return jsonify({"error": "Unknown object type"}), 404
    meta = TYPE_META[otype]
    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    def _loads(val):
        if not val:
            return []
        try:
            x = json.loads(val)
            return x if isinstance(x, list) else []
        except Exception:
            return []

    fields = {}
    for f in meta["input_fields"]:
        col = f[1]
        fields[col] = row[col]

    payload = {
        "object_type": otype,
        "record_id": row["id"],
        "fields": fields,
        "images": _loads(row["images_json"]),
        "thumbs": _loads(row["thumbs_json"]),
        "webps": _loads(row["webps_json"]),
        "image_json_files": _loads(row["json_files_json"]),
        "timestamp": row["timestamp"],
        "client_ip": row["ip"],
        "user_agent": row["user_agent"],
        "gps": {"lat": row["gps_lat"], "lon": row["gps_lon"], "alt": row["gps_alt"]},
        "exif": {
            "datetime": row["exif_datetime"],
            "make": row["exif_make"],
            "model": row["exif_model"],
            "orientation": row["exif_orientation"],
        },
    }
    return jsonify(payload)


@app.route("/admin/record/<otype>/<int:aid>/images")
@requires_admin
def admin_record_images(otype: str, aid: int):
    """Render a gallery of *all* images for a record.

    This exists because many records can accumulate multiple photos, and linking to a single
    JPEG is confusing.
    """
    otype = (otype or "").strip().lower()
    if otype not in TYPE_META:
        return "Unknown object type", 404
    g.current_type = otype
    meta = TYPE_META[otype]
    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        return "Not found", 404

    def _loads(val):
        if not val:
            return []
        try:
            x = json.loads(val)
            return x if isinstance(x, list) else []
        except Exception:
            return []

    images = _loads(row["images_json"])
    thumbs = _loads(row["thumbs_json"])
    return render_template(
        "record_images.html",
        otype=otype,
        meta=meta,
        r=row,
        images=images,
        thumbs=thumbs,
        banner_title=make_banner_title("Images", f"{meta['label']} {row['id']}"),
    )


@app.route("/admin/export.geojson")
@requires_admin
def admin_export_geojson():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    meta = TYPE_META[otype]
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM {otype} "
            "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL "
            "ORDER BY id ASC"
        ).fetchall()
    features = []
    for r in rows:
        props = {}
        for f in meta["input_fields"]:
            label, col, _ctype = f[0], f[1], f[2]
            props[col] = r[col]
        props.update({
            "id": r["id"],
            "images": json.loads(r["images_json"] or "[]") if r["images_json"] else [],
            "thumbs": json.loads(r["thumbs_json"] or "[]") if r["thumbs_json"] else [],
            "webps": json.loads(r["webps_json"] or "[]") if r["webps_json"] else [],
            "json_files": json.loads(r["json_files_json"] or "[]") if r["json_files_json"] else [],
            "timestamp": r["timestamp"],
            "exif_datetime": r["exif_datetime"],
            "camera": " ".join(p for p in [r["exif_make"], r["exif_model"]] if p),
        })
        feat = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["gps_lon"], r["gps_lat"]],
            },
            "properties": props,
        }
        features.append(feat)
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/admin/map")
@requires_admin
def admin_map():
    if not GPS_ENABLED:
        flash("GPS is disabled; map view is unavailable.")
        return redirect(url_for("admin_list", type=_get_current_type()))
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    g.current_type = otype
    return render_template(
        "admin_map.html",
        otype=otype,
        meta=TYPE_META[otype],
        banner_title=make_banner_title("Edit", "Map", TYPE_META[otype]["label"]),
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=3000)
