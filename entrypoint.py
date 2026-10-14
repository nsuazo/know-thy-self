#!/usr/bin/env python3
"""Container entrypoint: make /data writable for PUID:PGID, drop root, exec uvicorn."""
import os
import sys
from pathlib import Path

PUID = int(os.environ.get("PUID", "99"))
PGID = int(os.environ.get("PGID", "100"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
PORT = os.environ.get("PORT", "8480")


def chown_tree(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            st = path.lstat()
            if st.st_uid != PUID or st.st_gid != PGID:
                os.lchown(path, PUID, PGID)
        except OSError as exc:
            print(f"entrypoint: could not chown {path}: {exc}", file=sys.stderr)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        chown_tree(DATA_DIR)
        os.setgroups([])
        os.setgid(PGID)
        os.setuid(PUID)
    os.umask(0o002)
    args = [
        "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", PORT,
        "--proxy-headers", "--forwarded-allow-ips", "*",
        "--no-server-header",
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
