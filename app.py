
from __future__ import annotations

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_from_directory, jsonify, g, session, Response
)
from pathlib import Path
from io import BytesIO
from functools import wraps
import sqlite3, os, time, json, ast, re, collections
from datetime import datetime, date

from PIL import Image, ImageOps, ExifTags
from dateutil import parser as dtparser

import config as app_config


# -----------------------------------------------------------------------------
# App / paths / constants (keep compatible with config.py expectations)
# -----------------------------------------------------------------------------

APP_ROOT = Path(__file__).parent.resolve()

UPLOAD_DIR = Path(os.environ.get("ARTCAP_UPLOAD_DIR", str(APP_ROOT / "uploads"))).expanduser().resolve()
DB_PATH = Path(os.environ.get("ARTCAP_DB_PATH", str(APP_ROOT / "data" / "artifacts.db"))).expanduser().resolve()

ADMIN_USER = os.getenv("ARTCAP_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ARTCAP_ADMIN_PASS", "change-me")
APP_SECRET = os.getenv("ARTCAP_SECRET", "change-me")

MAX_DIM = int(os.getenv("ARTCAP_MAX_DIM", "3000"))
THUMB_DIM = int(os.getenv("ARTCAP_THUMB_DIM", "400"))
JPEG_QUALITY = int(os.getenv("ARTCAP_JPEG_QUALITY", "92"))
WEBP_QUALITY = int(os.getenv("ARTCAP_WEBP_QUALITY", "85"))

APP_BRAND = getattr(app_config, "APP_BRAND", "Artifact Capture")
APP_SUBTITLE = getattr(app_config, "APP_SUBTITLE", "")
APP_LOGO = getattr(app_config, "APP_LOGO", "logo.svg")
ADMIN_LABEL = getattr(app_config, "ADMIN_LABEL", "Admin")
DATE_FORMAT = getattr(app_config, "DATE_FORMAT", "%Y-%m-%d")
TIMESTAMP_FORMAT = getattr(app_config, "TIMESTAMP_FORMAT", DATE_FORMAT + "T%H:%M:%S")

BANNER_BG = getattr(app_config, "BANNER_BG", "#111827")
BANNER_FG = getattr(app_config, "BANNER_FG", "#ffffff")
BANNER_ACCENT = getattr(app_config, "BANNER_ACCENT", "#60a5fa")
SHOW_LOGO = bool(getattr(app_config, "SHOW_LOGO", True))

GRID_MAX_WIDTH = int(getattr(app_config, "GRID_MAX_WIDTH", getattr(app_config, "grid_max_width", 500)))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    raw = str(raw).strip().lower()
    if raw == "":
        return bool(default)
    return raw in ("1", "true", "yes", "y", "on")


GPS_ENABLED = _env_bool("ARTCAP_GPS_ENABLED", default=getattr(app_config, "GPS_ENABLED", False))


# -----------------------------------------------------------------------------
# Config normalization: build TYPE_META from config.object_types (unchanged schema)
# -----------------------------------------------------------------------------

def _parse_widget(widget_raw: str) -> tuple[str, list[str] | None]:
    """Parse DROPDOWN('a','b') / RADIO('a','b') strings from config.py."""
    widget_raw = (widget_raw or "").strip()
    if not widget_raw:
        return "text", None

    up = widget_raw.upper()
    if up.startswith("DROPDOWN"):
        kind = "dropdown"
    elif up.startswith("RADIO"):
        kind = "radio"
    else:
        return "text", None

    try:
        start = widget_raw.index("(")
        inside = widget_raw[start:]
        vals = ast.literal_eval(inside)
        if isinstance(vals, (list, tuple)):
            options = [str(v) for v in vals]
        else:
            options = [str(vals)]
        return kind, options
    except Exception as e:
        raise RuntimeError(f"Could not parse widget spec {widget_raw!r} in config.py") from e


OBJECT_TYPES = getattr(app_config, "object_types", None) or {}
if not isinstance(OBJECT_TYPES, dict) or not OBJECT_TYPES:
    raise RuntimeError("config.py must define a non-empty dict named object_types")

SYSTEM_COLUMNS = {
    "id",
    "gps_lat", "gps_lon", "gps_alt", "gps_acc",
    "thumbs_json", "images_json", "webps_json", "json_files_json",
    "date_last_saved", "date_recorded", "date_updated",
}

TYPE_META: dict[str, dict] = {}

