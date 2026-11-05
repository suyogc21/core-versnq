"""Platform admin commands. Usage: make create-staff"""

import argparse
import asyncio
import getpass
import sys

from email_validator import EmailNotValidError, validate_email

from app.core.security import hash_password
from app.core.tenancy import platform_session
from app.platform.staff.models import PlatformStaff

MIN_PASSWORD = 12


async def _create_staff(email: str, name: str, password: str) -> None:
    async with platform_session() as s:
        s.add(PlatformStaff(email=email, name=name, password_hash=hash_password(password)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="platform")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create-staff", help="Create a Versnq staff account")
    parser.parse_args()

    try:
        email = validate_email(input("Email: ").strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        sys.exit(f"Invalid email: {exc}")
    name = input("Name: ").strip() or sys.exit("Name is required")
    password = getpass.getpass(f"Password (min {MIN_PASSWORD} chars): ")
    if len(password) < MIN_PASSWORD:
        sys.exit("Password too short")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Passwords do not match")
    asyncio.run(_create_staff(email, name, password))
    print(f"Created staff account {email}")


if __name__ == "__main__":
    main()
