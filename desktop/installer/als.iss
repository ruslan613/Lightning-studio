; AI Lighting Studio — Inno Setup 6 script.
; Источник: electron-builder unpacked dir (desktop/dist/win-unpacked) — собирается `npx electron-builder --win dir --x64`.
; Компиляция: iscc /DAppVersion=0.5.0 desktop\installer\als.iss   →  desktop\dist\AI-Lighting-Studio-<ver>-inno-setup.exe
; Данные пользователя НЕ в Program Files: Electron пишет в %APPDATA%\AI Lighting Studio\data (ALS_DATA_DIR из main.js).

#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\win-unpacked"
#endif
#define AppName "AI Lighting Studio"
#define AppExe "AI Lighting Studio.exe"
#define AppPublisher "Gilil"

[Setup]
AppId={{8C1B5E7A-4F2D-4B8E-9A61-6E3C2D9F0A55}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AI-Lighting-Studio-{#AppVersion}-inno-setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.AssocAlsproj=Открывать файлы проектов .alsproj в {#AppName}
english.AssocAlsproj=Open .alsproj project files with {#AppName}
russian.KeepData=Пользовательские проекты в %APPDATA%\{#AppName} сохранены. Удалите папку вручную, если они не нужны.
english.KeepData=User projects in %APPDATA%\{#AppName} were kept. Delete the folder manually if not needed.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "{cm:AssocAlsproj}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.alsproj"; ValueType: string; ValueName: ""; ValueData: "AILightingStudio.Project"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AILightingStudio.Project"; ValueType: string; ValueName: ""; ValueData: "AI Lighting Studio Project"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AILightingStudio.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\AILightingStudio.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\resources\python\Lib\site-packages\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{userappdata}\{#AppName}')) and not UninstallSilent then
    MsgBox(CustomMessage('KeepData'), mbInformation, MB_OK);
end;
