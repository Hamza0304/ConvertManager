import os
from pathlib import Path

from app.utils.file_detector import SUPPORTED_FORMATS


SUPPORTED_EXTENSIONS = frozenset(SUPPORTED_FORMATS)


def normalized_path(file_path):
    return os.path.normcase(os.path.abspath(os.fspath(file_path)))


def validate_file(file_path):
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")

    try:
        size = path.stat().st_size
        with path.open("rb") as source:
            source.read(1)
    except OSError as error:
        raise PermissionError(f"Cannot access file: {path}") from error

    return {
        "path": str(path),
        "size": size,
    }


def import_files(file_paths, cancel_event=None, progress_callback=None):
    """Validate paths without copying or loading their contents into memory."""
    paths = [Path(path).expanduser().absolute() for path in file_paths]
    imported = []
    imported_keys = set()
    errors = []
    total = len(paths)

    for index, path in enumerate(paths, start=1):
        if cancel_event and cancel_event.is_set():
            break

        try:
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise ValueError("Unsupported file format")
            imported_path = validate_file(path)["path"]
            key = normalized_path(imported_path)
            if key not in imported_keys:
                imported.append(imported_path)
                imported_keys.add(key)
        except (OSError, ValueError) as error:
            errors.append({"file": str(path), "error": str(error)})

        if progress_callback:
            progress_callback(index, total, str(path))

    return imported, errors, bool(cancel_event and cancel_event.is_set())


def scan_folder(folder, recursive=False, cancel_event=None, progress_callback=None):
    """Scan supported files without following directory symlinks."""
    root = Path(folder).expanduser().absolute()
    imported = []
    imported_keys = set()
    errors = []
    scanned = 0

    if recursive:
        walker = os.walk(
            root,
            topdown=True,
            onerror=lambda error: errors.append({
                "file": getattr(error, "filename", str(root)),
                "error": str(error),
            }),
            followlinks=False
        )
    else:
        try:
            entries = list(root.iterdir())
        except OSError as error:
            return [], [{"file": str(root), "error": str(error)}], False
        walker = [(str(root), [], [entry.name for entry in entries])]

    for current_root, directories, filenames in walker:
        if cancel_event and cancel_event.is_set():
            return imported, errors, True

        directories[:] = [
            directory for directory in directories
            if not (Path(current_root) / directory).is_symlink()
        ]

        for filename in filenames:
            if cancel_event and cancel_event.is_set():
                return imported, errors, True

            scanned += 1
            path = Path(current_root) / filename
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                try:
                    imported_path = validate_file(path)["path"]
                    if normalized_path(imported_path) not in imported_keys:
                        imported.append(imported_path)
                        imported_keys.add(normalized_path(imported_path))
                except (OSError, ValueError) as error:
                    errors.append({"file": str(path), "error": str(error)})

            if progress_callback:
                progress_callback(scanned, None, str(path))

    return imported, errors, False


def import_dropped_items(items, recursive=False, cancel_event=None, progress_callback=None):
    imported = []
    imported_keys = set()
    errors = []
    processed = 0

    for item in items:
        if cancel_event and cancel_event.is_set():
            return imported, errors, True

        path = Path(item)
        if path.is_dir():
            found, scan_errors, cancelled = scan_folder(
                path,
                recursive=recursive,
                cancel_event=cancel_event,
                progress_callback=progress_callback
            )
            for found_path in found:
                if normalized_path(found_path) not in imported_keys:
                    imported.append(found_path)
                    imported_keys.add(normalized_path(found_path))
            errors.extend(scan_errors)
            if cancelled:
                return imported, errors, True
        else:
            found, import_errors, cancelled = import_files(
                [path],
                cancel_event=cancel_event,
                progress_callback=lambda current, total, current_path: progress_callback(
                    processed + current, None, current_path
                ) if progress_callback else None
            )
            for found_path in found:
                if normalized_path(found_path) not in imported_keys:
                    imported.append(found_path)
                    imported_keys.add(normalized_path(found_path))
            errors.extend(import_errors)
            if cancelled:
                return imported, errors, True

        processed += 1

    return imported, errors, False
