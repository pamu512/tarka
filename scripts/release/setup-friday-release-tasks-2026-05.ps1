$ErrorActionPreference = "Stop"

$taskPrefix = "Tarka-Friday-Release-2026-05"
$runner = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Pamu\Documents\fraud-stack\scripts\release\push-queued-commit.ps1 -QueueFile C:\Users\Pamu\Documents\fraud-stack\scripts\release\release-queue-2026-05.json"

$dates = @(
    "2026/05/01",
    "2026/05/08",
    "2026/05/15",
    "2026/05/22",
    "2026/05/29"
)

foreach ($date in $dates) {
    $suffix = $date.Replace("/", "-")
    $taskName = "$taskPrefix-$suffix"
    schtasks /Create /F /TN $taskName /SC ONCE /SD $date /ST 09:00 /TR $runner | Out-Null
    Write-Output "Created task: $taskName"
}
