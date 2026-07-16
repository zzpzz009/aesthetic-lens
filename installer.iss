; ============================================================
; AestheticLens — Inno Setup 安装脚本 (DiskSpanning 分卷)
; 编译: ISCC.exe installer.iss
; 产出: Output/AestheticLens_Setup.exe + Setup-*.bin (完整安装包)
; 包含: Python 依赖 + GPU DLL + 模型文件
; ============================================================

#define MyAppName "AestheticLens"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "AestheticLens"
#define SourceDir "dist\AestheticLens"

[Setup]
AppId={{A8F3C9E1-2B4D-4F6A-8E1C-5D7B9A3F6E2C}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; 输出
OutputDir=Output
OutputBaseFilename=AestheticLens_Setup
; 压缩 — 大文件 (GPU DLL/模型) 跳过压缩避免 ISCC 崩溃
Compression=none
; 界面
WizardStyle=modern
; 权限和系统
PrivilegesRequired=admin
MinVersion=6.1.7601
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; 主程序
Source: "{#SourceDir}\AestheticLens.exe"; DestDir: "{app}"; Flags: ignoreversion
; Python 依赖 + GPU DLL（nvidia/ 子目录通过 recursesubdirs 自动包含）
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; 模型文件
Source: "{#SourceDir}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\AestheticLens.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\AestheticLens.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AestheticLens.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup: Boolean;
begin
  Result := True;
  // WebView2 检测由 app.py 内置的 _check_webview2() 完成
end;
