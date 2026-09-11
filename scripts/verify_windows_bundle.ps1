param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = 'Stop'
$bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
$tempRoot = Join-Path $env:RUNNER_TEMP "uncloud-windows-smoke-$PID"
$installDir = Join-Path $tempRoot 'installed'
$stateDir = Join-Path $tempRoot 'state'
New-Item -ItemType Directory -Force -Path $installDir, $stateDir | Out-Null

$installer = Start-Process -FilePath $bundlePath -ArgumentList @('/S', "/D=$installDir") -Wait -PassThru
if ($installer.ExitCode -ne 0) {
    throw "NSIS installer exited with code $($installer.ExitCode)"
}

$uv = Get-ChildItem -LiteralPath $installDir -Recurse -File -Filter 'uv.exe' |
    Select-Object -First 1
$engineManifest = Get-ChildItem -LiteralPath $installDir -Recurse -File -Filter 'pyproject.toml' |
    Where-Object { $_.Directory.Name -eq 'engine' } |
    Select-Object -First 1
$app = Get-ChildItem -LiteralPath $installDir -Recurse -File -Filter '*.exe' |
    Where-Object {
        $_.Name -notin @('uv.exe', 'Uninstall.exe', 'uninstall.exe') -and
        $_.DirectoryName -notmatch '\\engine(\\|$)'
    } |
    Sort-Object Length -Descending |
    Select-Object -First 1

if (-not $uv) { throw 'Installed package does not include uv.exe' }
if (-not $engineManifest) { throw 'Installed package does not include engine/pyproject.toml' }
if (-not $app) { throw 'Installed package does not include the Uncloud application executable' }

$uvVersion = & $uv.FullName --version
if ($uvVersion -notlike 'uv 0.12.13*') { throw "Unexpected bundled runtime: $uvVersion" }

$env:HOME = $stateDir
$env:USERPROFILE = $stateDir
$appProcess = Start-Process -FilePath $app.FullName -PassThru
try {
    Start-Sleep -Seconds 10
    if ($appProcess.HasExited) {
        throw "Installed Uncloud executable exited during startup with code $($appProcess.ExitCode)"
    }
}
finally {
    if (-not $appProcess.HasExited) {
        Stop-Process -Id $appProcess.Id -Force
        $appProcess.WaitForExit()
    }
}

python scripts/smoke_engine.py --uv $uv.FullName --engine $engineManifest.Directory.FullName --work-dir (Join-Path $tempRoot 'engine-smoke')
if ($LASTEXITCODE -ne 0) { throw 'Packaged engine smoke test failed' }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
Copy-Item -LiteralPath $bundlePath -Destination $Output -Force
Write-Host "Verified Windows installer and wrote $Output"
