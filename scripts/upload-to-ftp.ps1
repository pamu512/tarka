# Upload git-tracked project files to an FTP path (e.g. NAS share).
# Requires a password: use -Credential, set FTP_PASS (username defaults to suop), or override with FTP_USER.
#
# Example:
#   $c = Get-Credential
#   .\scripts\upload-to-ftp.ps1 -Credential $c
#
#   $env:FTP_PASS = "secret"; .\scripts\upload-to-ftp.ps1
#
# Default remote root: ftp://192.168.0.1/G/Pamu/Projects/<RemoteProjectName>/ (see -RemoteProjectName).
# To put tracked files directly under Projects/ with no subfolder: -RemoteProjectName ""
#
# -IncludeIdeWorkspaceExtras: also uploads .cursor/, root .cursorignore, and root AGENTS.md (often gitignored).
# -SkipGitTracked: only uploads those workspace paths (no git ls-files); use for non-repo folders (e.g. Documents\.cursor).

[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$FtpPrefix = "ftp://192.168.0.1/G/Pamu/Projects/",
    [string]$RemoteProjectName = "fraud-stack",
    [string]$FtpUser = "suop",
    [bool]$IncludeIdeWorkspaceExtras = $true,
    [switch]$SkipGitTracked,
    [switch]$RemoveLocalAfterUpload,
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = "Stop"

if (-not $FtpPrefix.EndsWith("/")) {
    $FtpPrefix = "$FtpPrefix/"
}

if (-not $Credential) {
    $user = if ($env:FTP_USER) { $env:FTP_USER } else { $FtpUser }
    $plain = $env:FTP_PASS
    if ($null -ne $plain -and $plain -ne "") {
        $sec = ConvertTo-SecureString -String $plain -AsPlainText -Force
        $Credential = New-Object System.Management.Automation.PSCredential ($user, $sec)
    }
}
if (-not $Credential) {
    $promptUser = if ($env:FTP_USER) { $env:FTP_USER } else { $FtpUser }
    $Credential = Get-Credential -UserName $promptUser -Message "FTP password for 192.168.0.1 (TP-Share)"
}

function Normalize-FtpResponse {
    param([System.Net.FtpWebResponse]$Response)
    try {
        if ($Response) { $Response.Close() }
    } catch {
        # ignore
    }
}

function Ensure-FtpRemoteDirectory {
    param(
        [string]$BasePrefix,
        [string]$RelativePath,
        [System.Net.NetworkCredential]$NetCred
    )
    $relative = $RelativePath.Trim("/").Replace("\", "/")
    if (-not $relative) { return }

    $parts = $relative -split "/" | Where-Object { $_ }
    $built = ""
    foreach ($part in $parts) {
        $built = if ($built) { "$built/$part" } else { $part }
        $uri = "$BasePrefix$built"
        $req = [System.Net.FtpWebRequest]::Create($uri)
        $req.Method = [System.Net.WebRequestMethods+Ftp]::MakeDirectory
        $req.Credentials = $NetCred
        $req.UsePassive = $true
        try {
            $resp = $req.GetResponse()
            Normalize-FtpResponse -Response $resp
        } catch [System.Net.WebException] {
            $resp = $_.Exception.Response
            if ($resp -and $resp.StatusCode -eq [System.Net.FtpStatusCode]::ActionNotTakenFileUnavailable) {
                Normalize-FtpResponse -Response $resp
                continue
            }
            if ($resp) {
                Normalize-FtpResponse -Response $resp
            }
            # 550 "Directory already exists" — treat as success
            if ($_.Exception.Message -match "550") {
                continue
            }
            throw
        }
    }
}

function Send-FtpFile {
    param(
        [string]$LocalPath,
        [string]$FtpUri,
        [System.Net.NetworkCredential]$NetCred
    )
    $bytes = [System.IO.File]::ReadAllBytes($LocalPath)
    $req = [System.Net.FtpWebRequest]::Create($FtpUri)
    $req.Method = [System.Net.WebRequestMethods+Ftp]::UploadFile
    $req.Credentials = $NetCred
    $req.UseBinary = $true
    $req.UsePassive = $true
    $req.ContentLength = $bytes.Length
    $stream = $req.GetRequestStream()
    try {
        $stream.Write($bytes, 0, $bytes.Length)
    } finally {
        $stream.Close()
    }
    $resp = $req.GetResponse()
    Normalize-FtpResponse -Response $resp
}

$netCred = $Credential.GetNetworkCredential()

# Smoke test: list root (fails fast on bad password)
$testReq = [System.Net.FtpWebRequest]::Create($FtpPrefix)
$testReq.Method = [System.Net.WebRequestMethods+Ftp]::ListDirectory
$testReq.Credentials = $netCred
$testReq.UsePassive = $true
try {
    $testResp = $testReq.GetResponse()
    Normalize-FtpResponse -Response $testResp
} catch {
    throw "FTP login or path failed for '$FtpPrefix'. Check user, password, and that G/Pamu/Projects exists. $($_.Exception.Message)"
}

$files = @()
if (-not $SkipGitTracked) {
    Push-Location $RepoRoot
    try {
        $null = git rev-parse --git-dir 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Not a git repository: $RepoRoot (use -SkipGitTracked for workspace-metadata-only upload)"
        }
        $raw = git ls-files -z
        if ($LASTEXITCODE -ne 0) {
            throw "git ls-files failed."
        }
        $files = ($raw -split "`0") | Where-Object { $_ }
    } finally {
        Pop-Location
    }
} else {
    if (-not (Test-Path -LiteralPath $RepoRoot)) {
        throw "RepoRoot not found: $RepoRoot"
    }
}

$ideExtra = [System.Collections.Generic.List[string]]::new()
if ($IncludeIdeWorkspaceExtras) {
    $dotIdeDir = Join-Path $RepoRoot ".cursor"
    if (Test-Path -LiteralPath $dotIdeDir) {
        Get-ChildItem -LiteralPath $dotIdeDir -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            $rel = $_.FullName.Substring($RepoRoot.Length).TrimStart([char[]]@('\', '/'))
            [void]$ideExtra.Add(($rel -replace '\\', '/'))
        }
    }
    foreach ($name in @('.cursorignore', 'AGENTS.md')) {
        $p = Join-Path $RepoRoot $name
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            [void]$ideExtra.Add($name)
        }
    }
}

$gitSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($f in $files) { [void]$gitSet.Add($f) }
foreach ($c in $ideExtra) {
    if (-not $gitSet.Contains($c)) {
        [void]$gitSet.Add($c)
        $files += $c
    }
}

if ($files.Count -eq 0) {
    throw "Nothing to upload: empty git tree and no workspace IDE metadata files found under $RepoRoot"
}

$remoteBase = if ($RemoteProjectName) {
    "$FtpPrefix$RemoteProjectName".TrimEnd("/") + "/"
} else {
    $FtpPrefix
}
# Root-level files never triggered MKD for this segment; STOR then fails with 550 if the folder is missing.
if ($RemoteProjectName) {
    Ensure-FtpRemoteDirectory -BasePrefix $FtpPrefix -RelativePath $RemoteProjectName -NetCred $netCred
}
if ($SkipGitTracked) {
    Write-Host "Uploading $($files.Count) workspace metadata file(s) to $remoteBase"
} else {
    Write-Host "Uploading $($files.Count) file(s) (git + workspace IDE extras) to $remoteBase"
}

$done = 0
foreach ($rel in $files) {
    $rel = $rel.Replace("\", "/")
    $localFull = Join-Path $RepoRoot $rel
    if (-not (Test-Path -LiteralPath $localFull -PathType Leaf)) {
        Write-Warning "Skipping missing file: $rel"
        continue
    }
    $remoteDirRel = [System.IO.Path]::GetDirectoryName($rel).Replace("\", "/")
    if ($remoteDirRel) {
        Ensure-FtpRemoteDirectory -BasePrefix $remoteBase -RelativePath $remoteDirRel -NetCred $netCred
    }
    $escaped = ($rel -split "/" | ForEach-Object { [System.Uri]::EscapeDataString($_) }) -join "/"
    $ftpUri = "$remoteBase$escaped"
    if ($PSCmdlet.ShouldProcess($ftpUri, "Upload")) {
        Send-FtpFile -LocalPath $localFull -FtpUri $ftpUri -NetCred $netCred
    }
    $done++
    if (($done % 50) -eq 0) {
        Write-Host "  ... $done / $($files.Count)"
    }
}

Write-Host "Finished: $done file(s) uploaded to $remoteBase"

if ($RemoveLocalAfterUpload) {
    if (-not $PSCmdlet.ShouldContinue(
            "This will delete the entire local folder: $RepoRoot",
            "Confirm local delete")) {
        Write-Host "Local delete skipped."
        return
    }
    if ($PSCmdlet.ShouldProcess($RepoRoot, "Remove local project directory")) {
        Remove-Item -LiteralPath $RepoRoot -Recurse -Force
        Write-Host "Removed local copy: $RepoRoot"
    }
}
