# Build Saarthi Pro agent image from fraud-stack repo root (Windows).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Ver = if ($env:SAARTHI_PRO_VERSION) { $env:SAARTHI_PRO_VERSION } else { "0.1.0" }
$Sha = if ($env:FRAUD_STACK_GIT_SHA) { $env:FRAUD_STACK_GIT_SHA } else { (git rev-parse HEAD).Trim() }
$Contract = if ($env:INTEGRATION_CONTRACT_VERSION) { $env:INTEGRATION_CONTRACT_VERSION } else { "1.1.0" }
docker build -f distributions/saarthi-pro-agent/Dockerfile `
  --build-arg "SAARTHI_PRO_VERSION=$Ver" `
  --build-arg "FRAUD_STACK_GIT_SHA=$Sha" `
  --build-arg "INTEGRATION_CONTRACT_VERSION=$Contract" `
  -t "saarthi-pro-agent:$Ver" .
Write-Host "Built saarthi-pro-agent:$Ver (fraud-stack $Sha, contract $Contract)"
