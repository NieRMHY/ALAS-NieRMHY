' Generate AzurPilot desktop shortcut with custom icon.
' Run this script once to create AzurPilot.lnk in the project root,
' then copy/move AzurPilot.lnk to Desktop, Taskbar or anywhere to launch.
'
' Launch path: pythonw launcher_tray.py
'   pythonw has no console window, so the shortcut starts the tray launcher
'   directly (no VBS middleman) and runs windowless in the background.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")
q = Chr(34)

lnkPath = root & "\AzurPilot.lnk"
Set lnk = ws.CreateShortcut(lnkPath)
lnk.TargetPath = root & "\.venv\Scripts\pythonw.exe"
lnk.Arguments = q & root & "\launcher_tray.py" & q
lnk.WorkingDirectory = root
lnk.IconLocation = root & "\deploy\launcher\icon.ico,0"
lnk.Description = "AzurPilot WebUI"
lnk.WindowStyle = 1
lnk.Save

WScript.Echo "Created shortcut: " & lnkPath
