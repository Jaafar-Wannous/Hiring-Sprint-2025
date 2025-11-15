from ultralytics import YOLO
import os
import logging

# Store a single YOLO model instance so we do not reload weights for each request
_model = None

# Allow overriding the weights path through an environment variable.
DEFAULT_MODEL_PATH = os.getenv(
    "YOLO_MODEL_PATH", "runs/detect/cardd2/weights/best.pt"
)


def _load_weights(path: str):
    logging.info("Loading YOLO weights from %s", path)
    return YOLO(path)


def load_model(model_path: str = DEFAULT_MODEL_PATH):
    """
    Ensure the YOLO model is loaded only once so that subsequent requests stay fast.
    """
    global _model
    if _model is None:
        try:
            _model = _load_weights(model_path)
        except Exception as exc:
            fallback = "yolov8n.pt"
            logging.warning(
                "Failed to load model '%s' (%s). Falling back to '%s'.",
                model_path,
                exc,
                fallback,
            )
            _model = _load_weights(fallback)
    return _model


def get_model():
    """
    Helper that returns the cached YOLO instance.
    """
    return load_model()
