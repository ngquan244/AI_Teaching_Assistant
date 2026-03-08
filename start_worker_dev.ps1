# =============================================================================
# Single Celery Worker for Development (All Queues)
# =============================================================================
# Usage: .\start_worker_dev.ps1
# Starts one worker handling all queues with 4 concurrent threads

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Starting Development Celery Worker (All Queues)                " -ForegroundColor Cyan
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

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  - Queues: rag, llm, canvas, misc, celery" -ForegroundColor Gray
Write-Host "  - Pool: threads" -ForegroundColor Gray
Write-Host "  - Concurrency: 4 threads" -ForegroundColor Gray
Write-Host ""
Write-Host "Starting worker..." -ForegroundColor Green
Write-Host ""

# Start worker
& "$venvPath\Scripts\Activate.ps1"
& "$celeryExe" -A backend.celery_app worker -Q rag,llm,canvas,misc,celery --pool=threads -c 4 --loglevel=INFO -n dev@%COMPUTERNAME%
