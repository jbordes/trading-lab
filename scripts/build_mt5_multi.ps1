param([ValidateSet('TradingLabTelemetry','TradingLabActivity','TradingLabAttachCollectors','All')][string]$Name='All')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$build=Join-Path $root '_storage\multicuenta\compiled'
New-Item -ItemType Directory -Path $build -Force | Out-Null
$src=Join-Path $root 'apps\mt5-telemetry-collector'
Get-ChildItem -LiteralPath $src -Filter '*.mqh' | Copy-Item -Destination $build -Force
$names=if ($Name -eq 'All') {@('TradingLabTelemetry','TradingLabActivity','TradingLabAttachCollectors')} else {@($Name)}
foreach ($item in $names) {
    $source=Join-Path $build "$item.mq5"
    Copy-Item -LiteralPath (Join-Path $src "$item.mq5") -Destination $source -Force
    $log=Join-Path $build ("{0}-{1}.log" -f $item,[guid]::NewGuid().ToString('N'))
    $process=Start-Process -FilePath 'C:\Program Files\MetaTrader 5- Roboforex\metaeditor64.exe' -ArgumentList @("/compile:`"$source`"","/log:`"$log`"") -WindowStyle Hidden -PassThru -Wait
    if (!(Test-Path -LiteralPath $log) -or !(Select-String -LiteralPath $log -Pattern 'Result: 0 errors, 0 warnings') -or !(Test-Path -LiteralPath (Join-Path $build "$item.ex5"))) {
        if (Test-Path -LiteralPath $log) {Get-Content -LiteralPath $log -Tail 16}
        throw "Falló la compilación de $item"
    }
    Write-Output "$item compilado."
}
