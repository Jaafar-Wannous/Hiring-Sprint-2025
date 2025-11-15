import cv2
import numpy as np
from typing import Any

from model_loader import get_model
import utils


def _json_safe(value: Any):
    """
    Recursively convert numpy types into plain Python so JSON serialization never fails.
    """
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def analyze_image_bytes(image_bytes: bytes):
    """
    Decode the provided bytes, run YOLOv8 inference and return normalized detections.
    """
    image_array = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Unable to decode image bytes")

    model = get_model()
    # Use stricter thresholds to avoid duplicate boxes on the same damage spot.
    results = model.predict(
        source=img,
        conf=0.5,
        iou=0.5,
        max_det=40,
        save=False,
        verbose=False,
    )

    detections = []
    if results and len(results) > 0:
        result = results[0]
        boxes = result.boxes
        if boxes is not None and boxes.xyxy is not None:
            xyxy = boxes.xyxy.cpu().numpy()
            confidences = boxes.conf.cpu().numpy()
            classes = boxes.cls.cpu().numpy().astype(int)

            img_h, img_w, _ = img.shape

            for i in range(len(xyxy)):
                x_min, y_min, x_max, y_max = xyxy[i]
                conf = confidences[i]
                cls_id = classes[i]
                class_name = model.names.get(cls_id, f"class_{cls_id}")

                width = x_max - x_min
                height = y_max - y_min

                severity, area_ratio = utils.get_damage_severity(width, height, img_w, img_h)
                repair_details = utils.estimate_repair_details(
                    class_name,
                    severity,
                    area_ratio,
                    float(conf),
                )

                norm_x = float(x_min) / img_w
                norm_y = float(y_min) / img_h
                norm_w = float(width) / img_w
                norm_h = float(height) / img_h

                detections.append(
                    {
                        "class": class_name,
                        "type": class_name,
                        "conf": round(float(conf), 4),
                        "confidence": round(float(conf) * 100, 2),
                        "x": round(norm_x, 4),
                        "y": round(norm_y, 4),
                        "width": round(norm_w, 4),
                        "height": round(norm_h, 4),
                        "area_ratio": round(float(area_ratio), 4),
                        "severity": severity,
                        "repair_cost": int(repair_details["total_cost"]),
                        "repair_details": _json_safe(repair_details),
                    }
                )

    return detections
