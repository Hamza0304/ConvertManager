## ConvertManager

ConvertManager is a Windows desktop file conversion application built with
CustomTkinter, TkinterDnD2, Pillow, PyMuPDF, ReportLab, and Python's standard
library.

### Run

```bash
python -m pip install -r requirements.txt
python main.py
```

### Supported conversions

- Images: TIFF, TIF, JPG, JPEG, PNG, BMP, WEBP
- Images to PDF and PDF to images
- DOCX to TXT or PDF
- TXT to DOCX or PDF
- Any supported file to ZIP
- ZIP to a dedicated extracted folder

The default output is the current user's Desktop in `ConvertManager_Output`.
The original imported files are never deleted or modified. Conversion history
is saved locally in `history.json` and remains available after restarting.

### Settings

The Settings section is available at the bottom of the scrollable dashboard.
It persists the following choices in `settings.json`:

- Desktop or custom output folder
- Create copies, skip, or replace existing output files
- Include supported files in subfolders
- Open the output folder after conversion
- Show or hide the result window

During conversion, the action button becomes a cancellable operation. Cancelling
stops before the next file and keeps imported files available for another run.

### Importing large files

Importing validates file existence, permissions, size, and supported extension
in a background worker. ConvertManager stores the original path; it does not copy
or load the complete file into memory just to display it. File selection, folder
scanning, and Drag & Drop show a separate import status and can be cancelled.
Folder scanning does not follow directory symbolic links.

### Licensing

The Flask License Server database is the authoritative source for commercial
licenses and device activations. The desktop application stores only its stable
device ID and a cache of the last successful server response; it cannot create
or activate a commercial license locally. A new installation still receives a
persistent seven-day trial.

### License API integration

The desktop client uses `app/services/license_api.py` as the only HTTP boundary.
The default development endpoint is `http://127.0.0.1:5000/api/license`; set
`CONVERTMANAGER_LICENSE_API_URL` for production. No API secret is stored in the application. Activation,
startup validation, refresh, and device deactivation run in background threads.
The last successful license remains available during the configurable offline
grace period, and network failures are reported without blocking conversion.


Deployment configuration updated.
