# =============================================================================
# Celery Workers Startup Script for Windows
# =============================================================================
# Usage: .\start_workers.ps1
# This script starts 2 specialized Celery workers with thread pool for parallel execution

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Starting Celery Workers with Thread Pool (Windows Compatible)  " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
$venvPath = "E:\WorkSpace\Graduation Project\Project\Grader\venv-grader"
$celeryExe = "$venvPath\Scripts\celery.exe"

if (-not (Test-Path $celeryExe)) {
    Write-Host "ERROR: Celery not found at $celeryExe" -ForegroundColor Red
    Write-Host "Please install: pip install celery redis flower kombu" -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting workers..." -ForegroundColor Green
Write-Host ""

# Start Doc worker (3 concurrent threads) — handles RAG + LLM + default
Write-Host "[1/2] Starting Doc worker (queue: rag,llm,celery,default, concurrency: 3)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$venvPath\Scripts\Activate.ps1'; & '$celeryExe' -A backend.celery_app worker -Q rag,llm,celery,default --pool=threads -c 3 --loglevel=INFO -n doc@%COMPUTERNAME%"
) -WindowStyle Normal

Start-Sleep -Seconds 2

# Start Canvas worker (4 concurrent threads — unchanged)
Write-Host "[2/2] Starting Canvas worker (queue: canvas, concurrency: 4)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$venvPath\Scripts\Activate.ps1'; & '$celeryExe' -A backend.celery_app worker -Q canvas --pool=threads -c 4 --loglevel=INFO -n canvas@%COMPUTERNAME%"
) -WindowStyle Normal

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host "  All workers started successfully!                              " -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Total capacity: 7 concurrent tasks (3+4)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Worker details:" -ForegroundColor White
Write-Host "  - Doc worker    : 3 threads (RAG indexing, quiz generation, default tasks)" -ForegroundColor Gray
Write-Host "  - Canvas worker : 4 threads (Canvas API operations)" -ForegroundColor Gray
Write-Host ""
Write-Host "Monitoring:" -ForegroundColor White
Write-Host "  - Flower: http://localhost:5555 (run: celery -A backend.celery_app flower)" -ForegroundColor Gray
Write-Host "  - Jobs API: http://localhost:8000/api/jobs" -ForegroundColor Gray
Write-Host ""
Write-Host "To stop workers: Close the PowerShell windows or press Ctrl+C in each" -ForegroundColor Yellow
