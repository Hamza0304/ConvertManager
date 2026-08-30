import json
from pathlib import Path


SETTINGS_FILE = Path(__file__).resolve().parents[2] / "settings.json"

DEFAULT_SETTINGS = {
    "output_location": "desktop",
    "custom_output_folder": "",
    "file_handling": "create_copy",
    "include_subfolders": False,
    "auto_open_output": False,
    "show_result": True,
}


def load_settings():
    settings = DEFAULT_SETTINGS.copy()

    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as file:
                saved = json.load(file)
            if isinstance(saved, dict):
                settings.update({key: value for key, value in saved.items() if key in settings})
        except (OSError, json.JSONDecodeError):
            pass

    return settings


def save_settings(settings):
    try:
        with SETTINGS_FILE.open("w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2, ensure_ascii=False)
    except OSError:
        pass
