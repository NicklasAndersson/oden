[Setup]
AppName=Oden
AppVersion={#MyAppVersion}
AppPublisher=Oden
DefaultDirName={localappdata}\Programs\Oden
DefaultGroupName=Oden
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Oden-Setup-{#MyAppVersion}-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\images\oden.ico
UninstallDisplayIcon={app}\Oden.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "swedish"; MessagesFile: "compiler:Languages\Swedish.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"
Name: "startup"; Description: "Start Oden when I log in"; Flags: checkedonce

[Files]
Source: "..\dist\Oden\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Oden"; Filename: "{app}\Oden.exe"
Name: "{group}\Uninstall Oden"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Oden"; Filename: "{app}\Oden.exe"; Tasks: desktopicon
Name: "{userstartup}\Oden"; Filename: "{app}\Oden.exe"; Tasks: startup

[Run]
Filename: "{app}\Oden.exe"; Description: "Launch Oden"; Flags: nowait postinstall skipifsilent
