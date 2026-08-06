# FastAPI backend

The backend is a single-user FastAPI API designed for a Next.js client. Repository preprocessing and GraphFlow analysis execute in Redis-backed RQ workers; SQLite stores projects, durable run state, and canonical analysis results.

## Configuration

Copy `.env.example` to `.env` at the repository root and set a real `OPENAI_API_KEY`. The API validates required configuration on startup. `/health` is process liveness; `/ready` returns HTTP 200 only when configuration is valid and both SQLite and Redis are reachable.

`CORS_ALLOWED_ORIGINS` is a comma-separated list of exact browser origins, for example `http://localhost:3000,https://demo.example.com`. Wildcards are rejected.

Job execution is controlled by `PREPROCESSING_JOB_TIMEOUT_SECONDS`, `ANALYSIS_JOB_TIMEOUT_SECONDS`, `JOB_RETRY_MAX`, and `JOB_RETRY_INTERVAL_SECONDS`. A positive retry interval requires the scheduler, which `worker.py` enables automatically.

Required variables are `OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, and `CORS_ALLOWED_ORIGINS`. The remaining deployment settings are configurable with defaults:

- API/data: `BACKEND_HOST`, `BACKEND_PORT`, `DATA_DIR`, `LOG_LEVEL`
- Redis/RQ: `RQ_QUEUE_NAME`, `REDIS_CONNECT_TIMEOUT_SECONDS`, `REDIS_HEALTH_CHECK_INTERVAL_SECONDS`, `PREPROCESSING_JOB_TIMEOUT_SECONDS`, `ANALYSIS_JOB_TIMEOUT_SECONDS`, `JOB_RETRY_MAX`, `JOB_RETRY_INTERVAL_SECONDS`
- ingestion: `MAX_UPLOAD_ZIP_BYTES`, `MAX_EXTRACTED_TOTAL_BYTES`, `MAX_EXTRACTED_FILE_BYTES`, `MAX_EXTRACTED_FILES`, `MAX_ZIP_COMPRESSION_RATIO`, `REPOSITORY_CLONE_TIMEOUT_SECONDS`, `GITHUB_VALIDATION_TIMEOUT_SECONDS`
- OpenAI: `OPENAI_MODEL`, `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_TEMPERATURE`, `OPENAI_MAX_TOKENS`, `OPENAI_REQUEST_TIMEOUT_SECONDS`

## Local startup

From the repository root, install dependencies and start Redis. Then run the API and worker in separate terminals:

```powershell
pip install -r requirements.txt
docker run -d --name repo-research-redis -p 6379:6379 redis:7-alpine
cd backend/app
python server.py
```

```powershell
cd backend/app
python worker.py
```

On Windows, the worker entrypoint selects RQ's spawn-based worker. Linux containers use the standard process-isolated worker.

## Docker Compose

After creating `.env`:

```powershell
docker compose up --build
```

The API is exposed on `BACKEND_PORT` (8000 by default). Named volumes preserve Redis state and `/data`, which contains SQLite, uploads, project context, and FAISS indexes.

## Manual smoke check

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/ready
curl.exe -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"name":"FastAPI","github_url":"https://github.com/fastapi/fastapi"}'
curl.exe -X POST http://localhost:8000/projects/1/preprocess
curl.exe http://localhost:8000/projects/1/runs
```

Use the returned preprocessing run ID with `GET /projects/1/runs/{run_id}`. Once preprocessing completes:

```powershell
curl.exe -X POST http://localhost:8000/projects/1/analyze/graphflow -H "Content-Type: application/json" -d '{"personas":["SDE","PM"],"depth":"standard","verbosity":"medium"}'
curl.exe http://localhost:8000/projects/1/runs/latest
curl.exe http://localhost:8000/projects/1/result
```

Starting the same run type twice while it is queued or running returns HTTP 409. Stopping Redis makes `/ready` and new enqueue requests return HTTP 503 with the shared JSON error envelope.

To verify ZIP ingestion, replace the path below with a small valid archive. The first command should return HTTP 201; the second should return HTTP 400 with `invalid_file_type`.

```powershell
curl.exe -X POST http://localhost:8000/projects/upload -F "name=ZIP demo" -F "file=@C:\path\repository.zip;type=application/zip"
curl.exe -X POST http://localhost:8000/projects/upload -F "file=@C:\path\README.md"
```

Invalid GitHub paths, queries, credentials, and non-GitHub hosts should return a structured 4xx response:

```powershell
curl.exe -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"github_url":"https://github.com/owner/repo/issues"}'
curl.exe -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"github_url":"https://github.com/owner/repo?tab=readme"}'
curl.exe -X POST http://localhost:8000/projects -H "Content-Type: application/json" -d '{"github_url":"https://example.com/owner/repo"}'
```
