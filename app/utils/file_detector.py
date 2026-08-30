from pathlib import Path


SUPPORTED_FORMATS = {
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".bmp": "BMP",
    ".webp": "WEBP",
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".zip": "ZIP",
}


def detect_format(file_path):
    extension = Path(file_path).suffix.lower()
    return SUPPORTED_FORMATS.get(extension, "UNKNOWN")


def is_supported(file_path):
    return Path(file_path).suffix.lower() in SUPPORTED_FORMATS