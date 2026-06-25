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

[Code]
var
	RemoveAllUserData: Boolean;

function GetOdenHomeFromPointer(): string;
var
	PointerPath: string;
	Content: AnsiString;
begin
	Result := '';
	PointerPath := ExpandConstant('{userappdata}\Oden\oden_home.txt');

	if LoadStringFromFile(PointerPath, Content) then
	begin
		Content := Trim(Content);
		if Content <> '' then
			Result := RemoveBackslashUnlessRoot(Content);
	end;
end;

function IsSafeDirectoryToDelete(const DirPath: string): Boolean;
var
	Normalized: string;
begin
	Normalized := RemoveBackslashUnlessRoot(Trim(DirPath));

	if (Normalized = '') or (Normalized = '\\') or (Length(Normalized) <= 3) then
	begin
		Result := False;
		exit;
	end;

	Result := DirExists(Normalized);
end;

procedure DeleteDirectoryIfSafe(const DirPath: string);
begin
	if IsSafeDirectoryToDelete(DirPath) then
	begin
		if DelTree(DirPath, True, True, True) then
			Log(Format('Removed user data directory: %s', [DirPath]))
		else
			Log(Format('Failed to remove user data directory: %s', [DirPath]));
	end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
	OdenHome: string;
begin
	if CurUninstallStep = usUninstall then
	begin
		RemoveAllUserData :=
			MsgBox(
				'Also remove all Oden user data?' + #13#10 + #13#10 +
				'This deletes config.db, signal-data, logs, and signal-cli local data.',
				mbConfirmation,
				MB_YESNO or MB_DEFBUTTON2
			) = IDYES;
	end;

	if (CurUninstallStep = usPostUninstall) and RemoveAllUserData then
	begin
		OdenHome := GetOdenHomeFromPointer();
		if OdenHome = '' then
			OdenHome := ExpandConstant('{%USERPROFILE}\.oden');

		DeleteDirectoryIfSafe(OdenHome);
		DeleteDirectoryIfSafe(ExpandConstant('{userappdata}\Oden'));
		DeleteDirectoryIfSafe(ExpandConstant('{localappdata}\Oden'));
		DeleteDirectoryIfSafe(ExpandConstant('{localappdata}\signal-cli'));
		DeleteDirectoryIfSafe(ExpandConstant('{%USERPROFILE}\.local\share\signal-cli'));
	end;
end;
