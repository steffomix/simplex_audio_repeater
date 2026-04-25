from .app import SimplexRepeater


def main():
    import tkinter as tk
    root = tk.Tk()
    app = SimplexRepeater(root)
    root.protocol("WM_DELETE_WINDOW", lambda: [app.cleanup(), root.destroy()])
    root.mainloop()
