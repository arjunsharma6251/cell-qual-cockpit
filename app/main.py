"""Cell Qualification Cockpit — minimal FastAPI host.

Serves the precomputed bundle and the static frontend. All analysis happens in
scripts/build_bundle.py; nothing is fitted at request time. The frontend also
works fully static (any file server over app/static/).
"""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Hectocycle — cell qualification cockpit", docs_url=None, redoc_url=None)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
