@echo off
title 删除当前目录的 .git 文件夹
color 0A

:: 切换到脚本所在的目录
cd /d "%~dp0"

echo 准备检查并删除当前目录下的 .git 文件夹...
echo 当前目录: %~dp0
echo 正在修复...
echo.

:: 检查 .git 文件夹是否存在
if exist ".git\" (
    echo 发现 .git 文件夹，正在解除隐藏和只读属性...
    :: 移除隐藏(H)、只读(R)和系统(S)属性，防止 rmdir 删除失败
    attrib -R -S -H ".git\*.*" /S /D >nul 2>&1
    
    echo 正在强制删除...
    rmdir /S /Q ".git"
    
    :: 再次检查是否删除成功
    if exist ".git\" (
        echo [失败] 删除未能成功，可能是因为某些文件正被其他程序占用。
    ) else (
        echo [成功] .git 文件夹已彻底删除 请尝试重新启动Alas.exe！
    )
) else (
    echo [提示] 当前目录下未找到 .git 文件夹，无需清理。
)

echo.
pause