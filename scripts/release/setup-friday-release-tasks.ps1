$ErrorActionPreference = "Stop"

$taskPrefix = "Tarka-Friday-Release"
$runner = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Pamu\Documents\fraud-stack\scripts\release\push-queued-commit.ps1"

$dates = @(
    "2026/04/03",
    "2026/04/10",
    "2026/04/17",
    "2026/04/24"
)

foreach ($date in $dates) {
    $suffix = $date.Replace("/", "-")
    $taskName = "$taskPrefix-$suffix"
    schtasks /Create /F /TN $taskName /SC ONCE /SD $date /ST 09:00 /TR $runner | Out-Null
    Write-Output "Created task: $taskName"
}