for otype, cfg in OBJECT_TYPES.items():
    label = cfg.get("label") or otype.title()
    input_fields = cfg.get("input_fields") or []
    if not input_fields:
        raise RuntimeError(f"object_types[{otype!r}] has no input_fields")

    required_fields = tuple([c for c in (cfg.get("required_fields") or ()) if c not in SYSTEM_COLUMNS])

    field_meta: dict[str, dict] = {}
    for f in input_fields:
        flabel, col, sql_type = f[0], f[1], (f[2] if len(f) > 2 else "TEXT")
        sql_type_str = str(sql_type or "TEXT")
        st_up = sql_type_str.strip().upper()

        constant_value = None
        server_now = False

        if st_up == "CONSTANT":
            widget = "constant"
            options = None
            constant_value = str(f[3]) if len(f) > 3 else ""
            sqlite_type = "TEXT"
            sql_type_str = "TEXT"
        elif st_up == "UPPERCASE":
            widget = "uppercase"
            options = None
            sqlite_type = "TEXT"
            sql_type_str = "TEXT"
        else:
            widget_raw = f[3] if len(f) > 3 else ""
            widget, options = _parse_widget(widget_raw)
            sqlite_type = sql_type_str

        # server-managed timestamps
        if str(col).lower() == "date_updated" and st_up.startswith("TIMESTAMP"):
            server_now = True
        if str(col).lower() == "date_recorded" and (st_up.startswith("TIMESTAMP") or st_up == "TIMESTAMP"):
            server_now = True

        field_meta[col] = {
            "label": flabel,
            "col": col,
            "sql_type": sql_type_str,     # UI semantics
            "sqlite_type": sqlite_type,   # schema
            "widget": widget,
            "options": options,
            "constant_value": constant_value,
            "server_now": server_now,
            "required": col in required_fields,
        }

    TYPE_META[otype] = {
        "otype": otype,
        "label": label,
        "cfg": cfg,
        "input_fields": input_fields,
        "field_meta": field_meta,
        "index_fields": list(cfg.get("index") or []),
        "result_rows": cfg.get("result_rows") or cfg.get("layout_rows") or [],
        "layout_rows": cfg.get("layout_rows") or [],
        "fields_to_reset": cfg.get("fields_to_reset") or [],
        "copy_from": cfg.get("copy_from"),
        "filename_format": cfg.get("filename_format") or "",
        "result_grid": cfg.get("result_grid") or [],
    }


# Compute result_fields (used by table/grid renderers) from result_rows/layout_rows.
for _otype, _m in TYPE_META.items():
    cfg = _m["cfg"] or {}
    rr = cfg.get("result_rows") or cfg.get("layout_rows") or []
    if not rr:
        rr = [[f[1]] for f in (_m.get("input_fields") or []) if len(f) > 1]
    seen = set()
    result_fields = []
    for row in rr:
        for col in (row or []):
            if not col:
                continue
            if col in seen:
                continue
            seen.add(col)
            # Exclude image/json system columns from the textual table fields
            if col in ("thumbs_json", "images_json", "webps_json", "json_files_json"):
                continue
            if col in ("gps_lat", "gps_lon", "gps_alt", "gps_acc"):
                continue
            result_fields.append(col)
    _m["result_fields"] = result_fields



# -----------------------------------------------------------------------------
# Flask app + template globals
# -----------------------------------------------------------------------------

app = Flask(__name__, root_path=str(APP_ROOT))
app.secret_key = APP_SECRET

app.jinja_env.filters["fromjson"] = lambda s: json.loads(s) if s else []


def maps_links(lat, lon):
    if lat is None or lon is None:
        return None, None
    osm = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=18/{lat:.6f}/{lon:.6f}"
    gmaps = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    return osm, gmaps


app.jinja_env.globals["maps_links"] = maps_links


def make_banner_title(title: str | None) -> str:
    return title or ""


def _nav_links(active: str):
    # Only 3 navlinks are public
    return [
        {"label": "Upload", "url": url_for("form"), "active": active == "upload"},
        {"label": "Browse", "url": url_for("browse"), "active": active == "browse"},
        {"label": "Info", "url": url_for("info"), "active": active == "info"},
    ]


@app.context_processor
def inject_globals():
    return {
        "APP_BRAND": APP_BRAND,
        "APP_SUBTITLE": APP_SUBTITLE,
        "APP_LOGO": APP_LOGO,
        "ADMIN_LABEL": ADMIN_LABEL,
        "DATE_FORMAT": DATE_FORMAT,
        "TIMESTAMP_FORMAT": TIMESTAMP_FORMAT,
        "BANNER_BG": BANNER_BG,
        "BANNER_FG": BANNER_FG,
        "BANNER_ACCENT": BANNER_ACCENT,
        "SHOW_LOGO": SHOW_LOGO,
        "OBJECT_TYPES": TYPE_META,
        "TYPE_META": TYPE_META,
        "GPS_ENABLED": GPS_ENABLED,
        "grid_max_width": GRID_MAX_WIDTH,
    }


