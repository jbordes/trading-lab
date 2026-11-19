# Thin Windows launcher. The Python runtime owns validation and supervision.
[CmdletBinding()]
param([string]$DataDir, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ($CheckOnly) { Write-Output 'TradingLab launcher entry point OK'; return }
try {
    if (-not $DataDir) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.Application]::EnableVisualStyles()
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Title = 'Seleccione installation.json de la instalacion que desea iniciar'
        $dialog.Filter = 'Registro de instalacion (installation.json)|installation.json'
        $dialog.InitialDirectory = Join-Path $env:LOCALAPPDATA 'TradingLab'
        try {
            if ($dialog.ShowDialog() -ne 'OK') { return }
            $DataDir = Split-Path -Parent $dialog.FileName
        } finally { $dialog.Dispose() }
    }
    if (-not [IO.Path]::IsPathRooted($DataDir)) { throw 'Seleccione una carpeta de instalacion absoluta.' }
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Falta el entorno de esta version. Ejecute Instalar-TradingLab.cmd y continue su instalacion para preparar las dependencias.'
    }
    Set-Location -LiteralPath $repoRoot
    Write-Host 'Iniciando TradingLab. Mantenga esta consola abierta; Ctrl+C detiene sus servicios.'
    & $python (Join-Path $repoRoot 'scripts\run_tradinglab.py') --data-dir $DataDir
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar TradingLab. Revise el mensaje anterior. No se regeneraron bases ni tokens.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

