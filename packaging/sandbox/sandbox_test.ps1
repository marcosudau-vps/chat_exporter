# ChatExporter - Komplett-Test auf frischem Windows (Windows Sandbox). Nur ASCII (PowerShell 5.1).
# Start: python packaging/sandbox/run_sandbox_test.py --installer <Setup.exe> (siehe README.md daneben).
$ErrorActionPreference = 'Continue'
$in  = 'C:\Test\in'
$out = 'C:\Test\out'
New-Item -ItemType Directory -Force $out | Out-Null
$res = Join-Path $out 'results.txt'
Set-Content -Path $res -Value ("Start " + (Get-Date -Format s)) -Encoding UTF8
$env:PYTHONIOENCODING = 'utf-8'
$app  = Join-Path $env:LOCALAPPDATA 'Programs\ChatExporter'
$exe  = Join-Path $app 'chatexporter.exe'
$home_dir = Join-Path $env:USERPROFILE '.chatexporter'

function Check([bool]$ok, [string]$name, [string]$detail = '') {
    $s = 'FEHLER'
    if ($ok) { $s = 'OK    ' }
    Add-Content -Path $res -Value "$s $name $detail" -Encoding UTF8
}

function Run([string]$name, [string]$arguments, [string]$stdin = '', [int]$timeout = 300) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $arguments
    if ($stdin) {
        $answers = Join-Path $out "$name.answers.txt"
        [System.IO.File]::WriteAllText($answers, $stdin, [System.Text.Encoding]::ASCII)
        $psi.FileName = 'cmd.exe'
        $psi.Arguments = '/c ""' + $exe + '" ' + $arguments + ' < "' + $answers + '""'
        $stdin = ''
    }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.WorkingDirectory = $env:USERPROFILE
    $p = [System.Diagnostics.Process]::Start($psi)
    if ($stdin) { $b = [System.Text.Encoding]::ASCII.GetBytes($stdin); $p.StandardInput.BaseStream.Write($b, 0, $b.Length); $p.StandardInput.BaseStream.Flush() }
    $p.StandardInput.Close()
    $o = $p.StandardOutput.ReadToEndAsync()
    $e = $p.StandardError.ReadToEndAsync()
    $code = -999
    if ($p.WaitForExit($timeout * 1000)) { $code = $p.ExitCode } else { $p.Kill() }
    $text = $o.Result + "`r`n--- stderr ---`r`n" + $e.Result
    Set-Content -Path (Join-Path $out "$name.txt") -Value ("> chatexporter $arguments`r`nExitcode $code`r`n" + $text) -Encoding UTF8
    return @{ code = $code; text = $text }
}

