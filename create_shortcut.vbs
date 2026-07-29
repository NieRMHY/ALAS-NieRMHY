' 生成 AzurPilot 桌面快捷方式（带图标）
' 双击本脚本一次，会在项目根目录生成 AzurPilot.lnk，
' 可将其复制/移动到桌面、任务栏或任意位置双击启动。
'
' 启动方式：pythonw launcher_tray.py（无窗口后台运行 + 系统托盘图标）
' 快捷方式直接指向 pythonw，无需 VBS 中间层。
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")

lnkPath = root & "\AzurPilot.lnk"
Set lnk = ws.CreateShortcut(lnkPath)
lnk.TargetPath = root & "\.venv\Scripts\pythonw.exe"
lnk.Arguments = """" & root & "\launcher_tray.py"""
lnk.WorkingDirectory = root
lnk.IconLocation = root & "\deploy\launcher\icon.ico,0"
lnk.Description = "AzurPilot WebUI 托盘启动器"
lnk.WindowStyle = 1
lnk.Save

WScript.Echo "已创建快捷方式: " & lnkPath & vbCrLf & vbCrLf & _
              "可将 AzurPilot.lnk 复制到桌面或任意位置，双击即可启动。"
