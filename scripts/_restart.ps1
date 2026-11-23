$procs = Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*-m app*' }
foreach ($p in $procs) {
    Write-Output ("killing pid=" + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force
}
Start-Sleep -Seconds 2
Start-Process -FilePath 'C:\Users\TABURISS\AppData\Roaming\kimi-desktop\daimon-share\daimon\runtime\python\.venv\Scripts\pythonw.exe' `
    -ArgumentList '-m','app','--set-video','E:\LiveWallpaper\405bed4e8afb4596be7dc18860928e0f.mp4' `
    -WorkingDirectory 'C:\Users\TABURISS\Documents\kimi\tasks\2026-11-23\10-36-57-0b99d73b\MeWallpaper'
Write-Output "started"
