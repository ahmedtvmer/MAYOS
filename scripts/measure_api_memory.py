"""Measure peak RSS after importing the API and embedding one query."""

import os
import resource
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import svc.app  # noqa: E402,F401
from agent.clinical_guard import EMBED_MODEL  # noqa: E402


def main() -> None:
    vector = EMBED_MODEL.embed_query("lat pulldown cable")
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"embedding_dimension={len(vector)}")
    print(f"torch_loaded={'torch' in sys.modules}")
    print(f"peak_rss_mb={peak_rss_mb:.1f}")


if __name__ == "__main__":
    main()
