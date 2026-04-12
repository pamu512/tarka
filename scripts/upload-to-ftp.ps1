# Upload git-tracked project files to an FTP path (e.g. NAS share).
# Requires a password: use -Credential, set FTP_PASS (username defaults to suop), or override with FTP_USER.
#
# Example:
#   $c = Get-Credential
#   .\scripts\upload-to-ftp.ps1 -Credential $c
#
#   $env:FTP_PASS = "secret"; .\scripts\upload-to-ftp.ps1

[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$FtpPrefix = "ftp://192.168.0.1/G/Pamu/",
    [string]$RemoteProjectName = "fraud-stack",
    [string]$FtpUser = "suop",
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
    throw "FTP login or path failed for '$FtpPrefix'. Check user, password, and that G/Pamu exists. $($_.Exception.Message)"
}

Push-Location $RepoRoot
try {
    $null = git rev-parse --git-dir 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Not a git repository: $RepoRoot"
    }
    $raw = git ls-files -z
    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed."
    }
    $files = ($raw -split "`0") | Where-Object { $_ }
} finally {
    Pop-Location
}

$remoteBase = "$FtpPrefix$RemoteProjectName".TrimEnd("/") + "/"
Write-Host "Uploading $($files.Count) tracked files to $remoteBase"

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
