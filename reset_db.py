import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from core.database.models import Base

load_dotenv()

async def clear_tables_data():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ no database url found in .env")
        return

    engine = create_async_engine(database_url, echo=True)

    # استخراج نام تمام جداولی که در مدل‌های پایتون شما تعریف شده‌اند
    # نکته: جدول alembic_version در این لیست نیست، پس تاریخچه مایگریشن‌ها پاک نمی‌شود!
    table_names = [table.name for table in Base.metadata.sorted_tables]

    if not table_names:
        print("⚠️ هیچ جدولی در Base پیدا نشد.")
        return

    # چسباندن اسم جداول به هم با کاما
    tables_str = ", ".join(table_names)

    # دستور TRUNCATE برای PostgreSQL
    # RESTART IDENTITY: آیدی‌های اتوماتیک (Primary Keys) را دوباره از 1 شروع می‌کند
    # CASCADE: اگر جداول به هم کلید خارجی (Foreign Key) دارند، بدون ارور همه را با هم پاک می‌کند
    query = f"TRUNCATE TABLE {tables_str} RESTART IDENTITY CASCADE;"

    async with engine.begin() as conn:
        print(f"🔴 Clearing data from tables:\n{tables_str}")
        await conn.execute(text(query))

    await engine.dispose()
    print("\n✅ دیتای تمام جداول با موفقیت پاک شد! (ساختار جداول و Alembic دست‌نخورده باقی ماند)")

if __name__ == "__main__":
    asyncio.run(clear_tables_data())
