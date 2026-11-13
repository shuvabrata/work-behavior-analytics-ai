#!/usr/bin/env python3
"""Mint a live bearer for manual API exploration.

Drives the same authorization-code + PKCE flow the browser uses, then prints the
resulting token on stdout so it can be pasted into Swagger UI's Authorize box or
captured with ``$(...)``.

Usage (from workspace root)::

    PYTHONPATH=src python scripts/get_token.py --role admin --username <realm-username>

The token is the command's product, so it is the one thing written to stdout.
Every diagnostic — role, subject, remaining lifetime, the Swagger reminder — goes
to stderr, keeping stdout machine-parseable.

Environment variables
---------------------
WBA_TOKEN_PASSWORD            Password for the ``admin``/``user`` account named
                              by ``--username``.  When unset, the password is
                              prompted for interactively.
KEYCLOAK_SERVICE_CLIENT_SECRET  Secret for the ``service`` role's client grant.
APP_PUBLIC_BASE_URL           Base URL of the running stack.  Default:
                              ``https://localhost``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time

from common.auth import (
    Credentials,
    LoginError,
    credentials,
    env_value,
    login,
    resolve_ca_bundle,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--role",
        choices=["admin", "user", "service"],
        default="admin",
        help="role to mint (default: admin)",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="realm username to log in as; required for --role admin and --role user",
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


def _resolve_password(username: str) -> str:
    """Return the password from ``WBA_TOKEN_PASSWORD``, else prompt for it.

    Raises:
        LoginError: when the variable is unset and stdin is not a TTY, since a
            prompt could never be answered.
    """
    password = env_value("WBA_TOKEN_PASSWORD")
    if password:
        return password
    if not sys.stdin.isatty():
        raise LoginError(
            "WBA_TOKEN_PASSWORD is unset and stdin is not a TTY; "
            "set the environment variable to run non-interactively"
        )
    return getpass.getpass(f"Password for {username}: ")


def _mint(args: argparse.Namespace, base_url: str) -> Credentials:
    """Return live credentials for the requested role, or raise ``LoginError``."""
    if args.role == "service":
        return credentials(base_url=base_url, ca_bundle=resolve_ca_bundle())
    if not args.username:
        raise LoginError(f"--username is required for --role {args.role}")
    return login(
        args.username,
        _resolve_password(args.username),
        base_url=base_url,
        ca_bundle=resolve_ca_bundle(),
    )


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
        creds = _mint(args, base_url)
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

    user = args.username or args.role
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
