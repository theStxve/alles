; Inno Setup script for ALLES
; Build:  iscc /DAppVersion=2.1.0 installer\alles.iss   (after building dist\ALLES.exe)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "ALLES"
#define AppExe "ALLES.exe"
#define AppUrl "https://github.com/theStxve/alles"

[Setup]
AppId={{6F1E4C3A-9B57-4E1D-A7C2-0D5B8E2F11A1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=theStxve
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppComments=Blitzschnelle Dateisuche für Windows – mit Everything oder eigenem Index
; per-user install by default (no admin rights needed), all users optional
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ALLES-Setup-{#AppVersion}
SetupIconFile=..\assets\alles.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; ask the user to close a running ALLES (single-instance mutex of the app)
AppMutex=Local\ALLES_SingleInstance
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
LicenseFile=..\LICENSE

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.TaskExplorer=„Mit ALLES durchsuchen“ im Explorer-Kontextmenü
en.TaskExplorer=Add "Search with ALLES" to the Explorer context menu
de.TaskAutostart=ALLES mit Windows starten (im Tray)
en.TaskAutostart=Start ALLES with Windows (in the tray)
de.ExplorerLabel=Mit ALLES durchsuchen
en.ExplorerLabel=Search with ALLES
de.GroupIntegration=Windows-Integration:
en.GroupIntegration=Windows integration:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "explorer"; Description: "{cm:TaskExplorer}"; GroupDescription: "{cm:GroupIntegration}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:GroupIntegration}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Dateisuche"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Explorer context menu (folders, folder background, drives) - per user
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ALLES"; ValueType: string; ValueName: ""; ValueData: "{cm:ExplorerLabel}"; Tasks: explorer; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ALLES"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: explorer
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ALLES\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --folder ""%V"""; Tasks: explorer
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ALLES"; ValueType: string; ValueName: ""; ValueData: "{cm:ExplorerLabel}"; Tasks: explorer; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ALLES"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: explorer
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ALLES\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --folder ""%V"""; Tasks: explorer
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ALLES"; ValueType: string; ValueName: ""; ValueData: "{cm:ExplorerLabel}"; Tasks: explorer; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ALLES"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: explorer
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ALLES\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --folder ""%V"""; Tasks: explorer
; Autostart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ALLES"; ValueData: """{app}\{#AppExe}"" --tray"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; also removes integrations the user switched on later inside the app
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall-cleanup"; Flags: runhidden waituntilterminated; RunOnceId: "Cleanup"
