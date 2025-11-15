# AI-Powered Vehicle Condition Assessment

This repository contains a full-stack prototype for automated vehicle condition reporting:

- **Front-end**: Angular 17 single-page app for capturing pick-up/return media, saving baselines, and visualizing AI results.
- **Back-end API**: Laravel 11 service that stores inspections, orchestrates pick-up vs return workflows, and persists damages.
- **AI microservice**: FastAPI + YOLOv8 wrapper that performs damage detection, severity scoring, and repair cost estimation.

The solution enables rental teams to capture baseline photos at hand-off, resume the same inspection during vehicle return, highlight new damages, and expose the full report to downstream systems through a documented API.

---

## Features

- Two-step workflow: save pick-up baselines (`POST /api/inspections/pickup`) and resume them later with return photos (`POST /api/inspections/{id}/return`).
- Single-session mode for rapid experiments (`POST /api/inspections`).
- Damage comparison that deduplicates per-class detections using IoU thresholds and stores bounding boxes, confidence, and rich repair metadata.
- Dynamic repair estimates combining YOLO area ratios, configurable labor/material rates, and severity heuristics.
- Front-end UX with drag-and-drop upload, live camera capture, ID-based resume flow, and overlayed bounding boxes plus cost breakdowns.
- Dockerfiles for each service and a docker-compose stack for local orchestration.
- Automated Laravel feature tests that validate pickup/return flows under mocked AI responses.

---

## Repository Structure

```
/
+-- front-end/        # Angular application (standalone components, Tailwind styles)
+-- back-end/         # Laravel 11 API, MySQL migrations, PHPUnit tests, docker-compose
+-- ai-service/       # FastAPI app + YOLO utilities, model fine-tuning helper
+-- README.md         # You are here
```

---

## Quick Start with Docker Compose

From the `back-end` directory run the entire stack (front-end + API + AI + MySQL):

```bash
cd back-end
cp .env.example .env          # update DB + YOLO vars if needed
docker compose up --build     # starts frontend:4200, backend:8000, ai-service:8001, mysql:3306
```

Visit `http://localhost:4200` to access the UI. The Angular app targets the Laravel API at `http://localhost:8000/api`, while the API calls the AI service via `http://ai-service:8000/detect` inside the compose network.

---

## Running Services Individually

### 1. AI Microservice

```bash
cd ai-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
YOLO_MODEL_PATH=./runs/detect/cardd2/weights/best.pt uvicorn app:app --reload --port 8000
```

### 2. Laravel API

```bash
cd back-end
cp .env.example .env                  # configure DB + YOLO_URL=http://localhost:8001/detect
composer install
php artisan key:generate
php artisan migrate
php artisan serve --host=0.0.0.0 --port=8000
```

### 3. Angular Front-end

```bash
cd front-end
npm install
ng serve --host=0.0.0.0 --port=4200
```

Override the API endpoint at runtime by setting `window.__APP_API_URL__ = 'https://your-api.example.com/api'` in `index.html` or by editing `front-end/src/environments/environment.ts`.

---

## API Reference

| Endpoint | Description |
| --- | --- |
| `POST /api/inspections/pickup` | Save pick-up baseline photos. Returns `inspection_id` to resume later. |
| `POST /api/inspections/{inspection}/return` | Upload return photos for an existing inspection and receive the AI comparison. |
| `POST /api/inspections` | One-shot workflow: submit pickup + return photos at once. |
| `GET /api/inspections/{id}` | Retrieve stored images, damages, and summary for integrations. |

### Request Notes

- Use multipart fields `pickup_images[]` and/or `return_images[]` (JPEG/PNG/HEIC, <= 8 MB per file).
- Optional arrays `pickup_angles[]` / `return_angles[]` can tag each image with `front`, `rear`, etc.
- Responses include `results` (per-image damages with coordinates, severity, and repair details) and `metadata` totals.

Full payload samples are documented inside `back-end/app/Http/Controllers/InspectionController.php` and the front-end service calls (`front-end/src/app/inspection/inspection.ts`).

---

## Front-end Usage Tips

1. Capture pick-up photos and click **“Save pickup baseline”**. Share the inspection id with the return team.
2. On vehicle return, enter that id, upload the new images, and click **“Start Damage Analysis”** – the UI automatically calls the return endpoint.
3. For quick demos, upload both pick-up and return photos together and run a single analysis.
4. Result cards show the AI overlay plus labor/material/overhead breakdown per damage.

---

## Testing

- **Laravel API**: `cd back-end && php artisan test` (uses sqlite in-memory + HTTP fakes to simulate the AI service).
- **Angular**: `cd front-end && npm test` (Karma/Jasmine).
- **AI Service**: call `POST /detect` or `POST /analyze` with Thunder Client / curl for smoke tests.

---

## Configuration Cheat Sheet

| Variable | Purpose |
| --- | --- |
| `YOLO_URL` | Laravel -> AI service endpoint (default `http://ai-service:8000/detect`). |
| `YOLO_MODEL_PATH` | AI service weights path (env + Docker). |
| `window.__APP_API_URL__` | Optional runtime override for the Angular API base URL. |
| `LABOR_RATE_USD`, `MATERIAL_RATE_USD` | Control repair estimate sensitivity (AI service). |

---

## Deployment Notes

- The front-end Dockerfile builds static assets and serves them via nginx (`front-end/Dockerfile`).
- The back-end Dockerfile installs Composer dependencies, enables Apache mod_rewrite, and copies the Laravel app (`back-end/Dockerfile`).
- The AI service Dockerfile bundles the FastAPI app with YOLO weights (`ai-service/Dockerfile`).
- CI/CD hooks were not provided, but the project is structured so each service can be deployed independently (e.g., Vercel for front-end, Render / Fly.io for Laravel, Hugging Face Spaces or Cloud Run for the AI service).

---

## Next Steps

- Wire up authentication / tenant scoping for multi-branch rental operations.
- Persist YOLO debug images via the `SAVE_DEBUG_IMAGES` flag for audit-ready reports.
- Expand automated tests (Angular component logic + FastAPI unit tests) and add CI workflows.
