' AzurPilot 无窗口托盘启动器
' 双击本文件：后台启动 WebUI + 系统托盘图标（无任何窗口）
' 退出：右键托盘图标 → 退出 AzurPilot
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Run ".venv\Scripts\pythonw.exe """ & root & "\launcher_tray.py""", 0, False
