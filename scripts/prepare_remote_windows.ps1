param(
    [Parameter(Mandatory=$true)][string]$Config,
    [Parameter(Mandatory=$true)][string]$DataDir,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Esta entrada requiere Windows' }
if (-not [IO.Path]::IsPathRooted($Config) -or -not [IO.Path]::IsPathRooted($DataDir)) {
    throw 'Use rutas absolutas para Config y DataDir'
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { throw 'No existe el JSON' }
if (Test-Path -LiteralPath $DataDir) { throw 'El destino ya existe; no se toca' }
if (-not $Apply) {
    Write-Output 'Vista previa: instalar uv si falta, Python 3.14, dependencias locked y una base central privada.'
    Write-Output "Destino: $DataDir. No se modificó nada; repetir con -Apply."
    exit 0
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvBinary = if ($uvCommand) { $uvCommand.Source } else {
    Join-Path $env:USERPROFILE '.local\bin\uv.exe'
}
if (-not (Test-Path -LiteralPath $uvBinary -PathType Leaf)) {
    $installer = Join-Path ([IO.Path]::GetTempPath()) ("tradinglab-uv-" + [guid]::NewGuid() + '.ps1')
    $oldInstallDir = $env:UV_INSTALL_DIR
    $oldModifyPath = $env:UV_NO_MODIFY_PATH
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
        $env:UV_INSTALL_DIR = Split-Path -Parent $uvBinary
        $env:UV_NO_MODIFY_PATH = '1'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de uv' }
    } finally {
        $env:UV_INSTALL_DIR = $oldInstallDir
        $env:UV_NO_MODIFY_PATH = $oldModifyPath
        if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer }
    }
}
Push-Location -LiteralPath $repoRoot
try {
    & $uvBinary sync --locked --no-dev --python 3.14
    if ($LASTEXITCODE -ne 0) { throw 'Falló uv sync' }
    & $uvBinary run --locked --no-sync python scripts/prepare_remote_host.py --config $Config --data-dir $DataDir --apply
    if ($LASTEXITCODE -ne 0) { throw 'Falló la preparación. Revise un posible destino parcial.' }
} finally { Pop-Location }
