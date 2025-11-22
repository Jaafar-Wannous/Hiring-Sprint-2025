"""
Compare pickup/return images by:
1) Computing a CLIP-based similarity score (0–1).
2) Running YOLO damage detection on both.
3) Highlighting damages that appear in the return image but not the pickup image.
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import torch
from PIL import Image
import open_clip

import analyzer


def _load_image_from_bytes(payload: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(payload)).convert("RGB")
    return img


@lru_cache(maxsize=1)
def _get_clip_model(model_name: str, pretrained: str, device: str) -> Tuple[torch.nn.Module, Any, str]:
    """
    Lazy-load and cache the CLIP model to avoid reloading per request.
    """
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained, device=device
    )
    model.eval()
    return model, preprocess, device


def compute_similarity_bytes(
    pickup_bytes: bytes,
    return_bytes: bytes,
    *,
    model_name: str = "ViT-B-32",
    pretrained: str = "laion2b_s34b_b79k",
    device: str | None = None,
) -> float:
    """
    Compute cosine similarity between two images given as bytes.
    """
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model, preprocess, device = _get_clip_model(model_name, pretrained, device)

    img_a = preprocess(_load_image_from_bytes(pickup_bytes)).unsqueeze(0).to(device)
    img_b = preprocess(_load_image_from_bytes(return_bytes)).unsqueeze(0).to(device)

    device_type = "cuda" if device.startswith("cuda") else "cpu"
    with torch.no_grad(), torch.autocast(device_type=device_type, enabled=device_type == "cuda"):
        emb_a = model.encode_image(img_a)
        emb_b = model.encode_image(img_b)

    emb_a = emb_a / emb_a.norm(dim=-1, keepdim=True)
    emb_b = emb_b / emb_b.norm(dim=-1, keepdim=True)
    similarity = (emb_a * emb_b).sum(dim=-1).item()
    return float(similarity)


def _det_to_xyxy(det: Dict) -> Tuple[float, float, float, float]:
    x = float(det["x"])
    y = float(det["y"])
    w = float(det["width"])
    h = float(det["height"])
    return x, y, x + w, y + h


def _iou(box_a: Tuple[float, float, float, float], box_b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    return inter_area / denom if denom > 0 else 0.0


def find_new_damages(
    pickup_detections: List[Dict],
    return_detections: List[Dict],
    iou_threshold: float = 0.3,
) -> List[Dict]:
    """
    Mark damages present in the return image that were not seen in the pickup image.
    Matching is based on class name and IoU overlap with pickup boxes.
    """
    pickup_by_class = {}
    for det in pickup_detections:
        pickup_by_class.setdefault(det["class"], []).append(det)

    new_items: List[Dict] = []
    for ret_det in return_detections:
        candidates = pickup_by_class.get(ret_det["class"], [])
        ret_box = _det_to_xyxy(ret_det)

        matched = False
        for cand in candidates:
            if _iou(ret_box, _det_to_xyxy(cand)) >= iou_threshold:
                matched = True
                break
        if not matched:
            new_items.append(ret_det)
    return new_items


def analyze_pickup_return(
    pickup_bytes: bytes,
    return_bytes: bytes,
    *,
    iou_threshold: float = 0.3,
    compute_similarity: bool = True,
) -> Dict:
    """
    Run full pipeline: similarity + YOLO detections + new damage diff.
    """
    pickup_dets = analyzer.analyze_image_bytes(pickup_bytes)
    return_dets = analyzer.analyze_image_bytes(return_bytes)

    similarity = None
    if compute_similarity:
        similarity = compute_similarity_bytes(pickup_bytes, return_bytes)

    new_damages = find_new_damages(pickup_dets, return_dets, iou_threshold=iou_threshold)
    return {
        "similarity": similarity,
        "pickup_detections": pickup_dets,
        "return_detections": return_dets,
        "new_damages": new_damages,
    }
