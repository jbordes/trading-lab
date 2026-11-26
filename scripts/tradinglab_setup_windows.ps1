$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$OutputEncoding = New-Object Text.UTF8Encoding($false)
$python = Join-Path $root '.venv\Scripts\python.exe'

function Find-Uv {
    $found = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $places = @("$env:USERPROFILE\.local\bin\uv.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe")
    if (Test-Path "$env:LOCALAPPDATA\Programs\Python") {
        $places += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory | ForEach-Object { Join-Path $_.FullName 'Scripts\uv.exe' }
    }
    foreach ($place in $places) { if (Test-Path -LiteralPath $place) { return $place } }
}
try {
    $uv = Find-Uv
    if ($uv) {
        $reported = & $uv --version
        if ($LASTEXITCODE -ne 0 -or $reported -notmatch '^uv (\d+\.\d+\.\d+)\b' -or [version]$Matches[1] -lt [version]'0.13.0') { $uv = $null }
    }
    if (!$uv) {
        # SHA-256 and artifact paths published by PyPI for uv 0.13.0 (CI version).
        $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        $platform, $hash, $blob = switch ($arch) {
            'AMD64' { 'win_amd64','0367b4e0ae4dcef32da4aa2ad2f3853b6ad81d50c187abe50d343d892b8fea21','b20073abae6cafcdb868d42b2c71bf12c9c2eb06a8d229a09569760c41b7948d' }
            'ARM64' { 'win_arm64','286d5976bffe3ed0c62601c0393adb3748f0d88aa24f38cd80ebab773f5b5f74','e792cf7f8765cb61e56d61015e6e01acbe1edfe3ee5029ab9137c85239ddb4f8' }
            'x86' { 'win32','0d9886f69a2e6f9e85a7a11c37f208353aa559bdb5c91d7b69fe883c038439a1','556b98b4a16c96b9a6fefd8795228643a2e849347d54cc91cc2d07bb21afa572' }
            default { throw "Arquitectura no admitida: $arch" }
        }
        $folder = Join-Path $env:LOCALAPPDATA "TradingLab\tools\uv-0.13.0-$platform"
        [IO.Directory]::CreateDirectory($folder) | Out-Null
        $uv = Join-Path $folder 'uv.exe'
        if (![IO.File]::Exists($uv)) {
            $name = "uv-0.13.0-py3-none-$platform.whl"
            $url = 'https://files.pythonhosted.org/packages/{0}/{1}/{2}/{3}' -f $blob.Substring(0,2),$blob.Substring(2,2),$blob.Substring(4),$name
            $stage = Join-Path $folder ([guid]::NewGuid().ToString('N'))
            $wheel = "$stage.whl"
            try {
                Invoke-WebRequest -UseBasicParsing $url -OutFile $wheel
                if ((Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash -ne $hash) { throw 'Huella de uv incorrecta.' }
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                $zip = [IO.Compression.ZipFile]::OpenRead($wheel)
                try {
                    $entries = @($zip.Entries | Where-Object Name -ceq 'uv.exe')
                    if ($entries.Count -ne 1) { throw 'Contenido de uv inesperado.' }
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $stage)
                } finally { $zip.Dispose() }
                try { [IO.File]::Move($stage,$uv) } catch [IO.IOException] { if (![IO.File]::Exists($uv)) { throw } }
            } finally {
                [IO.File]::Delete($wheel)
                [IO.File]::Delete($stage)
            }
        }
    }
    if (!$uv) { throw 'No se encontró uv.' }
    & $uv sync --locked --no-dev
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar Python con las dependencias del paquete.' }
} catch {
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'TradingLab SetUp')
    exit 1
}

