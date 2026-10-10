"""Vercel entry point.

vercel.json routes every /api/* request here; SHELTER's WSGI app answers it. The web
page itself (public/) is served by Vercel's CDN. Locally, run
`python -m shelter.server.app` instead: it serves the same API and page.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shelter.server.app import app  # noqa: E402,F401  (Vercel looks for `app`)
