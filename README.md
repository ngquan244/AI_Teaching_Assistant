#  Teaching Assistant Grader

> AI-powered automated exam grading system with quiz generation capabilities

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61dafb.svg)](https://react.dev)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

##  Overview

Teaching Assistant Grader is a comprehensive AI-powered system designed to assist teachers with:

- **Automated Exam Grading**: Upload student answer sheets and get instant grading results
- **Quiz Generation**: Extract questions from PDF exams and generate randomized quizzes
- **AI Chat Assistant**: Interactive AI agent that can help with grading tasks
- **Result Analytics**: Summarize and export grading results to Excel

##  Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Ollama (for local LLM)
- SQL Server (for result storage)

### Backend Setup

```bash
# Clone repository
git clone <repository-url>
cd Grader

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Start backend server
python -m uvicorn backend.main:app --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Access Application

- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

```

##  API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat/send` | POST | Send message to AI agent |
| `/api/upload/images` | POST | Upload exam images |
| `/api/upload/pdf` | POST | Upload exam PDF |
| `/api/quiz/generate` | POST | Generate quiz from PDF |
| `/api/quiz/list` | GET | List all quizzes |
| `/api/grading/execute` | POST | Execute grading |
| `/api/grading/summary` | POST | Get grading summary |
| `/api/config/role` | POST | Set user role |

##  Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Server host | `127.0.0.1` |
| `PORT` | Server port | `8000` |
| `DEBUG` | Debug mode | `true` |
| `DEFAULT_MODEL` | Default AI model | `llama3.1:latest` |
| `EMAIL_USER` | SMTP email | - |
| `EMAIL_PASSWORD` | SMTP password | - |

##  Author

**UET - VNU**

---
*Built with love using FastAPI, React, and LangGraph*
