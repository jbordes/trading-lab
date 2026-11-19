[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ($CheckOnly) { Write-Output 'TradingLab setup entry point OK'; return }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
function Find-Uv {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $paths = @((Join-Path $env:USERPROFILE '.local\bin\uv.exe'), (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'))
    $pythonRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $pythonRoot) {
        $paths += @(Get-ChildItem -LiteralPath $pythonRoot -Directory | ForEach-Object { Join-Path $_.FullName 'Scripts\uv.exe' })
    }
    foreach ($candidate in $paths) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    return $null
}
$form = New-Object System.Windows.Forms.Form
$form.Text = 'TradingLab · Instalación'
$form.Icon = [Drawing.Icon]::new((Join-Path $repoRoot 'src\tradinglab\dashboard\static\favicon-black.ico'))
$form.BackColor = [Drawing.Color]::White
$form.AutoScaleMode = 'Dpi'
$form.Size = New-Object System.Drawing.Size(710, 750)
$form.AutoScroll = $true
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$brand = New-Object Windows.Forms.PictureBox
$brand.Image = [Drawing.Image]::FromFile((Join-Path $repoRoot 'src\tradinglab\dashboard\static\logo_black.png'))
$brand.SizeMode = 'Zoom'
$brand.SetBounds(20, 16, 48, 48)
$form.Controls.Add($brand)
$title = New-Object Windows.Forms.Label
$title.Text = 'Instalar TradingLab'
$title.Font = New-Object Drawing.Font('Segoe UI Semibold', 16)
$title.SetBounds(82, 12, 500, 34)
$form.Controls.Add($title)
$intro = New-Object Windows.Forms.Label
$intro.Text = 'Configure la cuenta y la captura. No se pide la contraseña del broker.'
$intro.SetBounds(84, 47, 555, 25)
$form.Controls.Add($intro)
$tips = New-Object Windows.Forms.ToolTip
$tips.AutoPopDelay = 16000
$tips.InitialDelay = 250
$tips.ReshowDelay = 100
function Add-HoverHelp([int]$top, [string]$name, [string]$message) {
    $hint = New-Object Windows.Forms.Button
    $hint.Text = '?'
    $hint.AccessibleName = "Ayuda de $name"
    $hint.AccessibleDescription = $message
    $hint.FlatStyle = 'Flat'
    $hint.FlatAppearance.BorderSize = 0
    $hint.ForeColor = [Drawing.Color]::SteelBlue
    $hint.SetBounds(632, $top, 28, 26)
    $tips.SetToolTip($hint, $message)
    $form.Controls.Add($hint)
}
$isCentral = Test-Path -LiteralPath (Join-Path $repoRoot 'src\tradinglab\installation_runtime.py')
$script:baseConfig = [pscustomobject][ordered]@{
    mt5_data_dir = ''
    login_id = ''
    server = ''
    currency = 'USD'
    account_mode = 'real'
    snapshot_port = 8876
    activity_port = 8877
    dashboard_port = 8875
    central_port = 8882
    broker_utc_offset_minutes = 120
    history_date = (Get-Date).ToString('yyyy.MM.dd') + ' 00:00:00'
}
$fields = [ordered]@{
    preset_login = @('MT5 Account Nr.', '')
    server = @('Servidor exacto de MT5', '')
    currency = @('Moneda', 'USD')
    broker_utc_offset_minutes = @('Diferencia UTC del broker (minutos)', '120')
    snapshot_port = @($(if ($isCentral) { 'Telemetry Relay Port' } else { 'Telemetry Port' }), '8876')
    activity_port = @($(if ($isCentral) { 'Activity Relay Port' } else { 'Activity Port' }), '8877')
    dashboard_port = @('Dashboard Port', '8875')
    central_port = @('API Port', '8882')
    destination = @('TradingLab Data File (carpeta)', (Join-Path $env:LOCALAPPDATA 'TradingLab\installation'))
    terminal = @('Carpeta de datos de MT5', '')
    preset_history = @('History Date From (hora broker)', ((Get-Date).ToString('yyyy.MM.dd') + ' 00:00:00'))
}
$controls = @{}
$hints = @{
    preset_login = 'Número de cuenta. Figura en el Navegador de MT5, dentro de Cuentas.'
    server = 'Nombre exacto del servidor que aparece junto a la cuenta conectada en MT5.'
    currency = 'Moneda de depósito de la cuenta, por ejemplo USD. Consúltela en el informe de cuenta del broker.'
    broker_utc_offset_minutes = 'Diferencia entre la hora del servidor y UTC, en minutos. UTC+2 equivale a 120. Confirme el huso vigente con el broker.'
    snapshot_port = 'Puerto local para recibir el estado de la cuenta. Puede conservar el sugerido si está libre.'
    activity_port = 'Puerto local para recibir órdenes y ejecuciones. Debe estar libre y ser distinto al de estado.'
    dashboard_port = 'Puerto local donde abrirá el dashboard en el navegador.'
    central_port = 'Puerto local del servicio API.'
    destination = 'Carpeta privada para las bases y los accesos de TradingLab. Elija una ubicación fuera del proyecto.'
    terminal = 'En la terminal correcta, abra Archivo → Abrir carpeta de datos. Seleccione esa carpeta, que contiene MQL5.'
    preset_history = 'Primera fecha a recuperar, expresada en hora del broker. Formato AAAA.MM.DD HH:MM:SS.'
}
$loadButton = New-Object System.Windows.Forms.Button
$loadButton.Text = 'Abrir JSON'
$loadButton.SetBounds(20, 82, 150, 30)
$form.Controls.Add($loadButton)
$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = 'Guardar JSON'
$saveButton.SetBounds(180, 82, 150, 30)
$form.Controls.Add($saveButton)
$y = 130
foreach ($key in $fields.Keys) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $fields[$key][0]
    $label.SetBounds(20, ($y + 3), 280, 26)
    $box = New-Object System.Windows.Forms.TextBox
    $box.Text = $fields[$key][1]
    $box.SetBounds(300, $y, 328, 25)
    $controls[$key] = $box
    if ($key -ne 'central_port' -or $isCentral) {
        $form.Controls.AddRange(@($label, $box))
        if ($key -eq 'terminal') {
            $box.Width = 288
            $browse = New-Object Windows.Forms.Button
            $browse.Text = '…'
            $browse.AccessibleName = 'Elegir carpeta de datos de MT5'
            $browse.SetBounds(592, $y, 36, 26)
            $browse.Add_Click({
                $picker = New-Object Windows.Forms.FolderBrowserDialog
                $picker.Description = $hints.terminal
                $picker.ShowNewFolderButton = $false
                try { if ($picker.ShowDialog($form) -eq 'OK') { $controls.terminal.Text = $picker.SelectedPath } }
                finally { $picker.Dispose() }
            })
            $form.Controls.Add($browse)
        }
        Add-HoverHelp $y $label.Text $hints[$key]
        $y += 36
    }
}
$real = New-Object System.Windows.Forms.CheckBox
$real.Text = 'Es Cuenta Demo'
$real.SetBounds(20, $y, 600, 28)
$form.Controls.Add($real)
Add-HoverHelp $y $real.Text 'Marque esta opción para una cuenta de demostración. Verifique el tipo en la cuenta de MT5.'
Add-HoverHelp ($y + 45) 'instalación' "uv`nPython 3.14`ntzdata 2026.5"
$button = New-Object System.Windows.Forms.Button
$button.Text = 'Instalar'
$button.SetBounds(478, ($y + 40), 150, 36)
$button.FlatStyle = 'Flat'
$button.BackColor = [Drawing.Color]::FromArgb(36, 65, 83)
$button.ForeColor = [Drawing.Color]::White
$form.Controls.Add($button)
$form.ClientSize = New-Object System.Drawing.Size(686, ($y + 96))
$script:setupConfig = $null
$script:setupDestination = $null
$script:configFile = $null
$script:saveOnly = $false
$script:resumeDirectory = $null
function Load-SetupConfig([string]$path) {
    if ([IO.Path]::GetFileName($path).StartsWith('.env')) { throw 'Seleccione un JSON de configuracion, no un archivo de secretos.' }
    try {
        $loaded = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw 'No se pudo leer el JSON. Revise que exista y que los nombres y valores de texto esten entre comillas dobles. Puede corregir el archivo y volver a abrirlo.'
    }
    $internalManifest = $loaded.PSObject.Properties.Name -contains 'config'
    if ($internalManifest) {
        $stored = $loaded.config
        $loaded = $script:baseConfig | ConvertTo-Json | ConvertFrom-Json
        foreach ($key in @('server','currency','account_mode','snapshot_port','activity_port','dashboard_port','central_port','broker_utc_offset_minutes')) { $loaded.$key = $stored.$key }
        if ($controls.preset_login.Text -and ('****' + $controls.preset_login.Text.Substring([Math]::Max(0, $controls.preset_login.Text.Length - 4))) -ne $stored.login_masked) { throw 'MT5 Account Nr. no coincide con la instalacion existente.' }
        $loaded.login_id = $controls.preset_login.Text
        $loaded.history_date = $controls.preset_history.Text
        $loaded.mt5_data_dir = $controls.terminal.Text
    }
    $known = @($script:baseConfig.PSObject.Properties.Name)
    foreach ($property in $loaded.PSObject.Properties) {
        if ($property.Name -notin $known) { throw 'El JSON tiene campos desconocidos. Use la configuracion de instalacion.' }
    }
    if ($loaded.account_mode -and $loaded.account_mode -notin @('demo','real')) { throw 'account_mode debe ser demo o real.' }
    foreach ($key in $known) {
        if ($loaded.PSObject.Properties.Name -contains $key) {
            $script:baseConfig.$key = $loaded.$key
            $controlKey = switch ($key) { 'mt5_data_dir' { 'terminal' }; 'login_id' { 'preset_login' }; 'history_date' { 'preset_history' }; default { $key } }
            if (-not $controls.ContainsKey($controlKey)) { continue }
            $value = [string]$loaded.$key
            $controls[$controlKey].Text = $value
        }
    }
    $real.Checked = $script:baseConfig.account_mode -eq 'demo'
    if (-not $internalManifest) {
        $script:configFile = [IO.Path]::GetFullPath($path)
    }
}
$loadButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = 'Configuracion JSON (*.json)|*.json'
    try {
        if ($dialog.ShowDialog() -eq 'OK') { Load-SetupConfig $dialog.FileName }
    } catch { [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'JSON invalido') }
    finally { $dialog.Dispose() }
})
$submit = {
    try {
        if ([string]::IsNullOrWhiteSpace($controls.server.Text)) { throw 'Complete el servidor MT5.' }
        $target = $controls.destination.Text.Trim()
        if (-not [IO.Path]::IsPathRooted($target)) { throw 'La carpeta debe tener una ruta absoluta.' }
        $target = [IO.Path]::GetFullPath($target)
        if (-not $script:saveOnly -and (Test-Path -LiteralPath $target) -and $script:resumeDirectory -ne $target) {
            $choice = [System.Windows.Forms.MessageBox]::Show('Hay una instalacion existente. Desea continuar desde ahi? Si conserva bases y tokens. No prepara una instalacion nueva en otra carpeta.', 'Instalacion existente', 'YesNoCancel', 'Question')
            if ($choice -eq 'Cancel') { return }
            if ($choice -eq 'No') {
                $controls.destination.Text = $target + '-nueva-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
                $script:resumeDirectory = $null
                [void][System.Windows.Forms.MessageBox]::Show('Se propuso una carpeta nueva. Revise los datos y pulse Instalar.')
                return
            }
            $manifest = Join-Path $target 'installation.json'
            if (-not (Test-Path -LiteralPath $manifest)) { throw 'Instalacion incompleta sin registro final. Conserve sus archivos. Seleccione No para crear otra instalacion; no se reparan bases parciales automaticamente.' }
            Load-SetupConfig $manifest
            $script:resumeDirectory = $target
            [void][System.Windows.Forms.MessageBox]::Show('Se cargaron los datos existentes. Revise login completo y fecha de historial y pulse Instalar. Las bases y los tokens se conservaran.')
            return
        }
        if ($target.StartsWith($repoRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Elija una carpeta fuera del repositorio.' }
        $config = $script:baseConfig | ConvertTo-Json | ConvertFrom-Json
        $login = $controls.preset_login.Text.Trim()
        if ($login -notmatch '^[0-9]{4,18}$') { throw 'Complete MT5 Account Nr. con el numero de cuenta completo (4 a 18 digitos).' }
        $config.login_id = $login
        $config.server = $controls.server.Text.Trim()
        $config.currency = $controls.currency.Text.Trim().ToUpperInvariant()
        $config.account_mode = if ($real.Checked) { 'demo' } else { 'real' }
        $ports = @()
        foreach ($key in @('snapshot_port','activity_port','dashboard_port','central_port')) {
            $number = 0
            if (-not [int]::TryParse($controls[$key].Text, [ref]$number) -or $number -lt 1024 -or $number -gt 65535) { throw 'Los puertos deben ser numeros entre 1024 y 65535.' }
            $config.$key = $number
            $ports += $number
        }
        if (@($ports | Select-Object -Unique).Count -ne 4) { throw 'Los puertos deben ser diferentes.' }
        if (-not $script:saveOnly) {
            foreach ($port in $ports) {
                if (-not $isCentral -and $port -eq $config.central_port) { continue }
                $probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
                try { $probe.Start() }
                catch { throw "El puerto $port esta ocupado o no disponible. Cambielo antes de instalar." }
                finally { $probe.Stop() }
            }
        }
        $offset = 0
        if (-not [int]::TryParse($controls.broker_utc_offset_minutes.Text, [ref]$offset) -or [math]::Abs($offset) -gt 840) { throw 'Revise la diferencia UTC del broker.' }
        $config.broker_utc_offset_minutes = $offset
        $config.mt5_data_dir = $controls.terminal.Text.Trim()
        $config.history_date = $controls.preset_history.Text
        $date = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($controls.preset_history.Text, 'yyyy.MM.dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$date) -or $date -gt [datetime]::UtcNow.AddMinutes($offset)) { throw 'Revise la fecha inicial del historial (hora del broker), no puede ser futura.' }
        $script:presetIdentity = @{login=$login;history_start=$controls.preset_history.Text}
        if ($script:saveOnly) {
            $dialog = New-Object System.Windows.Forms.SaveFileDialog
            $dialog.Filter = 'Configuracion JSON (*.json)|*.json'
            if ($script:configFile) { $dialog.InitialDirectory = Split-Path -Parent $script:configFile }
            $dialog.FileName = $login + '.json'
            try {
                if ($dialog.ShowDialog() -eq 'OK') {
                    if ([IO.Path]::GetFileName($dialog.FileName) -ne ($login + '.json')) { throw 'El archivo debe llamarse ' + $login + '.json' }
                    [IO.File]::WriteAllText($dialog.FileName, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
                    $script:configFile = $dialog.FileName
                }
            } finally { $dialog.Dispose() }
            return
        }
        $terminal = $controls.terminal.Text.Trim()
        $packaged = Test-Path -LiteralPath (Join-Path $repoRoot 'collectors') -PathType Container
        if ($terminal -or $packaged) {
            if (-not [IO.Path]::IsPathRooted($terminal) -or -not (Test-Path -LiteralPath (Join-Path $terminal 'MQL5\Experts') -PathType Container)) { throw $hints.terminal }
            foreach ($name in @('TradingLabActivity', 'TradingLabTelemetry', 'TradingLabAttachCollectors')) {
                if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "collectors\$name.ex5") -PathType Leaf)) { throw 'Para preparar MT5, use el paquete estable extraído que incluye los tres compilados en collectors.' }
            }
        }
        $summary = "Cuenta: $($config.login_id). Servidor: $($config.server). Modo: $($config.account_mode). Datos: $target. Terminal MT5: $terminal. ¿Continuar?"
        if ([System.Windows.Forms.MessageBox]::Show($summary, 'Confirmar instalacion', 'YesNo', 'Question') -ne 'Yes') { return }
        $script:terminalDirectory = $terminal
        $script:setupConfig = $config
        $script:setupDestination = $target
        $form.Close()
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Revise los datos', 'OK', 'Warning')
    }
    finally { $script:saveOnly = $false }
}
$button.Add_Click($submit)
$saveButton.Add_Click({ $script:saveOnly = $true; & $submit })
[void]$form.ShowDialog()
$tips.Dispose()
$brand.Image.Dispose()
$form.Dispose()
if ($null -eq $script:setupConfig) { return }
try {
    Set-Location -LiteralPath $repoRoot
    [Environment]::SetEnvironmentVariable('VIRTUAL_ENV', $null, 'Process')
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host 'Preparando uv con el instalador oficial de Astral...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('tradinglab-uv-' + [guid]::NewGuid().ToString('N') + '.ps1')
        Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar uv.' }
        $uv = Find-Uv
        if (-not $uv) { throw 'uv no fue encontrado despues de instalarlo.' }
    }
    $env:PATH = (Split-Path -Parent $uv) + ';' + $env:PATH
    Write-Host 'Preparando Python 3.14...'
    & $uv python install 3.14
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Python 3.14.' }
    $parent = Split-Path -Parent $script:setupDestination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $configFile = Join-Path $parent ($script:setupConfig.login_id + '.json')
    if ((Test-Path -LiteralPath $configFile) -and ([System.Windows.Forms.MessageBox]::Show('Actualizar la configuracion ' + $configFile + '?', 'Guardar configuracion', 'YesNo', 'Question') -ne 'Yes')) { throw 'Guardado cancelado. No se modifico la instalacion.' }
    $json = $script:setupConfig | ConvertTo-Json
    [IO.File]::WriteAllText($configFile, $json, (New-Object Text.UTF8Encoding($false)))
    $arguments = @('run','--no-project','--python','3.14','python', (Join-Path $repoRoot 'scripts\bootstrap_installation.py'), '--config', $configFile, '--data-dir', $script:setupDestination, '--apply')
    if ($script:setupConfig.account_mode -eq 'real') { $arguments += '--allow-real-account' }
    if ($script:resumeDirectory -eq $script:setupDestination) { $arguments += '--resume' }
    & $uv @arguments
    if ($LASTEXITCODE -ne 0) { throw 'La instalacion no finalizo. Revise esta consola; conserve los archivos para diagnostico.' }
    Write-Host "Instalacion lista: $script:setupDestination"
    $presetArguments = @('run','--no-sync','python', (Join-Path $repoRoot 'scripts\create_collector_presets.py'), '--data-dir', $script:setupDestination)
    if ($script:terminalDirectory) { $presetArguments += @('--mt5-data-dir', $script:terminalDirectory) }
    if ($script:resumeDirectory -eq $script:setupDestination) { $presetArguments += '--resume' }
    $script:presetIdentity | ConvertTo-Json -Compress | & $uv @presetArguments
    if ($LASTEXITCODE -ne 0) { throw 'Las bases están listas. Revise el error anterior y elija Continuar al reintentar.' }
    $instructions = "En MT5, permita WebRequest para http://127.0.0.1:$($script:setupConfig.snapshot_port) y http://127.0.0.1:$($script:setupConfig.activity_port).`nEn Navegador → Scripts, actualice la lista y ejecute TradingLabAttachCollectors en un gráfico."
    if (-not $script:terminalDirectory) { $instructions = "Compile ambos collectors, adjunte cada uno a un gráfico y cargue su archivo .set desde $script:setupDestination\collector-presets. Autorice ambos puertos en WebRequest." }
    Write-Host $instructions
    $message = "Instalación preparada.`n`n$instructions`n`n¿Iniciar TradingLab ahora?"
    if ([System.Windows.Forms.MessageBox]::Show($message, 'TradingLab', 'YesNo', 'Information') -eq 'Yes') {
        & $uv run --no-sync python (Join-Path $repoRoot 'scripts\run_tradinglab.py') --data-dir $script:setupDestination
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar TradingLab. Revise esta consola.' }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Instalacion incompleta', 'OK', 'Error')
    exit 1
}

