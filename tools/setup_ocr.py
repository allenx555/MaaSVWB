from __future__ import annotations

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCR_URL = "https://download.maafw.xyz/MaaCommonAssets/OCR/ppocr_v6/ppocr_v6-small.zip"
REQUIRED_FILES = ("det.onnx", "rec.onnx", "keys.txt")


def ensure_ocr_model(project_root: Path = PROJECT_ROOT) -> Path:
    target = project_root / "assets" / "resource" / "model" / "ocr"
    if all((target / name).is_file() for name in REQUIRED_FILES):
        print(f"OCR model is ready: {target}")
        return target

    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maasvwb-ocr-") as temp_dir:
        archive = Path(temp_dir) / "ocr.zip"
        print(f"Downloading OCR model: {OCR_URL}")
        urllib.request.urlretrieve(OCR_URL, archive)
        with zipfile.ZipFile(archive) as package:
            package.extractall(target)

    missing = [name for name in REQUIRED_FILES if not (target / name).is_file()]
    if missing:
        shutil.rmtree(target)
        raise RuntimeError(f"OCR 模型缺少文件: {', '.join(missing)}")
    print(f"OCR model is ready: {target}")
    return target


if __name__ == "__main__":
    ensure_ocr_model()
