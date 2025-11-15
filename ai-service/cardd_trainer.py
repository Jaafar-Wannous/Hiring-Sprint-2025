"""
Utilities for downloading the CarDD dataset, converting it into YOLO format,
and fine-tuning an Ultralytics YOLO model.

Typical usage (from the ai-service directory):

    python cardd_trainer.py --dataset-dir data/cardd_raw \
        --yolo-dataset-dir data/cardd_yolo \
        --model yolov8n.pt --epochs 100 --imgsz 960 --batch 8

By default the script will:
1. Download the CarDD dataset snapshot from Hugging Face (skipped when the
   files are already present locally).
2. Convert the FiftyOne samples.json annotations into YOLO txt files while
   preserving the official train/val/test split ratios.
3. Launch Ultralytics training and store the resulting weights inside
   runs/detect/train.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable

try:
    import torch
except Exception:  # pragma: no cover - torch is optional for CPU-only users
    torch = None

from huggingface_hub import snapshot_download
from ultralytics import YOLO

# Constants describing where to pull CarDD from and which classes exist.
CARD_DD_REPO_ID = "harpreetsahota/CarDD"
CARD_DD_CLASSES = [
    "dent",
    "scratch",
    "crack",
    "glass shatter",
    "lamp broken",
    "tire flat",
]

# Additional augmentations that help the model generalize to various lighting
# and viewing conditions commonly seen in inspection photos.
ADVANCED_AUGMENTATION_KWARGS: Dict[str, Any] = {
    "cos_lr": True,
    "close_mosaic": 10,
    "mixup": 0.15,
    "mosaic": 1.0,
    "scale": 0.7,
    "degrees": 5.0,
    "shear": 1.0,
    "translate": 0.1,
    "flipud": 0.05,
    "fliplr": 0.5,
    "hsv_h": 0.02,
    "hsv_s": 0.7,
    "hsv_v": 0.4,
}


def _normalize_path(path_str: str) -> Path:
    """
    Resolve user-provided paths while gracefully handling duplicated 'ai-service/' prefixes.
    """
    script_root = Path(__file__).resolve().parent
    path = Path(path_str)
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] == script_root.name:
        trimmed = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        return (script_root / trimmed).resolve()
    return (script_root / path).resolve()


def _validate_device(device: str | None) -> str | None:
    if not device:
        return None
    normalized = str(device).strip()
    if normalized.lower() == "cpu":
        return "cpu"
    if torch is None:
        raise ValueError(
            f"--device {normalized!r} requested but the installed torch build lacks CUDA support."
        )
    if not torch.cuda.is_available():
        raise ValueError(
            f"--device {normalized!r} requested but torch reports no CUDA GPUs. "
            "Install a CUDA-enabled torch build or use --device cpu."
        )
    return normalized


def _validate_numeric_args(args: argparse.Namespace) -> None:
    if args.imgsz < 64 or args.imgsz > 4096:
        raise ValueError("--imgsz must be between 64 and 4096 pixels")
    if args.batch < 1:
        raise ValueError("--batch must be a positive integer")
    if args.max_images is not None and args.max_images <= 0:
        raise ValueError("--max-images must be positive when provided")
    if not (0 < args.train_ratio < 1 and 0 < args.val_ratio < 1):
        raise ValueError("Train/val ratios must be in the (0, 1) range")
    if args.train_ratio + args.val_ratio >= 0.99:
        raise ValueError("Train + val ratio must leave room for a test split")


def _ensure_dataset_ready(dataset_dir: Path, skip_download: bool) -> None:
    samples_path = dataset_dir / "samples.json"
    if not samples_path.exists() and skip_download:
        raise FileNotFoundError(
            f"Expected CarDD annotations at {samples_path}. "
            "Either run without --skip-download or supply the correct --dataset-dir."
        )


def download_cardd_dataset(destination: Path, repo_id: str, revision: str | None) -> Path:
    """
    Download (or reuse) the CarDD snapshot from Hugging Face.
    """
    destination.mkdir(parents=True, exist_ok=True)
    logging.info("Ensuring CarDD dataset is available at %s", destination)
    snapshot_path = snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        allow_patterns=["data/*", "samples.json"],
        local_dir=str(destination),
        local_dir_use_symlinks=False,
    )
    return Path(snapshot_path)


def _sample_random_value(sample: Dict) -> float:
    """
    Return a deterministic pseudo-random float for the sample.
    """
    rand_value = sample.get("_rand")
    try:
        rand_value = float(rand_value)
    except (TypeError, ValueError):
        rand_value = None

    if rand_value is not None and 0.0 <= rand_value <= 1.0 and 0.05 <= rand_value <= 0.95:
        return rand_value

    identifier = (
        sample.get("filepath")
        or sample.get("_id", {}).get("$oid")
        or json.dumps(sample, sort_keys=True)
    )
    digest = hashlib.md5(identifier.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(0xFFFFFFFFFFFFFFFF)


def _decide_split(rand_value: float, train_ratio: float, val_ratio: float) -> str:
    """
    Map the provided value to a dataset split.
    """
    if rand_value < train_ratio:
        return "train"
    if rand_value < train_ratio + val_ratio:
        return "val"
    return "test"


def _materialize_image(
    src: Path,
    dst: Path,
    prefer_copy: bool,
) -> None:
    """
    Copy or hardlink the source image so that Ultralytics sees the expected structure.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return

    if prefer_copy:
        shutil.copy2(src, dst)
        return

    try:
        os.link(src, dst)
    except OSError:
        # Fall back to copying when hard-links are not supported (e.g. FAT32, WSL).
        shutil.copy2(src, dst)


