; Inno Setup 6 – Installer fuer ChatExporter (pro Benutzer, ohne Administratorrechte).
;
; Aufruf ueber packaging\build.py, sonst:
;   ISCC.exe /DAppVersion=0.0.1rc3 /DSourceDir=<dist>\ChatExporter /O<ziel> chatexporter.iss
;
; - installiert nach %LOCALAPPDATA%\Programs\ChatExporter (nur das gebaute Programm)
; - Daten, config.yaml, .env und Protokolle liegen NICHT im Programmordner,
;   sondern in %USERPROFILE%\.chatexporter und bleiben bei der Deinstallation erhalten
; - am Ende optional: Einrichtung (chatexporter setup)
; - Deinstallation: entfernt alle eigenen Windows-Aufgaben (task delete --all)
;   und den Registry-Spiegel HKCU\Software\ChatExporter
; - nicht signiert (private Nutzung); Windows SmartScreen kann deshalb warnen

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error "SourceDir fehlt (/DSourceDir=<dist>\ChatExporter)"
#endif

#define AppName "ChatExporter"
#define AppExe "chatexporter.exe"

[Setup]
AppId={{112F8EEC-58F3-4EFC-8740-C48CAC6BCC3B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=marcosudau-vps
AppPublisherURL=https://github.com/marcosudau-vps/chat_exporter
AppSupportURL=https://github.com/marcosudau-vps/chat_exporter/issues
AppUpdatesURL=https://github.com/marcosudau-vps/chat_exporter/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=ChatExporter-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\IconChatExporter.ico
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExe},0
UninstallDisplayName={#AppName}
ChangesEnvironment=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "path"; Description: "Befehl 'chatexporter' in der Eingabeaufforderung verfügbar machen (Benutzer-PATH)"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\ChatExporter"; Filename: "{app}\{#AppExe}"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\{#AppExe}"; IconIndex: 0; Comment: "Menü"
Name: "{group}\ChatExporter"; Filename: "{app}\{#AppExe}"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\{#AppExe}"; IconIndex: 0; Comment: "Menü"
Name: "{group}\ChatExporter – Einrichtung"; Filename: "{app}\{#AppExe}"; Parameters: "setup"; WorkingDir: "{%USERPROFILE}"; IconFilename: "{app}\{#AppExe}"; IconIndex: 0
Name: "{group}\Datenordner öffnen"; Filename: "{%USERPROFILE}\.chatexporter"
Name: "{group}\ChatExporter deinstallieren"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#AppExe}"; IconIndex: 0

[Registry]
; Nur damit der Schluessel bei der Deinstallation entfernt wird (Spiegel der Konfiguration).
Root: HKCU; Subkey: "Software\ChatExporter"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: path; Check: NeedsAddPath(ExpandConstant('{app}'))

[Dirs]
Name: "{%USERPROFILE}\.chatexporter"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "setup"; WorkingDir: "{%USERPROFILE}"; Description: "Einrichtung jetzt starten (Browser/ChatGPT-Anmeldung, täglicher Abruf)"; Flags: postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "uninstall --remove-tasks --yes"; WorkingDir: "{%USERPROFILE}"; RunOnceId: "DeleteTasks"; Flags: runhidden waituntilterminated

[UninstallDelete]
; Programmordner vollstaendig (z. B. __pycache__); Benutzerdaten liegen woanders.
Type: filesandordirs; Name: "{app}"

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') = 0;
end;

procedure RemovePath(Dir: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Paths) then
    exit;
  P := Pos(';' + Uppercase(Dir), ';' + Uppercase(Paths));
  if P = 0 then
    exit;
  { P zeigt auf das ';' vor Dir in ';'+Paths, also auf Dir-1 in Paths }
  if P = 1 then
    Delete(Paths, 1, Length(Dir) + 1)
  else
    Delete(Paths, P - 1, Length(Dir) + 1);
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Paths);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;
