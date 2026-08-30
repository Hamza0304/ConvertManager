from pathlib import Path

from PIL import Image


def image_to_pdf(input_path, output_folder):
    input_path = Path(input_path)
    output_path = Path(output_folder) / f"{input_path.stem}.pdf"

    with Image.open(input_path) as image:
        converted = image.convert("RGB")
        converted.save(output_path, "PDF", resolution=100.0)

    return output_path


def pdf_to_images(input_path, output_folder, output_format, cancel_event=None, progress_callback=None):
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError(
            "PDF conversion requires PyMuPDF. Install dependencies with: pip install -r requirements.txt"
        ) from error

    input_path = Path(input_path)
    output_folder = Path(output_folder)
    document = fitz.open(input_path)
    output_paths = []
    total_pages = len(document)

    try:
        for page_number, page in enumerate(document, start=1):
            if cancel_event and cancel_event.is_set():
                break
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            output_path = output_folder / f"{input_path.stem}_page_{page_number}.{output_format.lower()}"
            pixmap.save(str(output_path))
            output_paths.append(output_path)
            if progress_callback:
                progress_callback(page_number, total_pages)
    finally:
        document.close()

    return output_paths