# -----------------------------------------------------------------------------
# DB
# -----------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def _close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _table_columns(table: str) -> set[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {r[1] for r in rows}
        except Exception:
            return set()

    def _ensure_column(table: str, col: str, decl: str):
        existing = _table_columns(table)
        if col in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {decl}")

    conn = get_db()
    for otype, meta in TYPE_META.items():
        # Build the canonical schema for every table.
        # IMPORTANT: GPS columns must *always* exist so databases can be
        # imported/exported between GPS-enabled and non-GPS builds.
        cols = []
        cols.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
        cols += [
            "gps_lat REAL",
            "gps_lon REAL",
            "gps_alt REAL",
            "gps_acc REAL",
            "thumbs_json TEXT",
            "images_json TEXT",
            "webps_json TEXT",
            "json_files_json TEXT",
            "date_last_saved TEXT",
        ]

        for col, fm in meta["field_meta"].items():
            if col in SYSTEM_COLUMNS:
                # keep schema compatibility; these may appear in input_fields but are server-managed
                if col == "date_recorded":
                    cols.append("date_recorded TEXT")
                elif col == "date_updated":
                    cols.append("date_updated TEXT")
                continue
            cols.append(f'"{col}" {fm["sqlite_type"]}')

        ddl = f"CREATE TABLE IF NOT EXISTS {otype} ({', '.join(cols)})"
        conn.execute(ddl)

        # Lightweight migration: if the table already exists, add any missing
        # columns (e.g., when GPS columns were previously omitted).
        existing = _table_columns(otype)
        if existing:
            for decl in cols[1:]:  # skip id
                # decl can be like: gps_lat REAL or "col" TEXT
                m = re.match(r'^"?([A-Za-z0-9_]+)"?\s+.+$', decl)
                if not m:
                    continue
                c = m.group(1)
                if c not in existing:
                    _ensure_column(otype, c, decl)

    conn.commit()


@app.before_request
def _ensure_db():
    init_db()


# -----------------------------------------------------------------------------
# Auth (kept for hidden Account functionality)
# -----------------------------------------------------------------------------

def is_logged_in() -> bool:
    return session.get("is_admin") is True


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("account", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/account", methods=["GET", "POST"])
def account():
    # Hidden tab; route retained
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["is_admin"] = True
            flash("Logged in.")
            nxt = request.args.get("next") or url_for("browse")
            return redirect(nxt)
        flash("Invalid credentials.")
    return render_template("user.html", NAV_LINKS=_nav_links(active=""), banner_title="Account")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("browse"))


# -----------------------------------------------------------------------------
# Date handling (simplified)
# -----------------------------------------------------------------------------

_DIGITS_ONLY = re.compile(r"^\d{6,8}$")


