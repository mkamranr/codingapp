# Run on the INTERNET-connected build server (Windows + Docker Desktop, Linux containers).
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1              FULL package
#       -> release\codingapp-<version>-offline.tar.gz
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -CodeOnly    CODE update only
#       -> release\codingapp-code-<version>.tar.gz
#   option: -Platform linux/arm64   (default linux/amd64)
#
# Versions: VERSION (application) and RUNTIME_VERSION (runtime image; bump it whenever
# backend\requirements.txt or the runtime part of the Dockerfile changes).
param(
  [switch]$CodeOnly,
  [string]$Platform = "linux/amd64"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Version = (Get-Content VERSION -Raw).Trim()
$Runtime = (Get-Content RUNTIME_VERSION -Raw).Trim()
$Image = "codingapp-runtime:$Runtime"
$Mode = if ($CodeOnly) { "code" } else { "full" }
$Stage = Join-Path $Root "release\.stage"
$env:DOCKER_BUILDKIT = "1"
$Utf8 = New-Object Text.UTF8Encoding($false)

function Step($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Run([string[]]$cmd) {
  & $cmd[0] $cmd[1..($cmd.Length - 1)]
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $($cmd -join ' ')" }
}
function Write-Lf($src, $dst) {   # copy a text file with LF line endings, UTF-8 without BOM
  New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
  $text = [IO.File]::ReadAllText($src) -replace "`r`n", "`n"
  [IO.File]::WriteAllText($dst, $text, $Utf8)
}

Step "Pre-flight"
docker info *> $null; if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }
$os = (docker version -f '{{.Server.Os}}').Trim()
if ($os -ne "linux") { throw "Docker must be in Linux containers mode (current: $os)" }
Write-Host "mode=$Mode version=$Version runtime=$Runtime platform=$Platform"

$proxy = @()
foreach ($v in "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY") {
  $val = [Environment]::GetEnvironmentVariable($v)
  if ($val) { $proxy += @("--build-arg", "$v=$val") }
}

Step "1/6 Backend tests (on the runtime image)"
Run (@("docker", "build", "--pull", "--platform", $Platform, "--target", "test") + $proxy + @("-t", "codingapp-test:$Version", "."))
docker rmi "codingapp-test:$Version" *> $null

Step "2/6 Build the web UI"
Run (@("docker", "build", "--platform", $Platform, "--target", "web") + $proxy + @("-t", "codingapp-web:$Version", "."))
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force (Join-Path $Stage "code") | Out-Null
$cid = (docker create --platform $Platform "codingapp-web:$Version").Trim()
try { Run @("docker", "cp", "${cid}:/web/dist", (Join-Path $Stage "code\static")) } finally { docker rm $cid *> $null }
docker rmi "codingapp-web:$Version" *> $null

Step "3/6 Build runtime image $Image"
Run (@("docker", "build", "--platform", $Platform, "--target", "release", "--build-arg", "RUNTIME_VERSION=$Runtime") + $proxy + @("-t", $Image, "."))

Step "4/6 Assemble code $Version"
$appSrc = Join-Path $Root "backend\app"
Get-ChildItem $appSrc -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne ".pyc" } | ForEach-Object {
  $rel = $_.FullName.Substring($appSrc.Length + 1)
  Write-Lf $_.FullName (Join-Path $Stage "code\app\$rel")
}
Write-Lf (Join-Path $Root "backend\requirements.txt") (Join-Path $Stage "code\requirements.txt")
[IO.File]::WriteAllText((Join-Path $Stage "code\VERSION"), "$Version`n", $Utf8)

Step "5/6 Offline self-test: runtime image + code, container started with --network none"
$codeMount = "$(Join-Path $Stage 'code'):/code:ro"
Run @("docker", "run", "--rm", "--network", "none", "-v", $codeMount, "--entrypoint", "python", $Image, "/opt/runtime/start.py", "--check", "/code")
docker rm -f -v codingapp-selftest *> $null
Run @("docker", "run", "-d", "--name", "codingapp-selftest", "--platform", $Platform, "--network", "none", "-v", $codeMount,
      "-e", "ADMIN_PASSWORD=selftest-pass", "-e", "LLM_BASE_URL=http://127.0.0.1:9/v1", $Image)
