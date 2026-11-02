# Wrapper to run the Rokomari pipeline daily
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$script = Join-Path $ProjectDir "rokomari_pipeline.py"
$timestamp = (Get-Date).ToString("yyyy-MM-dd_HH-mm-ss")
$logFile = Join-Path $ProjectDir "data\logs\rokomari_daily_$timestamp.log"
$errFile = Join-Path $ProjectDir "data\logs\rokomari_daily_$timestamp.err.log"

# Ensure logs directory exists
New-Item -ItemType Directory -Path (Join-Path $ProjectDir "data\logs") -Force | Out-Null

# Run the pipeline and capture stdout/stderr to separate files
& $python $script --scrape > $logFile 2> $errFile
