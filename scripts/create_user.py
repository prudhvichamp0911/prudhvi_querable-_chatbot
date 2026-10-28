"""Create or reset a chatbot login.

Usage (from the project root, with the virtual environment active):

    python -m scripts.create_user <username> [--display-name "Name"] [--role analyst|admin]

The password is prompted for (not echoed). Use --reset to change the
password of an existing user.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.auth import create_user, ensure_indexes, hash_password, users  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--display-name")
    parser.add_argument("--role", default="analyst", choices=["analyst", "admin"])
    parser.add_argument("--reset", action="store_true", help="reset an existing user's password")
    parser.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    args = parser.parse_args()

    if args.password_stdin:
        # On Windows a piped line ends with \r\n. rstrip("\n") alone would
        # leave a trailing \r inside the password, and the account could then
        # never be signed into with the password you thought you set.
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")

    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    ensure_indexes()
    username = args.username.strip().lower()

    if args.reset:
        result = users.update_one({"username": username}, {"$set": {"password_hash": hash_password(password)}})
        sys.exit("User not found." if result.matched_count == 0 else f"Password reset for {username}.")

    if users.find_one({"username": username}):
        sys.exit(f"User {username} already exists (use --reset to change the password).")

    create_user(username, password, args.display_name, args.role)
    print(f"Created user {username}.")


if __name__ == "__main__":
    main()
