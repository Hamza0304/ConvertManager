from pathlib import Path
from PIL import Image


OUTPUT_FORMATS = {
    "PNG": "PNG",
    "JPG": "JPEG",
    "JPEG": "JPEG",
    "TIFF": "TIFF",
    "BMP": "BMP",
    "WEBP": "WEBP",
}


def convert_image(input_path, output_folder, output_format):
    input_path = Path(input_path)
    output_folder = Path(output_folder)

    output_folder.mkdir(parents=True, exist_ok=True)

    output_extension = output_format.lower()

    if output_extension == "jpeg":
        output_extension = "jpg"

    output_path = output_folder / f"{input_path.stem}.{output_extension}"

    with Image.open(input_path) as image:

        # JPG does not support transparency.
        if output_format in ("JPG", "JPEG"):
            if image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", image.size, "white")

                if image.mode == "P":
                    image = image.convert("RGBA")

                if image.mode in ("RGBA", "LA"):
                    background.paste(
                        image,
                        mask=image.getchannel("A")
                    )
                else:
                    background.paste(image)

                image = background
            else:
                image = image.convert("RGB")

        elif image.mode == "P":
            image = image.convert("RGBA")

        image.save(
            output_path,
            format=OUTPUT_FORMATS[output_format]
        )

    return output_path