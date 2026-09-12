; installer.iss -- Inno Setup script for Review Panel
; Requires: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Run this from packaging/ AFTER build.bat has produced dist\ReviewPanel.exe

#define AppName "Review Panel"
; Version source: src/core.py::__version__ — update together when bumping.
#define AppVersion "2.1.2"
#define AppPublisher "altugkanbakan"
#define AppExeName "ReviewPanel.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/altugkanbakan
DefaultDirName={autopf}\ReviewPanel
DefaultGroupName={#AppName}
OutputDir=installer_output
OutputBaseFilename=ReviewPanel-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Main executable (built by PyInstaller — already contains llmfit.exe inside)
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";             Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";  Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";    Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