def parse_user_date(raw: str) -> str | None:
    """Accepts flexible user date input; returns ISO date (YYYY-MM-DD) or None.

    Heuristics:
      - 6 digits: DDMMYY (e.g. 020286 -> 1986-02-02)
      - 8 digits: DDMMYYYY
      - otherwise: dateutil parser with dayfirst=True
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    if _DIGITS_ONLY.match(s):
        if len(s) == 6:
            dd, mm, yy = int(s[0:2]), int(s[2:4]), int(s[4:6])
            year = 1900 + yy if yy >= 50 else 2000 + yy
            return date(year, mm, dd).isoformat()
        if len(s) == 8:
            dd, mm, yyyy = int(s[0:2]), int(s[2:4]), int(s[4:8])
            return date(yyyy, mm, dd).isoformat()

    # "reasonable formats"
    dt = dtparser.parse(s, dayfirst=True, yearfirst=False, fuzzy=True, default=datetime(2000, 1, 1))
    return dt.date().isoformat()


def now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# -----------------------------------------------------------------------------
# Images + EXIF + GPS (carried over, but lightly simplified)
# -----------------------------------------------------------------------------

_EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}


def _save_derivatives(img: Image.Image, stem: str) -> tuple[str, str, str]:
    """Save main JPG, WEBP, and thumbnail JPG. Returns (jpg, webp, thumb) basenames."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # normalize orientation
    img = ImageOps.exif_transpose(img)

    # scale down large images
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)))

    jpg_name = f"{stem}.jpg"
    webp_name = f"{stem}.webp"
    thumb_name = f"{stem}.thumb.jpg"

    jpg_path = UPLOAD_DIR / jpg_name
    webp_path = UPLOAD_DIR / webp_name
    thumb_path = UPLOAD_DIR / thumb_name

    img.save(jpg_path, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    try:
        img.save(webp_path, format="WEBP", quality=WEBP_QUALITY, method=6)
    except Exception:
        # WEBP is optional
        webp_name = ""

    # thumbnail
    t = img.copy()
    t.thumbnail((THUMB_DIM, THUMB_DIM))
    t.save(thumb_path, format="JPEG", quality=85, optimize=True)

    return jpg_name, webp_name, thumb_name


def _exif_gps_from_pil(img: Image.Image):
    """Return (lat, lon, alt, acc) where acc is unknown (None)."""
    try:
        exif = img.getexif()
        if not exif:
            return None, None, None, None
        gps_info = exif.get(_EXIF_TAGS.get("GPSInfo"))
        if not gps_info:
            return None, None, None, None

        def _ratio_to_float(x):
            try:
                return float(x[0]) / float(x[1])
            except Exception:
                return float(x)

        def _dms_to_deg(dms, ref):
            d = _ratio_to_float(dms[0])
            m = _ratio_to_float(dms[1])
            s = _ratio_to_float(dms[2])
            deg = d + (m / 60.0) + (s / 3600.0)
            if ref in ("S", "W"):
                deg = -deg
            return deg

        lat = lon = alt = None
        if 2 in gps_info and 1 in gps_info:  # GPSLatitude + ref
            lat = _dms_to_deg(gps_info[2], gps_info[1])
        if 4 in gps_info and 3 in gps_info:  # GPSLongitude + ref
            lon = _dms_to_deg(gps_info[4], gps_info[3])
        if 6 in gps_info:
            alt = _ratio_to_float(gps_info[6])
        return lat, lon, alt, None
    except Exception:
        return None, None, None, None


# -----------------------------------------------------------------------------
# Upload (unchanged UX): /upload + /submit + /exists
# -----------------------------------------------------------------------------

@app.route("/")
def root():
    return redirect(url_for("form"))


@app.route("/upload", methods=["GET"])
@app.route("/form", methods=["GET"])
def form():
    last_id = request.args.get("last_id", type=int)
    last_type = request.args.get("last_type", type=str)
    last_row = None
    last_meta = None
    if last_id and last_type and last_type in TYPE_META:
        with get_db() as conn:
            last_row = conn.execute(f"SELECT * FROM {last_type} WHERE id=?", (last_id,)).fetchone()
            last_meta = TYPE_META[last_type]

    selected = request.args.get("type") or (last_type if last_type in TYPE_META else None)
    if selected not in TYPE_META:
        selected = next(iter(TYPE_META.keys()))
    g.current_type = selected

    prefill_by_type = session.get("prefill_by_type", {})
    current_record_by_type = session.get("current_record_by_type", {})

    return render_template(
        "upload.html",
        last_row=last_row, last_type=last_type, last_meta=last_meta,
        selected_type=selected,
        banner_title=make_banner_title(selected.capitalize()),
        NAV_LINKS=_nav_links(active="upload"),
        prefill_by_type=prefill_by_type,
        current_record_by_type=current_record_by_type,
    )


@app.route("/exists", methods=["POST"])
def exists():
    otype = (request.form.get("object_type") or "").strip().lower()
    if otype not in TYPE_META:
        return jsonify({"exists": False, "id": None})

    meta = TYPE_META[otype]

    meta_values = _coerce_form_values(meta, request.form, allow_missing=True)
    # remove server-managed timestamps from match key
    for k, fm in meta["field_meta"].items():
        if fm.get("server_now"):
            meta_values.pop(k, None)

    # Build a deterministic matching WHERE: all provided non-empty fields must match
    where = []
    params = []
    for col, v in meta_values.items():
        if v is None or str(v).strip() == "":
            continue
        where.append(f'"{col}" = ?')
        params.append(v)

    if not where:
        return jsonify({"exists": False, "id": None})

    sql = f"SELECT id FROM {otype} WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 1"
    row = get_db().execute(sql, params).fetchone()
    return jsonify({"exists": row is not None, "id": int(row["id"]) if row else None})


def _coerce_form_values(meta: dict, form, allow_missing: bool = False) -> dict:
    out = {}
    now_ts = now_timestamp()

    for fdef in meta["input_fields"]:
        _label, col, coltype = fdef[0], fdef[1], (fdef[2] if len(fdef) > 2 else "TEXT")
        fm = meta["field_meta"].get(col, {})
        t = str(coltype or "TEXT").strip().upper()

        if fm.get("widget") == "constant":
            out[col] = str(fm.get("constant_value") or "")
            continue

        if fm.get("widget") == "radio":
            selected = [str(v).strip() for v in form.getlist(col) if str(v).strip()]
            out[col] = json.dumps(selected, ensure_ascii=False, separators=(",", ":")) if selected else (None if allow_missing else "")
            continue

        raw = form.get(col)
        if raw is None and allow_missing:
            continue

        s = (raw or "").strip()
        if not s:
            out[col] = None
            continue

        if t == "DATE":
            out[col] = parse_user_date(s)
        elif t == "TIMESTAMP":
            # Users shouldn't need to enter timestamps; accept but coerce to ISO date-only if they do.
            out[col] = parse_user_date(s) + "T00:00:00"
        elif fm.get("widget") == "uppercase" or t == "UPPERCASE":
            out[col] = s.upper()
        else:
            out[col] = s

        if fm.get("server_now"):
            out[col] = now_ts

    return out


@app.route("/submit", methods=["POST"])
def submit():
    """Create (or duplicate) a new record and/or add an image to the current record (unchanged UX)."""
    otype = (request.form.get("object_type") or "").strip().lower()
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("form"))

    meta = TYPE_META[otype]

    # Coerce form values
    values = _coerce_form_values(meta, request.form, allow_missing=False)

    # If GPS is enabled, accept gps_ fields from form OR EXIF
    gps_lat = request.form.get("gps_lat", type=float)
    gps_lon = request.form.get("gps_lon", type=float)
    gps_alt = request.form.get("gps_alt", type=float)
    gps_acc = request.form.get("gps_acc", type=float)

    # Button routing (matches existing upload template)
    action = (request.form.get("action") or "").strip().lower()

    photo = request.files.get("photo")

    # Create a new record row first (New Record)
    if action in ("new", "new_record", "newrecord", "metadata", "upload metadata"):
        rid = _insert_record_only(otype, meta, values, gps_lat, gps_lon, gps_alt, gps_acc)
        session.setdefault("current_record_by_type", {})[otype] = rid
        flash(f"Saved {meta['label']} ID {rid}")
        return redirect(url_for("form", last_id=rid, last_type=otype, type=otype))

    # Add image (may create record if needed)
    if action in ("add", "add_image", "add image", "upload image"):
        rid = session.get("current_record_by_type", {}).get(otype)
        if not rid:
            rid = _insert_record_only(otype, meta, values, gps_lat, gps_lon, gps_alt, gps_acc)
            session.setdefault("current_record_by_type", {})[otype] = rid

        if not photo or not getattr(photo, "filename", ""):
            flash("No image selected.")
            return redirect(url_for("form", last_id=rid, last_type=otype, type=otype))

        _attach_image(otype, rid, photo, gps_lat, gps_lon, gps_alt, gps_acc)
        flash(f"Added image to {meta['label']} ID {rid}")
        return redirect(url_for("form", last_id=rid, last_type=otype, type=otype))

    # Update metadata for the current record (Upload tab behavior)
    if action in ("update_record", "update"):
        rid = session.get("current_record_by_type", {}).get(otype)
        if not rid:
            rid = _insert_record_only(otype, meta, values, gps_lat, gps_lon, gps_alt, gps_acc)
            session.setdefault("current_record_by_type", {})[otype] = rid

        conn = get_db()
        sets = []
        params = []
        for col, v in values.items():
            if col in SYSTEM_COLUMNS:
                continue
            sets.append(f'"{col}"=?')
            params.append(v)

        sets.append("date_last_saved=?")
        params.append(now_timestamp())

        # Always allow storing GPS values when provided; schema always includes GPS columns.
        if gps_lat is not None and gps_lon is not None:
            sets += ["gps_lat=?", "gps_lon=?", "gps_alt=?", "gps_acc=?"]
            params += [gps_lat, gps_lon, gps_alt, gps_acc]

        params.append(rid)
        conn.execute(f"UPDATE {otype} SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
        flash(f"Updated {meta['label']} ID {rid}")
        return redirect(url_for("form", last_id=rid, last_type=otype, type=otype))

    # Reset / copy-from behavior preserved by keeping existing JS+template
    # Fall back: treat as new record
    rid = _insert_record_only(otype, meta, values, gps_lat, gps_lon, gps_alt, gps_acc)
    session.setdefault("current_record_by_type", {})[otype] = rid
    flash(f"Saved {meta['label']} ID {rid}")
    return redirect(url_for("form", last_id=rid, last_type=otype, type=otype))


def _insert_record_only(otype: str, meta: dict, values: dict, gps_lat, gps_lon, gps_alt, gps_acc) -> int:
    conn = get_db()

    cols = []
    params = []
    for col, val in values.items():
        if col in SYSTEM_COLUMNS:
            # keep explicit date_recorded/date_updated if present
            if col in ("date_recorded", "date_updated", "date_last_saved"):
                cols.append(col)
                params.append(val)
            continue
        cols.append(f'"{col}"')
        params.append(val)

    # system columns
    cols += ["thumbs_json", "images_json", "webps_json", "json_files_json", "date_last_saved"]
    params += ["[]", "[]", "[]", "[]", now_timestamp()]

    # GPS columns always exist in the schema; include them in every insert.
    cols += ["gps_lat", "gps_lon", "gps_alt", "gps_acc"]
    params += [gps_lat, gps_lon, gps_alt, gps_acc]

    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO {otype} ({', '.join(cols)}) VALUES ({placeholders})"
    cur = conn.execute(sql, params)
    conn.commit()
    return int(cur.lastrowid)


def _attach_image(otype: str, rid: int, file_storage, gps_lat, gps_lon, gps_alt, gps_acc):
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (rid,)).fetchone()
    if not row:
        raise RuntimeError("Record not found")

    raw_bytes = file_storage.read()
    img = Image.open(BytesIO(raw_bytes))

    exif_lat, exif_lon, exif_alt, exif_acc = _exif_gps_from_pil(img)
    if GPS_ENABLED and (gps_lat is None or gps_lon is None):
        gps_lat, gps_lon, gps_alt, gps_acc = exif_lat, exif_lon, exif_alt, exif_acc

    stem = f"{otype}-{rid}-{int(time.time())}"
    jpg_name, webp_name, thumb_name = _save_derivatives(img, stem)

    def _append_json_list(colname, val):
        arr = json.loads(row[colname] or "[]")
        if not isinstance(arr, list):
            arr = []
        arr.append(val)
        return json.dumps(arr, ensure_ascii=False, separators=(",", ":"))

    thumbs_json = _append_json_list("thumbs_json", thumb_name)
    images_json = _append_json_list("images_json", jpg_name)
    webps_json = _append_json_list("webps_json", webp_name) if webp_name else row["webps_json"]

    upd_cols = {
        "thumbs_json": thumbs_json,
        "images_json": images_json,
        "webps_json": webps_json,
        "date_last_saved": now_timestamp(),
    }
    if gps_lat is not None and gps_lon is not None:
        upd_cols.update({"gps_lat": gps_lat, "gps_lon": gps_lon, "gps_alt": gps_alt, "gps_acc": gps_acc})

    sets = ", ".join([f"{k}=?" for k in upd_cols.keys()])
    conn.execute(f"UPDATE {otype} SET {sets} WHERE id=?", list(upd_cols.values()) + [rid])
    conn.commit()


