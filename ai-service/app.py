from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
import base64
import os

import analyzer
import model_loader
import utils

app = FastAPI(title="Vehicle Damage Detection Service")
SAVE_DEBUG_IMAGES = os.getenv("SAVE_DEBUG_IMAGES", "false").lower() in {"1", "true", "yes"}


@app.on_event("startup")
def on_startup():
    """
    Warm up the YOLO model so the first request is fast.
    """
    model_loader.load_model()


async def _run_inference(image_bytes: bytes, filename: Optional[str] = None):
    try:
        detections = analyzer.analyze_image_bytes(image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    # Persist a debug copy with the drawn bounding boxes for quick verification
    if SAVE_DEBUG_IMAGES:
        try:
            utils.save_image_with_bboxes(image_bytes, detections, filename or "image.jpg")
        except Exception as exc:
            # Saving previews should not break the API, so only log the error
            print(f"Failed to persist debug image: {exc}")

    return detections


@app.post("/detect")
async def detect_damage(images: List[UploadFile] = File(...)):
    """
    Multipart endpoint used by the Laravel backend.
    Accepts multiple files under the 'images' field and returns detections per image.
    """
    if not images:
        raise HTTPException(status_code=400, detail="No images were provided")

    batched_results = []
    for upload in images:
        content = await upload.read()
        if not content:
            batched_results.append([])
            continue
        detections = await _run_inference(content, upload.filename)
        batched_results.append(detections)

    return JSONResponse(content=batched_results)


@app.post("/analyze")
async def analyze_single_image(request: Request, file: UploadFile = File(None)):
    """
    Helper endpoint for debugging from tools like Thunder Client / curl.
    Accepts either multipart upload or JSON payload { "image": "<base64>" }.
    """
    image_bytes = None
    filename = "image.jpg"

    if file is not None:
        filename = file.filename or filename
        image_bytes = await file.read()
    else:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Provide an image file or a JSON body with 'image'")

        base64_str = data.get("image")
        if not base64_str:
            raise HTTPException(status_code=400, detail="JSON payload must include an 'image' field")

        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        try:
            image_bytes = base64.b64decode(base64_str)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64 image: {exc}") from exc

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image payload")

    detections = await _run_inference(image_bytes, filename)
    return JSONResponse(content=detections)
