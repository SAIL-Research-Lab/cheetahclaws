"""Operator commands.

    docker compose exec gateway python -m ccloud.admin users
    docker compose exec gateway python -m ccloud.admin credit someone@example.com 10
    docker compose exec gateway python -m ccloud.admin set-password someone@example.com
"""
from __future__ import annotations

import getpass
import sys
import time

from .db import MICRO, Database
from .security import hash_password
from .settings import settings


def main(argv: list[str]) -> int:
    db = Database(settings.db_url)
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "users":
        from sqlalchemy import select
        from .db import User
        with db.session() as s:
            for u in s.scalars(select(User).order_by(User.id)):
                print(f"{u.id:>5}  {u.email:<40} ${u.balance_micro / MICRO:>9.4f}  "
                      f"{u.model_mode:<8} {time.strftime('%Y-%m-%d', time.localtime(u.created_at))}")
        return 0
    if cmd == "credit" and len(argv) == 4:
        u = db.get_user_by_email(argv[2].lower())
        if not u:
            print("no such user", file=sys.stderr)
            return 1
        amount = int(round(float(argv[3]) * MICRO))
        db.credit(u.id, amount, "admin", f"admin-{u.id}-{time.time_ns()}")
        print(f"credited ${float(argv[3]):g} to {u.email}; balance now "
              f"${db.get_user(u.id).balance_micro / MICRO:.4f}")
        return 0
    if cmd == "set-password" and len(argv) == 3:
        u = db.get_user_by_email(argv[2].lower())
        if not u:
            print("no such user", file=sys.stderr)
            return 1
        pw = getpass.getpass("new password (8+ chars): ")
        if len(pw) < 8:
            print("too short", file=sys.stderr)
            return 1
        db.update_user(u.id, password_hash=hash_password(pw))
        print("password updated")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