@app.route("/uploads/<path:fname>")
def serve_upload(fname):
    return send_from_directory(str(UPLOAD_DIR), fname, as_attachment=False)


# -----------------------------------------------------------------------------
# Browse (merged Recent+Review)
# -----------------------------------------------------------------------------

@app.route("/browse")
def browse():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    g.current_type = otype
    meta = TYPE_META[otype]

    index_fields = [f for f in (meta.get("index_fields") or []) if f in meta["field_meta"]]
    field = (request.args.get("field") or (index_fields[0] if index_fields else "")).strip()
    if field not in index_fields and index_fields:
        field = index_fields[0]

    view = (request.args.get("view") or "para").strip().lower()
    if view not in ("para", "table", "grid"):
        view = "para"

    mode = (request.args.get("mode") or "index").strip().lower()
    if mode not in ("index", "recent"):
        mode = "index"

    q = (request.args.get("q") or "").strip()

    # pagination
    page = max(int(request.args.get("page") or 1), 1)
    per_page_choices = [10, 25, 50, 100, 300]
    try:
        per_page = int(request.args.get("per_page") or 25)
    except ValueError:
        per_page = 25
    if per_page not in per_page_choices:
        per_page = 25

    offset = (page - 1) * per_page

    where_clauses = []
    params = []

    if mode == "index" and field:
        where_clauses.append(f'("{field}" IS NOT NULL AND TRIM(CAST("{field}" AS TEXT)) != "" AND CAST("{field}" AS TEXT) != ?)')
        params.append("[]")

    if q:
        # generic LIKE search across user fields + id
        like = f"%{q}%"
        or_terms = ['CAST(id AS TEXT) LIKE ?']
        params.append(like)
        for col in meta["field_meta"].keys():
            if col in ("thumbs_json", "images_json", "webps_json", "json_files_json"):
                continue
            or_terms.append(f'CAST("{col}" AS TEXT) LIKE ?')
            params.append(like)
        where_clauses.append("(" + " OR ".join(or_terms) + ")")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db()
    # Fetch all matching rows first, then paginate in Python. This keeps pagination stable
    # for grouped/index views (and matches legacy Review behavior more closely).
    all_rows = conn.execute(
        f"SELECT * FROM {otype}{where_sql}",
        params
    ).fetchall()

    def _group_key(r):
        if not field:
            return ""
        v = r[field] if field in r.keys() else ""
        if v is None:
            s = ""
        else:
            s = str(v).strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    s = ", ".join([str(x) for x in arr if str(x).strip()])
            except Exception:
                pass
        return s.strip() or "(no value)"

    if mode == "recent":
        all_rows = sorted(all_rows, key=lambda r: int(r["id"]), reverse=True)
    else:
        # index mode: sort by the displayed group key, then newest within group
        all_rows = sorted(
            all_rows,
            key=lambda r: (
                1 if _group_key(r) == "(no value)" else 0,
                _group_key(r).lower(),
                -int(r["id"])
            )
        )

    total = len(all_rows)
    rows = all_rows[offset: offset + per_page]

    start_n = offset + 1 if total and rows else 0
    end_n = offset + len(rows) if total and rows else 0
    has_prev = page > 1
    has_next = (offset + per_page) < total

    def _q(**kw):
        base = {"type": otype, "field": field, "view": view, "page": page, "per_page": per_page, "mode": mode, "q": q}
        base.update(kw)
        return base

    prev_q = _q(page=page - 1) if has_prev else None
    next_q = _q(page=page + 1) if has_next else None

    # grouping
    groups = []
    if mode == "recent" or not field:
        groups = [("Recent" if mode == "recent" else "", rows)]
    else:
        tmp = collections.defaultdict(list)
        for r in rows:
            v = r[field] if field in r.keys() else ""
            key = ""
            if v is None:
                key = ""
            else:
                s = str(v).strip()
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

    return render_template(
        "index.html",
        page_mode="browse",
        banner_title=make_banner_title(meta["label"]),
        NAV_LINKS=_nav_links(active="browse"),
        otype=otype,
        meta=meta,
        index_fields=index_fields,
        field=field,
        view=view,
        mode=mode,
        q=q,
        groups=groups,
        rows=rows,
        page=page,
        per_page=per_page,
        per_page_choices=per_page_choices,
        total=total,
        start_n=start_n,
        end_n=end_n,
        has_prev=has_prev,
        has_next=has_next,
        prev_q=prev_q,
        next_q=next_q,
    )


