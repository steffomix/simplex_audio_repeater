import tkinter as tk
from tkinter import messagebox
import threading
import time


class CallbacksMixin:

    # ── Label-Update-Callbacks ────────────────────────────────────────────────

    def update_threshold_label(self, *args):
        self.threshold_label.config(text=str(self.start_threshold_var.get()))

    def update_stop_threshold_label(self, *args):
        self.stop_threshold_label.config(text=str(self.stop_threshold_var.get()))
        self.update_threshold_lines()

    def update_stop_time_label(self, *args):
        self.stop_time_label.config(text=f"{self.stop_time_var.get():.1f}s")

    def update_record_time_label(self, *args):
        self.record_time_label.config(text=f"{self.record_time_var.get():.1f}s")

    def update_dead_time_label(self, *args):
        self.dead_time_label.config(text=f"{self.dead_time_var.get():.1f}s")

    def update_playback_delay_label(self, *args):
        value = self.playback_delay_var.get()
        self.playback_delay_label.config(text=f"{value} ms")

    def update_rise_time_label(self, *args):
        value = self.rise_time_var.get()
        if value == 0:
            self.rise_time_label.config(text="Aus")
        else:
            self.rise_time_label.config(text=f"{value:.0f} ms")

    def update_fall_time_label(self, *args):
        value = self.fall_time_var.get()
        if value == 0:
            self.fall_time_label.config(text="Aus")
        else:
            self.fall_time_label.config(text=f"{value:.0f} ms")

    def update_gain_label(self, *args):
        value = self.gain_var.get()
        self.gain_label.config(text=f"{value:+.1f} dB")

    def update_input_gain_label(self, *args):
        value = self.input_gain_var.get()
        self.input_gain_label.config(text=f"{value:+.1f} dB")

    def update_eq_label(self, band):
        """Aktualisiert das Label für ein Equalizer-Band"""
        value = self.eq_gains[band].get()
        self.eq_labels[band].config(text=f"{value:+.1f} dB")

    # ── Event-Handler ─────────────────────────────────────────────────────────

    def on_playback_delay_change(self, value):
        """Wird aufgerufen wenn sich die Wiedergabeverzögerung ändert"""
        self.playback_delay_ms = int(float(value))
        self.calculate_delayed_buffer_size()

    def on_equalizer_toggle(self):
        """Wird aufgerufen wenn Equalizer aktiviert/deaktiviert wird"""
        self.equalizer_enabled = self.equalizer_enabled_var.get()
        # Aktiviere/Deaktiviere alle Equalizer-Slider
        state = tk.NORMAL if self.equalizer_enabled else tk.DISABLED
        for band in self.eq_bands:
            self.eq_scales[band].config(state=state)

    def on_monitoring_toggle(self):
        """Wird aufgerufen wenn Monitoring aktiviert/deaktiviert wird"""
        self.monitoring_enabled = self.monitoring_var.get()

    def on_sample_rate_changed(self, event=None):
        """Wird aufgerufen wenn Abtastrate geändert wird"""
        if self.running:
            messagebox.showwarning("Warnung",
                "Bitte stoppen Sie den Repeater, bevor Sie die Abtastrate ändern!")
            # Setze zurück auf alte Rate
            self.sample_rate_combo.set(self.RATE)
        else:
            self.RATE = self.sample_rate_var.get()

    def toggle_mode(self):
        """Wechselt zwischen Simplex und Duplex Modus"""
        if self.running:
            messagebox.showwarning("Warnung", "Bitte stoppen Sie den Repeater zuerst!")
            return

        self.is_duplex_mode = not self.is_duplex_mode

        if self.is_duplex_mode:
            self.title_label.config(text="Duplex Repeater")
            self.mode_button.config(text="Zu Simplex wechseln")
        else:
            self.title_label.config(text="Simplex Repeater")
            self.mode_button.config(text="Zu Duplex wechseln")

    def on_threshold_change(self, value):
        """Wird aufgerufen wenn sich der Eingangspegel ändert"""
        start_threshold = int(float(value))
        stop_threshold = self.stop_threshold_var.get()

        # Wenn Eingangspegel unter Abbruch-Pegel geht, ziehe Abbruch-Pegel mit
        if start_threshold < stop_threshold:
            self.stop_threshold_var.set(start_threshold)

        # Aktualisiere Maximum des Abbruch-Pegel-Schiebereglers
        self.stop_threshold_scale.config(to=start_threshold)

        # Aktualisiere Schwellwert-Linien im Canvas
        self.update_threshold_lines()

    def on_canvas_resize(self, event):
        """Wird aufgerufen wenn Canvas Größe ändert"""
        self.update_threshold_lines()

    # ── Canvas-Zeichenmethoden ────────────────────────────────────────────────

    def update_threshold_lines(self):
        """Aktualisiert die Schwellwert-Linien im Canvas"""
        canvas_width = self.level_canvas.winfo_width()
        if canvas_width <= 1:
            return

        canvas_height = 40
        max_level = 10000  # Maximum des Eingangspegels

        # Berechne X-Positionen
        start_threshold = self.start_threshold_var.get()
        stop_threshold = self.stop_threshold_var.get()

        threshold_x = (start_threshold / max_level) * canvas_width
        stop_threshold_x = (stop_threshold / max_level) * canvas_width

        # Lösche alte Linien
        if self.threshold_line:
            self.level_canvas.delete(self.threshold_line)
        if self.stop_threshold_line:
            self.level_canvas.delete(self.stop_threshold_line)

        # Zeichne neue Linien
        self.stop_threshold_line = self.level_canvas.create_line(
            stop_threshold_x, 1, stop_threshold_x, canvas_height+1,
            fill='green', width=4, tags='stop_threshold')
        self.threshold_line = self.level_canvas.create_line(
            threshold_x, 1, threshold_x, canvas_height+1,
            fill='red', width=4, tags='start_threshold')

    # ── Status- und Pegelanzeige ──────────────────────────────────────────────

    def update_status(self, text, color='black'):
        """Aktualisiert den Status"""
        self.status_label.config(text=text, foreground=color)

    def update_level(self, level):
        """Aktualisiert die Pegel-Anzeige mit Attack/Release-Dämpfung
        Performance-optimiert mit Rate-Limiting"""
        current_time = time.time()
        time_elapsed = current_time - self.last_update_time
        self.last_update_time = current_time

        # Dämpfungsparameter
        rise_time_ms = self.rise_time_var.get()
        fall_time_ms = self.fall_time_var.get()

        # Berechne gedämpften Pegel (immer berechnen für genaue Trigger-Logik)
        if level > self.current_damped_level:
            # Anstieg
            if rise_time_ms == 0:
                self.current_damped_level = level
            else:
                max_change = (level - self.current_damped_level) * (time_elapsed * 1000 / rise_time_ms)
                self.current_damped_level = min(self.current_damped_level + max_change, level)
        else:
            # Abfall
            if fall_time_ms == 0:
                self.current_damped_level = level
            else:
                max_change = (self.current_damped_level - level) * (time_elapsed * 1000 / fall_time_ms)
                self.current_damped_level = max(self.current_damped_level - max_change, level)

        self._update_level_gui(self.current_damped_level)

    def _update_level_gui(self, level):
        """Aktualisiert die GUI für Pegelanzeige (wird nur periodisch aufgerufen)"""
        # Canvas-Darstellung
        canvas_width = self.level_canvas.winfo_width()
        if canvas_width <= 1:
            return

        canvas_height = 40
        max_level = 10000  # Maximum des Eingangspegels

        # Berechne Breite des Pegelbalkens
        bar_width = (level / max_level) * canvas_width
        bar_width = min(bar_width, canvas_width)

        # Optimierung: Verwende coords() statt delete/create wenn Balken existiert
        if self.level_bar:
            try:
                self.level_canvas.coords(self.level_bar, 0, 0, bar_width, canvas_height)
            except Exception:
                # Balken existiert nicht mehr, erstelle neu
                self.level_bar = None

        if not self.level_bar:
            self.level_bar = self.level_canvas.create_rectangle(
                0, 0, bar_width, canvas_height,
                fill='lightgray', outline='', tags='level')
            # Schwellwert-Linien in den Vordergrund (nur beim ersten Mal)
            self.level_canvas.tag_raise('start_threshold')
            self.level_canvas.tag_raise('stop_threshold')

    def update_progress(self, value):
        """Aktualisiert den Fortschrittsbalken"""
        self.progress['value'] = value

    # ── Repeater-Steuerung ────────────────────────────────────────────────────

    def start_repeater(self):
        """Startet den Repeater"""
        input_device_id, input_channels = self.get_selected_input_device()
        output_device_id, output_channels = self.get_selected_output_device()

        if input_device_id is None or output_device_id is None:
            messagebox.showerror("Fehler", "Bitte wählen Sie Ein- und Ausgabegeräte aus!")
            return

        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        # Deaktiviere Geräte- und Abtastrate-Dropdowns während Betrieb
        self.input_device_combo.config(state=tk.DISABLED)
        self.output_device_combo.config(state=tk.DISABLED)
        self.sample_rate_combo.config(state=tk.DISABLED)
        self.update_status("Simplex Bereit - Warte auf überschreiten des Startpegels...", 'green')

        # PipeWire-Verbindungen herstellen
        self.apply_pipewire_patchbay()

        # Audio-Thread starten
        self.audio_thread = threading.Thread(target=self.audio_loop, daemon=True)
        self.audio_thread.start()

    def stop_repeater(self):
        """Stoppt den Repeater"""
        self.running = False
        self.is_recording = False
        self.is_playing = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        # Aktiviere Geräte- und Abtastrate-Dropdowns wieder
        self.input_device_combo.config(state='readonly')
        self.output_device_combo.config(state='readonly')
        self.sample_rate_combo.config(state='readonly')
        self.update_status("Gestoppt", 'red')
        self.progress['value'] = 0
        # Konfiguration speichern
        self.save_config()
