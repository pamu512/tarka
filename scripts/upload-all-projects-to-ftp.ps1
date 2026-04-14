# Upload git repos under Documents + Cursor IDE metadata (.cursor, .cursorignore, AGENTS.md) to
# ftp://192.168.0.1/G/Pamu/Projects/<folder-name>/ . Excludes large SDK checkouts by default.
#
# Examples:
#   $env:FTP_PASS = "secret"; .\upload-all-projects-to-ftp.ps1
#   .\upload-all-projects-to-ftp.ps1 -ExcludeRepo @() -IncludeFlutterSdk
#   .\upload-all-projects-to-ftp.ps1 -IncludeCursorIdeFiles:$false   # git only, no .cursor uploads

[CmdletBinding()]
param(
    [string]$DocumentsRoot = (Join-Path $env:USERPROFILE "Documents"),
    [string]$FtpPrefix = "ftp://192.168.0.1/G/Pamu/Projects/",
    [string]$FtpUser = "suop",
    [string[]]$ExcludeRepo = @("flutter_sdk"),
    [switch]$IncludeFlutterSdk,
    [bool]$IncludeCursorIdeFiles = $true,
    [switch]$StopOnError,
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = "Stop"
$uploadScript = Join-Path $PSScriptRoot "upload-to-ftp.ps1"

if (-not (Test-Path -LiteralPath $uploadScript)) {
    throw "Missing: $uploadScript"
}

if ($IncludeFlutterSdk) {
    $ExcludeRepo = @()
}

$repos = Get-ChildItem -LiteralPath $DocumentsRoot -Directory -ErrorAction Stop |
    Where-Object {
        $name = $_.Name
        if ($ExcludeRepo -contains $name) { return $false }
        Test-Path -LiteralPath (Join-Path $_.FullName ".git")
    } |
    Sort-Object Name

$hasWorkspaceCursor = (
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot ".cursor")) -or
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot ".cursorignore")) -or
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot "AGENTS.md"))
)

if (-not $repos -and -not ($hasWorkspaceCursor -and $IncludeCursorIdeFiles)) {
    Write-Warning "No git repositories under $DocumentsRoot (after excludes), and no Documents-level Cursor files to upload."
    exit 0
}

if ($repos) {
    Write-Host "Found $($repos.Count) repo(s): $($repos.Name -join ', ')"
}

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($dir in $repos) {
    Write-Host ""
    Write-Host "======== $($dir.Name) ========"
    try {
        $params = @{
            RepoRoot              = $dir.FullName
            RemoteProjectName     = $dir.Name
            FtpPrefix             = $FtpPrefix
            FtpUser               = $FtpUser
            IncludeCursorIdeFiles = $IncludeCursorIdeFiles
        }
        if ($Credential) {
            $params.Credential = $Credential
        }
        & $uploadScript @params
    } catch {
        $msg = "$($dir.Name): $($_.Exception.Message)"
        [void]$failures.Add($msg)
        Write-Warning $msg
        if ($StopOnError) {
            throw
        }
    }
}

if ($hasWorkspaceCursor -and $IncludeCursorIdeFiles) {
    Write-Host ""
    Write-Host "======== Documents (workspace Cursor IDE files) -> _documents-cursor ========"
    try {
        $params = @{
            RepoRoot               = $DocumentsRoot
            RemoteProjectName      = "_documents-cursor"
            FtpPrefix              = $FtpPrefix
            FtpUser                = $FtpUser
            SkipGitTracked         = $true
            IncludeCursorIdeFiles  = $true
        }
        if ($Credential) {
            $params.Credential = $Credential
        }
        & $uploadScript @params
    } catch {
        $msg = "_documents-cursor: $($_.Exception.Message)"
        [void]$failures.Add($msg)
        Write-Warning $msg
        if ($StopOnError) {
            throw
        }
    }
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "Completed with $($failures.Count) failure(s):"
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host "All uploads finished successfully."