try {
  Get-Content scripts\selftest.py -Raw | docker exec -i codingapp-selftest python -
  if ($LASTEXITCODE -ne 0) { docker logs codingapp-selftest; throw "SELF-TEST FAILED: nothing is packaged." }
} finally {
  docker rm -f -v codingapp-selftest *> $null
}

Step "6/6 Package"
if ($Mode -eq "full") { $Name = "codingapp"; $File = "codingapp-$Version-offline.tar.gz" }   # unpacks to .\codingapp = the project folder
else { $Name = "codingapp-code-$Version"; $File = "codingapp-code-$Version.tar.gz" }
$Pkg = Join-Path $Root "release\.pkg"
if (Test-Path $Pkg) { Remove-Item -Recurse -Force $Pkg }
$Out = Join-Path $Pkg $Name
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $Out | Out-Null
Move-Item (Join-Path $Stage "code") (Join-Path $Out "code")
Write-Lf (Join-Path $Root "scripts\selftest.py") (Join-Path $Out "selftest.py")
Write-Lf (Join-Path $Root "CHANGELOG.md") (Join-Path $Out "CHANGELOG.md")
if ($Mode -eq "full") {
  $tar = Join-Path $Out "codingapp-runtime-$Runtime.tar"
  Run @("docker", "save", "-o", $tar, $Image)
  foreach ($f in "deploy\docker-compose.yml", "deploy\.env.example", "deploy\codingapp.sh", "deploy\install.sh", "DEPLOY.md") {
    Write-Lf (Join-Path $Root $f) (Join-Path $Out (Split-Path $f -Leaf))
  }
  $envFile = Join-Path $Out ".env.example"
  $envText = [IO.File]::ReadAllText($envFile) -replace "(?m)^RUNTIME_VERSION=.*$", "RUNTIME_VERSION=$Runtime"
  [IO.File]::WriteAllText($envFile, $envText, $Utf8)
}
$imgId = (docker image inspect -f '{{.Id}}' $Image).Trim()
$manifest = "name=codingapp`nkind=$Mode`nversion=$Version`nruntime=$Runtime`narch=$Platform`nimage=$Image`nimage_id=$imgId`nbuilt_at=$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))`nbuilt_on=$env:COMPUTERNAME`n"
[IO.File]::WriteAllText((Join-Path $Out "MANIFEST.txt"), $manifest, $Utf8)

$sums = Get-ChildItem $Out -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring($Out.Length + 1).Replace('\', '/')
  [pscustomobject]@{ Rel = $rel; Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() }
} | Sort-Object { [string]$_.Rel } -CaseSensitive | ForEach-Object { "$($_.Hash)  $($_.Rel)" }
[IO.File]::WriteAllText((Join-Path $Out "SHA256SUMS"), (($sums -join "`n") + "`n"), $Utf8)
Remove-Item -Recurse -Force $Stage

$bundle = Join-Path $Root "release\$File"
# tar.exe ships with Windows 10 1803+ / Server 2019+
Push-Location $Pkg
try { Run @("tar.exe", "-czf", $bundle, $Name) } finally { Pop-Location }
Remove-Item -Recurse -Force $Pkg
$bh = (Get-FileHash $bundle -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$bundle.sha256", "$bh  $File`n", $Utf8)

Write-Host ""
Write-Host "DONE" -ForegroundColor Green
Write-Host "  Carry to the air-gapped server:  $bundle"
Write-Host "  Its checksum (sha256):           $bh"
if ($Mode -eq "full") { Write-Host "  First install there:    tar -xzf $File && cd codingapp && sudo bash install.sh"; Write-Host "  Upgrade installed one:  cd codingapp && sudo ./codingapp.sh update /path/to/$File" }
else { Write-Host "  Apply there:            cd codingapp && sudo ./codingapp.sh update /path/to/$File" }