# -----------------------------------------------------------------------------
# Edit (single record, reached only from Browse)
# -----------------------------------------------------------------------------

@app.route("/admin/edit/<otype>/<int:aid>", methods=["GET", "POST"])
def admin_edit(otype, aid):
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("browse"))
    meta = TYPE_META[otype]

    conn = get_db()
    row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        flash("Record not found.")
        return redirect(url_for("browse", type=otype))

    if request.method == "POST":
        # Update only fields present in form
        values = _coerce_form_values(meta, request.form, allow_missing=True)

        sets = []
        params = []
        for col, v in values.items():
            if col in SYSTEM_COLUMNS:
                continue
            sets.append(f'"{col}"=?')
            params.append(v)
        # server-managed timestamp
        sets.append("date_last_saved=?")
        params.append(now_timestamp())

        if sets:
            params.append(aid)
            conn.execute(f"UPDATE {otype} SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
            flash("Saved.")
        return redirect(url_for("admin_edit", otype=otype, aid=aid))

    return render_template(
        "admin_edit.html",
        otype=otype,
        meta=meta,
        # Keep template compatibility: older templates expect `r`.
        r=row,
        row=row,
        banner_title=f"{meta['label']} {aid}",
        NAV_LINKS=_nav_links(active="browse"),
    )


@app.route("/admin/add-image/<otype>/<int:aid>", methods=["POST"])
def admin_add_image(otype, aid):
    """Add an image to an existing record from the Edit page."""
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("browse"))

    photo = request.files.get("photo")
    if not photo or not getattr(photo, "filename", ""):
        flash("No image selected.")
        return redirect(url_for("admin_edit", otype=otype, aid=aid))

    # Optional GPS fields may be posted; schema always includes GPS columns.
    gps_lat = request.form.get("gps_lat", type=float)
    gps_lon = request.form.get("gps_lon", type=float)
    gps_alt = request.form.get("gps_alt", type=float)
    gps_acc = request.form.get("gps_acc", type=float)

    try:
        _attach_image(otype, aid, photo, gps_lat, gps_lon, gps_alt, gps_acc)
        flash("Added image.")
    except Exception as e:
        flash(f"Failed to add image: {e}")

    return redirect(url_for("admin_edit", otype=otype, aid=aid))


