# scripts/export_logs.ps1 — export log การใช้งานทั้งหมด + backup DB + รันรายงาน [DEV_LOG Entry 73]
#
# รัน (จาก root chabot/, Docker ต้องเปิดอยู่):
#   powershell -ExecutionPolicy Bypass -File scripts\export_logs.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\export_logs.ps1 -Since 2026-10-21
#
# ผล: eval\results\export_<วันเวลา>\  (โฟลเดอร์นี้ gitignored — มีข้อมูลผู้ทดสอบ ห้ามขึ้น git)
#   log_interaction_logs.csv   ทุกข้อความ: input, route, fallback, reply_text, เวลาตอบ
#   log_food_logs.csv          บันทึกการกิน (source = typed/button/image)
#   log_food_image_predictions.csv   ผล CNN + ผู้ใช้ยืนยัน/ยกเลิก
#   log_recommendations.csv / log_recommendation_items.csv   รอบแนะนำ + reward ของ Bandit
#   log_users.csv              โปรไฟล์ผู้ทดสอบ
#   backup_ncd_chatbot.sql     สำรองฐานข้อมูลทั้งก้อน (กู้คืนได้)
#   usage_report.txt / review_replies.txt   ผลสรุป

param(
    [string]$Since = "2000-01-01",
    [string]$Exclude = "Udf56bab1bd5a51aec820b06881a5481a"   # ไอดีผู้พัฒนา (ไม่นับในรายงาน)
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8   # ให้ไฟล์รายงานภาษาไทยไม่เพี้ยน
$env:PYTHONIOENCODING = "utf-8"
$c = "ncd_chatbot_postgres"
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$out = "eval\results\export_$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$tables = @{
    "interaction_logs"       = "SELECT * FROM interaction_logs WHERE created_at >= '$Since' ORDER BY created_at"
    "food_logs"              = "SELECT * FROM food_logs WHERE eaten_at >= '$Since' ORDER BY eaten_at"
    "food_image_predictions" = "SELECT * FROM food_image_predictions WHERE created_at >= '$Since' ORDER BY created_at"
    "recommendations"        = "SELECT * FROM recommendations WHERE created_at >= '$Since' ORDER BY created_at"
    "recommendation_items"   = "SELECT ri.* FROM recommendation_items ri JOIN recommendations r ON r.id = ri.recommendation_id WHERE r.created_at >= '$Since' ORDER BY ri.id"
    "users"                  = "SELECT * FROM users ORDER BY created_at"
}

foreach ($t in $tables.Keys) {
    Write-Host "export $t ..."
    docker exec $c psql -U postgres -d ncd_chatbot -c "\copy ($($tables[$t])) TO '/tmp/$t.csv' CSV HEADER"
    docker cp "${c}:/tmp/$t.csv" "$out\log_$t.csv" | Out-Null
}

Write-Host "backup ฐานข้อมูลทั้งก้อน ..."
docker exec $c pg_dump -U postgres -d ncd_chatbot -f /tmp/backup.sql
docker cp "${c}:/tmp/backup.sql" "$out\backup_ncd_chatbot.sql" | Out-Null

$ErrorActionPreference = "Continue"   # TensorFlow เขียน warning ลง stderr — ไม่ใช่ error
Write-Host "รันรายงาน ..."
$since_arg = if ($Since -ne "2000-01-01") { @("--since", $Since) } else { @("--since", "2000-01-01") }
python -X utf8 -m eval.usage_report @since_arg --exclude $Exclude --csv "$out\usage_tasks.csv" 2>$null | Out-File -Encoding utf8 "$out\usage_report.txt"
python -X utf8 -m eval.review_replies @since_arg --exclude $Exclude 2>$null | Out-File -Encoding utf8 "$out\review_replies.txt"

Write-Host ""
Write-Host "เสร็จแล้ว → $out"
Get-ChildItem $out | Format-Table Name, Length
