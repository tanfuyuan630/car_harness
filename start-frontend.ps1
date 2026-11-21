<#
    启动前端开发服务器（Vue3 + Vite）
    用法：
        .\start-frontend.ps1               # 默认 127.0.0.1:5173
        .\start-frontend.ps1 -Port 5174    # 指定端口
#>
param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $root "frontend"
if (-not (Test-Path $frontendDir)) { throw "未找到前端目录：$frontendDir" }

Push-Location $frontendDir
try {
    # 首次运行时自动安装依赖
    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        Write-Host "首次运行，安装前端依赖..." -ForegroundColor Yellow
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install 执行失败" }
    }

    Write-Host "前端启动中：http://127.0.0.1:$Port" -ForegroundColor Green
    npm run dev -- --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
}
