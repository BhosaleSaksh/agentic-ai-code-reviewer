# ==============================================================================
# One-Click Application Startup Script
# Project: An Agentic AI Framework for Reliable and Evidence-Based Code Review
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting Agentic Code Reviewer Full-Stack Application... " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Start PostgreSQL (Port 5433)
Write-Host "[1/4] Starting PostgreSQL Database Server on Port 5433..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'PostgreSQL Server (Port 5433)' -ForegroundColor Cyan; & 'C:\Program Files\PostgreSQL\18\bin\postgres.exe' -D 'D:\pgdata' -p 5433"

# 2. Start Ollama Server (Port 11434)
Write-Host "[2/4] Starting Ollama Local LLM Server on Port 11434..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Ollama Local LLM Server (Port 11434)' -ForegroundColor Cyan; `$env:OLLAMA_MODELS = 'D:\AI\Ollama\models'; & 'D:\Apps\Ollama\ollama.exe' serve"

# 3. Start FastAPI Backend (Port 8000)
Write-Host "[3/4] Starting FastAPI Backend on Port 8000..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'FastAPI Backend (Port 8000)' -ForegroundColor Cyan; Set-Location 'D:\Projects\agentic-code-reviewer'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"

# 4. Start Vite Frontend (Port 5173)
Write-Host "[4/4] Starting Vite React Frontend on Port 5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Vite Frontend (Port 5173)' -ForegroundColor Cyan; Set-Location 'D:\Projects\agentic-code-reviewer\frontend'; npm run dev -- --host 127.0.0.1 --port 5173"

Start-Sleep -Seconds 3

Write-Host "`nAll 4 services launched successfully in dedicated terminals!" -ForegroundColor Green
Write-Host "Open your browser to: http://127.0.0.1:5173/dashboard`n" -ForegroundColor Yellow
