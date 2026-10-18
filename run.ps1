param(
    [switch]$Lan,
    [ValidateRange(1,65535)][int]$Port=8000,
    [switch]$OpenBrowser,
    [switch]$InstallOnly
)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$root=$PSScriptRoot
$python=Join-Path $root '.venv\Scripts\python.exe'
$lock=Join-Path $root 'requirements.lock.txt'
try {
    if(-not(Test-Path -LiteralPath $python)){
        $base='D:\ProgramData\anaconda3\python.exe'
        if(Test-Path -LiteralPath $base){ & $base -m venv (Join-Path $root '.venv') }
        elseif(Test-Path -LiteralPath 'C:\WINDOWS\py.exe'){ & 'C:\WINDOWS\py.exe' -3 -m venv (Join-Path $root '.venv') }
        else { throw '找不到 Python。请安装 Python 3.11 或更新版本后重新运行。' }
        if($LASTEXITCODE -ne 0){ throw '创建独立虚拟环境失败。' }
    }
    & $python -c "import sys; assert sys.version_info >= (3,11), '需要 Python 3.11 或更新版本'"
    if($LASTEXITCODE -ne 0){ throw '当前 Python 版本不符合要求。' }
    $hash=(Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
    $marker=Join-Path $root '.venv\.requirements-sha256'
    if(-not(Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $hash){
        Write-Host '正在准备项目独立环境（首次安装需要联网）…' -ForegroundColor Cyan
        & $python -m pip install --disable-pip-version-check -r $lock
        if($LASTEXITCODE -ne 0){ throw '依赖安装失败。请检查网络，不要向 Conda 基础环境安装。' }
        Set-Content -LiteralPath $marker -Value $hash -Encoding ascii
    }
    if($InstallOnly){Write-Host '独立环境已就绪。' -ForegroundColor Green;exit 0}
    $arguments=@((Join-Path $root 'scripts\serve.py'),'--port',"$Port")
    if($Lan){$arguments+='--lan'}
    if($OpenBrowser){$arguments+='--open-browser'}
    & $python @arguments
    if($LASTEXITCODE -ne 0){throw '应用启动失败或异常停止。请查看上方信息。'}
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
