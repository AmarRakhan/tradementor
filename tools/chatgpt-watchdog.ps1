param(
    [ValidateRange(15, 3600)]
    [int]$CheckIntervalSeconds = 30,

    [ValidateRange(1, 60)]
    [int]$UnresponsiveChecksBeforeRestart = 3,

    [ValidateRange(1, 100)]
    [int]$MaximumChatGPTProcesses = 20,

    [switch]$RestartChatGPT
)

$ErrorActionPreference = 'Stop'
$state = @{}
$logRoot = Join-Path $env:LOCALAPPDATA 'TradeMentor\Watchdog'
$logFile = Join-Path $logRoot 'chatgpt-watchdog.log'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Write-WatchdogLog {
    param([string]$Message)
    $line = '{0:u} {1}' -f (Get-Date), $Message
    Add-Content -LiteralPath $logFile -Value $line
    Write-Host $line
}

function Start-ChatGPTApp {
    try {
        Start-Process 'shell:AppsFolder\OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0!App'
        Write-WatchdogLog 'ChatGPT opnieuw gestart.'
    }
    catch {
        Write-WatchdogLog "ChatGPT kon niet automatisch worden gestart: $($_.Exception.Message)"
    }
}

Write-WatchdogLog "Watchdog gestart; interval=${CheckIntervalSeconds}s, limiet=$MaximumChatGPTProcesses processen."

while ($true) {
    try {
        $processes = @(Get-Process -Name 'ChatGPT', 'codex' -ErrorAction SilentlyContinue)
        $liveIds = @($processes | ForEach-Object { $_.Id })

        foreach ($knownId in @($state.Keys)) {
            if ($liveIds -notcontains [int]$knownId) {
                $state.Remove($knownId)
            }
        }

        foreach ($process in $processes) {
            if ($process.Responding) {
                $state[$process.Id] = 0
                continue
            }

            $previousCount = if ($state.ContainsKey($process.Id)) { [int]$state[$process.Id] } else { 0 }
            $state[$process.Id] = 1 + $previousCount
            Write-WatchdogLog "$($process.ProcessName) PID $($process.Id) reageert niet ($($state[$process.Id])/$UnresponsiveChecksBeforeRestart)."

            if ($state[$process.Id] -ge $UnresponsiveChecksBeforeRestart) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                $state.Remove($process.Id)
                Write-WatchdogLog "$($process.ProcessName) PID $($process.Id) na herhaalde controles afgesloten."
            }
        }

        $chatGptProcesses = @($processes | Where-Object ProcessName -eq 'ChatGPT')
        if ($chatGptProcesses.Count -gt $MaximumChatGPTProcesses) {
            Write-WatchdogLog "Waarschuwing: $($chatGptProcesses.Count) ChatGPT-processen actief; er worden geen reagerende processen automatisch gesloten."
        }

        if ($RestartChatGPT -and -not (Get-Process -Name 'ChatGPT' -ErrorAction SilentlyContinue)) {
            Start-Sleep -Seconds 2
            Start-ChatGPTApp
        }
    }
    catch {
        Write-WatchdogLog "Controlefout: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $CheckIntervalSeconds
}
