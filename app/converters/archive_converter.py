from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def create_zip(input_path, output_folder):
    input_path = Path(input_path)
    output_path = Path(output_folder) / f"{input_path.stem}.zip"

    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        archive.write(input_path, arcname=input_path.name)

    return output_path


def extract_zip(input_path, output_folder):
    input_path = Path(input_path)
    destination = Path(output_folder) / input_path.stem
    destination.mkdir(parents=True, exist_ok=True)

    with ZipFile(input_path) as archive:
        destination_root = destination.resolve()

        for member in archive.infolist():
            target = (destination / member.filename).resolve()

            if destination_root not in target.parents and target != destination_root:
                raise ValueError("Unsafe ZIP entry outside the output folder")

        archive.extractall(destination)

    return destination