@app.route("/admin/delete/<otype>/<int:aid>", methods=["POST"])
def admin_delete(otype, aid):
    """Delete a single record and any attached files."""
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("browse"))

    conn = get_db()
    row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        flash("Record not found.")
        return redirect(url_for("browse", type=otype))

    # Remove attached files
    for col in ("thumbs_json", "images_json", "webps_json", "json_files_json"):
        try:
            arr = json.loads(row[col] or "[]")
            if isinstance(arr, list):
                for fname in arr:
                    if fname:
                        try:
                            (UPLOAD_DIR / fname).unlink(missing_ok=True)
                        except Exception:
                            pass
        except Exception:
            pass

    conn.execute(f"DELETE FROM {otype} WHERE id=?", (aid,))
    conn.commit()
    flash(f"Deleted {TYPE_META[otype]['label']} {aid}.")
    return redirect(url_for("browse", type=otype))


@app.route("/recent")
def recent():
    """Backward-compatible alias used by older templates: redirects to Browse (Recent mode)."""
    otype = (request.args.get("type") or request.args.get("otype") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    view = (request.args.get("view") or "para").strip().lower()
    if view not in ("para", "table", "grid"):
        view = "para"
    return redirect(url_for("browse", type=otype, mode="recent", view=view))


@app.route("/admin/delete-image/<otype>/<int:aid>/<int:idx>", methods=["POST"])
def admin_delete_image(otype, aid, idx):
    if otype not in TYPE_META:
        return jsonify({"ok": False})
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {otype} WHERE id=?", (aid,)).fetchone()
    if not row:
        return jsonify({"ok": False})

    def _pop(colname):
        arr = json.loads(row[colname] or "[]")
        if not isinstance(arr, list) or idx < 0 or idx >= len(arr):
            return row[colname]
        removed = arr.pop(idx)
        # try remove file on disk
        if removed:
            try:
                (UPLOAD_DIR / removed).unlink(missing_ok=True)
            except Exception:
                pass
        return json.dumps(arr, ensure_ascii=False, separators=(",", ":"))

    thumbs_json = _pop("thumbs_json")
    images_json = _pop("images_json")
    webps_json = _pop("webps_json")

    conn.execute(
        f"UPDATE {otype} SET thumbs_json=?, images_json=?, webps_json=?, date_last_saved=? WHERE id=?",
        (thumbs_json, images_json, webps_json, now_timestamp(), aid),
    )
    conn.commit()
    return jsonify({"ok": True})


# -----------------------------------------------------------------------------
# Import / Export (retained endpoints; buttons are now on Browse)
# -----------------------------------------------------------------------------

@app.route("/admin/export.csv")
def admin_export_csv():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    conn = get_db()
    rows = conn.execute(f"SELECT * FROM {otype} ORDER BY id ASC").fetchall()
    if not rows:
        return Response("", mimetype="text/csv")

    import csv
    buf = BytesIO()
    # write utf-8 with BOM for Excel friendliness
    text = []
    cols = rows[0].keys()
    text.append(",".join([f'"{c}"' for c in cols]) + "\n")
    for r in rows:
        vals = []
        for c in cols:
            v = r[c]
            if v is None:
                vals.append("")
            else:
                s = str(v).replace('"', '""')
                vals.append(f'"{s}"')
        text.append(",".join(vals) + "\n")
    data = "".join(text).encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{otype}.csv"'}
    )
