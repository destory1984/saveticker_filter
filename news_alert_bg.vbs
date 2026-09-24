' Run news_alert.bat with no window. Log: news_alert.log / stop: news_alert_stop.bat
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "cmd /c """ & dir & "\news_alert.bat""", 0, False
