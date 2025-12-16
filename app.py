from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, send_from_directory, jsonify
)
from pathlib import Path
from functools import wraps
from io import BytesIO
import sqlite3, time, os, base64, json, ast

from PIL import Image, ImageOps, ExifTags

from config import input_fields, layout_rows, required_fields

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

GPS_ENABLED = os.getenv("ARTCAP_GPS_ENABLED", "0").lower() not in ("0", "false", "off", "no")
app = Flask(__name__)
app.secret_key = APP_SECRET

FIELD_META = {}
for f in input_fields:
    label, col, sql_type = f[0], f[1], f[2]
    widget_raw = f[3] if len(f) > 3 else ""
    widget = "auto"
    options = None
    if isinstance(widget_raw, str) and widget_raw.upper().startswith("DROPDOWN"):
        widget = "dropdown"
        try:
            start = widget_raw.index("(")
            inside = widget_raw[start:]
            vals = ast.literal_eval(inside)
            if isinstance(vals, (list, tuple)):
                options = [str(v) for v in vals]
            else:
                options = [str(vals)]
        except Exception:
            print(f'Could not parse {widget_raw} in config.py. Exiting')
            exit(1)
    FIELD_META[col] = {
        "label": label,
        "col": col,
        "sql_type": sql_type,
        "widget": widget,
        "options": options,
        "required": col in required_fields,
    }

app.jinja_env.globals["input_fields"] = input_fields
app.jinja_env.globals["layout_rows"] = layout_rows
app.jinja_env.globals["field_meta"] = FIELD_META
app.jinja_env.globals["required_fields"] = required_fields
app.jinja_env.globals["GPS_ENABLED"] = GPS_ENABLED


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    meta_cols = []
    for f in input_fields:
        label, col, coltype = f[0], f[1], f[2]
        meta_cols.append((col, coltype))

    base_cols = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("filename", "TEXT"),
        ("thumb_filename", "TEXT"),
        ("webp_filename", "TEXT"),
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
        ("json_filename", "TEXT"),
    ]

    with get_db() as conn:
        cols_sql = ",\n                ".join(
            [f"{name} {ctype}" for name, ctype in [base_cols[0]] + meta_cols + base_cols[1:]]
        )
        conn.execute(f"CREATE TABLE IF NOT EXISTS artifacts ({cols_sql});")

        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(artifacts)")
        }
        for name, ctype in meta_cols + base_cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE artifacts ADD COLUMN {name} {ctype}")


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
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Artifact Admin"'}
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


@app.route("/", methods=["GET"])
def form():
    last_id = request.args.get("last_id", type=int)
    last_row = None
    if last_id:
        with get_db() as conn:
            last_row = conn.execute(
                "SELECT * FROM artifacts WHERE id=?", (last_id,)
            ).fetchone()
    return render_template("upload.html", last_row=last_row)


@app.route("/submit", methods=["POST"])
def submit():
    ts = int(time.time())
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    meta_values = {}
    for f in input_fields:
        label, col, coltype = f[0], f[1], f[2]
        t = (coltype or "TEXT").upper()
        if t.startswith("TIMESTAMP"):
            meta_values[col] = ts_str
            continue

        raw = (request.form.get(col) or "").strip()
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
        elif "DATE" in t and "TIME" not in t:
            meta_values[col] = raw
        else:
            meta_values[col] = raw

    for col in required_fields:
        if not meta_values.get(col):
            label = FIELD_META.get(col, {}).get("label", col.replace("_", " ").title())
            flash(f"Please fill in required field: {label}.")
            return redirect(url_for("form"))

    require_gps = False
    if GPS_ENABLED:
        require_gps = request.form.get("require_gps") == "on"

    f = request.files.get("photo")

    if not f or f.filename == "":
        flash("Please take or choose a photo.")
        return redirect(url_for("form"))

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
            return redirect(url_for("form"))

    img, width, height = resize_if_needed(img)
    thumb = make_thumbnail(img)

    exif_datetime = exif_small["exif_datetime"]
    exif_make = exif_small["exif_make"]
    exif_model = exif_small["exif_model"]
    exif_orientation = exif_small["exif_orientation"]

    meta_cols = [f[1] for f in input_fields]
    db_cols = meta_cols + [
        "width", "height", "timestamp", "ip", "user_agent",
        "exif_datetime", "exif_make", "exif_model", "exif_orientation",
        "gps_lat", "gps_lon", "gps_alt",
    ]
    values = [meta_values[c] for c in meta_cols] + [
        width, height, ts, ip, ua,
        exif_datetime, exif_make, exif_model, exif_orientation,
        gps_lat, gps_lon, gps_alt,
    ]

    with get_db() as conn:
        placeholders = ",".join(["?"] * len(db_cols))
        cur = conn.execute(
            f"INSERT INTO artifacts ({','.join(db_cols)}) VALUES ({placeholders})",
            values,
        )
        new_id = cur.lastrowid

        unit = slug(meta_values.get("excavation_unit"))
        tnum = slug(meta_values.get("tnumber"))
        lot = slug(meta_values.get("lot"))
        area = slug(meta_values.get("area"))
        level = slug(meta_values.get("level"))
        base = f"TAP_2025_KNNM_{unit}_{tnum}_{lot}_{area}_{level}_ID{new_id}"

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

        json_payload = {
            "id": new_id,
            "tap_filename_base": base,
            "filename": jpg_name,
            "thumb_filename": thumb_name,
            "webp_filename": webp_name,
            "timestamp": ts,
            "client_ip": ip,
            "user_agent": ua,
            "gps": {
                "lat": gps_lat,
                "lon": gps_lon,
                "alt": gps_alt,
            },
            "exif": {
                "datetime": exif_datetime,
                "make": exif_make,
                "model": exif_model,
                "orientation": exif_orientation,
            },
            "fields": meta_values,
        }
        (UPLOAD_DIR / json_name).write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

        conn.execute(
            "UPDATE artifacts SET filename=?, thumb_filename=?, webp_filename=?, json_filename=? WHERE id=?",
            (jpg_name, thumb_name, webp_name, json_name, new_id),
        )

    return redirect(url_for("form", last_id=new_id))


