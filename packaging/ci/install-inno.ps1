$ErrorActionPreference = 'Stop'
$installer = Join-Path $env:RUNNER_TEMP 'innosetup-6.7.3.exe'
$directory = Join-Path $env:RUNNER_TEMP 'InnoSetup6'
Invoke-WebRequest 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installer
$expected = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'Inno Setup checksum mismatch'
}
$process = Start-Process -FilePath $installer -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/NOICONS', ('/DIR="' + $directory + '"'))
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $directory 'ISCC.exe'))) {
    throw 'Inno Setup installation failed'
}
$directory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
