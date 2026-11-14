; Inno Setup script for JK BMS Monitor (JkBmsWidget).
; Built by build.ps1, which passes /DAppVersion=x.y.z and expects the
; PyInstaller one-folder build in dist\JkBmsWidget\.
;
; Per-user install, no administrator rights:
;   program  -> %LOCALAPPDATA%\Programs\JkBmsWidget
;   settings -> %APPDATA%\JkBmsWidget (written by the app, kept on uninstall
;               so a reinstall keeps the chart history)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "JK BMS Monitor"
#define AppExe "JkBmsWidget.exe"

[Setup]
; Fixed AppId: lets a newer setup update an existing install in place.
AppId={{6B0E4C1F-7A35-4E61-9C4B-2F1D8A93B7E2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=linux2020l
AppPublisherURL=https://github.com/linux2020l/JkBMS-PC-Monitor
AppSupportURL=https://github.com/linux2020l/JkBMS-PC-Monitor/issues
DefaultDirName={autopf}\JkBmsWidget
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
OutputBaseFilename=JkBmsWidget-Setup-{#AppVersion}
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
Source: "..\dist\JkBmsWidget\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value the app's own "Start with Windows" setting uses (autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JkBmsWidget"; ValueData: """{app}\{#AppExe}"" --autostart"; Tasks: autostart; Flags: uninsdeletevalue
; Without the task: still remove the value on uninstall (the app may have set it).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "JkBmsWidget"; Flags: uninsdeletevalue dontcreatekey

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
  Result := '';
end;
