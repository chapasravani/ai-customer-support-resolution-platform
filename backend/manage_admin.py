"""
Administrative User Provisioning & Password Reset CLI Utility.

Usage:
  py -3.12 -m backend.manage_admin list
  py -3.12 -m backend.manage_admin create --email admin@supportai.com --password <secret> --name "Support Admin"
  py -3.12 -m backend.manage_admin reset-password --email admin@supportai.com --password <newsecret>
  py -3.12 -m backend.manage_admin promote --email user@example.com

Security rules:
- Passwords are ALWAYS hashed using bcrypt (via auth.hash_password).
- Plaintext passwords are NEVER stored, logged, or displayed.
"""

import argparse
import sys
from . import auth, models


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

    hashed = auth.hash_password(password)
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

    hashed = auth.hash_password(new_password)
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
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # list
    subparsers.add_parser("list", help="List all admin accounts")

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

    if args.command == "list":
        list_admins()
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
