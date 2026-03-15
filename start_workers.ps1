# =============================================================================
# Celery Workers Startup Script for Windows
# =============================================================================
# Usage: .\start_workers.ps1
# This script starts 3 specialized Celery workers with thread pool for parallel execution

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

# Start RAG worker (2 concurrent threads) — also handles default/celery queues
Write-Host "[1/3] Starting RAG worker (queue: rag,celery,default, concurrency: 2)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$venvPath\Scripts\Activate.ps1'; & '$celeryExe' -A backend.celery_app worker -Q rag,celery,default --pool=threads -c 2 --loglevel=INFO -n rag@%COMPUTERNAME%"
) -WindowStyle Normal

Start-Sleep -Seconds 2

# Start LLM worker (2 concurrent threads)
Write-Host "[2/3] Starting LLM worker (queue: llm, concurrency: 2)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& '$venvPath\Scripts\Activate.ps1'; & '$celeryExe' -A backend.celery_app worker -Q llm --pool=threads -c 2 --loglevel=INFO -n llm@%COMPUTERNAME%"
) -WindowStyle Normal

Start-Sleep -Seconds 2

# Start Canvas worker (4 concurrent threads)
Write-Host "[3/3] Starting Canvas worker (queue: canvas, concurrency: 4)..." -ForegroundColor Yellow
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
Write-Host "Total capacity: 8 concurrent tasks (2+2+4)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Worker details:" -ForegroundColor White
Write-Host "  - RAG worker    : 2 threads (document indexing, RAG queries, default tasks)" -ForegroundColor Gray
Write-Host "  - LLM worker    : 2 threads (quiz generation, topic extraction)" -ForegroundColor Gray
Write-Host "  - Canvas worker : 4 threads (Canvas API operations)" -ForegroundColor Gray
Write-Host ""
Write-Host "Monitoring:" -ForegroundColor White
Write-Host "  - Flower: http://localhost:5555 (run: celery -A backend.celery_app flower)" -ForegroundColor Gray
Write-Host "  - Jobs API: http://localhost:8000/api/jobs" -ForegroundColor Gray
Write-Host ""
Write-Host "To stop workers: Close the PowerShell windows or press Ctrl+C in each" -ForegroundColor Yellow
