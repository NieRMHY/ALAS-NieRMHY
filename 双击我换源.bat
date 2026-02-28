@echo off
:: 设置控制台为 UTF-8 编码，解决中文显示问题
chcp 65001 >nul
title Alas 部署文件自动更新

:: 设置下载链接
set "URL=https://alas.nanoda.work/data/deploy.yaml"

:: 获取当前脚本所在目录
set "BASE_DIR=%~dp0"
set "CONFIG_DIR=%BASE_DIR%config"
set "TOOLKIT_DIR=%BASE_DIR%toolkit"
set "WEBAPP_DIR=%BASE_DIR%webapp"
set "DEST_FILE=%CONFIG_DIR%\deploy.yaml"

echo ============================================
echo         Alas 自动更新脚本 (deploy.yaml)
echo ============================================
echo.

:: --- 环境检查 ---
echo [1/3] 正在检查运行环境...
set "CHECK_FAILED=0"

if not exist "%TOOLKIT_DIR%\" (
    echo [错误] 找不到 toolkit 文件夹！
    set "CHECK_FAILED=1"
)
if not exist "%WEBAPP_DIR%\" (
    echo [错误] 找不到 webapp 文件夹！
    set "CHECK_FAILED=1"
)

if "%CHECK_FAILED%"=="1" (
    echo.
    echo ❌ 错误：请将此脚本放在 Alas 根目录下运行（与 toolkit 和 webapp 文件夹同级）。
    echo 脚本将退出。
    echo.
    pause
    exit /b
)
echo [确认] toolkit 和 webapp 文件夹已找到。

:: --- 检查并创建 config 目录 ---
echo [2/3] 正在检查目录结构...
if not exist "%CONFIG_DIR%\" (
    mkdir "%CONFIG_DIR%"
    echo 已创建 config 文件夹。
) else (
    echo [确认] config 文件夹已存在。
)

:: --- 执行下载 ---
echo [3/3] 正在从远程服务器下载并覆盖...
echo 下载地址: %URL%

:: 使用 curl 下载。-k 忽略证书校验，-L 处理重定向，-s 静默模式，-o 指定保存路径
curl -k -L -o "%DEST_FILE%" "%URL%"

:: --- 结果判断 ---
if %errorlevel% equ 0 (
    echo.
    echo ✅ [成功] deploy.yaml 已成功下载并覆盖到 config 目录下！
) else (
    echo.
    echo ❌ [失败] 下载过程中出现错误。
    echo 请检查：
    echo 1. 网络连接是否正常
    echo 2. 网址 %URL% 是否能在浏览器打开
)

echo.
echo ============================================
pause