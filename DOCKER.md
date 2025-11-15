# AI-Powered Vehicle Condition Assessment – Docker Guide

This document explains how to run the complete stack (front-end, back-end, AI service, database) using Docker.  
It assumes Docker Desktop (or equivalent) and Docker Compose are installed.

---

## 1. Prepare environment variables

1. Copy the backend example env and customize it:
   ```bash
   cp back-end/.env.example back-end/.env
   ```
2. Update these keys inside `back-end/.env`:
   - `APP_KEY` – run `php artisan key:generate --show` locally and paste the value.
   - `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` – must match the MySQL service (defaults are already set).
   - `YOLO_URL=http://ai-service:8000/detect` – leave as-is so Laravel can call the AI container.
3. (Optional) For the AI service you can specify a custom model:
   - `YOLO_MODEL_PATH=/app/runs/detect/cardd2/weights/best.pt`
   - `SAVE_DEBUG_IMAGES=true` to persist annotated images under `/app/output`.

---

## 2. Build and start the stack

Use the docker-compose file that lives under `back-end/`:

```bash
cd back-end
docker compose up --build
```

This spins up four services:

| Service    | Port | Description                                 |
|------------|------|---------------------------------------------|
| frontend   | 4200 | Angular UI served via nginx                 |
| backend    | 8000 | Laravel API (Apache + PHP 8.2)              |
| ai-service | 8001 | FastAPI YOLO detection microservice         |
| db         | 3306 | MySQL 8 with a named Docker volume          |

Once the containers report “ready”, open http://localhost:4200 to use the app.

---

## 3. Database migrations & artisan commands

Run Laravel commands inside the `backend` container:

```bash
docker compose exec backend php artisan migrate --force
docker compose exec backend php artisan storage:link
```

Need tinker or queue workers? Just reuse the same `docker compose exec backend ...` pattern.

---

## 4. Logs & debugging

Follow logs from any service:

```bash
docker compose logs -f backend
docker compose logs -f ai-service
```

If `SAVE_DEBUG_IMAGES=true`, annotated return photos are saved under `ai-service/output` within the container.  
Copy them out with `docker cp ai-service:/app/output ./debug-output`.

---

## 5. Stopping and cleaning up

```bash
docker compose down        # stop containers
docker compose down -v     # stop and remove the MySQL volume
```

Use the second command only if you want to reset the database.

---

## 6. Common troubleshooting tips

- **Port conflicts**: Ensure ports 4200/8000/8001/3306 are free or change them in `docker-compose.yml`.
- **MySQL init errors**: Delete the `dbdata` Docker volume (`docker volume rm back-end_dbdata`) then rerun compose.
- **Model weights missing**: Mount or copy your YOLO weights into `ai-service/runs/...` before building, then set `YOLO_MODEL_PATH`.
- **CORS issues**: `back-end/config/cors.php` already allows `http://localhost:4200`. Add your deployed domains if needed.

With these steps the entire prototype runs locally with a single command, matching the architecture expected by the hiring sprint brief.
