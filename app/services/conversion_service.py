from pathlib import Path
import shutil
import tempfile

from app.converters.image_converter import convert_image
from app.converters.archive_converter import create_zip, extract_zip
from app.converters.document_converter import (
    docx_to_pdf,
    docx_to_txt,
    pdf_to_docx,
    pdf_to_txt,
    text_to_pdf,
    txt_to_docx,
)
from app.converters.pdf_converter import image_to_pdf, pdf_to_images
from app.utils.file_detector import detect_format, is_supported


def create_output_folder(input_files, output_format, selected_output=None):
    """
    Create a separate folder for converted files.
    """

    # If the user manually selected an output folder,
    # use that folder.
    if selected_output:
        output_folder = Path(selected_output)
        output_folder.mkdir(parents=True, exist_ok=True)
        return output_folder

    # Otherwise create the folder automatically
    # beside the selected files.
    if not input_files:
        raise ValueError("No files selected.")

    first_file = Path(input_files[0])

    parent_folder = first_file.parent

    output_folder = (
        parent_folder / f"ConvertManager_{output_format.upper()}"
    )

    output_folder.mkdir(parents=True, exist_ok=True)

    return output_folder


def convert_files(
    files,
    output_format,
    selected_output=None,
    progress_callback=None,
    file_handling="create_copy",
    cancel_event=None
):

    if not files:
        raise ValueError("No files selected.")

    output_folder = create_output_folder(
        files,
        output_format,
        selected_output
    )

    total = len(files)

    successful = 0
    failed = 0
    errors = []
    skipped = 0
    cancelled = False
    input_formats = []

    for file_path in files:
        detected = detect_format(file_path)
        if detected not in input_formats:
            input_formats.append(detected)

    for index, file_path in enumerate(files, start=1):

        if cancel_event and cancel_event.is_set():
            cancelled = True
            break

        try:

            if not is_supported(file_path):
                raise ValueError(
                    "Unsupported file format"
                )

            with tempfile.TemporaryDirectory(prefix="convertmanager-") as temporary:
                temporary_result = convert_one_file(
                    file_path,
                    Path(temporary),
                    output_format,
                    cancel_event=cancel_event
                )

                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    break

                produced = temporary_result if isinstance(temporary_result, list) else [temporary_result]
                moved = 0
                for source in produced:
                    destination = _resolve_destination(
                        Path(source),
                        output_folder,
                        file_handling
                    )
                    if destination is None:
                        skipped += 1
                        continue
                    if destination.exists() and file_handling == "replace":
                        if destination.is_dir():
                            shutil.rmtree(destination)
                        else:
                            destination.unlink()
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                    moved += 1

            if moved:
                successful += 1

        except Exception as error:

            failed += 1

            errors.append({
                "file": str(file_path),
                "input_format": detect_format(file_path),
                "output_format": output_format.upper(),
                "error": str(error)
            })

        if progress_callback:
            progress_callback(index, total)

    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "cancelled": cancelled,
        "errors": errors,
        "input_formats": input_formats,
        "output_folder": str(output_folder)
    }


def _resolve_destination(source, output_folder, file_handling):
    destination = Path(output_folder) / source.name

    if not destination.exists():
        return destination
    if file_handling == "skip":
        return None
    if file_handling == "replace":
        return destination

    stem = destination.stem
    suffix = destination.suffix
    counter = 1
    while True:
        candidate = destination.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def convert_one_file(file_path, output_folder, output_format, cancel_event=None):
    input_format = detect_format(file_path)
    target = output_format.upper()

    image_formats = {"PNG", "JPG", "JPEG", "TIFF", "BMP", "WEBP"}

    if input_format in {"TIFF", "PNG", "JPG", "JPEG", "BMP", "WEBP"}:
        if target in image_formats:
            return convert_image(file_path, output_folder, target)
        if target == "PDF":
            return image_to_pdf(file_path, output_folder)

    if input_format == "PDF" and target in image_formats:
        return pdf_to_images(file_path, output_folder, target, cancel_event)

    if input_format == "PDF" and target == "DOCX":
        return pdf_to_docx(file_path, output_folder, cancel_event)

    if input_format == "PDF" and target == "TXT":
        return pdf_to_txt(file_path, output_folder, cancel_event)

    if input_format == "DOCX":
        if target == "TXT":
            return docx_to_txt(file_path, output_folder)
        if target == "PDF":
            return docx_to_pdf(file_path, output_folder)

    if input_format == "TXT":
        if target == "DOCX":
            return txt_to_docx(file_path, output_folder)
        if target == "PDF":
            return text_to_pdf(file_path, output_folder)

    if target == "ZIP" and input_format != "ZIP":
        return create_zip(file_path, output_folder)

    if input_format == "ZIP" and target in {"EXTRACT", "FOLDER"}:
        return extract_zip(file_path, output_folder)

    raise ValueError(f"Conversion from {input_format} to {target} is not supported")