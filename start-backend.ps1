<#
    启动后端服务（FastAPI + Uvicorn）
    用法：
        .\start-backend.ps1               # 默认 127.0.0.1:8000
        .\start-backend.ps1 -Port 8001    # 指定端口
        .\start-backend.ps1 -Reload       # 开发热重载
#>
param(
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
if (-not (Test-Path $backendDir)) { throw "未找到后端目录：$backendDir" }

# 首次运行时由模板生成 .env
$envFile = Join-Path $backendDir ".env"
$envTemplate = Join-Path $backendDir ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envTemplate $envFile
    Write-Host "已根据 .env.example 生成 .env，请先填写 OPENAI_API_KEY 后重新启动" -ForegroundColor Yellow
    exit 1
}

# 解析 Python 解释器：PYTHON_EXE > pyenv exec python > python
$launcher = if ($env:PYTHON_EXE -and (Test-Path $env:PYTHON_EXE)) { @($env:PYTHON_EXE) }
            elseif (Get-Command pyenv -ErrorAction SilentlyContinue) { @("pyenv", "exec", "python") }
            else { @("python") }
$exe = $launcher[0]
$preArgs = @($launcher | Select-Object -Skip 1)

$uvicornArgs = $preArgs + @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port")
if ($Reload) { $uvicornArgs += "--reload" }

Write-Host "后端启动中：http://127.0.0.1:$Port  接口文档：http://127.0.0.1:$Port/docs" -ForegroundColor Green
Push-Location $backendDir
try {
    & $exe @uvicornArgs
} finally {
    Pop-Location
}
