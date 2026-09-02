
import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD
from tkinter import filedialog, messagebox
from pathlib import Path
import os
import threading
import time
import webbrowser
from PIL import Image

from app.services.conversion_service import convert_files
from app.services.history_service import (
    add_history_record,
    clear_history,
    delete_history_record,
    load_history,
)
from app.services.settings_service import load_settings, save_settings
from app.services.file_service import import_dropped_items, import_files, normalized_path, scan_folder
from app.services.license_service import LicenseService
from app.services.license_api import LicenseAPI, LicenseAPIError
from app.utils.file_detector import detect_format


class MainWindow(ctk.CTk, TkinterDnD.DnDWrapper):

    def __init__(self):
        super().__init__()

        # Initialize Drag & Drop
        self.TkdndVersion = TkinterDnD._require(self)

        # Window
        self.title("ConvertManager")
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "branding" / "ConvertManager.ico"

        if icon_path.exists():
            self.iconbitmap(str(icon_path))
            self.geometry("1280x820")
            self.minsize(1024, 680)

        # Application data
        self.files = []
        self.settings = load_settings()
        self.license_service = LicenseService()
        self.license_api = LicenseAPI()
        self.output_folder = self.get_configured_output_folder()
        self.history = load_history()
        self.cancel_event = None
        self.conversion_started_at = None
        self.import_cancel_event = None

        # Setup
        self.setup_theme()
        self.create_layout()
        self.after(150, self.check_license_on_startup)

    def get_desktop_folder(self):

        candidates = []

        if os.name == "nt":

            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                ) as key:
                    desktop, _ = winreg.QueryValueEx(key, "Desktop")
                    candidates.append(Path(os.path.expandvars(desktop)))

            except (OSError, ImportError):
                pass

        candidates.append(Path.home() / "Desktop")

        for variable in ("OneDrive", "USERPROFILE"):

            value = os.environ.get(variable)

            if value:
                candidates.append(Path(value) / "Desktop")

        for candidate in candidates:

            if candidate.exists():
                output_folder = candidate / "ConvertManager_Output"
                output_folder.mkdir(parents=True, exist_ok=True)
                return output_folder

        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        output_folder = desktop / "ConvertManager_Output"
        output_folder.mkdir(parents=True, exist_ok=True)
        return output_folder

    def get_configured_output_folder(self):
        if self.settings.get("output_location") == "custom":
            custom = self.settings.get("custom_output_folder", "")
            if custom:
                folder = Path(custom)
                folder.mkdir(parents=True, exist_ok=True)
                return folder

        return self.get_desktop_folder()

    # =========================================================
    # THEME
    # =========================================================

    def setup_theme(self):

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bg_color = "#0F1117"
        self.sidebar_color = "#151821"
        self.card_color = "#1B1F2A"
        self.card_hover = "#252B3A"

        self.text_color = "#F8FAFC"
        self.secondary_text = "#94A3B8"

        self.accent_color = "#6C63FF"
        self.secondary_accent = "#8B5CF6"
        self.success_color = "#22C55E"
        self.warning_color = "#F59E0B"
        self.error_color = "#EF4444"
        self.border_color = "#2A3040"

        self.configure(
            fg_color=self.bg_color
        )

    # =========================================================
    # MAIN LAYOUT
    # =========================================================

    def create_layout(self):

        self.grid_columnconfigure(
            0,
            weight=0
        )

        self.grid_columnconfigure(
            1,
            weight=1
        )

        self.grid_rowconfigure(
            0,
            weight=1
        )

        self.create_sidebar()
        self.create_dashboard()

    # =========================================================
    # SIDEBAR
    # =========================================================

    def create_sidebar(self):

        self.sidebar = ctk.CTkFrame(
            self,
            width=248,
            corner_radius=0,
            fg_color=self.sidebar_color
        )

        self.sidebar.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        self.sidebar.grid_propagate(False)

        
        
        
        
        # -------------------------
        # Logo
        # -------------------------

        logo_frame = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent"
        )

        logo_frame.pack(
            fill="x",
            padx=22,
            pady=(30, 35)
        )
        # Logo image
        logo_path = Path(__file__).resolve().parents[2] / "assets" / "branding" / "ConvertManager.png"

        logo_image = ctk.CTkImage(
            light_image=Image.open(logo_path),
            dark_image=Image.open(logo_path),
            size=(45, 45)
        )

        logo = ctk.CTkLabel(
            logo_frame,
            text="",
            image=logo_image,
            width=45,
            height=45,
            
            fg_color="transparent",
        
        )

        logo.pack(
            side="left"
        )

        brand = ctk.CTkLabel(
            logo_frame,
            text="ConvertManager",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=18,
                weight="bold"
            )
        )

        # Brand name
        brand = ctk.CTkLabel(
            logo_frame,
            text="ConvertManager",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=18,
                weight="bold"
                )
        )

        brand.pack(
            side="left",
            padx=12
        )

        # -------------------------
        # Navigation
        # -------------------------

        nav_title = ctk.CTkLabel(
            self.sidebar,
            text="WORKSPACE",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=11,
                weight="bold"
            )
        )

        nav_title.pack(
            anchor="w",
            padx=25,
            pady=(0, 10)
        )

        self.create_nav_button(
            "⌂",
            "Dashboard",
            True,
            self.scroll_to_top
        )

        self.create_nav_button(
            "⚙",
            "Settings",
            False,
            self.open_settings_window
        )

        # -------------------------
        # License
        # -------------------------

        bottom = ctk.CTkFrame(
            self.sidebar,
            fg_color="transparent"
        )

        bottom.pack(
            side="bottom",
            fill="x",
            padx=20,
            pady=25
        )

        license_card = ctk.CTkFrame(
            bottom,
            fg_color=self.card_color,
            corner_radius=12
        )

        license_card.pack(
            fill="x"
        )

        self.license_status_label = ctk.CTkLabel(
            license_card,
            text="",
            text_color=self.success_color,
            font=ctk.CTkFont(
                size=11,
                weight="bold"
            )
        )
        self.license_status_label.pack(
            anchor="w",
            padx=15,
            pady=(14, 3)
        )

        self.license_detail_label = ctk.CTkLabel(
            license_card,
            text="",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=10
            )
        )
        self.license_detail_label.pack(
            anchor="w",
            padx=15,
            pady=(0, 14)
        )
        self.update_license_sidebar()

    # =========================================================
    # NAVIGATION BUTTON
    # =========================================================

    def create_nav_button(
        self,
        icon,
        text,
        active=False,
        command=None
    ):

        color = (
            self.card_color
            if active
            else "transparent"
        )

        button = ctk.CTkButton(
            self.sidebar,
            text=f"{icon}    {text}",
            anchor="w",
            height=45,
            corner_radius=10,
            fg_color=color,
            hover_color=self.card_hover,
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=14,
                weight="bold"
                if active
                else "normal"
            ),
            command=command or (lambda: None)
        )

        button.pack(
            fill="x",
            padx=15,
            pady=3
        )

    # =========================================================
    # DASHBOARD
    # =========================================================

    def create_dashboard(self):

        # Keep the sidebar fixed while the dashboard owns the available space.
        self.dashboard_host = ctk.CTkFrame(
            self,
            fg_color="transparent",
            corner_radius=0
        )

        self.dashboard_host.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=25,
            pady=20
        )

        self.dashboard_host.grid_rowconfigure(
            0,
            weight=1
        )

        self.dashboard_host.grid_columnconfigure(
            0,
            weight=1
        )

        # All dashboard sections live inside this scrollable content area.
        self.main = ctk.CTkScrollableFrame(
            self.dashboard_host,
            corner_radius=0,
            fg_color="transparent"
        )

        self.main.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self.main.grid_columnconfigure(
            0,
            weight=1,
            uniform="dashboard"
        )

        self.create_header()
        self.create_upload_card()
        self.create_stats()
        self.create_file_list()
        self.create_conversion_settings()
        self.create_progress_section()
        self.create_history_section()

    def scroll_to_top(self):
        self.main._parent_canvas.yview_moveto(0)

  
    def open_settings_window(self):
        if getattr(self, "settings_window", None) is not None:
            if self.settings_window.winfo_exists():
                self.settings_window.focus_force()
                self.settings_window.lift()
            return

        self.settings_window = ctk.CTkToplevel(self)
        self.settings_window.title("ConvertManager Settings")
        self.settings_window.geometry("620x680")
        self.settings_window.minsize(520, 600)
        self.settings_window.transient(self)

        # ConvertManager icon
        icon_path = (
        Path(__file__).resolve().parents[2]
            / "assets"
            / "branding"
            / "ConvertManager.ico"
        )

        if icon_path.exists():
            self.settings_window.iconbitmap(str(icon_path))

        # Scrollable settings area
        settings_scroll = ctk.CTkScrollableFrame(
            self.settings_window,
            fg_color="transparent",
            corner_radius=0
        )

        settings_scroll.pack(
            fill="both",
            expand=True,
            padx=0,
            pady=0
        )

        # Put all settings inside the scrollable area
        self.create_settings_section(settings_scroll)

        # When the window closes, reset the variable
        def on_settings_close():
            self.settings_window.destroy()
            self.settings_window = None
        self.settings_window.protocol("WM_DELETE_WINDOW", on_settings_close)

        # Keep the window in front
        self.settings_window.lift()
        self.settings_window.focus_force()


    def check_license_on_startup(self):
        status = self.license_service.get_status()
        if status not in {"ACTIVE", "TRIAL"}:
            self.open_license_window()
        elif status == "ACTIVE":
            self.start_online_validation()

    def start_online_validation(self):
        license_data = self.license_service.get_license()
        key = license_data.get("license_key")
        if not key:
            return

        def worker():
            try:
                response = self.license_api.validate_license(
                    key,
                    self.license_service.get_device_id()
                )
                success = self.license_service.save_server_license(response)
                self.after(0, self.finish_online_validation, success, "Connected")
            except LicenseAPIError as error:
                self.license_service.apply_server_error(error.code)
                if error.code == "NETWORK_ERROR":
                    self.license_service.record_validation_failure()
                    connection = "Offline"
                else:
                    connection = self.friendly_license_error(error)
                self.after(0, self.finish_online_validation, False, connection)

        threading.Thread(target=worker, daemon=True).start()

    def finish_online_validation(self, success, connection):
        self.update_license_sidebar()
        self.refresh_license_settings()
        if not success:
            self.open_license_window()

    @staticmethod
    def friendly_license_error(error):
        messages = {
            "INVALID_LICENSE": "Invalid license key.",
            "LICENSE_EXPIRED": "License expired.",
            "LICENSE_REVOKED": "This license has been revoked.",
            "LICENSE_ALREADY_ACTIVATED": "This license is already activated on another device.",
            "DEVICE_LIMIT_REACHED": "The device limit for this license has been reached.",
            "DEVICE_NOT_AUTHORIZED": "This device is not authorized for the license.",
            "INVALID_REQUEST": "The license request was invalid.",
            "SERVER_ERROR": "The license server returned an invalid response.",
            "RATE_LIMITED": "Too many attempts. Please try again later.",
            "NETWORK_ERROR": "Unable to connect to the license server.",
        }
        return messages.get(error.code, "The license server could not complete the request.")

    def update_license_sidebar(self):
        status = self.license_service.get_status()
        if status == "ACTIVE":
            self.license_status_label.configure(text="ACTIVE", text_color=self.success_color)
            self.license_detail_label.configure(
                text=f"{self.license_service.get_plan()} license"
            )
        elif status == "TRIAL":
            self.license_status_label.configure(
                text="FREE TRIAL",
                text_color=self.warning_color
            )
            self.license_detail_label.configure(
                text=f"{self.license_service.get_days_remaining()} days remaining"
            )
        else:
            self.license_status_label.configure(text=status, text_color=self.error_color)
            self.license_detail_label.configure(text="Activate to continue")
        if status in {"ACTIVE", "TRIAL"} and self.license_service.get_connection_status() == "OFFLINE":
            self.license_detail_label.configure(text=f"{self.license_detail_label.cget('text')} • Offline")

    def open_license_window(self):

        # If License window is already open, bring it to the front
        if getattr(self, "license_window", None) is not None:
            try:
                if self.license_window.winfo_exists():
                    self.license_window.deiconify()
                    self.license_window.lift()
                    self.license_window.focus_force()
                    return
            except Exception:
                self.license_window = None

        # Create License window
        window = ctk.CTkToplevel(self)

        self.license_window = window

        window.title("License / Activation")
        window.geometry("560x590")
        window.resizable(False, False)

        # Keep it connected to the main application
        window.transient(self)

        # Bring window to front
        window.lift()
        window.focus_force()

        # Center the window on the screen
        window.update_idletasks()

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        window_width = 560
        window_height = 590

        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2

        window.geometry(
            f"{window_width}x{window_height}+{x}+{y}"
        )

        # Window icon
        icon_path = (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "branding"
            / "ConvertManager.ico"
        )

        if icon_path.exists():
            window.iconbitmap(str(icon_path))

        # Close handler
        def on_close():
            self.license_window = None
            window.destroy()

        window.protocol(
            "WM_DELETE_WINDOW",
            on_close
        )

        # ==========================================
        # ConvertManager Logo
        # ==========================================

        logo_path = (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "branding"
            / "ConvertManager.png"
        )

        if logo_path.exists():

            self.license_logo_image = ctk.CTkImage(
                light_image=Image.open(logo_path),
                dark_image=Image.open(logo_path),
                size=(48, 48)
            )

            logo_label = ctk.CTkLabel(
                window,
                text="",
                image=self.license_logo_image,
                fg_color="transparent"
            )

            logo_label.pack(
                pady=(22, 5)
            )

        # ==========================================
        # Title
        # ==========================================

        ctk.CTkLabel(
            window,
            text="License / Activation",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=25,
                weight="bold"
            )
        ).pack(
            anchor="center",
            padx=30,
            pady=(5, 8)
        )

        # ==========================================
        # Subtitle
        # ==========================================

        ctk.CTkLabel(
            window,
            text="Activate, verify, or deactivate this computer's license.",
            text_color=self.secondary_text
        ).pack(
            anchor="center",
            padx=30,
            pady=(0, 22)
        )

        # ==========================================
        # License Status
        # ==========================================

        status = ctk.CTkLabel(
            window,
            text="",
            justify="left",
            anchor="w",
            text_color=self.secondary_text,
            fg_color=self.card_color,
            corner_radius=10,
            padx=16,
            pady=12,
        )

        status.pack(
            fill="x",
            padx=30,
            pady=(0, 16)
        )

        # ==========================================
        # License Key Entry
        # ==========================================

        entry = ctk.CTkEntry(
            window,
            width=460,
            height=44,
            placeholder_text="XXXX-XXXX-XXXX-XXXX"
        )

        entry.pack(
            padx=30,
            pady=5
        )

        # ==========================================
        # Message
        # ==========================================

        message = ctk.CTkLabel(
            window,
            text="",
            text_color=self.secondary_text,
            wraplength=480,
            justify="left"
        )

        message.pack(
            anchor="w",
            padx=30,
            pady=(8, 0)
        )

        def update_window_status():
            data = self.license_service.get_license()
            state = self.license_service.get_status()
            plan = self.license_service.get_plan()
            expires = data.get("expires_at") or data.get("trial_expires_at") or "Never"
            days = "Unlimited" if state == "ACTIVE" and plan == "LIFETIME" else str(self.license_service.get_days_remaining())
            device_id = self.license_service.get_device_id()
            devices = f"{data.get('active_devices', 0)} / {data.get('max_devices', '-')}" if data.get("license_key") else "-"
            status.configure(
                text=(
                    f"Status: {state}\nPlan: {plan}\nExpires: {expires}\n"
                    f"Days Remaining: {days}\nDevices: {devices}\nDevice: {device_id[:6]}...{device_id[-4:]}"
                ),
                text_color=self.success_color if state in {"ACTIVE", "TRIAL"} else self.error_color,
            )

        def finish_action(success, text):
            activate_button.configure(state="normal", text="Activate License")
            refresh_button.configure(state="normal", text="Check / Refresh License")
            deactivate_button.configure(state="normal" if self.license_service.get_license().get("license_key") else "disabled")
            message.configure(text=text, text_color=self.success_color if success else self.error_color)
            update_window_status()
            self.update_license_sidebar()
            self.refresh_license_settings()

        def open_plans_page():
            url = os.environ.get("CONVERTMANAGER_PLANS_URL", "https://convertmanager-ymaa1.faable.link/plans")
            try:
                webbrowser.open(url, new=2)
                message.configure(text="Opening the ConvertManager pricing page in your browser.", text_color=self.success_color)
            except Exception:
                message.configure(text="Unable to open the pricing page automatically. Visit the license server in your browser.", text_color=self.error_color)

        def activate():
            key = self.license_service.normalize_key(entry.get())
            if not self.license_service.is_valid_key_format(key):
                message.configure(text="Invalid license key.", text_color=self.error_color)
                return

            activate_button.configure(state="disabled", text="Activating...")
            message.configure(text="Contacting license server...", text_color=self.secondary_text)

            def worker():
                try:
                    response = self.license_api.activate_license(
                        key,
                        self.license_service.get_device_id()
                    )
                    saved = self.license_service.save_server_license(response)
                    if not saved:
                        raise LicenseAPIError("SERVER_ERROR", "The license server returned invalid license data.")
                    self.after(0, finish_action, True, "License activated successfully.")
                except LicenseAPIError as error:
                    self.license_service.apply_server_error(error.code)
                    message = self.friendly_license_error(error)
                    self.after(0, finish_action, False, message)

            threading.Thread(target=worker, daemon=True).start()

        activate_button = ctk.CTkButton(
            window,
            text="Activate License",
            height=44,
            fg_color=self.accent_color,
            hover_color=self.secondary_accent,
            command=activate
        )
        activate_button.pack(fill="x", padx=30, pady=(18, 8))

        def refresh():
            data = self.license_service.get_license()
            key = data.get("license_key")
            if not key:
                finish_action(False, "Enter a license key and activate it first.")
                return
            refresh_button.configure(state="disabled", text="Checking...")
            message.configure(text="Contacting license server...", text_color=self.secondary_text)

            def worker():
                try:
                    response = self.license_api.validate_license(key, self.license_service.get_device_id())
                    if not self.license_service.save_server_license(response):
                        raise LicenseAPIError("SERVER_ERROR", "The license server returned invalid license data.")
                    self.after(0, finish_action, True, "License is active and verified by the server.")
                except LicenseAPIError as error:
                    self.license_service.apply_server_error(error.code)
                    if error.code == "NETWORK_ERROR":
                        self.license_service.record_validation_failure()
                    message = self.friendly_license_error(error)
                    self.after(0, finish_action, False, message)

            threading.Thread(target=worker, daemon=True).start()

        refresh_button = ctk.CTkButton(
            window, text="Check / Refresh License", height=38,
            fg_color=self.card_hover, command=refresh,
        )
        refresh_button.pack(fill="x", padx=30, pady=4)

        ctk.CTkButton(
            window,
            text="Buy License / View Plans",
            height=38,
            fg_color=self.card_hover,
            command=open_plans_page,
        ).pack(fill="x", padx=30, pady=4)

        def deactivate():
            data = self.license_service.get_license()
            key = data.get("license_key")
            if not key:
                return
            if not messagebox.askyesno("Deactivate This Device", "Deactivate this device from the license server?"):
                return
            deactivate_button.configure(state="disabled", text="Deactivating...")

            def worker():
                try:
                    self.license_api.deactivate_license(key, self.license_service.get_device_id())
                    self.license_service.deactivate_license()
                    self.after(0, finish_action, True, "This device was deactivated.")
                except LicenseAPIError as error:
                    message = self.friendly_license_error(error)
                    self.after(0, finish_action, False, message)

            threading.Thread(target=worker, daemon=True).start()

        deactivate_button = ctk.CTkButton(
            window, text="Deactivate This Device", height=38,
            fg_color="#7F1D1D", hover_color="#991B1B", command=deactivate,
        )
        deactivate_button.pack(fill="x", padx=30, pady=4)


        trial_text = "Continue with Free Trial" if self.license_service.get_status() == "TRIAL" else ""
        if trial_text:
            ctk.CTkButton(
                window,
                text=trial_text,
                height=38,
                fg_color="transparent",
                hover_color=self.card_hover,
                command=window.destroy
            ).pack(fill="x", padx=30, pady=3)

        ctk.CTkButton(
            window,
            text="Close",
            height=38,
            fg_color=self.card_hover,
            command=window.destroy
        ).pack(fill="x", padx=30, pady=5)
        update_window_status()
        deactivate_button.configure(state="normal" if self.license_service.get_license().get("license_key") else "disabled")

    def scroll_to_history(self):
        self.main._parent_canvas.yview_moveto(1)

    # =========================================================
    # HEADER
    # =========================================================

    def create_header(self):

        header = ctk.CTkFrame(
            self.main,
            fg_color="transparent"
        )

        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(5, 25)
        )

        ctk.CTkLabel(
            header,
            text="Good morning",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=28,
                weight="bold"
            )
        ).pack(
            anchor="w"
        )

        ctk.CTkLabel(
            header,
            text="Ready to convert your files?",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=14
            )
        ).pack(
            anchor="w",
            pady=(5, 0)
        )

    # =========================================================
    # UPLOAD CARD
    # =========================================================

    def create_upload_card(self):

        card = ctk.CTkFrame(
            self.main,
            fg_color=self.card_color,
            corner_radius=18,
            border_width=1,
            border_color=self.border_color
        )

        card.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 20)
        )

        ctk.CTkLabel(
            card,
            text="Add files",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=21,
                weight="bold"
            )
        ).pack(
            pady=(25, 5)
        )

        ctk.CTkLabel(
            card,
            text="Drop files into your workspace or browse from your computer.",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=13
            )
        ).pack(
            pady=(0, 20)
        )

        # -------------------------
        # Drag & Drop area
        # -------------------------

        self.drop_area = ctk.CTkFrame(
            card,
            height=150,
            corner_radius=15,
            fg_color="#202532",
            border_width=2,
            border_color=self.accent_color
        )

        self.drop_area.pack(
            fill="x",
            padx=30,
            pady=(10, 20)
        )

        self.drop_area.pack_propagate(False)

        self.drop_title = ctk.CTkLabel(
            self.drop_area,
            text="Drop Files Here",
            font=ctk.CTkFont(
                size=22,
                weight="bold"
            ),
            text_color=self.text_color
        )

        self.drop_title.pack(
            pady=(30, 5)
        )

        self.drop_subtitle = ctk.CTkLabel(
            self.drop_area,
            text="Images • PDF • DOCX • TXT • ZIP",
            font=ctk.CTkFont(
                size=12
            ),
            text_color=self.secondary_text
        )

        self.drop_subtitle.pack()

        # Register Drag & Drop
        self.drop_area.drop_target_register(
            DND_FILES
        )

        self.drop_area.dnd_bind(
            "<<Drop>>",
            self.handle_drop
        )

        self.drop_area.dnd_bind(
            "<<DragEnter>>",
            self.handle_drag_enter
        )

        self.drop_area.dnd_bind(
            "<<DragLeave>>",
            self.handle_drag_leave
        )

        self.drop_area.bind("<Enter>", self.handle_drop_hover)
        self.drop_area.bind("<Leave>", self.handle_drop_hover_leave)

        # -------------------------
        # Buttons
        # -------------------------

        button_frame = ctk.CTkFrame(
            card,
            fg_color="transparent"
        )

        button_frame.pack(
            pady=(0, 25)
        )

        self.select_files_button = ctk.CTkButton(
            button_frame,
            text="＋  Select files",
            width=180,
            height=45,
            corner_radius=10,
            command=self.select_files
        )
        self.select_files_button.pack(
            side="left",
            padx=8
        )

        self.select_folder_button = ctk.CTkButton(
            button_frame,
            text="▣  Select folder",
            width=180,
            height=45,
            corner_radius=10,
            fg_color=self.card_hover,
            hover_color=self.accent_color,
            command=self.select_folder
        )
        self.select_folder_button.pack(
            side="left",
            padx=8
        )

        self.clear_button = ctk.CTkButton(
            button_frame,
            text="×  Clear all",
            width=160,
            height=45,
            corner_radius=10,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            command=self.clear_all_files
        )

        self.clear_button.pack(
            side="left",
            padx=8
        )

        self.cancel_import_button = ctk.CTkButton(
            button_frame,
            text="Cancel Import",
            width=140,
            height=45,
            corner_radius=10,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            command=self.cancel_import,
            state="disabled"
        )
        self.cancel_import_button.pack(side="left", padx=8)

    def create_file_list(self):

        section = ctk.CTkFrame(
            self.main,
            fg_color=self.card_color,
            corner_radius=18,
            border_width=1,
            border_color=self.border_color
        )

        section.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(0, 20)
        )

        section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            section,
            text="Files",
            text_color=self.text_color,
            font=ctk.CTkFont(size=19, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 10))

        self.file_list = ctk.CTkScrollableFrame(
            section,
            height=220,
            fg_color="#151821",
            corner_radius=10
        )

        self.file_list.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 18)
        )

        self.file_list.grid_columnconfigure(0, weight=1)
        self.update_file_list()

    def update_file_list(self):

        for child in self.file_list.winfo_children():
            child.destroy()

        self.file_list.grid_columnconfigure(0, weight=1)
        self.file_list.grid_columnconfigure(1, weight=0)
        self.file_list.grid_columnconfigure(2, weight=0)
        self.file_list.grid_columnconfigure(3, weight=0)

        headers = ("File Name", "Size", "Format", "Action")

        for column, header in enumerate(headers):
            ctk.CTkLabel(
                self.file_list,
                text=header,
                text_color=self.secondary_text,
                font=ctk.CTkFont(size=11, weight="bold")
            ).grid(row=0, column=column, sticky="w", padx=10, pady=(4, 8))

        if not self.files:
            ctk.CTkLabel(
                self.file_list,
                text="No files imported",
                text_color=self.secondary_text
            ).grid(row=1, column=0, columnspan=4, pady=20)
            return

        for row, file_path in enumerate(self.files, start=1):
            path = Path(file_path)
            try:
                size = self.format_file_size(path.stat().st_size)
            except OSError:
                size = "Unavailable"

            ctk.CTkLabel(
                self.file_list,
                text=path.name,
                text_color=self.text_color,
                anchor="w"
            ).grid(row=row, column=0, sticky="ew", padx=10, pady=5)

            ctk.CTkLabel(
                self.file_list,
                text=size,
                text_color=self.secondary_text
            ).grid(row=row, column=1, sticky="w", padx=10, pady=5)

            ctk.CTkLabel(
                self.file_list,
                text=detect_format(file_path),
                text_color=self.secondary_text
            ).grid(row=row, column=2, sticky="w", padx=10, pady=5)

            ctk.CTkButton(
                self.file_list,
                text="Remove",
                width=70,
                height=28,
                fg_color="transparent",
                hover_color="#7F1D1D",
                text_color="#FCA5A5",
                command=lambda path=file_path: self.remove_file(path)
            ).grid(row=row, column=3, padx=10, pady=3)

    @staticmethod
    def format_file_size(size):
        units = ("B", "KB", "MB", "GB")
        value = float(size)

        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024

    def handle_drop_hover(self, event):
        self.drop_area.configure(border_color=self.secondary_accent)

    def handle_drop_hover_leave(self, event):
        self.drop_area.configure(border_color=self.accent_color)

    def remove_file(self, file_path):
        if file_path in self.files:
            self.files.remove(file_path)
            self.update_file_information()

    def clear_all_files(self):
        if not self.files:
            return

        confirmed = messagebox.askyesno(
            "Clear All",
            "Remove all imported files from the current session?"
        )

        if confirmed:
            self.files.clear()
            self.update_file_information()

    # =========================================================
    # STATISTICS
    # =========================================================

    def create_stats(self):

        stats = ctk.CTkFrame(
            self.main,
            fg_color="transparent"
        )

        stats.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(0, 20)
        )

        stats.grid_columnconfigure(
            (0, 1, 2),
            weight=1
        )

        self.files_card = self.create_stat_card(
            stats,
            0,
            "FILES",
            "0",
            "Selected files"
        )

        self.format_card = self.create_stat_card(
            stats,
            1,
            "FORMATS",
            "—",
            "Detected formats"
        )

        self.status_card = self.create_stat_card(
            stats,
            2,
            "STATUS",
            "Ready",
            "System status"
        )

    def create_stat_card(
        self,
        parent,
        column,
        title,
        value,
        description
    ):

        card = ctk.CTkFrame(
            parent,
            fg_color=self.card_color,
            corner_radius=16,
            border_width=1,
            border_color=self.border_color
        )

        card.grid(
            row=0,
            column=column,
            sticky="ew",
            padx=5
        )

        indicator_color = {
            "FILES": self.accent_color,
            "FORMATS": self.secondary_accent,
            "STATUS": self.success_color,
        }.get(title, self.accent_color)

        ctk.CTkFrame(
            card,
            height=3,
            fg_color=indicator_color,
            corner_radius=2
        ).pack(fill="x", padx=14, pady=(10, 0))

        ctk.CTkLabel(
            card,
            text=title,
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=10,
                weight="bold"
            )
        ).pack(
            anchor="w",
            padx=18,
            pady=(15, 3)
        )

        value_label = ctk.CTkLabel(
            card,
            text=value,
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=22,
                weight="bold"
            )
        )

        value_label.pack(
            anchor="w",
            padx=18
        )

        ctk.CTkLabel(
            card,
            text=description,
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=10
            )
        ).pack(
            anchor="w",
            padx=18,
            pady=(0, 15)
        )

        return value_label

    # =========================================================
    # CONVERSION SETTINGS
    # =========================================================

    def create_conversion_settings(self):

        settings = ctk.CTkFrame(
            self.main,
            fg_color=self.card_color,
            corner_radius=18,
            border_width=1,
            border_color=self.border_color
        )

        settings.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(0, 20)
        )

        settings.grid_columnconfigure(
            0,
            weight=1,
            uniform="settings"
        )

        settings.grid_columnconfigure(
            1,
            weight=1,
            uniform="settings"
        )

        ctk.CTkLabel(
            settings,
            text="Conversion Settings",
            text_color=self.text_color,
            font=ctk.CTkFont(
                size=19,
                weight="bold"
            )
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            padx=25,
            pady=(20, 15)
        )

        # -------------------------
        # Output Format
        # -------------------------

        ctk.CTkLabel(
            settings,
            text="Convert To",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=12
            )
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=25
        )

        self.format_menu = ctk.CTkOptionMenu(
            settings,
            values=[
                "PNG",
                "JPG",
                "JPEG",
                "TIFF",
                "BMP",
                "WEBP",
                "PDF",
                "DOCX",
                "TXT",
                "ZIP",
                "EXTRACT"
            ],
            width=220,
            height=40
        )

        self.format_menu.set("PNG")

        self.format_menu.grid(
            row=2,
            column=0,
            sticky="w",
            padx=25,
            pady=(5, 20)
        )

        # -------------------------
        # Output Folder
        # -------------------------

        ctk.CTkLabel(
            settings,
            text="Output Folder",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=12
            )
        ).grid(
            row=1,
            column=1,
            sticky="w",
            padx=25
        )

        self.output_button = ctk.CTkButton(
            settings,
            text="↗  Choose output folder",
            width=220,
            height=40,
            fg_color=self.card_hover,
            hover_color=self.accent_color,
            command=self.select_output_folder
        )

        self.output_button.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=25,
            pady=(5, 20)
        )

        self.output_label = ctk.CTkLabel(
            settings,
            text=str(self.output_folder),
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=10
            )
        )

        self.output_label.grid(
            row=3,
            column=1,
            sticky="w",
            padx=25,
            pady=(0, 15)
        )

        # -------------------------
        # Convert Button
        # -------------------------

        self.convert_button = ctk.CTkButton(
            settings,
            text="→  Convert files",
            height=50,
            width=280,
            corner_radius=12,
            fg_color=self.accent_color,
            hover_color="#2563EB",
            font=ctk.CTkFont(
                size=15,
                weight="bold"
            ),
            command=self.start_conversion
        )

        self.convert_button.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="n",
            pady=(10, 25)
        )

    # =========================================================
    # PROGRESS
    # =========================================================

    def create_progress_section(self):

        progress_frame = ctk.CTkFrame(
            self.main,
            fg_color="transparent"
        )

        progress_frame.grid(
            row=5,
            column=0,
            sticky="ew",
            pady=(0, 30)
        )

        self.progress_label = ctk.CTkLabel(
            progress_frame,
            text="Ready to convert",
            text_color=self.secondary_text,
            font=ctk.CTkFont(
                size=12
            )
        )

        self.progress_label.pack(
            anchor="w"
        )

        self.progress = ctk.CTkProgressBar(
            progress_frame,
            height=10,
            corner_radius=5
        )

        self.progress.set(0)

        self.progress.pack(
            fill="x",
            pady=(8, 0)
        )

    def create_history_section(self):

        self.history_section = ctk.CTkFrame(
            self.main,
            fg_color=self.card_color,
            corner_radius=18,
            border_width=1,
            border_color=self.border_color
        )

        self.history_section.grid(
            row=6,
            column=0,
            sticky="ew",
            pady=(0, 30)
        )

        self.history_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.history_section,
            text="History",
            text_color=self.text_color,
            font=ctk.CTkFont(size=19, weight="bold")
        ).pack(anchor="w", padx=20, pady=(18, 10))

        self.clear_history_button = ctk.CTkButton(
            self.history_section,
            text="Clear History",
            width=130,
            height=32,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            command=self.clear_conversion_history
        )
        self.clear_history_button.pack(anchor="e", padx=20, pady=(0, 8))

        self.history_content = ctk.CTkScrollableFrame(
            self.history_section,
            height=180,
            fg_color="transparent"
        )
        self.history_content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.render_history()

    def render_history(self):

        for child in self.history_content.winfo_children():
            child.destroy()

        if not self.history:
            ctk.CTkLabel(
                self.history_content,
                text="No completed conversions yet",
                text_color=self.secondary_text
            ).pack(pady=20)
            return

        for index, record in enumerate(self.history):
            card = ctk.CTkFrame(
                self.history_content,
                fg_color=self.card_color,
                corner_radius=10
            )
            card.pack(fill="x", padx=4, pady=4)

            formats = ", ".join(record.get("input_formats", []))
            summary = (
                f"{record.get('date', '')}  {record.get('time', '')}    "
                f"{record.get('files', 0)} files    {formats} -> "
                f"{record.get('output_format', '')}\n"
                f"Successful: {record.get('successful', 0)}    "
                f"Failed: {record.get('failed', 0)}    "
                f"Skipped: {record.get('skipped', 0)}\n"
                f"Status: {record.get('status', 'Completed')}    "
                f"Duration: {record.get('duration', 0)} seconds"
            )

            ctk.CTkLabel(
                card,
                text=summary,
                justify="left",
                anchor="w",
                text_color=self.text_color
            ).pack(side="left", fill="x", expand=True, padx=12, pady=10)

            ctk.CTkButton(
                card,
                text="Open Output",
                width=110,
                height=30,
                command=lambda path=record.get("output_folder", ""): self.open_output_folder(path)
            ).pack(side="right", padx=10, pady=8)

            ctk.CTkButton(
                card,
                text="Delete",
                width=70,
                height=30,
                fg_color="transparent",
                hover_color="#7F1D1D",
                text_color="#FCA5A5",
                command=lambda item_index=index: self.delete_conversion_history(item_index)
            ).pack(side="right", padx=2, pady=8)

    def clear_conversion_history(self):
        if not self.history:
            return

        confirmed = messagebox.askyesno(
            "Clear Conversion History?",
            "This will remove all conversion records from the application history.\n\n"
            "Your original files and converted files will NOT be deleted."
        )
        if confirmed:
            clear_history()
            self.history = []
            self.render_history()
            messagebox.showinfo("History", "History cleared successfully.")

    def delete_conversion_history(self, index):
        confirmed = messagebox.askyesno(
            "Delete History Record?",
            "Remove this record from history? Original and converted files will not be deleted."
        )
        if confirmed and delete_history_record(index):
            self.history = load_history()
            self.render_history()

    def create_settings_section(self, parent):

        self.settings_section = ctk.CTkFrame(
            parent,
            fg_color=self.card_color,
            corner_radius=18,
            border_width=1,
            border_color=self.border_color
        )
        self.settings_section.pack(fill="both", expand=True, padx=18, pady=18)
        self.settings_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.settings_section,
            text="Settings",
            text_color=self.text_color,
            font=ctk.CTkFont(size=19, weight="bold")
        ).pack(anchor="w", padx=20, pady=(18, 15))

        output_frame = ctk.CTkFrame(self.settings_section, fg_color="transparent")
        output_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(
            output_frame,
            text="Default output location",
            text_color=self.secondary_text
        ).pack(anchor="w")

        self.output_location_var = ctk.StringVar(value=self.settings["output_location"])
        ctk.CTkRadioButton(
            output_frame,
            text="Desktop / ConvertManager_Output",
            variable=self.output_location_var,
            value="desktop",
            command=self.apply_settings
        ).pack(anchor="w", pady=(7, 2))
        ctk.CTkRadioButton(
            output_frame,
            text="Custom folder",
            variable=self.output_location_var,
            value="custom",
            command=self.choose_custom_output_folder
        ).pack(anchor="w", pady=2)

        self.settings_output_label = ctk.CTkLabel(
            output_frame,
            text=str(self.output_folder),
            text_color=self.secondary_text,
            anchor="w"
        )
        self.settings_output_label.pack(fill="x", pady=(2, 5))

        handling_frame = ctk.CTkFrame(self.settings_section, fg_color="transparent")
        handling_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(
            handling_frame,
            text="Output file handling",
            text_color=self.secondary_text
        ).pack(anchor="w")
        self.file_handling_var = ctk.StringVar(value=self.settings["file_handling"])
        for label, value in (
            ("Create copies (safest)", "create_copy"),
            ("Skip existing files", "skip"),
            ("Replace existing files", "replace"),
        ):
            ctk.CTkRadioButton(
                handling_frame,
                text=label,
                variable=self.file_handling_var,
                value=value,
                command=self.apply_settings
            ).pack(anchor="w", pady=2)

        self.include_subfolders_var = ctk.BooleanVar(value=self.settings["include_subfolders"])
        self.auto_open_var = ctk.BooleanVar(value=self.settings["auto_open_output"])
        self.show_result_var = ctk.BooleanVar(value=self.settings["show_result"])

        for text, variable in (
            ("Include files in subfolders", self.include_subfolders_var),
            ("Automatically open output folder", self.auto_open_var),
            ("Show conversion result after completion", self.show_result_var),
        ):
            ctk.CTkCheckBox(
                self.settings_section,
                text=text,
                variable=variable,
                command=self.apply_settings
            ).pack(anchor="w", padx=20, pady=4)

        ctk.CTkButton(
            self.settings_section,
            text="Save Settings",
            width=160,
            command=self.apply_settings
        ).pack(anchor="w", padx=20, pady=(12, 20))

        license_frame = ctk.CTkFrame(
            self.settings_section,
            fg_color="#202532",
            corner_radius=12
        )
        license_frame.pack(fill="x", padx=20, pady=(5, 20))
        license_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            license_frame,
            text="License",
            text_color=self.text_color,
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(14, 8))

        self.license_settings_label = ctk.CTkLabel(
            license_frame,
            text="",
            justify="left",
            anchor="w",
            text_color=self.secondary_text
        )
        self.license_settings_label.grid(
            row=1,
            column=0,
            sticky="w",
            padx=15,
            pady=(0, 10)
        )

        ctk.CTkButton(
            license_frame,
            text="Manage License",
            width=150,
            height=34,
            command=self.open_license_window
        ).grid(row=2, column=0, sticky="w", padx=15, pady=(0, 14))
        self.license_connection_label = ctk.CTkLabel(
            license_frame,
            text="",
            text_color=self.secondary_text,
            font=ctk.CTkFont(size=10)
        )
        self.license_connection_label.grid(row=3, column=0, sticky="w", padx=15, pady=(0, 6))
        self.refresh_license_button = ctk.CTkButton(
            license_frame,
            text="Refresh License",
            width=140,
            height=32,
            fg_color=self.card_hover,
            command=self.refresh_license_online
        )
        self.refresh_license_button.grid(row=4, column=0, sticky="w", padx=15, pady=(0, 6))
        self.deactivate_license_button = ctk.CTkButton(
            license_frame,
            text="Deactivate This Device",
            width=170,
            height=32,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            command=self.deactivate_license_online
        )
        self.deactivate_license_button.grid(row=5, column=0, sticky="w", padx=15, pady=(0, 14))
        self.refresh_license_settings()

    def refresh_license_settings(self):
        if not hasattr(self, "license_settings_label"):
            return
        if not self.license_settings_label.winfo_exists():
            return

        status = self.license_service.get_status()
        license_data = self.license_service.get_license()
        plan = self.license_service.get_plan()
        days = "Unlimited" if status == "ACTIVE" and plan == "LIFETIME" else self.license_service.get_days_remaining()
        expiration = license_data.get("expires_at") or license_data.get("trial_expires_at")
        expiration = expiration or "No expiration"
        activated = license_data.get("activated_at", "Not activated")
        last_validation = license_data.get("last_validation_at", "Not checked")
        device_id = self.license_service.get_device_id()
        masked_device = f"{device_id[:6]}...{device_id[-4:]}"
        devices = f"{license_data.get('active_devices', 0)} / {license_data.get('max_devices', '-')}" if license_data.get("license_key") else "-"
        self.license_settings_label.configure(
            text=(
                f"Plan: {plan}\n"
                f"Status: {status}\n"
                f"Activated: {activated}\n"
                f"Expires: {expiration}\n"
                f"Days remaining: {days}\n"
                f"Devices: {devices}\n"
                f"Last validation: {last_validation}\n"
                f"Device: {masked_device}"
            ),
            text_color=self.success_color if status in {"ACTIVE", "TRIAL"} else self.error_color
        )
        connection = self.license_service.get_connection_status()
        self.license_connection_label.configure(
            text=f"License server: {connection.replace('_', ' ').title()}"
        )
        self.deactivate_license_button.configure(
            state="normal" if self.license_service.get_license().get("license_key") else "disabled"
        )

    def refresh_license_online(self):
        data = self.license_service.get_license()
        key = data.get("license_key")
        if not key:
            self.open_license_window()
            return

        self.refresh_license_button.configure(state="disabled", text="Checking...")
        self.license_connection_label.configure(text="License server: Checking...")

        def worker():
            try:
                response = self.license_api.validate_license(key, self.license_service.get_device_id())
                success = self.license_service.save_server_license(response)
                if not success:
                    raise LicenseAPIError("SERVER_ERROR", "Invalid license data")
                self.after(0, self.finish_license_refresh, True, "License server: Connected")
            except LicenseAPIError as error:
                self.license_service.apply_server_error(error.code)
                if error.code == "NETWORK_ERROR":
                    self.license_service.record_validation_failure()
                    message = "License server: Offline"
                else:
                    message = f"License server: {self.friendly_license_error(error)}"
                self.after(0, self.finish_license_refresh, False, message)

        threading.Thread(target=worker, daemon=True).start()

    def finish_license_refresh(self, success, message):
        self.refresh_license_button.configure(state="normal", text="Refresh License")
        self.license_connection_label.configure(text=message)
        self.update_license_sidebar()
        self.refresh_license_settings()

    def deactivate_license_online(self):
        if not messagebox.askyesno(
            "Deactivate This Device",
            "Deactivate this device from the license? The original license will not be deleted from the server."
        ):
            return

        data = self.license_service.get_license()
        self.deactivate_license_button.configure(state="disabled", text="Deactivating...")

        def worker():
            try:
                response = self.license_api.deactivate_license(data["license_key"], self.license_service.get_device_id())
                if not response.get("success"):
                    raise LicenseAPIError("SERVER_ERROR", "The server rejected deactivation.")
                self.license_service.deactivate_license()
                self.after(0, self.finish_deactivation)
            except LicenseAPIError as error:
                message = self.friendly_license_error(error)
                self.after(0, self.finish_deactivation_error, message)

        threading.Thread(target=worker, daemon=True).start()

    def finish_deactivation(self):
        self.deactivate_license_button.configure(state="normal", text="Deactivate This Device")
        self.update_license_sidebar()
        self.refresh_license_settings()
        messagebox.showinfo("License", "This device was deactivated.")

    def finish_deactivation_error(self, message):
        self.deactivate_license_button.configure(state="normal", text="Deactivate This Device")
        messagebox.showerror("License", message)

    def apply_settings(self):
        self.settings.update({
            "output_location": self.output_location_var.get(),
            "file_handling": self.file_handling_var.get(),
            "include_subfolders": self.include_subfolders_var.get(),
            "auto_open_output": self.auto_open_var.get(),
            "show_result": self.show_result_var.get(),
        })
        save_settings(self.settings)

        if self.settings["output_location"] == "desktop":
            self.output_folder = self.get_desktop_folder()
        self.output_label.configure(text=str(self.output_folder))
        self.settings_output_label.configure(text=str(self.output_folder))

    def choose_custom_output_folder(self):
        folder = filedialog.askdirectory(title="Choose Default Output Folder")
        if not folder:
            self.output_location_var.set(self.settings.get("output_location", "desktop"))
            return

        self.settings["custom_output_folder"] = folder
        self.output_location_var.set("custom")
        self.output_folder = Path(folder)
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.apply_settings()

    # =========================================================
    # FILE SELECTION
    # =========================================================

    def select_files(self):

        files = filedialog.askopenfilenames(
            title="Select Files"
        )

        if files:
            self.start_file_import(list(files), "Adding files...")

    # =========================================================
    # FOLDER SELECTION
    # =========================================================

    def select_folder(self):

        folder = filedialog.askdirectory(
            title="Select Folder"
        )

        if not folder:
            return

        self.start_folder_scan(folder)

    # =========================================================
    # ADD FILES
    # =========================================================

    def add_files(self, files):

        existing = {normalized_path(item) for item in self.files}

        for file in files:

            file = str(Path(file).expanduser().absolute())
            key = normalized_path(file)

            if key not in existing:

                self.files.append(file)
                existing.add(key)

        self.update_file_information()

    def start_file_import(self, files, status_text):
        if self.import_cancel_event:
            return

        self.import_cancel_event = threading.Event()
        self.set_import_controls(True)
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.status_card.configure(text="Adding files...")
        self.progress_label.configure(text=status_text)

        def worker():
            last_update = [0.0]

            def report(current, total, current_path):
                now = time.monotonic()
                if total and current != total and now - last_update[0] < 0.15:
                    return
                last_update[0] = now
                self.after(0, lambda: self.update_import_progress(current, total, current_path))

            imported, errors, cancelled = import_files(
                files,
                cancel_event=self.import_cancel_event,
                progress_callback=report
            )
            self.after(0, lambda: self.finish_import(imported, errors, cancelled))

        threading.Thread(target=worker, daemon=True).start()

    def start_folder_scan(self, folder):
        if self.import_cancel_event:
            return

        self.import_cancel_event = threading.Event()
        self.set_import_controls(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status_card.configure(text="Scanning folder...")
        self.progress_label.configure(text="Scanning folder...")

        def worker():
            last_update = [0.0]

            def report(current, total, current_path):
                now = time.monotonic()
                if now - last_update[0] < 0.15:
                    return
                last_update[0] = now
                self.after(0, lambda: self.update_import_progress(current, total, current_path))

            imported, errors, cancelled = scan_folder(
                folder,
                recursive=self.settings.get("include_subfolders", False),
                cancel_event=self.import_cancel_event,
                progress_callback=report
            )
            self.after(0, lambda: self.finish_import(imported, errors, cancelled))

        threading.Thread(target=worker, daemon=True).start()

    def update_import_progress(self, current, total, current_path):
        if total:
            self.progress.configure(mode="determinate")
            self.progress.set(current / total)
            detail = f"Adding files... {current} / {total}"
        else:
            detail = f"Scanning... {current} items checked"
        self.progress_label.configure(text=f"{detail}\n{Path(current_path).name}")

    def finish_import(self, imported, errors, cancelled):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.import_cancel_event = None
        self.set_import_controls(False)
        self.add_files(imported)

        if cancelled:
            self.status_card.configure(text="Cancelled")
            self.progress_label.configure(text="Import cancelled.")
        elif errors:
            self.status_card.configure(text="Warning")
            self.progress_label.configure(text=f"{len(imported)} files added; {len(errors)} skipped")
            messagebox.showwarning("Import warning", f"{len(errors)} file(s) could not be added.")
        else:
            self.status_card.configure(text="Ready")
            self.progress.set(1)
            self.progress_label.configure(text=f"{len(imported)} file(s) added")

    def set_import_controls(self, importing):
        state = "disabled" if importing else "normal"
        self.select_files_button.configure(state=state)
        self.select_folder_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.convert_button.configure(state="disabled" if importing else "normal")
        self.cancel_import_button.configure(state="normal" if importing else "disabled")

    def cancel_import(self):
        if self.import_cancel_event:
            self.import_cancel_event.set()
            self.progress_label.configure(text="Cancelling import safely...")

    # =========================================================
    # DRAG ENTER
    # =========================================================

    def handle_drag_enter(self, event):

        self.drop_area.configure(
            border_color=self.success_color
        )

        self.drop_title.configure(
            text="Release to Add Files"
        )

    # =========================================================
    # DRAG LEAVE
    # =========================================================

    def handle_drag_leave(self, event):

        self.drop_area.configure(
            border_color=self.accent_color
        )

        self.drop_title.configure(
            text="Drop Files Here"
        )

    # =========================================================
    # DROP
    # =========================================================

    def handle_drop(self, event):

        self.drop_area.configure(
            border_color=self.accent_color
        )

        self.drop_title.configure(
            text="Drop Files Here"
        )

        dropped_items = self.tk.splitlist(
            event.data
        )

        self.start_dropped_import(list(dropped_items))

    def start_dropped_import(self, items):
        if self.import_cancel_event:
            return

        self.import_cancel_event = threading.Event()
        self.set_import_controls(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status_card.configure(text="Adding dropped items...")
        self.progress_label.configure(text="Preparing dropped files...")

        def worker():
            def report(current, total, current_path):
                self.after(0, lambda: self.update_import_progress(current, total, current_path))

            imported, errors, cancelled = import_dropped_items(
                items,
                recursive=self.settings.get("include_subfolders", False),
                cancel_event=self.import_cancel_event,
                progress_callback=report
            )
            self.after(0, lambda: self.finish_import(imported, errors, cancelled))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # UPDATE FILE INFORMATION
    # =========================================================

    def update_file_information(self):

        self.update_file_list()

        if not self.files:

            self.files_card.configure(
                text="0"
            )

            self.format_card.configure(
                text="—"
            )

            self.status_card.configure(
                text="No files"
            )

            self.progress_label.configure(
                text="Ready to convert"
            )

            self.progress.set(0)

            return

        formats = {}

        for file in self.files:

            try:

                detected = detect_format(file)

            except Exception:

                detected = Path(
                    file
                ).suffix.upper().replace(
                    ".",
                    ""
                )

            formats[detected] = (
                formats.get(
                    detected,
                    0
                ) + 1
            )

        self.files_card.configure(
            text=str(
                len(self.files)
            )
        )

        self.format_card.configure(
            text=str(
                len(formats)
            )
        )

        self.status_card.configure(
            text="Ready"
        )

        self.progress_label.configure(
            text=f"{len(self.files)} files ready for conversion"
        )

    # =========================================================
    # OUTPUT FOLDER
    # =========================================================

    def select_output_folder(self):

        folder = filedialog.askdirectory(
            title="Select Output Folder"
        )

        if not folder:
            return

        self.output_folder = folder

        display = folder

        if len(display) > 45:

            display = (
                "..."
                + display[-42:]
            )

        self.output_label.configure(
            text=display
        )

    # =========================================================
    # START CONVERSION
    # =========================================================

    def start_conversion(self):

        if not self.license_service.can_use_application():
            detail = (
                "License validation requires the License Server, but it is currently unavailable. "
                "Reconnect and check your license to continue."
                if self.license_service.get_connection_status() == "OFFLINE"
                else "Your free trial has expired or your license is no longer valid. Activate or check a license to continue using ConvertManager."
            )
            messagebox.showwarning(
                "License Required",
                detail
            )
            self.open_license_window()
            return

        if not self.files:
            messagebox.showwarning(
                "No Files",
                "Please import at least one file first."
            )
            return

        if not self.output_folder:

            messagebox.showwarning(
                "Output Folder",
                "Please select an output folder."
            )

            return

        output_format = (
            self.format_menu.get()
        )

        self.convert_button.configure(
            state="normal",
            text="×  Cancel conversion",
            command=self.cancel_conversion
        )

        self.status_card.configure(
            text="Working"
        )

        self.progress.set(0)

        self.progress_label.configure(
            text="Starting conversion..."
        )

        files = list(self.files)
        output_folder = self.output_folder
        self.cancel_event = threading.Event()
        self.conversion_started_at = time.perf_counter()

        thread = threading.Thread(
            target=self.run_conversion,
            args=(output_format, files, output_folder, self.cancel_event),
            daemon=True
        )

        thread.start()

    # =========================================================
    # RUN CONVERSION
    # =========================================================

    def run_conversion(
        self,
        output_format,
        files,
        output_folder,
        cancel_event
    ):

        def update_progress(
            current,
            total
        ):

            if total <= 0:
                progress = 0
            else:
                progress = (
                    current / total
                )

            self.after(
                0,
                lambda: self.update_progress(
                    progress,
                    current,
                    total
                )
            )

        try:

            result = convert_files(
                files,
                output_format,
                output_folder,
                update_progress,
                file_handling=self.settings.get("file_handling", "create_copy"),
                cancel_event=cancel_event
            )

            self.after(
                0,
                lambda: self.conversion_finished(
                    result
                )
            )

        except Exception as error:
            message = str(error)
            self.after(0, self.conversion_error, message)

    # =========================================================
    # UPDATE PROGRESS
    # =========================================================

    def update_progress(
        self,
        progress,
        current,
        total
    ):

        self.progress.set(
            progress
        )

        self.progress_label.configure(
            text=(
                f"Converting files... "
                f"{current} / {total}"
            )
        )

    # =========================================================
    # CONVERSION FINISHED
    # =========================================================

    def conversion_finished(
        self,
        result
    ):

        self.convert_button.configure(
            state="normal",
            text="→  Convert files",
            command=self.start_conversion
        )

        self.progress.set(1)

        self.status_card.configure(
            text="Cancelled" if result.get("cancelled") else "Completed"
        )

        successful = result.get(
            "successful",
            0
        )

        failed = result.get(
            "failed",
            0
        )

        skipped = result.get("skipped", 0)
        status = "Cancelled" if result.get("cancelled") else "Completed"
        duration = time.perf_counter() - self.conversion_started_at

        total = result.get(
            "total",
            len(self.files)
        )

        output_folder = result.get(
            "output_folder",
            self.output_folder
        )

        self.history.insert(
            0,
            add_history_record(
                result.get("input_formats", []),
                self.format_menu.get(),
                total,
                successful,
                failed,
                output_folder,
                skipped,
                status,
                duration
            )
        )

        self.render_history()
        if self.settings.get("auto_open_output"):
            self.open_output_folder(output_folder)
        if self.settings.get("show_result", True):
            self.show_result_window(result)

        self.progress_label.configure(
            text="Conversion cancelled" if result.get("cancelled") else "Conversion completed successfully"
        )

    def cancel_conversion(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.progress_label.configure(text="Cancelling safely...")

    def show_result_window(self, result):

        window = ctk.CTkToplevel(self)
        window.title("Conversion Complete")
        window.geometry("560x360")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()

        ctk.CTkLabel(
            window,
            text="Conversion Complete",
            text_color=self.text_color,
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w", padx=28, pady=(25, 15))

        summary = (
            f"Total Files: {result.get('total', 0)}\n"
            f"Successfully: {result.get('successful', 0)}\n"
            f"Failed: {result.get('failed', 0)}\n\n"
            f"Skipped: {result.get('skipped', 0)}\n"
            f"Status: {'Cancelled' if result.get('cancelled') else 'Completed'}\n\n"
            f"Output Folder:\n{result.get('output_folder', '')}"
        )

        ctk.CTkLabel(
            window,
            text=summary,
            justify="left",
            anchor="w",
            text_color=self.secondary_text
        ).pack(fill="x", padx=28)

        actions = ctk.CTkFrame(window, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=28, pady=25)

        ctk.CTkButton(
            actions,
            text="Open Output Folder",
            command=lambda: self.open_output_folder(result.get("output_folder", ""))
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions,
            text="View Errors",
            state="normal" if result.get("errors") else "disabled",
            fg_color=self.card_hover,
            command=lambda: self.show_errors(result.get("errors", []))
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            actions,
            text="Close",
            fg_color=self.card_hover,
            command=window.destroy
        ).pack(side="right")

    def show_errors(self, errors):

        window = ctk.CTkToplevel(self)
        window.title("Conversion Errors")
        window.geometry("620x420")
        window.transient(self)

        content = ctk.CTkScrollableFrame(window, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=15)

        for item in errors:
            ctk.CTkLabel(
                content,
                text=(
                    f"{Path(item.get('file', '')).name}\n"
                    f"{item.get('input_format', 'UNKNOWN')} -> "
                    f"{item.get('output_format', 'UNKNOWN')}\n"
                    f"Reason: {item.get('error', 'Conversion failed')}"
                ),
                justify="left",
                anchor="w",
                text_color=self.text_color
            ).pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(
            window,
            text="Close",
            command=window.destroy
        ).pack(pady=(0, 15))

    @staticmethod
    def open_output_folder(folder):

        path = Path(folder)

        if path.exists() and os.name == "nt":
            os.startfile(str(path))
        elif path.exists():
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    # =========================================================
    # CONVERSION ERROR
    # =========================================================

    def conversion_error(
        self,
        error
    ):

        self.convert_button.configure(
            state="normal",
            text="→  Convert files",
            command=self.start_conversion
        )

        self.status_card.configure(
            text="Error"
        )

        self.progress_label.configure(
            text="Conversion failed"
        )

        messagebox.showerror(
            "Conversion Error",
            error
        )