@app.route("/admin/delete-image/<otype>/<int:aid>/<int:img_idx>", methods=["POST"])
def admin_delete_image_compat(otype, aid, img_idx):
    # Backward-compatible alias for older templates that used img_idx.
    return admin_delete_image(otype, aid, img_idx)




@app.route("/admin/import.csv", methods=["POST"])
def admin_import_csv():
    otype = (request.form.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        flash("Unknown object type.")
        return redirect(url_for("browse"))

    file = request.files.get("csv_file")
    if not file or not getattr(file, "filename", ""):
        flash("No CSV selected.")
        return redirect(url_for("browse", type=otype))

    import csv, io
    meta = TYPE_META[otype]
    allowed = set(meta["field_meta"].keys()) | SYSTEM_COLUMNS

    raw = file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    conn = get_db()

    inserted = 0
    bad_dates = []  # (csv_row_num, field, raw_value)

    # csv.DictReader starts at first data row; for friendlier reporting we track row numbers
    csv_row_num = 1  # header line
    for row in reader:
        csv_row_num += 1
        cols = []
        params = []
        for k, v in row.items():
            if k not in allowed or k == "id":
                continue
            vv = (v or "").strip()

            # Gentle DATE parsing: invalid dates are zapped (NULL) and reported.
            if k in meta["field_meta"] and meta["field_meta"][k]["sql_type"].upper() == "DATE":
                if vv:
                    try:
                        vv = parse_user_date(vv)
                    except Exception:
                        bad_dates.append((csv_row_num, k, vv))
                        vv = None
                else:
                    vv = None

            cols.append(f'"{k}"')
            params.append(vv if vv != "" else None)

        cols.append("date_last_saved")
        params.append(now_timestamp())

        if cols:
            placeholders = ",".join(["?"] * len(cols))
            conn.execute(f"INSERT INTO {otype} ({', '.join(cols)}) VALUES ({placeholders})", params)
            inserted += 1

    conn.commit()

    if bad_dates:
        # Show a short summary (avoid spamming flash)
        preview = bad_dates[:8]
        more = len(bad_dates) - len(preview)
        msg = "; ".join([f"row {rn} {fld}='{val}'" for rn, fld, val in preview])
        if more > 0:
            msg += f" (+{more} more)"
        flash(f"Imported {inserted} rows into {otype}. Some invalid dates were cleared: {msg}", "warning")
    else:
        flash(f"Imported {inserted} rows into {otype}.")

    return redirect(url_for("browse", type=otype))

@app.route("/admin/export.geojson")
def admin_export_geojson():
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    conn = get_db()
    rows = conn.execute(
        f"SELECT * FROM {otype} WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL ORDER BY id ASC"
    ).fetchall()

    features = []
    for r in rows:
        props = {k: r[k] for k in r.keys() if k not in ("gps_lat", "gps_lon", "gps_alt", "gps_acc")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["gps_lon"], r["gps_lat"]]},
            "properties": props,
        })

    geo = {"type": "FeatureCollection", "features": features}
    data = json.dumps(geo, ensure_ascii=False).encode("utf-8")
    return Response(
        data,
        mimetype="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{otype}.geojson"'}
    )


@app.route("/admin/map")
def admin_map():
    # retained: used for GPS browsing
    otype = (request.args.get("type") or "").strip().lower()
    if otype not in TYPE_META:
        otype = next(iter(TYPE_META.keys()))
    meta = TYPE_META[otype]
    return render_template(
        "admin_map.html",
        otype=otype,
        meta=meta,
        banner_title=f"{meta['label']} Map",
        NAV_LINKS=_nav_links(active="browse"),
    )


# -----------------------------------------------------------------------------
# Info
# -----------------------------------------------------------------------------

@app.route("/info")
def info():
    return render_template("index.html",
                           page_mode="info",
                           banner_title="Info",
                           NAV_LINKS=_nav_links(active="info"))


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")


# run(server='gunicorn', port=parmz.PORT)
if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser(description="Run the Flask app.")
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)
