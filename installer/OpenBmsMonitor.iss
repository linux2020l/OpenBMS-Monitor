; Inno Setup script for OpenBMS Monitor (formerly JK BMS Monitor / JkBmsWidget).
; Built by build.ps1, which passes /DAppVersion=x.y.z and expects the
; PyInstaller one-folder build in dist\OpenBmsMonitor\.
;
; Per-user install, no administrator rights:
;   program  -> %LOCALAPPDATA%\Programs\OpenBmsMonitor
;   settings -> %APPDATA%\OpenBmsMonitor (written by the app, kept on uninstall
;               so a reinstall keeps the chart history; the app moves the old
;               %APPDATA%\JkBmsWidget folder there on its first start)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "OpenBMS Monitor"
#define AppExe "OpenBmsMonitor.exe"
; Before the rename (v0.8.0): removed on update so no old copy stays behind.
#define OldExe "JkBmsWidget.exe"
#define OldName "JK BMS Monitor"

[Setup]
; Fixed AppId (kept through the rename): a newer setup replaces the old install.
AppId={{6B0E4C1F-7A35-4E61-9C4B-2F1D8A93B7E2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=linux2020l
AppPublisherURL=https://github.com/linux2020l/OpenBMS-Monitor
AppSupportURL=https://github.com/linux2020l/OpenBMS-Monitor/issues
DefaultDirName={autopf}\OpenBmsMonitor
; Old installs live in ...\JkBmsWidget: always use the new folder.
UsePreviousAppDir=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Python 3.12 + PySide6 builds are 64-bit; bleak's WinRT backend needs
; Windows 10 1709 (build 16299) or newer.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.16299
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=OpenBmsMonitor-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
LicenseFile=..\LICENSE

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[CustomMessages]
en.AutostartTask=Start {#AppName} with Windows
uk.AutostartTask=Запускати {#AppName} разом з Windows
en.LaunchApp=Launch {#AppName}
uk.LaunchApp=Запустити {#AppName}

[Tasks]
Name: "autostart"; Description: "{cm:AutostartTask}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\OpenBmsMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Files of the previous version: [Files] only overwrites, so a DLL that a
; newer build no longer ships would stay behind forever. The folder holds
; nothing but the program (settings and history live in %APPDATA%).
Type: filesandordirs; Name: "{app}\_internal"
; Leftovers of the version before the rename (program folder, shortcuts).
Type: filesandordirs; Name: "{autopf}\JkBmsWidget"
Type: files; Name: "{autoprograms}\{#OldName}.lnk"
Type: files; Name: "{autodesktop}\{#OldName}.lnk"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value the app's own "Start with Windows" setting uses (autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OpenBmsMonitor"; ValueData: """{app}\{#AppExe}"" --autostart"; Tasks: autostart; Flags: uninsdeletevalue
; Without the task: still remove the value on uninstall (the app may have set it).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "OpenBmsMonitor"; Flags: uninsdeletevalue dontcreatekey
; The value used before the rename would start a program that no longer exists.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "JkBmsWidget"; Flags: deletevalue dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; The widget has no window to close: stop it so its files can be removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
// Stop a running copy before files are replaced (update over an old version).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  // The version before the rename (its files are removed by [InstallDelete]).
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#OldExe}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
