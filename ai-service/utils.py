# utils.py
import os
import cv2
import numpy as np
import uuid

# Define colors for each damage type (optional for improving box display on images)
# If we want specific colors for each damage type, we can define them here
COLOR_MAP = {
    "scratch": (0, 255, 0),    # Green for scratches
    "dent":    (0, 0, 255),    # Red for dents
    # Can add more based on expected damage types
}

def get_damage_severity(width, height, img_width, img_height):
    """
    Calculate severity label and the corresponding area ratio. Incorporates the absolute size
    of the bounding box so close-up shots of tiny damages are not marked as "high".
    """
    damage_area = max(0.0, width) * max(0.0, height)
    image_area = max(1.0, float(img_width) * float(img_height))
    ratio = damage_area / image_area

    bbox_pixels = damage_area
    low_threshold = max(0.04, 2500 / image_area)
    medium_threshold = max(0.12, 8000 / image_area)

    if bbox_pixels < 1500:
        severity = "low"
    elif ratio < low_threshold:
        severity = "low"
    elif ratio < medium_threshold:
        severity = "medium"
    else:
        severity = "high"

    return severity, ratio

LABOR_RATE = float(os.getenv("LABOR_RATE_USD", "70"))
MATERIAL_RATE = float(os.getenv("MATERIAL_RATE_USD", "50"))

TYPE_COMPLEXITY = {
    "scratch": {"base_hours": 0.8, "material_factor": 0.5},
    "scratches": {"base_hours": 0.8, "material_factor": 0.5},
    "paint": {"base_hours": 1.0, "material_factor": 0.7},
    "dent": {"base_hours": 1.5, "material_factor": 1.0},
    "ding": {"base_hours": 1.2, "material_factor": 0.8},
    "crack": {"base_hours": 1.1, "material_factor": 1.2},
    "glass shatter": {"base_hours": 2.2, "material_factor": 1.6},
    "lamp broken": {"base_hours": 1.3, "material_factor": 1.1},
    "tire flat": {"base_hours": 1.0, "material_factor": 0.9},
    "broken": {"base_hours": 1.8, "material_factor": 1.4},
    "default": {"base_hours": 1.0, "material_factor": 0.9},
}

SEVERITY_LOAD = {
    "low": 0.7,
    "medium": 1.0,
    "high": 1.5,
    "unknown": 0.85,
}

def estimate_repair_details(damage_type, severity, area_ratio, confidence):
    """
    Build a richer repair estimate factoring in damage type, size and model confidence.
    """
    profile = TYPE_COMPLEXITY.get(damage_type.lower(), TYPE_COMPLEXITY["default"])
    severity_factor = SEVERITY_LOAD.get(severity, SEVERITY_LOAD["unknown"])

    effort_multiplier = max(0.6, min(2.5, 0.9 + area_ratio * 5))
    confidence_factor = max(0.55, min(1.1, 0.75 + float(confidence) * 0.35))

    labor_hours = profile["base_hours"] * severity_factor * effort_multiplier
    material_units = profile["material_factor"] * (0.7 + effort_multiplier * 0.5)

    labor_cost = LABOR_RATE * labor_hours
    material_cost = MATERIAL_RATE * material_units
    overhead_cost = 0.15 * (labor_cost + material_cost)

    raw_total = (labor_cost + material_cost + overhead_cost) * confidence_factor
    total_cost = int(round(raw_total / 10.0) * 10)

    return {
        "damage_type": damage_type,
        "severity": severity,
        "area_ratio": round(area_ratio, 4),
        "labor_hours": round(labor_hours, 2),
        "material_units": round(material_units, 2),
        "labor_cost": round(labor_cost, 2),
        "material_cost": round(material_cost, 2),
        "overhead_cost": round(overhead_cost, 2),
        "confidence_factor": round(confidence_factor, 2),
        "total_cost": total_cost,
    }

def get_repair_cost(damage_type, severity, area_ratio=0.0, confidence=1.0):
    """
    Backwards compatible helper returning just the total cost.
    """
    return estimate_repair_details(damage_type, severity, area_ratio, confidence)["total_cost"]

def save_image_with_bboxes(image_bytes, detections, original_filename="image.jpg"):
    """
    Save a copy of the image with bounding boxes and labels drawn around detected damages.
    - image_bytes: Original image bytes.
    - detections: List of detections (as returned from analyzer.analyze_image_bytes).
    - original_filename: Original image filename (for creating output filename).
    """
    # Create output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)

    # Convert image bytes to OpenCV image array
    image_array = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to process image for saving")

    # Draw each bounding box with label
    for det in detections:
        raw_x = det["x"]
        raw_y = det["y"]
        raw_w = det["width"]
        raw_h = det["height"]

        if 0 <= float(raw_x) <= 1 and 0 <= float(raw_w) <= 1:
            x = int(float(raw_x) * img.shape[1])
            w = int(float(raw_w) * img.shape[1])
        else:
            x = int(raw_x)
            w = int(raw_w)

        if 0 <= float(raw_y) <= 1 and 0 <= float(raw_h) <= 1:
            y = int(float(raw_y) * img.shape[0])
            h = int(float(raw_h) * img.shape[0])
        else:
            y = int(raw_y)
            h = int(raw_h)
        damage_type = det["type"]
        confidence = det["confidence"]
        severity = det["severity"]

        # Determine box color based on damage type (if defined in map) or use default color
        color = COLOR_MAP.get(damage_type.lower(), (255, 255, 0))  # Yellow as default
        # Draw rectangle around damage
        cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness=2)
        # Prepare label text to be written on image: damage type, confidence, and severity
        label = f"{damage_type} ({confidence:.1f}%) - {severity}"
        # Choose appropriate font size
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2
        # Measure text size to adjust label background
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        # Draw semi-transparent text background (filled rectangle behind text for easier reading)
        cv2.rectangle(img, (x, y - text_height - 10), (x + text_width + 2, y), color, thickness=-1)
        # Draw label text in black over colored background
        cv2.putText(img, label, (x, y - 5), font, font_scale, (0, 0, 0), thickness)

    # Create output filename:
    # If original filename is available, use it with "_result" suffix
    # If not available (e.g., in base64 case), create a random unique name.
    if original_filename:
        name, ext = os.path.splitext(original_filename)
        if not ext:
            ext = ".jpg"
        result_filename = f"{name}_result{ext}"
    else:
        # Create random name using uuid
        result_filename = f"result_{uuid.uuid4().hex[:8]}.jpg"

    output_path = os.path.join("output", result_filename)
    # Save modified image (with boxes) to specified path
    cv2.imwrite(output_path, img)
    return output_path
