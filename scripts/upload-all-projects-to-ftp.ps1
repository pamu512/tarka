# Upload git repos under Documents + editor workspace metadata (.cursor, .cursorignore, AGENTS.md) to
# ftp://192.168.0.1/G/Pamu/Projects/<folder-name>/ . Excludes large SDK checkouts by default.
#
# Examples:
#   $env:FTP_PASS = "secret"; .\upload-all-projects-to-ftp.ps1
#   .\upload-all-projects-to-ftp.ps1 -ExcludeRepo @() -IncludeFlutterSdk
#   .\upload-all-projects-to-ftp.ps1 -IncludeIdeWorkspaceExtras:$false   # git only, no .cursor uploads

[CmdletBinding()]
param(
    [string]$DocumentsRoot = (Join-Path $env:USERPROFILE "Documents"),
    [string]$FtpPrefix = "ftp://192.168.0.1/G/Pamu/Projects/",
    [string]$FtpUser = "suop",
    [string[]]$ExcludeRepo = @("flutter_sdk"),
    [switch]$IncludeFlutterSdk,
    [bool]$IncludeIdeWorkspaceExtras = $true,
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

$hasWorkspaceIdeMetadata = (
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot ".cursor")) -or
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot ".cursorignore")) -or
    (Test-Path -LiteralPath (Join-Path $DocumentsRoot "AGENTS.md"))
)

if (-not $repos -and -not ($hasWorkspaceIdeMetadata -and $IncludeIdeWorkspaceExtras)) {
    Write-Warning "No git repositories under $DocumentsRoot (after excludes), and no Documents-level workspace metadata files to upload."
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
            RepoRoot                 = $dir.FullName
            RemoteProjectName      = $dir.Name
            FtpPrefix                = $FtpPrefix
            FtpUser                  = $FtpUser
            IncludeIdeWorkspaceExtras = $IncludeIdeWorkspaceExtras
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

if ($hasWorkspaceIdeMetadata -and $IncludeIdeWorkspaceExtras) {
    Write-Host ""
    Write-Host "======== Documents (workspace IDE metadata) -> _documents-ide-workspace ========"
    try {
        $params = @{
            RepoRoot                  = $DocumentsRoot
            RemoteProjectName         = "_documents-ide-workspace"
            FtpPrefix                 = $FtpPrefix
            FtpUser                   = $FtpUser
            SkipGitTracked            = $true
            IncludeIdeWorkspaceExtras = $true
        }
        if ($Credential) {
            $params.Credential = $Credential
        }
        & $uploadScript @params
    } catch {
        $msg = "_documents-ide-workspace: $($_.Exception.Message)"
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
