import os
from app import app as application

os.environ.setdefault("ARTCAP_ADMIN_USER", "admin")
os.environ.setdefault("ARTCAP_ADMIN_PASS", "change-me")
os.environ.setdefault("ARTCAP_SECRET", "change-me-secret")