$form = New-Object Windows.Forms.Form
$form.Text = 'TradingLab SetUp · Instalación'
$form.BackColor = [Drawing.Color]::White
$form.Font = New-Object Drawing.Font('Segoe UI',10)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.ClientSize = New-Object Drawing.Size(752,632)
$form.AutoScaleMode = 'Dpi'
$form.Icon = New-Object Drawing.Icon((Join-Path $root 'src\tradinglab\dashboard\static\favicon-black.ico'))
$tabs = New-Object Windows.Forms.TabControl
$tabs.Dock = 'Fill'
$form.Controls.Add($tabs)
$header = New-Object Windows.Forms.Panel
$header.Dock = 'Top'
$header.Height = 124
$form.Controls.Add($header)
$brand = New-Object Windows.Forms.PictureBox
$brand.Image = [Drawing.Image]::FromFile((Join-Path $root 'src\tradinglab\dashboard\static\logo_black.png'))
$brand.SizeMode = 'Zoom'
$brand.SetBounds(20,16,48,48)
$header.Controls.Add($brand)
$heading = New-Object Windows.Forms.Label
$heading.Font = New-Object Drawing.Font('Segoe UI Semibold',16)
$heading.SetBounds(82,12,640,34)
$header.Controls.Add($heading)
$intro = New-Object Windows.Forms.Label
$intro.SetBounds(84,47,645,28)
$header.Controls.Add($intro)
$tips = New-Object Windows.Forms.ToolTip
$tips.AutoPopDelay = 16000
$tips.InitialDelay = 250
$tips.ReshowDelay = 100
function Add-HoverHelp($page,[int]$y,[string]$name,[string]$message) {
    $hint = New-Object Windows.Forms.Button
    $hint.Text = '?'
    $hint.AccessibleName = "Ayuda de $name"
    $hint.AccessibleDescription = $message
    $hint.FlatStyle = 'Flat'
    $hint.FlatAppearance.BorderSize = 0
    $hint.ForeColor = [Drawing.Color]::SteelBlue
    $hint.SetBounds(694,$y,28,26)
    $tips.SetToolTip($hint,$message)
    $hint.Add_Click({
        param($sender,$eventArgs)
        $tips.Show($sender.AccessibleDescription,$sender,0,$sender.Height,$tips.AutoPopDelay)
    })
    $page.Controls.Add($hint)
}
function Page($title,$pageHeading,$description) {
    $page = New-Object Windows.Forms.TabPage($title)
    $page.AutoScroll = $true
    $page.BackColor = [Drawing.Color]::White
    $page.Tag = @{ Heading=$pageHeading; Description=$description }
    $tabs.TabPages.Add($page)
    return $page
}
function Label($page,$title,$x,$y,$w=263) {
    $c = New-Object Windows.Forms.Label
    $c.Text=$title
    $c.SetBounds($x,$y,$w,26)
    $page.Controls.Add($c)
}
function Field($page,$title,$y,$hint,$value='',[switch]$Masked,[switch]$Browse) {
    Label $page $title 20 ($y+3)
    $c = New-Object Windows.Forms.TextBox
    $c.Text=$value
    $c.AccessibleName=$title
    $c.SetBounds(290,$y,394,26)
    $c.UseSystemPasswordChar=$Masked.IsPresent
    $page.Controls.Add($c)
    if ($Browse) {
        $c.Width=352
        $picker=New-Object Windows.Forms.Button
        $picker.Text='…'
        $picker.AccessibleName="Elegir $title"
        $picker.Tag=$c
        $picker.SetBounds(648,$y,36,26)
        $picker.Add_Click({param($sender,$eventArgs) Folder $sender.Tag})
        $page.Controls.Add($picker)
    }
    Add-HoverHelp $page $y $title $hint
    return $c
}
function Button($page,$title,$x,$y,$width,$handler,[switch]$Primary,[string]$Tip='') {
    $b = New-Object Windows.Forms.Button
    $b.Text=$title
    $b.SetBounds($x,$y,$width,34)
    if ($Primary) {
        $b.FlatStyle='Flat'
        $b.BackColor=[Drawing.Color]::FromArgb(36,65,83)
        $b.ForeColor=[Drawing.Color]::White
        Add-HoverHelp $page ($y+4) $title $Tip
    }
    if ($Tip) {
        $b.AccessibleDescription=$Tip
        $tips.SetToolTip($b,$Tip)
    }
    $b.Add_Click($handler)
    $page.Controls.Add($b)
}
function Action([scriptblock]$task) {
    $form.UseWaitCursor=$true
    try { & $task } catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'TradingLab SetUp') }
    finally { $form.UseWaitCursor=$false }
}
function Folder($field) {
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.SelectedPath=$field.Text
    if ($dialog.ShowDialog() -eq 'OK') {$field.Text=$dialog.SelectedPath}
    $dialog.Dispose()
}
function Checks($page,$y) {
    $table=@{}
    $roles=@{api='API';relay='Relay';dashboard='Dashboard'}
    $descriptions=@{
        api='API · Registra las cuentas y guarda su historial en la base central.'
        relay='Relay · Recibe la captura de MT5 y conserva los envíos pendientes hasta que la API los recibe.'
        dashboard='Dashboard · Muestra en el navegador la cuenta que elija dentro de su sesión.'
    }
    $i=0
    foreach ($role in @('api','relay','dashboard')) {
        $c=New-Object Windows.Forms.CheckBox
        $c.Text=$roles[$role]
        $c.Checked=$true
        $c.SetBounds((290+125*$i),$y,120,28)
        $tips.SetToolTip($c,$descriptions[$role])
        $page.Controls.Add($c)
        $table[$role]=$c
        $i++
    }
    Add-HoverHelp $page $y 'servicios' ($descriptions.api + [Environment]::NewLine + $descriptions.relay + [Environment]::NewLine + $descriptions.dashboard)
    return $table
}
function Selected($table) {
    foreach ($role in @('api','relay','dashboard')) { if ($table[$role].Checked) { $role } }
}
function Configuration {
    $cfg=[ordered]@{ version=2; components=@(Selected $components) }
    foreach ($name in $fields.Keys) { $cfg[$name]=$fields[$name].Text.Trim() }
    foreach ($name in @('api_listen_port','dashboard_listen_port')) {
        if (!$cfg[$name]) { $cfg[$name]=$null } else { $cfg[$name]=[int]$cfg[$name] }
    }
    return $cfg
}
function Invoke-SetUp($op,$extra=@{}) {
    $inputData=@{config=(Configuration)}
    foreach ($key in $extra.Keys) { $inputData[$key]=$extra[$key] }
    $payload=$inputData | ConvertTo-Json -Depth 5 -Compress
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$python
    $info.Arguments='"'+(Join-Path $root 'scripts\tradinglab_setup.py')+'" '+$op
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.EnvironmentVariables['PYTHONUTF8']='1'
    $info.StandardOutputEncoding=[Text.Encoding]::UTF8
    $info.StandardErrorEncoding=[Text.Encoding]::UTF8
    $proc=[Diagnostics.Process]::Start($info)
    try {
        $outTask=$proc.StandardOutput.ReadToEndAsync()
        $errTask=$proc.StandardError.ReadToEndAsync()
        $bytes=[Text.Encoding]::UTF8.GetBytes($payload)
        $proc.StandardInput.BaseStream.Write($bytes,0,$bytes.Length)
        $proc.StandardInput.Close()
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {throw $errTask.Result.Trim()}
        return ($outTask.Result | ConvertFrom-Json)
    } finally { $proc.Dispose() }
}
function Message($response) { [void][Windows.Forms.MessageBox]::Show($response.message,'TradingLab SetUp') }
$hostPage=Page 'Equipo' 'Instalar TradingLab' 'Elija los componentes de este equipo y las direcciones de conexión.'
$servicePage=Page 'Servicios' 'Iniciar servicios de TradingLab' 'Seleccione los servicios que desea iniciar o detener en este equipo.'
$mt5Page=Page 'Terminal MT5' 'Instalar los collectors de TradingLab' 'Prepare la captura una vez por cada terminal MT5.'
$accountPage=Page 'Cuentas' 'Agregar cuenta a TradingLab' 'Configure la cuenta y la captura con los datos que figuran en MT5.'
$setHeading = {
    $page = $tabs.SelectedTab
    if ($null -eq $page) { $page = $hostPage }
    $heading.Text = $page.Tag.Heading
    $intro.Text = $page.Tag.Description
}
$tabs.Add_SelectedIndexChanged($setHeading)
& $setHeading
$fields=@{}
Label $hostPage 'Componentes de este equipo' 20 20
$components=Checks $hostPage 16
$fields.data_dir=Field $hostPage 'Carpeta de datos de TradingLab' 56 'Carpeta privada para las bases y las claves de este equipo. Para continuar una instalación, abra el archivo setup.json de esa carpeta con Abrir JSON.' (Join-Path $env:LOCALAPPDATA 'TradingLab Data') -Browse
$fields.snapshot_ingest_url=Field $hostPage 'Telemetry Relay URL' 92 'Dirección donde Telemetry entrega el estado de la cuenta al relay. En el mismo equipo use HTTP en loopback. Para un relay remoto use su URL HTTPS con la ruta /account-state.' 'http://127.0.0.1:8776/account-state'
$fields.activity_ingest_url=Field $hostPage 'Activity Relay URL' 128 'Dirección donde Activity entrega órdenes y ejecuciones al relay. Indique la URL HTTPS publicada o la dirección HTTP local con la ruta /trading-events.' 'http://127.0.0.1:8777/trading-events'
$fields.dashboard_url=Field $hostPage 'Dashboard URL' 164 'Dirección completa que abrirá en el navegador. Conserve /dashboard al final. Para acceso remoto, indique la dirección HTTPS publicada por el proxy.' 'http://127.0.0.1:8775/dashboard'
$fields.api_base_url=Field $hostPage 'API URL' 200 'Dirección base que usan el relay y el dashboard para conectarse a la API. Si está en otro equipo, indique su URL HTTPS, por ejemplo https://api.tradinglab.com.' 'http://127.0.0.1:8782'
$fields.api_listen_port=Field $hostPage 'API Port (escucha local)' 236 'Opcional. Con una URL HTTPS, el proxy reenvía las peticiones al puerto local 8782 de la API. Complete este campo si configuró otro puerto de escucha.'
$fields.dashboard_listen_port=Field $hostPage 'Dashboard Port (escucha local)' 272 'Opcional. Con una URL HTTPS, el proxy reenvía las peticiones al puerto local 8775 del dashboard. Complete este campo si configuró otro puerto de escucha.'
$admin=Field $hostPage 'Clave de administración' 320 'SetUp genera esta clave en el equipo de la API y la usa allí automáticamente. Desde otro equipo, ingrese el valor del campo admin de api.private.json para dar de alta cuentas o vincular servicios.' -Masked
$password=Field $hostPage 'Contraseña del dashboard (opcional)' 356 'Deje el campo vacío para generar la contraseña de acceso. Para iniciar sesión, consulte el campo password de dashboard.private.json en la carpeta privada del dashboard. Al continuar se conserva la contraseña existente.' -Masked
$updateAdminField = {
    $admin.Enabled = -not $components.api.Checked
    if (!$admin.Enabled) { $admin.Clear() }
}
$components.api.Add_CheckedChanged($updateAdminField)
& $updateAdminField
Button $hostPage 'Preparar equipo' 509 410 175 {Action {Message (Invoke-SetUp 'prepare' @{admin=$admin.Text;password=$password.Text})}} -Primary -Tip 'Aplica la configuración de los componentes seleccionados. Puede iniciarlos después desde Servicios.'
Button $header 'Abrir JSON' 20 82 150 {Action {
    $d=New-Object Windows.Forms.OpenFileDialog
    $d.Filter='Configuración JSON|*.json'
    if ($d.ShowDialog() -eq 'OK') {
        $cfg=Get-Content -Raw -Encoding UTF8 -LiteralPath $d.FileName | ConvertFrom-Json
        if ($cfg.version -eq 2) {
            foreach ($key in $fields.Keys) {$fields[$key].Text=[string]$cfg.$key}
            foreach ($key in @('snapshot_ingest_url','activity_ingest_url')) {
                $fields[$key].Text = $fields[$key].Text -replace '/api/(account-state|trading-events)$','/$1'
            }
            foreach ($role in $components.Keys) {$components[$role].Checked=$role -in $cfg.components}
        } else { throw 'Formato de configuración desconocido.' }
    }
    $d.Dispose()
}} -Tip 'Carga un perfil de instalación. Para continuar en este equipo, elija el archivo setup.json de la carpeta privada.'
Button $header 'Guardar JSON' 180 82 150 {Action {
    $cfg=Invoke-SetUp 'validate'
    $d=New-Object Windows.Forms.SaveFileDialog
    $d.Filter='Configuración JSON|*.json'
    $d.FileName='tradinglab-setup.json'
    if ($d.ShowDialog() -eq 'OK') {
        if ($d.FileName -like '*.private.json' -or ([IO.Path]::GetDirectoryName($d.FileName) -eq $fields.data_dir.Text)) {throw 'Exporte el perfil fuera de la carpeta privada.'}
        [IO.File]::WriteAllText($d.FileName,($cfg | ConvertTo-Json -Depth 5),[Text.Encoding]::UTF8)
    }
    $d.Dispose()
}} -Tip 'Exporta los componentes, carpetas y URLs del perfil. Las cuentas se registran en la API desde Cuentas.'
Label $servicePage 'Servicios a controlar' 20 20
$selectedServices=Checks $servicePage 16
Button $servicePage 'Iniciar selección' 509 76 175 {Action {Message (Invoke-SetUp 'start' @{roles=@(Selected $selectedServices)})}} -Primary -Tip 'Inicia los servicios seleccionados, cada uno en su propia consola. Puede cerrar el SetUp después de iniciarlos.'
Button $servicePage 'Detener selección' 20 76 152 {Action {Message (Invoke-SetUp 'stop' @{roles=@(Selected $selectedServices)})}} -Tip 'Detiene los servicios marcados en este equipo.'
Button $servicePage 'Consultar estado' 182 76 152 {Action {Message (Invoke-SetUp 'status')}} -Tip 'Muestra qué servicios locales responden, los envíos pendientes del relay y la disponibilidad de la API configurada.'
Button $servicePage 'Abrir dashboard' 344 76 152 {Action {
    $cfg=Invoke-SetUp 'validate'
    Start-Process -FilePath ([Uri]$cfg.dashboard_url).AbsoluteUri
}} -Tip 'Abre la Dashboard URL configurada en el navegador.'
$fields.mt5_data_dir=Field $mt5Page 'Carpeta de datos de MT5' 20 'En la terminal que desea preparar, abra Archivo → Abrir carpeta de datos. Seleccione esa carpeta, que contiene MQL5.' -Browse
$fields.remote_relay_id=Field $mt5Page 'ID del relay remoto' 56 'Para una terminal en otro equipo, copie el ID público que muestra Preparar equipo en el servidor del relay. Al preparar los collectors se usa la clave de administración ingresada en Equipo.'
Button $mt5Page 'Preparar collectors' 509 108 175 {Action {Message (Invoke-SetUp 'attach' @{admin=$admin.Text})}} -Primary -Tip 'Instala Telemetry, Activity y el asistente de gráficos en esta terminal. Al terminar verá las dos direcciones que debe autorizar para WebRequest en MT5.'
$aliasBox=Field $accountPage 'Nombre en el dashboard' 20 'Nombre que verá en el selector de cuentas. Elija uno que le permita distinguir esta cuenta, por ejemplo Evaluación A.'
$loginBox=Field $accountPage 'MT5 Account Nr.' 56 'Número completo de la cuenta. Figura en el Navegador de MT5, dentro de Cuentas.'
$broker=Field $accountPage 'Servidor exacto de MT5' 92 'Copie el nombre del servidor que aparece junto a la cuenta en MT5. TradingLab usa el servidor y el número de cuenta para reconocer la captura.'
$currency=Field $accountPage 'Moneda' 128 'Moneda de depósito de la cuenta, por ejemplo USD. Puede consultarla en el informe de cuenta del broker.' 'USD'
Label $accountPage 'Diferencia UTC del broker (minutos)' 20 167
$offset=New-Object Windows.Forms.NumericUpDown
$offset.Minimum=-840
$offset.Maximum=840
$offset.AccessibleName='Diferencia UTC del broker (minutos)'
$offset.SetBounds(290,164,394,26)
$accountPage.Controls.Add($offset)
Add-HoverHelp $accountPage 164 $offset.AccessibleName 'Diferencia en minutos entre el reloj del servidor y UTC. Para UTC+2 escriba 120. Confirme el huso vigente con el broker.'
$since=Field $accountPage 'History Date From (hora broker)' 200 'Primera fecha desde la que Activity recuperará las operaciones disponibles. Escríbala en hora del broker con el formato AAAA.MM.DD HH:MM:SS. La curva de equity comienza con las capturas de Telemetry.' ((Get-Date).ToString('yyyy.MM.dd 00:00:00'))
$demo=New-Object Windows.Forms.CheckBox
$demo.Text='Es Cuenta Demo'
$demo.SetBounds(20,238,260,28)
$demo.Checked=$true
$accountPage.Controls.Add($demo)
Add-HoverHelp $accountPage 238 $demo.Text 'Marque la casilla si MT5 identifica la cuenta como demo. Para una cuenta que MT5 identifica como real, déjela desmarcada. La etapa de fondeo se determina por separado.'
Button $accountPage 'Dar de alta' 509 296 175 {Action {
    $accountMode=if ($demo.Checked) { 'demo' } else { 'real' }
    $account=@{ label=$aliasBox.Text.Trim(); login=$loginBox.Text.Trim(); server=$broker.Text.Trim(); currency=$currency.Text.Trim(); mode=$accountMode; history_from=$since.Text.Trim(); broker_offset=[int]$offset.Value }
    Message (Invoke-SetUp 'register' @{account=$account;admin=$admin.Text})
}} -Primary -Tip 'Registra la cuenta en la API central. Una vez dada de alta, se puede seleccionar en el dashboard y capturar desde una terminal preparada.'
try { [void]$form.ShowDialog() }
finally {
    $tips.Dispose()
    $brand.Image.Dispose()
    $form.Dispose()
}
