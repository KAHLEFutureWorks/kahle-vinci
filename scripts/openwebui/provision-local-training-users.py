"""Create or reset local OpenWebUI accounts used for training recordings."""

from __future__ import annotations

import asyncio
import json
import sys

from open_webui.models.auths import Auths
from open_webui.models.users import Users
from open_webui.utils.auth import get_password_hash


async def upsert_account(name: str, email: str, password: str) -> dict[str, str]:
    email = email.strip().lower()
    existing = await Users.get_user_by_email(email)
    password_hash = await get_password_hash(password)
    if existing:
        await Users.update_user_by_id(
            existing.id,
            {"name": name, "email": email, "role": "user"},
        )
        await Auths.update_email_by_id(existing.id, email)
        await Auths.update_user_password_by_id(existing.id, password_hash)
        user_id = existing.id
        action = "updated"
    else:
        created = await Auths.insert_new_auth(
            email=email,
            password=password_hash,
            name=name,
            role="user",
        )
        if not created:
            raise RuntimeError(f"Account could not be created: {email}")
        user_id = created.id
        action = "created"
    return {"id": user_id, "email": email, "name": name, "action": action}


async def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: provision-local-training-users.py "
            "<employee-name> <employee-email> <employee-password> "
            "<manager-name> <manager-email> <manager-password>"
        )
    employee = await upsert_account(sys.argv[1], sys.argv[2], sys.argv[3])
    manager = await upsert_account(sys.argv[4], sys.argv[5], sys.argv[6])
    print(json.dumps({"employee": employee, "manager": manager}))


if __name__ == "__main__":
    asyncio.run(main())
