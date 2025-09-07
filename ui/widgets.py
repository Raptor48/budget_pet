import customtkinter as ctk
import tkinter as tk

class ToolTip:
    """Tooltip widget that shows text on hover."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        lbl = ctk.CTkLabel(self.tip, text=self.text, text_color="#000000", fg_color="#ffffff")
        lbl.pack(ipadx=6, ipady=4)

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None
