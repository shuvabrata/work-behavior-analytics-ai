#!/usr/bin/env python3
"""Mint a live bearer for manual API exploration.

Drives the same authorization-code + PKCE flow the browser uses, then prints the
resulting token on stdout so it can be pasted into Swagger UI's Authorize box or
captured with ``$(...)``.

Usage (from workspace root)::

    PYTHONPATH=src python scripts/get_token.py --role admin

The token is the command's product, so it is the one thing written to stdout.
Every diagnostic — role, subject, remaining lifetime, the Swagger reminder — goes
to stderr, keeping stdout machine-parseable.

Environment variables
---------------------
DEV_WBA_ADMIN_PASSWORD        Password for the ``admin`` dev user.
DEV_WBA_USER_PASSWORD         Password for the ``user`` dev user.
KEYCLOAK_SERVICE_CLIENT_SECRET  Secret for the ``service`` role's client grant.
APP_PUBLIC_BASE_URL           Base URL of the running stack.  Default:
                              ``https://localhost``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from common.auth import LoginError, credentials, env_value, resolve_ca_bundle

_DEV_USERS = {"admin": "dev-admin", "user": "dev-user"}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--role",
        choices=["admin", "user", "service"],
        default="admin",
        help="role to mint (default: admin)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a JSON object on stdout instead of the bare token",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="base URL of the stack (default: APP_PUBLIC_BASE_URL, else https://localhost)",
    )
    return parser.parse_args(argv)


def _base_url(override: str | None) -> str:
    return override or env_value("APP_PUBLIC_BASE_URL", "https://localhost") or "https://localhost"


def _subject(access_token: str) -> str:
    """Return the ``sub`` claim from *access_token* without verifying it."""
    import base64

    payload = access_token.split(".")[1]
    padding = "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload + padding))
    return str(claims.get("sub", ""))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base_url = _base_url(args.base_url)

    try:
        creds = credentials(args.role, base_url=base_url, ca_bundle=resolve_ca_bundle())
    except LoginError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"error: login failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    remaining = max(0, int(creds.expires_at - time.monotonic()))
    subject = _subject(creds.access_token)

    if args.as_json:
        json.dump(
            {
                "access_token": creds.access_token,
                "expires_in": remaining,
                "role": args.role,
                "subject": subject,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
    else:
        sys.stdout.write(creds.access_token + "\n")

    user = _DEV_USERS.get(args.role, args.role)
    print(
        f"role={args.role} subject={subject} expires_in={remaining}s "
        f"({creds.expires_at - time.monotonic():.0f}s remaining)",
        file=sys.stderr,
    )
    print(
        f"Minted {args.role} ({user}) against {base_url}. "
        "Paste the bare token (no 'Bearer ' prefix) into the Authorize box at "
        "/docs.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
