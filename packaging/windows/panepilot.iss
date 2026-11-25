; PanePilot – Windows-Setup (v3.0, L-4001). Wird von build.ps1 mit ISCC übersetzt:
;   ISCC /DAppVersion=3.0.0 /DSourceDir=…\dist\PanePilot /DIconFile=…\panepilot.ico /O…\dist panepilot.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3C2A8E-4D1B-4E7A-9C55-8B2E1F0A7D31}
AppName=PanePilot
AppVersion={#AppVersion}
AppVerName=PanePilot {#AppVersion}
AppPublisher=PanePilot
AppPublisherURL=https://github.com/NEA1971/PanePilot
AppSupportURL=https://github.com/NEA1971/PanePilot/issues
AppUpdatesURL=https://github.com/NEA1971/PanePilot/releases
DefaultDirName={autopf}\PanePilot
DefaultGroupName=PanePilot
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=PanePilot-{#AppVersion}-windows-x64-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\PanePilot.exe
UninstallDisplayName=PanePilot
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; alte Programmdateien entfernen, damit nach einem Update nichts Veraltetes liegen bleibt
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\PanePilot"; Filename: "{app}\PanePilot.exe"
Name: "{autodesktop}\PanePilot"; Filename: "{app}\PanePilot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PanePilot.exe"; Description: "{cm:LaunchProgram,PanePilot}"; Flags: nowait postinstall skipifsilent
