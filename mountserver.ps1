$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    & $dockerCmd.Source compose up --build
    exit $LASTEXITCODE
}

$dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
if (Test-Path $dockerExe) {
    & $dockerExe compose up --build
    exit $LASTEXITCODE
}

Write-Error "Docker CLI not found. Install Docker Desktop first."
exit 1
