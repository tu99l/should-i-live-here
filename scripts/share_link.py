"""Start a view-only results link roommates can open on their phones.

Runs a free Cloudflare quick tunnel to the app on this laptop (no account needed) and saves the public
address, so the page's "Share" box and the iMessage bot can hand out the link. The link only works
while this script and the app are running. Through the tunnel, only the view-only results page answers
(see app/share.py); nothing that edits the group or costs API calls can be reached.

Needs cloudflared (brew install cloudflared) and the app running on port 8000.
Run:  .venv/bin/python scripts/share_link.py      Stop: Ctrl+C (the link stops working).
"""
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import share  # noqa: E402

PORT = 8000
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def main() -> None:
    exe = shutil.which("cloudflared")
    if not exe:
        sys.exit("cloudflared is not installed. Run: brew install cloudflared")
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def stop(*_):
        share.set_public_url(None)
        proc.terminate()
        print("\nShare link stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    found = False
    for line in proc.stdout:
        m = URL_PATTERN.search(line)
        if m and not found:
            found = True
            share.set_public_url(m.group(0))
            print(f"Share link ready (view only): {share.link()}", flush=True)
            print("Keep this running while roommates look. Ctrl+C to stop.", flush=True)
        elif "ERR" in line and not found:
            print(line.rstrip(), flush=True)
    share.set_public_url(None)
    sys.exit("The tunnel stopped.")


if __name__ == "__main__":
    main()