def convert_to_yolo(
    dataset_dir: Path,
    output_dir: Path,
    *,
    train_ratio: float,
    val_ratio: float,
    max_images: int | None,
    prefer_copy: bool,
) -> Path:
    """
    Build YOLO-friendly directories (images/labels per split) for CarDD.
    """
    samples_path = dataset_dir / "samples.json"
    if not samples_path.exists():
        raise FileNotFoundError(f"Missing CarDD annotations file: {samples_path}")

    if output_dir.exists():
        logging.info("Cleaning previous YOLO dataset at %s", output_dir)
        shutil.rmtree(output_dir)

    logging.info("Converting CarDD annotations into YOLO format at %s", output_dir)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "labels").mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    with samples_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    processed = 0
    split_counts = {"train": 0, "val": 0, "test": 0}
    for sample in payload.get("samples", []):
        if max_images and processed >= max_images:
            break

        rel_image = sample.get("filepath")
        if not rel_image:
            continue
        source_image = dataset_dir / rel_image
        if not source_image.exists():
            logging.warning("Skipping %s because image is missing", rel_image)
            continue

        rand_value = _sample_random_value(sample)
        split = _decide_split(rand_value, train_ratio, val_ratio)

        detections = sample.get("detections", {}).get("detections") or []
        label_lines = list(_format_label_lines(detections))
        if not label_lines:
            # Images without annotations are not very useful for detection.
            continue

        split_images = output_dir / "images" / split
        split_labels = output_dir / "labels" / split
        split_images.mkdir(parents=True, exist_ok=True)
        split_labels.mkdir(parents=True, exist_ok=True)

        image_name = Path(rel_image).name
        label_name = Path(image_name).with_suffix(".txt").name

        _materialize_image(source_image, split_images / image_name, prefer_copy)
        (split_labels / label_name).write_text("\n".join(label_lines), encoding="utf-8")
        processed += 1
        split_counts[split] += 1

    if processed == 0:
        raise RuntimeError("No images were converted - ensure the dataset was downloaded correctly")

    logging.info(
        "Prepared %s annotated images (train=%s, val=%s, test=%s)",
        processed,
        split_counts["train"],
        split_counts["val"],
        split_counts["test"],
    )
    yaml_path = _write_dataset_yaml(output_dir)
    return yaml_path


def _format_label_lines(detections: Iterable[Dict]) -> Iterable[str]:
    """
    Transform the detection dictionaries into YOLO label rows.
    """
    for det in detections:
        label = det.get("label")
        bbox = det.get("bounding_box")
        if label not in CARD_DD_CLASSES or not bbox:
            continue

        class_id = CARD_DD_CLASSES.index(label)
        x_min, y_min, width, height = bbox
        x_center = x_min + width / 2
        y_center = y_min + height / 2

        def _clip(value: float) -> float:
            return max(0.0, min(1.0, float(value)))

        x_center = _clip(x_center)
        y_center = _clip(y_center)
        width = _clip(width)
        height = _clip(height)

        yield f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def _write_dataset_yaml(output_dir: Path) -> Path:
    """
    Emit the Ultralytics data config file that references the converted dataset.
    """
    yaml_path = output_dir / "cardd.yaml"
    yaml_content = [
        f"path: {output_dir.resolve()}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        f"nc: {len(CARD_DD_CLASSES)}",
        "names:",
    ]
    yaml_content.extend([f"  - {name}" for name in CARD_DD_CLASSES])
    yaml_path.write_text("\n".join(yaml_content) + "\n", encoding="utf-8")
    return yaml_path