# Beobachtet waehrend eines Laufs die Befehlszeilen der vom ChatExporter gestarteten Browser.
function WatchFlags([string]$name, $proc, [int]$timeout) {
    $seen = @{ offscreen = $false; sync = $false; implicit = $false; count = 0 }
    $t0 = Get-Date
    while (-not $proc.HasExited -and ((Get-Date) - $t0).TotalSeconds -lt $timeout) {
        foreach ($c in @(Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue)) {
            $cl = [string]$c.CommandLine
            if ($cl -match 'remote-debugging-port') {
                $seen.count++
                if ($cl -match '--window-position=-32000,-32000') { $seen.offscreen = $true }
                if ($cl -match '--disable-sync') { $seen.sync = $true }
                if ($cl -match 'msImplicitSignin') { $seen.implicit = $true }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $proc.HasExited) { $proc.Kill() }
    return $seen
}

function TaskCount {
    try {
        $s = New-Object -ComObject Schedule.Service; $s.Connect()
        return $s.GetFolder('\ChatExporter').GetTasks(1).Count
    } catch { return 0 }
}

# 0. Umgebung
$edge = Test-Path 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$py = [bool](Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' })
Check $true 'Umgebung' ("Windows " + [Environment]::OSVersion.Version + ", Edge=" + $edge + ", Python=" + $py + ", Benutzer=" + $env:USERNAME)

# 1. Installation (still, mit PATH-Option)
$setup = Get-ChildItem $in -Filter 'ChatExporter-Setup-*.exe' | Select-Object -First 1
$p = Start-Process -FilePath $setup.FullName -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/TASKS=path',"/LOG=$out\install.log" -Wait -PassThru
Check ($p.ExitCode -eq 0) 'Installation' ("Exitcode " + $p.ExitCode + ", " + $setup.Name)
Check (Test-Path $exe) 'Programmdatei' $exe
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ChatExporter.lnk'
Check (Test-Path $desktop) 'Desktop-Verknuepfung' $desktop
$shell = New-Object -ComObject WScript.Shell
if (Test-Path $desktop) {
    $link = $shell.CreateShortcut($desktop)
    Check ($link.TargetPath -eq $exe -and $link.IconLocation -eq "$exe,0") 'Desktop-Ziel und Icon' $link.IconLocation
}
Add-Type -AssemblyName System.Drawing
$appIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($exe)
Check ($null -ne $appIcon) 'Programm-Icon lesbar' ''
if ($appIcon) { $appIcon.Dispose() }
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\ChatExporter'
$links = @(Get-ChildItem $menu -ErrorAction SilentlyContinue).Count
Check ($links -eq 4) 'Startmenue' ("$links Eintraege")
$uninst = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | Where-Object { $_.PSChildName -like '*112F8EEC*' }).Count
Check ($uninst -eq 1) 'Eintrag unter Apps' ''
$uninstKey = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | Where-Object { $_.PSChildName -like '*112F8EEC*' } | Select-Object -First 1
if ($uninstKey) {
    $displayIcon = (Get-ItemProperty $uninstKey.PSPath).DisplayIcon
    Check ($displayIcon -eq "$exe,0") 'Icon unter Apps' $displayIcon
}
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
Check ($userPath -like "*$app*") 'PATH-Eintrag' ''

# 2. Programm ohne Python
$r = Run '01_version' '--version'
Check ($r.code -eq 0 -and $r.text -match '\d+\.\d+') 'Version' ($r.text.Split("`n")[0].Trim())
$r = Run '02_config_path' 'config path'
Check ($r.code -eq 0 -and (Test-Path (Join-Path $home_dir 'config.yaml'))) 'config.yaml angelegt' $home_dir
$r = Run '02b_storage_show' 'storage show'
Check ($r.code -eq 0) 'storage show (Speicherverwaltung)' ("Exitcode " + $r.code)
$r = Run '03_login_help' 'chatgpt login -h'
Check ($r.code -eq 0 -and $r.text -match 'profil') 'Befehl chatgpt login vorhanden' ("Exitcode " + $r.code)
Check ($r.text -match 'schrittweise') 'chatgpt login --schrittweise vorhanden' ''
$r = Run '03c_window' 'config get providers.chatgpt.browser.window'
Check ($r.code -eq 0 -and $r.text -match 'offscreen') 'Einstellung browser.window = offscreen' 
$env:CHATGPT_PASSWORD = 'sandbox-geheim-123'
$r = Run '03b_config_list' 'config list'
Remove-Item Env:CHATGPT_PASSWORD
Check ($r.code -eq 0 -and $r.text -notmatch 'sandbox-geheim-123' -and $r.text -match 'auth.password') 'Passwort in config list nicht angezeigt' ''
$r = Run '04_status' 'status'
Check ($r.code -eq 0) 'status' ("Exitcode " + $r.code)
$r = Run '05_export' 'export'
Check ($r.code -eq 0) 'export' ("Exitcode " + $r.code)
$r = Run '06_task_list' 'task list'
Check ($r.code -eq 0) 'task list (Aufgabenplanung, pywin32)' ("Exitcode " + $r.code)

# 3. Einrichtung: Browser ueberspringen, taegliche Aufgabe 07:30
$r = Run '07_setup' 'setup' "n`r`n07:30`r`n"
Check ($r.code -eq 0 -and $r.text -match '07:30') 'setup mit taeglicher Aufgabe' ("Exitcode " + $r.code)
Check ((TaskCount) -ge 1) 'Aufgabe in der Windows-Aufgabenplanung' ("Anzahl " + (TaskCount))

# 4. Geplanter Lauf: Testaufgabe mit 'status' sofort ausfuehren
$r = Run '08_task_create' 'task create Lauftest --once "2099-01-01 00:00" --command status'
$j = Run '09_task_get_json' 'task get lauftest --json'
$tid = ''
try { $tid = (($j.text -split '--- stderr ---')[0] | ConvertFrom-Json).task_id } catch {}
if ($tid) {
    schtasks /Run /TN "\ChatExporter\$tid" | Out-Null
    $last = ''
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        $g = Run '10_task_get' 'task get lauftest'
        if ($g.text -match 'Letztes Ergebnis:\s+(-?\d+)') { $last = $Matches[1]; if ($g.text -notmatch 'running') { break } }
    }
    Check ($last -eq '0') 'Geplanter Lauf (Aufgabenplanung startet chatexporter.exe)' ("Letztes Ergebnis " + $last)
} else { Check $false 'Geplanter Lauf' 'Aufgabe nicht angelegt' }

# 4b. Start beim Hochfahren (--startup): mit Administratorrechten anlegen, sonst verstaendliche Ablehnung
$r = Run '10b_task_startup' 'task create Starttest --startup --paused --command status'
$admin = ($r.code -eq 0)
Check ($admin -or $r.text -match 'Administratorrechte') 'task create --startup: angelegt oder verstaendlich abgelehnt' ("Exitcode " + $r.code + ", angelegt=" + $admin)
if ($admin) {
    $r = Run '10c_task_startup_delete' 'task delete starttest --yes'
    Check ($r.code -eq 0) 'Starttest-Aufgabe wieder entfernt' ("Exitcode " + $r.code)
}

# 5. ChatGPT ohne Anmeldung, ohne Interaktion: Browser-Suche auf frischem Windows
$before = @(Get-Process msedge -ErrorAction SilentlyContinue).Count
$cmdline = '/c ""' + $exe + '" update --source chatgpt --non-interactive > "' + (Join-Path $out '11_update_chatgpt.txt') + '" 2>&1"'
$p = Start-Process -FilePath cmd.exe -ArgumentList $cmdline -PassThru -WindowStyle Hidden -WorkingDirectory $env:USERPROFILE
$null = $p.Handle
$ef = WatchFlags 'msedge.exe' $p 420
$r = @{ code = $p.ExitCode; text = (Get-Content (Join-Path $out '11_update_chatgpt.txt') -Raw -Encoding UTF8) }
Check ($ef.count -ge 1) 'Edge vom ChatExporter gestartet (Befehlszeile beobachtet)' ("Beobachtungen " + $ef.count)
Check ($ef.offscreen) 'Edge ausserhalb des Bildschirms gestartet' ''
Check ($ef.sync -and $ef.implicit) 'Edge ohne Synchronisierung und stille Kontoanmeldung gestartet' ("disable-sync=" + $ef.sync + ", msImplicitSignin=" + $ef.implicit)
$noCrash = $r.text -notmatch 'Traceback'
Check $noCrash 'ChatGPT-Lauf ohne Anmeldung endet ohne Absturz' ("Exitcode " + $r.code)
Check ($r.text -match 'Browser-Suche|nicht verwendet|Anmeldung') 'Browser-Suche protokolliert' ''
Start-Sleep -Seconds 5
$after = @(Get-Process msedge -ErrorAction SilentlyContinue).Count
Check ($after -le $before) 'Kein Browser offen geblieben' ("Edge-Prozesse vorher $before, nachher $after")

# 5b. Ersatz-Browser (Chrome for Testing): echter Download, Entpacken, Start, Fernsteuerung
# Weg 'Edge mit eigenem Profil' fuer den Test sperren (Datei statt Ordner), damit die Suche bis zum Ersatz-Browser kommt.
$block = Join-Path $home_dir 'browser\profiles'
New-Item -ItemType Directory -Force $block | Out-Null
Remove-Item -Recurse -Force (Join-Path $block 'edge') -ErrorAction SilentlyContinue
Set-Content -Path (Join-Path $block 'edge') -Value 'Testsperre' -Encoding ASCII
Check (Test-Path (Join-Path $block 'edge') -PathType Leaf) 'Testsperre fuer Edge-Profil gesetzt' ''
[System.IO.File]::WriteAllText((Join-Path $out 'answers.txt'), "j`r`n", [System.Text.Encoding]::ASCII)
$cmdline = '/c ""' + $exe + '" chatgpt browser-setup < "' + (Join-Path $out 'answers.txt') + '" > "' + (Join-Path $out '13_cft.txt') + '" 2>&1"'
$p = Start-Process -FilePath cmd.exe -ArgumentList $cmdline -PassThru -WindowStyle Hidden -WorkingDirectory $env:USERPROFILE
$null = $p.Handle
$cf = WatchFlags 'chrome.exe' $p 900
$t = Get-Content (Join-Path $out '13_cft.txt') -Raw -Encoding UTF8
Check ($cf.offscreen -and $cf.sync) 'Ersatz-Browser verborgen und ohne Synchronisierung gestartet' ("offscreen=" + $cf.offscreen + ", disable-sync=" + $cf.sync + ", Beobachtungen " + $cf.count)
$chrome = @(Get-ChildItem (Join-Path $home_dir 'browser\chrome-for-testing') -Recurse -Filter chrome.exe -ErrorAction SilentlyContinue)
Check ($t -notmatch 'CERTIFICATE_VERIFY_FAILED') 'Ersatz-Browser: Zertifikat ok' ''
Check ($chrome.Count -ge 1) 'Ersatz-Browser heruntergeladen und entpackt' ($chrome | Select-Object -First 1 | ForEach-Object { $_.FullName })
Check ($t -notmatch 'Download/Installation fehlgeschlagen' -and $t -notmatch 'Chrome for Testing \(eigenes Profil\): nicht verwendet .{1,4} Start/CDP') 'Ersatz-Browser gestartet und ferngesteuert' ''
Check ($t -match 'Chrome for Testing \(eigenes Profil\): nicht verwendet .{1,4} Anmeldung nicht pruefbar|keine ChatGPT-Anmeldung') 'Ersatz-Browser: Anmeldung geprueft (ohne Konto erwartungsgemaess keine)' ''
Start-Sleep -Seconds 5
$left = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
Check ($left -eq 0) 'Ersatz-Browser wieder geschlossen' ("Chrome-Prozesse: $left")

# 6. Deinstallation
$r = Run '12_uninstall' 'uninstall --silent --yes'
for ($i = 0; $i -lt 60 -and (Test-Path $app); $i++) { Start-Sleep -Seconds 2 }
Start-Sleep -Seconds 3
Check (-not (Test-Path $app)) 'Programmordner entfernt' ''
Check (-not (Test-Path $menu)) 'Startmenue entfernt' ''
Check (-not (Test-Path $desktop)) 'Desktop-Verknuepfung entfernt' ''
Check (-not (Test-Path 'HKCU:\Software\ChatExporter')) 'Registry-Schluessel entfernt' ''
$uninst = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | Where-Object { $_.PSChildName -like '*112F8EEC*' }).Count
Check ($uninst -eq 0) 'Eintrag unter Apps entfernt' ''
Check ((TaskCount) -eq 0) 'Aufgaben entfernt' ("Anzahl " + (TaskCount))
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
Check (-not ($userPath -like "*$app*")) 'PATH-Eintrag entfernt' ''
Check (Test-Path (Join-Path $home_dir 'config.yaml')) 'Daten-/Konfigurationsordner bleibt erhalten' $home_dir

Copy-Item (Join-Path $env:TEMP 'Setup Log*.txt') $out -ErrorAction SilentlyContinue
Add-Content -Path $res -Value ("Ende " + (Get-Date -Format s)) -Encoding UTF8
Set-Content -Path (Join-Path $out 'done.txt') -Value 'fertig' -Encoding UTF8
shutdown.exe /s /t 20
