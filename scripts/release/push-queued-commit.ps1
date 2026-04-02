$ErrorActionPreference = "Stop"

param(
    [string]$RepoPath = "C:\Users\Pamu\Documents\fraud-stack",
    [string]$QueueFile = "C:\Users\Pamu\Documents\fraud-stack\scripts\release\release-queue.json"
)

if (-not (Test-Path $QueueFile)) {
    throw "Queue file not found: $QueueFile"
}

$queue = Get-Content -Raw -Path $QueueFile | ConvertFrom-Json
$today = Get-Date -Format "yyyy-MM-dd"
$entry = $queue.updates | Where-Object { $_.date -eq $today } | Select-Object -First 1

if (-not $entry) {
    Write-Output "No scheduled release for $today."
    exit 0
}

Set-Location $RepoPath

git fetch origin
git checkout master
git pull --ff-only origin master

$targetCommit = $entry.commit
git rev-parse --verify "$targetCommit^{commit}" | Out-Null

# Fast-forward remote master to the queued commit.
git push origin "$targetCommit`:master"

Write-Output "Released commit $targetCommit for scheduled date $today."
