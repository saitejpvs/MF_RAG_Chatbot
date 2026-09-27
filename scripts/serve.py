"""Server entry point that loads the embedding model in the serving process.

Why not plain `streamlit run`: Streamlit binds its port and answers
`/_stcore/health` before it ever runs the app script, so the encoder is not
resident until the first user question arrives. On a 512 MB instance that first
question is when torch and MiniLM push the container over its limit, and an
OOM kill looks like a random crash to whoever was using the app.

Warming here instead means the peak is allocated before the health check goes
green, and the process that holds the memory is the one that serves traffic.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running this file directly puts scripts/ on sys.path, not the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.embedder import embed_text  # noqa: E402


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8501"
    print("[serve] loading the embedding model in the serving process...", flush=True)
    dims = len(embed_text("warm up the encoder"))
    print(f"[serve] warm: {dims}-dim encoder resident", flush=True)

    from streamlit.web.cli import main as streamlit_main

    sys.argv = [
        "streamlit",
        "run",
        "app/ui/app.py",
        "--server.address=0.0.0.0",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    print(f"[serve] starting Streamlit on port {port}", flush=True)
    streamlit_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
