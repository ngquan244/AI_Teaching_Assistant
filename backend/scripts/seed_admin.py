"""
Seed Admin User Script
======================
Creates the first ADMIN user in the database.
Run: python -m backend.scripts.seed_admin
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database import AsyncSessionLocal, User, UserRole, UserStatus
from backend.core.security import hash_password
from sqlalchemy import select


DEFAULT_ADMIN_EMAIL = "admin@grader.local"
DEFAULT_ADMIN_NAME = "System Admin"
DEFAULT_ADMIN_PASSWORD = "Admin@2024!"


async def seed_admin(
    email: str = DEFAULT_ADMIN_EMAIL,
    name: str = DEFAULT_ADMIN_NAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
):
    """Create admin user if not exists."""
    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        result = await db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        existing = result.scalar_one_or_none()

        if existing:
            if existing.role == UserRole.ADMIN:
                print(f"✓ Admin user already exists: {email}")
                return
            else:
                # Promote to admin
                existing.role = UserRole.ADMIN
                await db.commit()
                print(f"✓ User {email} promoted to ADMIN")
                return

        # Create new admin
        admin = User(
            email=email.lower().strip(),
            name=name.strip(),
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(admin)
        await db.commit()

        print(f"✓ Admin user created successfully!")
        print(f"  Email:    {email}")
        print(f"  Password: {password}")
        print(f"  Role:     ADMIN")
        print(f"\n  ⚠️  Change this password after first login!")


async def main():
    """Entry point with optional CLI args."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed admin user")
    parser.add_argument("--email", default=DEFAULT_ADMIN_EMAIL, help="Admin email")
    parser.add_argument("--name", default=DEFAULT_ADMIN_NAME, help="Admin name")
    parser.add_argument("--password", default=DEFAULT_ADMIN_PASSWORD, help="Admin password")
    args = parser.parse_args()

    await seed_admin(email=args.email, name=args.name, password=args.password)


if __name__ == "__main__":
    asyncio.run(main())
