"""Admin CLI.

python -m app.cli secret                 # random value for ADMIN_API_KEY etc. in .env
python -m app.cli keys create <label>    # new API key for a client app (shown once)
python -m app.cli keys list
python -m app.cli keys revoke <id>
"""

import argparse
import sys
from datetime import UTC, datetime

from app.api.keys import KeyStore, generate_secret
from app.config import get_settings


def _fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M") if ts else "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("secret", help="print a random secret for .env")
    sub.add_parser("console-otp", help="one-time login code for the phone console (PWA)")
    keys = sub.add_parser("keys", help="manage client API keys").add_subparsers(
        dest="action", required=True
    )
    keys.add_parser("create").add_argument("label")
    keys.add_parser("list")
    keys.add_parser("revoke").add_argument("id", type=int)
    parser.add_argument("--db", help="database path (default: from settings)")
    args = parser.parse_args(argv)

    if args.cmd == "secret":
        print(generate_secret())
        return 0

    if args.cmd == "console-otp":
        from app.console.manager import ConsoleManager

        mgr = ConsoleManager(args.db or get_settings().db_path)
        try:
            otp, ttl = mgr.create_otp()
        finally:
            mgr.close()
        print(otp)
        print(
            f"valid for {ttl // 60} min; open /console/ on your phone and enter it", file=sys.stderr
        )
        return 0

    store = KeyStore(args.db or get_settings().db_path)
    try:
        if args.action == "create":
            key, rec = store.create(args.label)
            print(f"id={rec.id} label={rec.label}")
            print(key)
            print("Store it now - it cannot be shown again.", file=sys.stderr)
        elif args.action == "list":
            for r in store.list():
                state = "active" if r.active else f"revoked {_fmt(r.revoked_at)}"
                print(
                    f"{r.id:>3}  {r.label:<20} {r.prefix}…  created {_fmt(r.created_at)}  "
                    f"last used {_fmt(r.last_used_at)}  {state}"
                )
        elif args.action == "revoke":
            if not store.revoke(args.id):
                print(f"no active key with id {args.id}", file=sys.stderr)
                return 1
            print(f"revoked {args.id}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
