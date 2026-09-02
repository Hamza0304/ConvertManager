#define MyAppName "ConvertManager"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Hamza Senhaji"
#define MyAppExeName "ConvertManager.exe"

[Setup]
AppId={{8B9E9E52-8A9F-4C6D-9D2B-5D7F3A4C91E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

OutputDir=installer
OutputBaseFilename=ConvertManager-Setup

Compression=lzma
SolidCompression=yes
WizardStyle=modern

ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\ConvertManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent