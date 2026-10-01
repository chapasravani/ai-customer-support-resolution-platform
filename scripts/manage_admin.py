"""
Administrative User Provisioning & Password Reset CLI Utility.

Usage:
  py -3.12 -m scripts.manage_admin list
  py -3.12 -m scripts.manage_admin create --email admin@supportai.com --password <secret> --name "Support Admin"
  py -3.12 -m scripts.manage_admin reset-password --email admin@supportai.com --password <newsecret>
  py -3.12 -m scripts.manage_admin promote --email user@example.com

Security rules:
- Passwords are ALWAYS hashed using bcrypt (via security.hash_password).
- Plaintext passwords are NEVER stored, logged, or displayed.
"""

import argparse
import sys
from backend.app.core import security
from backend.app.domains import models
from backend.app.infrastructure import db


def list_admins():
    admins = models.list_admin_users()
    print("\n" + "=" * 60)
    print(f" ADMINISTRATOR ACCOUNTS ({len(admins)} found)")
    print("=" * 60)
    if not admins:
        print(" No administrator accounts found.")
    else:
        for idx, u in enumerate(admins, start=1):
            print(f" {idx}. {u.get('name', 'Admin')} <{u.get('email')}> (ID: {u.get('_id')})")
    print("=" * 60 + "\n")


def list_all_users():
    raw_users = list(db.get_db().users.find({}, {"hashed_password": 1, "email": 1, "name": 1, "role": 1, "customer_id": 1}))
    print("\n" + "=" * 75)
    print(f" ALL REGISTERED USERS ({len(raw_users)} found)")
    print("=" * 75)
    if not raw_users:
        print(" No user accounts found.")
    else:
        for idx, u in enumerate(raw_users, start=1):
            has_hash = bool(u.get("hashed_password") and str(u.get("hashed_password")).startswith("$2b$"))
            hash_status = "valid_hash" if has_hash else "missing_or_invalid_hash"
            cid = u.get("customer_id") or "none"
            print(f" {idx}. [{u.get('role', 'customer').upper()}] {u.get('name', 'User')} <{u.get('email')}> | CID: {cid} | Auth: {hash_status}")
    print("=" * 75 + "\n")


def verify_account(email: str):
    email = email.strip().lower()
    user = models.get_user_by_email(email)
    print("\n" + "=" * 60)
    print(f" ACCOUNT VERIFICATION: {email}")
    print("=" * 60)
    if not user:
        print(f" [NOT FOUND] No registered user found with email '{email}'.")
    else:
        has_hash = bool(user.get("hashed_password") and str(user.get("hashed_password")).startswith("$2b$"))
        print(f" [EXISTS] User ID: {user.get('_id')}")
        print(f" Name: {user.get('name')}")
        print(f" Email: {user.get('email')}")
        print(f" Role: {user.get('role')}")
        print(f" Customer ID: {user.get('customer_id', 'N/A')}")
        print(f" Password Hash Status: {'Ready for login' if has_hash else 'Invalid/Missing Hash - reset password required'}")
    print("=" * 60 + "\n")


def create_admin(email: str, password: str, name: str):
    email = email.strip().lower()
    if not email or "@" not in email:
        print("[ERROR] Invalid email address provided.")
        sys.exit(1)
    if len(password) < 6:
        print("[ERROR] Password must be at least 6 characters long.")
        sys.exit(1)

    existing = models.get_user_by_email(email)
    if existing:
        print(f"[ERROR] User with email '{email}' already exists. Use 'reset-password' or 'promote' instead.")
        sys.exit(1)

    hashed = security.hash_password(password)
    user = models.create_user(
        email=email,
        hashed_password=hashed,
        name=name or "Administrator",
        role="admin"
    )
    print(f"[SUCCESS] Admin account created successfully for: {email} (ID: {user['_id']})")


def reset_password(email: str, new_password: str):
    email = email.strip().lower()
    if len(new_password) < 6:
        print("[ERROR] Password must be at least 6 characters long.")
        sys.exit(1)

    user = models.get_user_by_email(email)
    if not user:
        print(f"[ERROR] No user found with email '{email}'.")
        sys.exit(1)

    hashed = security.hash_password(new_password)
    models.update_user_password(email, hashed)
    print(f"[SUCCESS] Password for '{email}' has been reset successfully.")


def promote_user(email: str):
    email = email.strip().lower()
    user = models.get_user_by_email(email)
    if not user:
        print(f"[ERROR] No user found with email '{email}'.")
        sys.exit(1)

    models.update_user_role(email, "admin")
    print(f"[SUCCESS] User '{email}' has been promoted to administrator role.")


def main():
    parser = argparse.ArgumentParser(description="SupportAI Administrator Provisioning Utility")
    parser.add_argument("--local", action="store_true", help="Target local persistent fallback JSON database directly")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # list
    subparsers.add_parser("list", help="List all admin accounts")

    # list-users
    subparsers.add_parser("list-users", help="List all registered user accounts (admins and customers)")

    # verify-account
    verify_parser = subparsers.add_parser("verify-account", help="Verify whether a customer or admin account exists")
    verify_parser.add_argument("--email", required=True, help="User email address to verify")

    # create
    create_parser = subparsers.add_parser("create", help="Create a new admin account")
    create_parser.add_argument("--email", required=True, help="Admin email address")
    create_parser.add_argument("--password", required=True, help="Admin password (will be hashed)")
    create_parser.add_argument("--name", default="Administrator", help="Admin display name")

    # reset-password
    reset_parser = subparsers.add_parser("reset-password", help="Reset password for an admin/user account")
    reset_parser.add_argument("--email", required=True, help="User email address")
    reset_parser.add_argument("--password", required=True, help="New password (will be hashed)")

    # promote
    promote_parser = subparsers.add_parser("promote", help="Promote an existing customer account to admin")
    promote_parser.add_argument("--email", required=True, help="User email address")

    args = parser.parse_args()

    if args.local:
        db.set_local_mode()
        print("[INFO] Target database: local persistent fallback (data/runtime/db_store.json)")
    else:
        info = db.get_storage_info()
        print(f"[INFO] Target database: {info.get('storage_type')} ({info.get('details')})")

    if args.command == "list":
        list_admins()
    elif args.command == "list-users":
        list_all_users()
    elif args.command == "verify-account":
        verify_account(args.email)
    elif args.command == "create":
        create_admin(args.email, args.password, args.name)
    elif args.command == "reset-password":
        reset_password(args.email, args.password)
    elif args.command == "promote":
        promote_user(args.email)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
