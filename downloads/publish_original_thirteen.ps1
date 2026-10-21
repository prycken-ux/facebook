[CmdletBinding()]
param(
    [ValidateSet('off', 'on', 'configured')]
    [string]$AiLabel = 'off'
)

$ErrorActionPreference = 'Stop'
$fbRoot = $PSScriptRoot
$fbPython = Join-Path $fbRoot '.venv\Scripts\python.exe'
$fbBatch = Join-Path $fbRoot 'batch_upload.py'
$fbCaptionTool = Join-Path $fbRoot 'apply_common_caption.py'
$fbCaptionFile = Join-Path $fbRoot 'common_caption_today.txt'
$fbJobs = @(
    'fb01/page01', 'fb02/page01', 'fb03/personal', 'fb04/personal',
    'fb05/page01', 'fb06/page01', 'fb07/personal', 'fb08/personal',
    'fb09/personal', 'fb10/personal', 'fb11/personal', 'fb12/page01', 'fb13/page01'
)
$fbAccounts = (($fbJobs | ForEach-Object { ($_ -split '/')[0] }) -join ',')
$fbTargets = $fbJobs -join ','

foreach ($fbRequired in @($fbPython, $fbBatch, $fbCaptionTool, $fbCaptionFile)) {
    if (-not (Test-Path -LiteralPath $fbRequired -PathType Leaf)) {
        throw "Missing required file: $fbRequired"
    }
}
if ([string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $fbCaptionFile -Raw -Encoding UTF8))) {
    throw 'Saved common caption is empty. Stopped before publication.'
}

Write-Host '本轮：原来的 13 个目标；fb10 仅个人主页。每个目标最多发布一条新视频。'
Write-Host "使用已保存文案：$fbCaptionFile；本轮 AI 标签：$AiLabel"
& $fbPython $fbBatch plan "--accounts=$fbAccounts" "--targets=$fbTargets"
if ($LASTEXITCODE -ne 0) { throw 'Target validation failed. Stopped before publication.' }

& $fbPython $fbCaptionTool "--accounts=$fbAccounts" "--targets=$fbTargets" --text-file $fbCaptionFile
if ($LASTEXITCODE -ne 0) { throw 'Caption preparation failed. Stopped before publication.' }

Write-Host '文案处理完成，等待 65 秒让文件稳定，然后开始逐个发布。'
Start-Sleep -Seconds 65
$fbResults = @()
foreach ($fbJob in $fbJobs) {
    $fbParts = $fbJob -split '/'
    $fbAccount = $fbParts[0]
    Write-Host "正在处理：$fbJob"
    $fbArguments = @($fbBatch, 'publish', "--accounts=$fbAccount", "--targets=$fbJob", '--continue-on-review')
    if ($AiLabel -ne 'configured') {
        $fbArguments += @('--ai-label', $AiLabel)
    }
    & $fbPython @fbArguments
    $fbCode = $LASTEXITCODE
    $fbResults += [pscustomobject]@{ Target = $fbJob; ExitCode = $fbCode }
    if ($fbCode -ne 0) {
        Write-Host "$fbJob 需要检查，保留任务记录，继续下一个目标。"
    }
}
$fbResults | Format-Table -AutoSize
Write-Host '本轮尝试结束。返回 0 也可能是没有新视频；实际发布结果以 logs\publish_state.json 和 Facebook 页面为准。'
Write-Host '待核对及失败记录未重置，不要直接重复发布。'
if (@($fbResults | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) { exit 1 }
exit 0