@app.route("/recent")
def recent():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return render_template("recent.html", rows=rows)


@app.route("/uploads/<path:fname>")
def serve_upload(fname):
    return send_from_directory(UPLOAD_DIR, fname, as_attachment=False)


@app.route("/admin")
@requires_admin
def admin_list():
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM artifacts"
    params = []
    if q:
        text_cols = [f[1] for f in input_fields if f[2].upper().startswith("TEXT")]
        if text_cols:
            where_clauses = [f"{c} LIKE ?" for c in text_cols]
            sql += " WHERE " + " OR ".join(where_clauses)
            like = f"%{q}%"
            params = [like] * len(text_cols)
    sql += " ORDER BY id DESC LIMIT 500"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return render_template("admin_list.html", rows=rows, q=q)


@app.route("/admin/edit/<int:aid>", methods=["GET", "POST"])
@requires_admin
def admin_edit(aid):
    with get_db() as conn:
        if request.method == "POST":
            updates = {}
            for f in input_fields:
                label, col, coltype = f[0], f[1], f[2]
                t = (coltype or "TEXT").upper()
                if t.startswith("TIMESTAMP"):
                    continue
                raw = (request.form.get(col) or "").strip()
                if not raw:
                    updates[col] = None
                elif t.startswith("INT"):
                    try:
                        updates[col] = int(raw)
                    except ValueError:
                        updates[col] = None
                elif t.startswith("FLOAT") or t.startswith("REAL") or t.startswith("DOUBLE"):
                    try:
                        updates[col] = float(raw)
                    except ValueError:
                        updates[col] = None
                else:
                    updates[col] = raw
            if updates:
                set_clause = ", ".join([f"{c}=?" for c in updates.keys()])
                params = list(updates.values()) + [aid]
                conn.execute(f"UPDATE artifacts SET {set_clause} WHERE id=?", params)
                flash(f"Updated artifact {aid}")
            return redirect(url_for("admin_list"))

        row = conn.execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()
    if not row:
        flash("Not found")
        return redirect(url_for("admin_list"))
    return render_template("admin_edit.html", r=row)


@app.route("/admin/delete/<int:aid>", methods=["POST"])
@requires_admin
def admin_delete(aid):
    with get_db() as conn:
        row = conn.execute(
            "SELECT filename, thumb_filename, webp_filename, json_filename FROM artifacts WHERE id=?",
            (aid,),
        ).fetchone()
        conn.execute("DELETE FROM artifacts WHERE id=?", (aid,))
    if row:
        for fn in [row["filename"], row["thumb_filename"], row["json_filename"], row["webp_filename"]]:
            if fn:
                try:
                    (UPLOAD_DIR / fn).unlink(missing_ok=True)
                except Exception:
                    pass
    flash(f"Deleted artifact {aid}")
    return redirect(url_for("admin_list"))


@app.route("/admin/export.csv")
@requires_admin
def admin_export_csv():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts ORDER BY id ASC"
        ).fetchall()
        headers = rows[0].keys() if rows else []

    def generate():
        yield ",".join(headers) + "\n"
        with get_db() as conn2:
            for r in conn2.execute("SELECT * FROM artifacts ORDER BY id ASC"):
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
        headers={"Content-Disposition": "attachment; filename=artifacts.csv"},
    )


@app.route("/admin/export.geojson")
@requires_admin
def admin_export_geojson():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts "
            "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL "
            "ORDER BY id ASC"
        ).fetchall()
    features = []
    for r in rows:
        props = {}
        for f in input_fields:
            label, col, _ctype = f[0], f[1], f[2]
            props[col] = r[col]
        props.update({
            "id": r["id"],
            "filename": r["filename"],
            "thumb_filename": r["thumb_filename"],
            "webp_filename": r["webp_filename"],
            "json_filename": r["json_filename"],
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
    return render_template("admin_map.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=3000)
