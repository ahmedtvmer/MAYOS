"""Serve the throwaway #143 capture viewer without accounts or dependencies."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

review_root = Path(__file__).resolve().parent.parent
server = ThreadingHTTPServer(
    ("127.0.0.1", 8143),
    partial(SimpleHTTPRequestHandler, directory=str(review_root)),
)
print("http://localhost:8143/selected/prototype-gallery.html?variant=C", flush=True)
server.serve_forever()
