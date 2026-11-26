param(
    [ValidateSet('TradingLabTelemetry','TradingLabActivity','TradingLabAttachCollectors','All')]
    [string]$Name='All',
    [string]$MetaEditor='C:\Program Files\MetaTrader 5- Roboforex\metaeditor64.exe'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$build=Join-Path $root '_storage\setup\compiled'
$src=Join-Path $root 'apps\mt5-telemetry-collector'
New-Item -ItemType Directory -Path $build -Force | Out-Null
$names=if ($Name -eq 'All') {@('TradingLabTelemetry','TradingLabActivity','TradingLabAttachCollectors')} else {@($Name)}
$compilerVersion=(Get-Item -LiteralPath $MetaEditor).VersionInfo.FileVersion
$lock=[IO.File]::Open((Join-Path $build 'build.lock'),'OpenOrCreate','ReadWrite','None')
try {
    foreach ($item in $names) {
        $stage=Join-Path $build ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stage | Out-Null
        $inputs=@{}
        $files=@(Get-ChildItem -LiteralPath $src -Filter '*.mqh') + @(Get-Item -LiteralPath (Join-Path $src "$item.mq5"))
        foreach ($file in $files) {
            $target=Join-Path $stage $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $target
            $inputs[$file.Name]=(Get-FileHash -LiteralPath $target).Hash.ToLowerInvariant()
        }
        $source=Join-Path $stage "$item.mq5"
        $binary=Join-Path $stage "$item.ex5"
        $log=Join-Path $stage 'compile.log'
        Start-Process -FilePath $MetaEditor -ArgumentList @("/compile:`"$source`"","/log:`"$log`"") -WindowStyle Hidden -Wait
        if (!(Test-Path -LiteralPath $log) -or !(Select-String -LiteralPath $log -Pattern 'Result: 0 errors, 0 warnings') -or !(Get-Item -LiteralPath $binary).Length) {
            throw "Falló la compilación de $item. Revise $log"
        }
        $manifest=@{compiler=$compilerVersion;inputs=$inputs;binary=(Get-FileHash -LiteralPath $binary).Hash.ToLowerInvariant()}
        $descriptor=Join-Path $stage "$item.build.json"
        [IO.File]::WriteAllText($descriptor,($manifest | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        Copy-Item -LiteralPath $binary -Destination $build -Force
        Copy-Item -LiteralPath $descriptor -Destination $build -Force
        Write-Output "$item compilado."
    }
} finally {
    $lock.Dispose()
}
