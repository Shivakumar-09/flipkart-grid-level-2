import logging
import os
import tempfile
import threading
import time

logger = logging.getLogger("TrafficFlowRuntime")

YOLO_CONFIG_DIR = os.environ.setdefault(
    "YOLO_CONFIG_DIR",
    os.path.join(tempfile.gettempdir(), "Ultralytics")
)
try:
    os.makedirs(YOLO_CONFIG_DIR, exist_ok=True)
except OSError as exc:
    logger.warning(f"Could not create YOLO_CONFIG_DIR at {YOLO_CONFIG_DIR}: {exc}")

_YOLO_CACHE = {}
_YOLO_LOCK = threading.Lock()
_RUNTIME_DEVICE = None


def get_runtime_device():
    """
    Pick a GPU automatically when torch reports CUDA availability.
    Ultralytics accepts device 0 for CUDA and 'cpu' otherwise.
    """
    global _RUNTIME_DEVICE
    if _RUNTIME_DEVICE is not None:
        return _RUNTIME_DEVICE

    requested = os.environ.get("TRAFFICFLOW_DEVICE", "").strip().lower()
    if requested:
        _RUNTIME_DEVICE = requested
        return _RUNTIME_DEVICE

    try:
        import torch
        _RUNTIME_DEVICE = 0 if torch.cuda.is_available() else "cpu"
    except Exception:
        _RUNTIME_DEVICE = "cpu"
    return _RUNTIME_DEVICE


def get_yolo_model(model_path):
    """
    Load each YOLO model once per process and share it across detector objects.
    """
    key = os.path.abspath(model_path) if os.path.exists(model_path) else model_path
    with _YOLO_LOCK:
        cached = _YOLO_CACHE.get(key)
        if cached is not None:
            return cached["model"], cached["device"], cached["load_ms"], True

        started = time.perf_counter()
        from ultralytics import YOLO

        model = YOLO(model_path)
        device = get_runtime_device()
        try:
            model.to(device)
        except Exception as exc:
            logger.info(f"YOLO model {model_path} could not be moved to {device}: {exc}")

        load_ms = (time.perf_counter() - started) * 1000
        _YOLO_CACHE[key] = {
            "model": model,
            "device": device,
            "load_ms": load_ms
        }
        return model, device, load_ms, False


def get_resource_snapshot():
    """
    Best-effort resource snapshot used in profiling responses and reports.
    """
    snapshot = {
        "device": get_runtime_device(),
        "cpu_percent": None,
        "memory_mb": None,
        "gpu_memory_mb": None,
        "gpu_name": None
    }

    try:
        import psutil
        proc = psutil.Process(os.getpid())
        snapshot["cpu_percent"] = psutil.cpu_percent(interval=None)
        snapshot["memory_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass

    try:
        import torch
        if torch.cuda.is_available():
            idx = 0
            snapshot["gpu_name"] = torch.cuda.get_device_name(idx)
            snapshot["gpu_memory_mb"] = round(torch.cuda.memory_allocated(idx) / (1024 * 1024), 1)
    except Exception:
        pass

    return snapshot


def empty_stage_profile():
    return {
        "image_load_ms": 0.0,
        "image_resize_ms": 0.0,
        "preprocess_ms": 0.0,
        "vehicle_detection_ms": 0.0,
        "plate_detection_ms": 0.0,
        "ocr_ms": 0.0,
        "rider_association_ms": 0.0,
        "helmet_ms": 0.0,
        "seatbelt_ms": 0.0,
        "wrong_side_ms": 0.0,
        "stop_line_ms": 0.0,
        "red_light_ms": 0.0,
        "evidence_generation_ms": 0.0,
        "database_ms": 0.0,
        "total_inference_ms": 0.0
    }


def add_ms(profile, key, started):
    profile[key] = round(profile.get(key, 0.0) + ((time.perf_counter() - started) * 1000), 2)
