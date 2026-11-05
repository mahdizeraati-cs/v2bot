#!/bin/bash
set -eo pipefail

BACKUP_ZIP="$1"
DB_URL="$2"

if [ -z "$BACKUP_ZIP" ] || [ -z "$DB_URL" ]; then
    echo "استفاده صحیح:"
    echo "  bash restore_backup.sh <فایل بکاپ.zip> <DATABASE_URL>"
    exit 1
fi

if ! command -v psql &> /dev/null; then
    echo "❌ ابزار psql روی این سیستم نصب نیست."
    exit 1
fi

RESTORE_DIR="$(pwd)/restore_tmp_$$"
mkdir -p "$RESTORE_DIR"

echo "📦 در حال استخراج فایل بکاپ..."
unzip -o "$BACKUP_ZIP" -d "$RESTORE_DIR" > /dev/null

echo "🚀 در حال آماده‌سازی و ارسال اطلاعات به دیتابیس (لطفا صبر کنید)..."

# اجرای تمام دستورات در یک Session واحد برای جلوگیری از باگ Foreign Key
{
    echo "SET session_replication_role = 'replica';"

    # فاز اول: پاکسازی (TRUNCATE) برای جلوگیری از ارور Duplicate Key
    for csv_file in "$RESTORE_DIR"/*.csv; do
        table_name=$(basename "$csv_file" .csv)
        echo "TRUNCATE TABLE \"$table_name\" CASCADE;"
    done

    # فاز دوم: ایمپورت
    for csv_file in "$RESTORE_DIR"/*.csv; do
        table_name=$(basename "$csv_file" .csv)
        echo "\copy \"$table_name\" FROM '$csv_file' WITH (FORMAT csv, HEADER true)"
    done

    echo "SET session_replication_role = 'origin';"
} | psql "$DB_URL"

echo "🔄 همگام‌سازی شماره آیدی‌ها (Sequences)..."
TABLES=$(psql "$DB_URL" -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
for table in $TABLES; do
    HAS_ID=$(psql "$DB_URL" -t -c "SELECT column_name FROM information_schema.columns WHERE table_name='$table' AND column_name='id';")
    if [[ ! -z "$HAS_ID" ]]; then
       psql "$DB_URL" -c "SELECT setval(pg_get_serial_sequence('$table', 'id'), COALESCE((SELECT MAX(id) FROM \"$table\"), 1), true);" > /dev/null 2>&1 || true
    fi
done

rm -rf "$RESTORE_DIR"
echo "✅ بازگردانی با موفقیت و به صورت امن انجام شد."
