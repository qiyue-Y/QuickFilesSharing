# QuickFilesSharing 本地快速启动脚本
# 用法：双击桌面快捷方式，或在项目根目录执行  powershell -ExecutionPolicy Bypass -File .\start.ps1
# 行为：用 uv 同步环境并前台启动 waitress；日志实时打印在本窗口，同时落 logs\app.log
# 停止：按 Ctrl+C，或直接关闭本窗口

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host "=== QuickFilesSharing 启动中 (uv run) ===" -ForegroundColor Cyan
Write-Host "项目目录: $PSScriptRoot"
Write-Host "服务端口: 5000   关闭本窗口即停止服务"
Write-Host ""

uv run python http_messages_share.py

Write-Host ""
Write-Host "=== 服务进程已退出 (exit code: $LASTEXITCODE) ===" -ForegroundColor Yellow
Read-Host "按回车键关闭此窗口"