def train_yolo(
    model_path: str,
    data_yaml: Path,
    epochs: int,
    imgsz: int,
    batch: int,
    device: str | None,
    workers: int,
    patience: int,
    project: str,
    run_name: str,
    *,
    extra_train_kwargs: Dict[str, Any] | None = None,
) -> None:
    """
    Launch Ultralytics training with the prepared dataset.
    """
    logging.info("Starting YOLO training with %s", model_path)
    model = YOLO(model_path)
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        workers=workers,
        patience=patience,
        project=project,
        name=run_name,
        **(extra_train_kwargs or {}),
    )


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO on the CarDD dataset")
    parser.add_argument("--dataset-dir", default="data/cardd_raw", help="Where the raw CarDD snapshot is stored/downloaded")
    parser.add_argument("--yolo-dataset-dir", default="data/cardd_yolo", help="Where the YOLO-formatted dataset should be generated")
    parser.add_argument("--repo-id", default=CARD_DD_REPO_ID, help="Hugging Face dataset repository to download")
    parser.add_argument("--revision", default=None, help="Optional dataset revision/tag")
    parser.add_argument("--skip-download", action="store_true", help="Skip pulling from Hugging Face (expects dataset to exist locally)")
    parser.add_argument("--skip-train", action="store_true", help="Prepare data only without running YOLO training")
    parser.add_argument("--max-images", type=int, default=None, help="Limit the number of images (useful for quick smoke tests)")
    parser.add_argument("--train-ratio", type=float, default=0.704, help="Train split ratio")
    parser.add_argument("--val-ratio", type=float, default=0.2025, help="Validation split ratio")
    parser.add_argument("--prefer-copy", action="store_true", help="Copy images instead of creating hardlinks/symlinks")
    parser.add_argument("--model", default="yolov8m.pt", help="Base YOLO model checkpoint")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default=None, help="Device passed to Ultralytics (e.g. '0', 'cpu')")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--patience", type=int, default=50)
    parser.add_argument("--optimizer", default="AdamW", help="Optimizer to use during training")
    parser.add_argument("--lr0", type=float, default=0.0007, help="Initial learning rate")
    parser.add_argument("--lrf", type=float, default=0.01, help="Final learning rate fraction")
    parser.add_argument("--momentum", type=float, default=0.937, help="Optimizer momentum / beta1")
    parser.add_argument("--weight-decay", type=float, default=0.0005, help="Weight decay factor")
    parser.add_argument("--warmup-epochs", type=float, default=3.0, help="Warmup epochs")
    parser.add_argument("--warmup-momentum", type=float, default=0.8, help="Warmup momentum start value")
    parser.add_argument("--warmup-bias-lr", type=float, default=0.1, help="Warmup learning rate for bias")
    parser.add_argument(
        "--disable-advanced-augmentations",
        dest="advanced_aug",
        action="store_false",
        help="Use vanilla YOLO augmentations without the inspection-specific tweaks",
    )
    parser.set_defaults(advanced_aug=True)
    parser.add_argument("--project", default="runs/detect", help="Training project directory")
    parser.add_argument("--name", default="cardd", help="Training run name")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    dataset_dir = _normalize_path(args.dataset_dir)
    yolo_dataset_dir = _normalize_path(args.yolo_dataset_dir)

    _validate_numeric_args(args)
    args.device = _validate_device(args.device)

    if not args.skip_download:
        download_cardd_dataset(dataset_dir, args.repo_id, args.revision)
    else:
        logging.info("Skipping dataset download as requested")

    _ensure_dataset_ready(dataset_dir, args.skip_download)

    data_yaml = convert_to_yolo(
        dataset_dir,
        yolo_dataset_dir,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        max_images=args.max_images,
        prefer_copy=args.prefer_copy,
    )

    if args.skip_train:
        logging.info("Training step skipped. Dataset is ready at %s", data_yaml)
        return

    extra_train_kwargs: Dict[str, Any] = {
        "optimizer": args.optimizer,
        "lr0": args.lr0,
        "lrf": args.lrf,
        "momentum": args.momentum,
        "weight_decay": args.weight_decay,
        "warmup_epochs": args.warmup_epochs,
        "warmup_momentum": args.warmup_momentum,
        "warmup_bias_lr": args.warmup_bias_lr,
    }
    if args.advanced_aug:
        extra_train_kwargs.update(ADVANCED_AUGMENTATION_KWARGS)

    train_yolo(
        args.model,
        data_yaml,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        project=args.project,
        run_name=args.name,
        extra_train_kwargs=extra_train_kwargs,
    )


if __name__ == "__main__":
    main()
