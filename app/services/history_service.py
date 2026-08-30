import json
from datetime import datetime
from pathlib import Path


HISTORY_FILE = Path(__file__).resolve().parents[2] / "history.json"


def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            history = json.load(file)

        return history if isinstance(history, list) else []

    except (OSError, json.JSONDecodeError):
        return []


def add_history_record(
    input_formats,
    output_format,
    total,
    successful,
    failed,
    output_folder,
    skipped=0,
    status="Completed",
    duration=0
):
    history = load_history()
    record = {
        "date": datetime.now().strftime("%d %b %Y"),
        "time": datetime.now().strftime("%I:%M %p"),
        "files": total,
        "input_formats": input_formats,
        "output_format": output_format,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "status": status,
        "duration": round(duration, 2),
        "output_folder": output_folder,
    }

    history.insert(0, record)

    _save_history(history)

    return record


def clear_history():
    """Remove history records only; never touch referenced output files."""
    _save_history([])
    return []


def delete_history_record(index):
    """Delete one record by its current display index."""
    history = load_history()

    if not isinstance(index, int) or not 0 <= index < len(history):
        return False

    history.pop(index)
    _save_history(history)
    return True


def _save_history(history):
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = HISTORY_FILE.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(history, file, indent=2, ensure_ascii=False)
        temporary.replace(HISTORY_FILE)
    except OSError:
        return False

    return True
