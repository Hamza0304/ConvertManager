import customtkinter as ctk
import logging
import os

from app.ui.main_window import MainWindow


logging.basicConfig(
    level=os.environ.get("CONVERTMANAGER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")


if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
