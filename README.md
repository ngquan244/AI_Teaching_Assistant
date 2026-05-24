# AI Teaching Assistant

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-green.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19+-61dafb.svg)](https://react.dev)
![License](https://img.shields.io/badge/License-Not%20specified-lightgrey.svg)

AI Teaching Assistant là hệ thống trợ giảng thông minh hỗ trợ giảng viên/trợ giảng tạo câu hỏi trắc nghiệm từ học liệu số và triển khai kết quả lên Canvas LMS. Hệ thống không tập trung vào chấm điểm bài thi tự động; trọng tâm hiện tại là quy trình từ tài liệu học tập đến Quiz: tiếp nhận tài liệu, lập chỉ mục, truy hồi ngữ cảnh bằng RAG, sinh câu hỏi bằng LLM, rà soát/chỉnh sửa và đưa Quiz vào Canvas.

Tên repository và một số service vẫn dùng chữ `Grader` do lịch sử phát triển, nhưng phạm vi chức năng hiện tại là AI Teaching Assistant cho tạo Quiz từ học liệu.

## Overview

Trong thực tế giảng dạy, việc tạo Quiz từ slide, giáo trình hoặc tài liệu trên LMS thường tốn thời gian: giảng viên phải đọc tài liệu, chọn nội dung trọng tâm, viết câu hỏi, tạo đáp án đúng/sai và nhập lại lên Canvas. AI Teaching Assistant bán tự động hóa quy trình này bằng cách kết hợp RAG, LLM và Canvas API.

Luồng nghiệp vụ chính:

1. Người dùng tải PDF lên hệ thống hoặc chọn file PDF từ khóa học Canvas.
2. Backend xử lý tài liệu, chia nhỏ nội dung, tạo embedding và lưu vào Chroma.
3. Khi cần tạo Quiz, hệ thống truy hồi các đoạn liên quan theo chủ đề/phạm vi người dùng chọn.
4. LLM sinh câu hỏi trắc nghiệm dựa trên ngữ cảnh truy hồi, có kiểm tra cấu trúc và số lượng đầu ra.
5. Người dùng rà soát, chỉnh sửa, lưu vào kho đề, xuất QTI hoặc triển khai lên Canvas.
6. Các tác vụ dài như index tài liệu, sinh Quiz và thao tác Canvas được chạy bất đồng bộ qua Celery/Redis hoặc eager mode khi chạy local.

Các nhóm chức năng hiện có:

- **Tài liệu RAG**: upload PDF, tải PDF từ URL an toàn, lập chỉ mục, hỏi đáp, trích xuất chủ đề, sinh Quiz.
- **Canvas LMS**: kết nối token Canvas, lấy danh sách khóa học/file/quiz, tải file từ Canvas, import QTI/question bank.
- **Domain RAG theo khóa học**: đánh dấu tài liệu Canvas làm tri thức nền cấp khóa học để hỗ trợ sinh câu hỏi có thêm bối cảnh nhưng vẫn ưu tiên tài liệu chính.
- **Quiz Builder**: chỉnh sửa câu hỏi, đáp án, triển khai thành Canvas Quiz hoặc question bank.
- **Kho đề thi**: lưu, xem lại và nạp lại các bộ câu hỏi đã sinh.

- **Kết quả Canvas**: lấy và export kết quả/điểm từ Canvas.
- **Admin**: quản lý người dùng, mã mời, panel hiển thị, Groq API key pool và job nền.
- **Hướng dẫn trong ứng dụng**: nội dung hướng dẫn có thể quản trị và gắn ảnh minh họa.

## Kiến trúc

```text
frontend/                    React + TypeScript + Vite
backend/                     FastAPI API, services, routes, Celery tasks
backend/modules/document_rag RAG, ingest PDF, retriever, quiz generator
alembic/                     Database migrations
docker/                      Nginx, PostgreSQL init, backup script
data/                        Runtime data: PDF uploads, Chroma, guide images
exports/                     File export
logs/                        Backend/worker logs
```

Thành phần runtime:

| Thành phần | Công nghệ | Vai trò |
| --- | --- | --- |
| Frontend | React, TypeScript, Vite | Giao diện quản lý tài liệu, tạo Quiz, Canvas và admin |
| Backend API | FastAPI | Xác thực, điều phối nghiệp vụ, API cho frontend |
| Database | PostgreSQL | Người dùng, job, metadata tài liệu, cấu hình, quiz đã lưu |
| Queue/cache | Redis | Celery broker/result backend, rate limit, blacklist token |
| Vector store | Chroma | Lưu embedding và chunks phục vụ RAG |
| Worker | Celery | Index PDF, sinh Quiz, tải file Canvas, import QTI |
| LLM provider | Groq API | Sinh câu hỏi/trích xuất nội dung bằng LLM |
| Reverse proxy | Nginx | Phục vụ frontend production và proxy API |

## Yêu cầu hệ thống

Chạy local:

- Python 3.11.
- Node.js 20.
- Docker Desktop hoặc Docker Engine để chạy PostgreSQL/Redis.
- Git.

Deploy production:

- VPS/VM Linux, khuyến nghị Ubuntu 24.04.
- Docker Engine và Docker Compose plugin.
- Domain trỏ DNS về server nếu dùng HTTPS.
- Tối thiểu 2 GB RAM; nên có swap vì embedding/indexing PDF có thể tốn bộ nhớ.

## Cài đặt local

Các lệnh dưới đây chạy từ thư mục gốc repository.

### 1. Clone source

```bash
git clone <repository-url>
cd Grader
```

### 2. Tạo môi trường Python

Windows PowerShell:

```powershell
python -m venv venv-grader
.\venv-grader\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv venv-grader
source venv-grader/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Dependency cho test/lint:

```bash
pip install -r requirements-dev.txt
```

### 3. Tạo `.env`

Windows:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Cấu hình tối thiểu cho local:

```env
ENVIRONMENT=development
DEBUG=true

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=grader_user
POSTGRES_PASSWORD=your_secure_database_password_here
POSTGRES_DB=grader_db

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key-here
GROQ_MODEL=llama-3.3-70b-versatile

SIGNUP_MODE=open
```

Redis local trong `docker-compose.dev.yml` không bật password, vì vậy đặt `REDIS_PASSWORD=` rỗng. Nếu giữ giá trị mẫu `your_redis_password_here`, các phần dùng Redis như Celery, rate limit hoặc token blacklist có thể lỗi xác thực.

Sinh secret cho JWT và mã hóa Canvas token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Điền vào `.env`:

```env
JWT_SECRET_KEY=<secret-1>
JWT_REFRESH_SECRET_KEY=<secret-2>
ENCRYPTION_KEY=<fernet-key>
```

### 4. Chạy PostgreSQL và Redis

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
```

### 5. Chạy migration

```bash
alembic upgrade head
```

### 6. Tạo tài khoản admin

Nếu `SIGNUP_MODE=open`, có thể đăng ký trực tiếp trên giao diện. Nếu cần tạo admin ngay:

```bash
python -m backend.scripts.seed_admin --email admin@grader.local --name "System Admin"
```

Nếu không truyền `--password`, script sẽ sinh mật khẩu và in ra terminal.

## Chạy ứng dụng local

### Backend

```bash
python run.py --reload
```

Địa chỉ:

- API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Frontend

Mở terminal mới:

```bash
cd frontend
npm install
npm run dev
```

Frontend chạy tại `http://localhost:5173`. Vite đã proxy `/api` và `/media` về backend local nên không cần đặt `VITE_API_URL` khi phát triển.

### Worker và job nền

Mặc định cấu hình code đang đặt `CELERY_TASK_ALWAYS_EAGER=true`, nghĩa là job được chạy trong process backend theo eager/background thread. Cách này thuận tiện cho chạy thử local.

Nếu muốn chạy đúng mô hình Celery worker, thêm/sửa trong `.env`:

```env
CELERY_TASK_ALWAYS_EAGER=false
REDIS_PASSWORD=
```

Một worker dev xử lý tất cả queue:

```bash
celery -A backend.celery_app worker -Q rag,rag_index,llm,canvas,celery,default --pool=threads -c 8 --loglevel=INFO -n dev@%h
```

Chạy tách worker theo nhóm tác vụ:

```bash
celery -A backend.celery_app worker -Q rag,celery,default --pool=threads -c 2 --loglevel=INFO -n rag@%h
celery -A backend.celery_app worker -Q rag_index --pool=threads -c 1 --loglevel=INFO -n rag_index@%h
celery -A backend.celery_app worker -Q llm --pool=threads -c 2 --loglevel=INFO -n llm@%h
celery -A backend.celery_app worker -Q canvas --pool=threads -c 4 --loglevel=INFO -n canvas@%h
```

Trên Windows có thể dùng `start_worker_dev.ps1` hoặc `start_workers.ps1`, nhưng hai script này đang hardcode đường dẫn `venv-grader`; nếu repo nằm nơi khác, sửa biến `$venvPath` hoặc chạy lệnh `celery` thủ công.

Flower:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile monitoring up -d flower
```

Mở `http://localhost:5555`.

## Chạy thử phần mềm

### 1. Kiểm tra backend

```bash
curl http://localhost:8000/health
```

Kết quả mong đợi:

```json
{"status":"healthy","version":"1.0.0"}
```

### 2. Đăng nhập frontend

Mở `http://localhost:5173`, đăng ký tài khoản hoặc đăng nhập bằng admin đã seed.

### 3. Cấu hình Groq

Có thể cấu hình bằng một trong hai cách:

- Đặt `GROQ_API_KEY` trong `.env` rồi restart backend.
- Đăng nhập admin và cấu hình Groq key trong giao diện admin/settings.

Không có Groq key thì các chức năng cần LLM như sinh Quiz, trích xuất chủ đề hoặc hỏi đáp RAG sẽ không chạy đầy đủ.

### 4. Thử tạo Quiz từ PDF

1. Vào panel **Tài liệu**.
2. Upload file `.pdf` tối đa 50 MB.
3. Chạy lập chỉ mục cho tài liệu.
4. Chờ job hoàn tất trong modal tiến trình hoặc qua `GET /api/jobs/{job_id}`.
5. Chọn tài liệu/chủ đề và sinh câu hỏi trắc nghiệm.
6. Rà soát kết quả, lưu vào **Kho Đề Thi** hoặc chuyển sang **Tạo Canvas Quiz**.

### 5. Thử tích hợp Canvas

1. Vào **Cài đặt** và lưu Canvas access token.
2. Mở **Canvas LMS** để lấy danh sách khóa học/file.
3. Tải và lập chỉ mục PDF từ Canvas.
4. Dùng tài liệu đã index để sinh Quiz.
5. Triển khai Quiz hoặc ngân hàng câu hỏi lên Canvas.

Canvas mặc định dùng `DEFAULT_CANVAS_BASE_URL=https://lms.uet.vnu.edu.vn`. Có thể đổi trong `.env` nếu dùng hệ Canvas khác.

## Deploy production bằng Docker Compose

Production stack gồm:

- `backend`: FastAPI API, chỉ expose nội bộ cho nginx.
- `nginx`: phục vụ frontend build, proxy `/api`, `/media`, `/static/exports`.
- `postgres`: PostgreSQL 16.
- `redis`: Redis có password, dùng cho Celery và token/rate-limit.
- `worker-rag`: truy hồi, query, tác vụ RAG nhẹ.
- `worker-rag-index`: lập chỉ mục PDF, concurrency 1 để giới hạn RAM.
- `worker-llm`: sinh Quiz/trích xuất nội dung bằng LLM.
- `worker-canvas`: thao tác Canvas API.
- `certbot`: xin/gia hạn chứng chỉ Let's Encrypt.

### 1. Chuẩn bị server

Ví dụ trên Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo apt-get install -y docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
```

Clone source:

```bash
git clone <repository-url> /root/grader
cd /root/grader
```

### 2. Tạo `.env` production

```bash
cp .env.production.example .env
nano .env
```

Cấu hình tối thiểu:

```env
ENVIRONMENT=production
DEBUG=false
PRODUCTION_DOMAIN=grader.yourdomain.com
LETSENCRYPT_EMAIL=admin@yourdomain.com

POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=grader_user
POSTGRES_PASSWORD=<strong-secret>
POSTGRES_DB=grader_db

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=<strong-secret>

JWT_SECRET_KEY=<strong-secret>
JWT_REFRESH_SECRET_KEY=<strong-secret>
ENCRYPTION_KEY=<fernet-key>

LLM_PROVIDER=groq
GROQ_API_KEY=<groq-key>
GROQ_MODEL=llama-3.3-70b-versatile

SIGNUP_MODE=invite
SIGNUP_INVITE_CODE=<invite-code-at-least-16-chars>
INVITE_SECRET=<secret-at-least-32-chars>

CORS_ORIGINS=["https://grader.yourdomain.com"]
CELERY_TASK_ALWAYS_EAGER=false
```

Production phải dùng secret thật, không dùng các giá trị `CHANGE_ME...`. Đặt `CELERY_TASK_ALWAYS_EAGER=false` để job chạy qua Redis và các worker thay vì chạy trong process API.

Sinh secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Nếu server chưa có package `cryptography`, sinh `ENCRYPTION_KEY` bằng container sau khi build:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Build frontend và image backend

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile build run --rm frontend-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
```

### 4. Khởi động database, Redis, migration

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend python -m backend.scripts.seed_admin --email admin@grader.local --name "System Admin"
```

### 5. Khởi động backend và worker

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend worker-rag worker-rag-index worker-llm worker-canvas
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Kiểm tra log:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
```

### 6. Cấu hình nginx và HTTPS

Trước khi xin certificate, đảm bảo DNS của `PRODUCTION_DOMAIN` đã trỏ về IP server và firewall mở port 80/443.

Chạy nginx HTTP-only để certbot xác thực:

```bash
cp docker/nginx/nginx.conf docker/nginx/nginx.conf.https
cp docker/nginx/nginx.dev.conf docker/nginx/nginx.conf
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d nginx
```

Nạp biến từ `.env` và xin certificate:

```bash
set -a
. ./.env
set +a
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile ssl run --rm certbot certonly --webroot -w /var/www/certbot -d "$PRODUCTION_DOMAIN" --agree-tos -m "$LETSENCRYPT_EMAIL" --non-interactive
```

Khôi phục nginx HTTPS:

```bash
mv docker/nginx/nginx.conf.https docker/nginx/nginx.conf
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

Kiểm tra:

```bash
curl -I https://$PRODUCTION_DOMAIN/health
```

Ứng dụng production:

- Frontend: `https://<PRODUCTION_DOMAIN>`
- Health check: `https://<PRODUCTION_DOMAIN>/health`
- API: `https://<PRODUCTION_DOMAIN>/api/...`

### 7. Gia hạn SSL

Ví dụ cron:

```cron
0 3,15 * * * cd /root/grader && docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile ssl run --rm certbot renew --quiet && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

### 8. Deploy bằng script

Repo có `deploy.sh` cho VPS Ubuntu:

```bash
bash deploy.sh
```

Script sẽ kiểm tra `.env`, build frontend/backend, chạy migration, khởi động backend/worker/nginx và xin SSL. Khi cập nhật source:

```bash
bash deploy.sh update
```

## Vận hành

Xem trạng thái:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Xem log:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker-rag
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker-rag-index
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker-llm
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker-canvas
```

Update thủ công:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile build run --rm frontend-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend worker-rag worker-rag-index worker-llm worker-canvas nginx
```

Backup PostgreSQL:

```bash
bash docker/backup_postgres.sh
```

Tắt stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

Không dùng `down -v` trừ khi muốn xóa volume PostgreSQL/Redis.

## API chính

| Nhóm | Endpoint tiêu biểu | Mục đích |
| --- | --- | --- |
| Auth | `/api/auth/login`, `/api/auth/signup`, `/api/auth/me` | Đăng ký, đăng nhập, phiên người dùng |
| Admin | `/api/admin/users`, `/api/admin/jobs`, `/api/admin/invite-codes`, `/api/admin/groq-keys` | Quản trị hệ thống |
| Config | `/api/config`, `/api/config/public`, `/api/config/panels` | Cấu hình ứng dụng/panel |
| Jobs | `/api/jobs`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/stream` | Theo dõi job nền |
| Document RAG | `/api/document-rag/upload`, `/api/document-rag/async/upload-and-index`, `/api/document-rag/async/generate-quiz` | PDF, index, query, sinh Quiz |
| Canvas | `/api/canvas/courses`, `/api/canvas/download`, `/api/canvas/import-qti-bank` | Tích hợp Canvas file/QTI |
| Canvas RAG | `/api/canvas-rag/files`, `/api/canvas-rag/async/index`, `/api/canvas-rag/async/generate-quiz` | RAG trên tài liệu Canvas |
| Canvas Quiz | `/api/canvas-quiz/create-quiz` | Tạo Quiz/question trên Canvas |
| Canvas Simulation | `/api/canvas-sim/...` | Giả lập luồng làm Quiz |
| Canvas Results | `/api/canvas-results/...` | Lấy và export kết quả |
| Saved Quizzes | `/api/saved-quizzes` | Lưu và quản lý bộ câu hỏi |
| Guide | `/api/guide` | Nội dung hướng dẫn trong UI |

Khi chạy development, xem schema đầy đủ tại `http://localhost:8000/docs`.

## Ghi chú quan trọng

- Upload trực tiếp hiện chỉ hỗ trợ PDF, giới hạn 50 MB/file.
- Chỉ Groq đang được hỗ trợ qua `LLM_PROVIDER=groq`.
- `data/`, `exports/`, `logs/` là dữ liệu runtime cần backup khi vận hành thật.
- `worker-rag-index` chạy concurrency 1 để tránh nhiều PDF lớn sinh embedding cùng lúc.
- Production không publish PostgreSQL/Redis ra Internet; nginx chỉ expose 80/443.
- Kết quả Quiz do LLM sinh ra cần được giảng viên rà soát trước khi sử dụng chính thức.
