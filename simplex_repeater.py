#!/usr/bin/env python3
"""
Simplex Repeater - Einfacher Audio Repeater mit GUI
Nimmt Audio auf wenn ein Schwellwert überschritten wird und spielt es danach ab.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyaudio
import numpy as np
import threading
import time
import json
import os
from collections import deque


class SimplexRepeater:
    def __init__(self, root):
        self.root = root
        self.root.title("Simplex Repeater")
        self.root.geometry("500x700")
        
        # Audio-Parameter
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 44100
        
        # Konfigurationsdatei
        self.config_file = os.path.join(os.path.expanduser("~"), ".simplex_repeater_config.json")
        
        # Status
        self.running = False
        self.is_recording = False
        self.is_playing = False
        self.audio_buffer = deque()
        self.dead_time_end = 0  # Zeitpunkt wenn Totzeit endet
        self.current_damped_level = 0  # Aktueller gedämpfter Pegel
        self.last_update_time = time.time()  # Zeitpunkt der letzten Pegel-Aktualisierung
        
        # Streams für dynamisches Umschalten
        self.stream_in = None
        self.stream_out = None
        self.streams_lock = threading.Lock()  # Lock für Thread-Sicherheit
        self.restart_streams_flag = False  # Flag für Stream-Neustart
        
        # PyAudio Initialisierung
        self.p = pyaudio.PyAudio()
        
        # GUI erstellen
        self.create_gui()
        
        # Audio-Geräte laden
        self.load_audio_devices()
        
        # Konfiguration laden
        self.load_config()
        
        # Thread für Audio-Verarbeitung
        self.audio_thread = None
        
    def create_gui(self):

        row = 0
        column = 0

        # Hauptframe
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=row, column=column, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Titel
        title_label = ttk.Label(main_frame, text="Simplex Repeater", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=row, column=0, columnspan=2, pady=10)

        # Titel Pegeleinstellungen
        row += 1 
        ttk.Label(main_frame, text="Pegeleinstellungen:", font=('Arial', 12, 'bold')).grid(
            row=row, column=0, sticky=tk.W, pady=5)
        
        # Eingangspegel-Einstellung (Start Threshold)
        row += 1 
        ttk.Label(main_frame, text="Startpegel (rot):").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.start_threshold_var = tk.IntVar(value=1000)
        threshold_frame = ttk.Frame(main_frame)
        threshold_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.threshold_scale = ttk.Scale(threshold_frame, from_=0, to=10000,
                                        variable=self.start_threshold_var, orient=tk.HORIZONTAL,
                                        command=self.on_threshold_change)
        self.threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.threshold_label = ttk.Label(threshold_frame, text="1000")
        self.threshold_label.pack(side=tk.LEFT, padx=5)
        self.start_threshold_var.trace('w', self.update_threshold_label)
        
        # Abbruch-Pegel-Einstellung (Stop Threshold)
        row += 1 
        ttk.Label(main_frame, text="Stoppegel (grün):").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.stop_threshold_var = tk.IntVar(value=100)
        stop_threshold_frame = ttk.Frame(main_frame)
        stop_threshold_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.stop_threshold_scale = ttk.Scale(stop_threshold_frame, from_=0, to=10000,
                                             variable=self.stop_threshold_var, orient=tk.HORIZONTAL)
        self.stop_threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stop_threshold_label = ttk.Label(stop_threshold_frame, text="100")
        self.stop_threshold_label.pack(side=tk.LEFT, padx=5)
        self.stop_threshold_var.trace('w', self.update_stop_threshold_label)
        
        # Canvas für Pegelanzeige
        row += 1 
        self.level_canvas = tk.Canvas(main_frame, height=40, bg='white', 
                                      highlightthickness=1, highlightbackground='gray')
        self.level_canvas.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5, padx=5)
        
        # Elemente für Level-Anzeige
        self.level_bar = None
        self.threshold_line = None
        self.stop_threshold_line = None

        # Titel Pegeldämpfung
        row += 1 
        ttk.Label(main_frame, text="Pegeldämpfung:", font=('Arial', 12, 'bold')).grid(
            row=row, column=0, sticky=tk.W, pady=5)
        
        # Anstiegsdämpfung-Einstellung (Attack in ms)
        row += 1 
        ttk.Label(main_frame, text="Anstiegsdämpfung (Attack):").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        rise_time_frame = ttk.Frame(main_frame)
        rise_time_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.rise_time_var = tk.DoubleVar(value=0.0)
        self.rise_time_scale = ttk.Scale(rise_time_frame, from_=0.0, to=1000.0,
                                        variable=self.rise_time_var, orient=tk.HORIZONTAL)
        self.rise_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.rise_time_label = ttk.Label(rise_time_frame, text="Aus")
        self.rise_time_label.pack(side=tk.LEFT, padx=5)
        self.rise_time_var.trace('w', self.update_rise_time_label)
        
        # Abfalldämpfung-Einstellung (Release in ms)
        row += 1 
        ttk.Label(main_frame, text="Abfalldämpfung (Release)").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        fall_time_frame = ttk.Frame(main_frame)
        fall_time_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.fall_time_var = tk.DoubleVar(value=100.0)
        self.fall_time_scale = ttk.Scale(fall_time_frame, from_=0.0, to=1000.0,
                                        variable=self.fall_time_var, orient=tk.HORIZONTAL)
        self.fall_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.fall_time_label = ttk.Label(fall_time_frame, text="100.0 ms")
        self.fall_time_label.pack(side=tk.LEFT, padx=5)
        self.fall_time_var.trace('w', self.update_fall_time_label)

        # Titel Zeiteinstellungen
        row += 1 
        ttk.Label(main_frame, text="Zeiteinstellungen:", font=('Arial', 12, 'bold')).grid(
            row=row, column=0, sticky=tk.W, pady=5)
        
        # Maximale Aufnahmezeit-Einstellung
        row += 1 
        ttk.Label(main_frame, text="Max. Aufnahmezeit:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        record_frame = ttk.Frame(main_frame)
        record_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.record_time_var = tk.DoubleVar(value=30.0)
        self.record_time_scale = ttk.Scale(record_frame, from_=1.0, to=120.0,
                                          variable=self.record_time_var, orient=tk.HORIZONTAL)
        self.record_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.record_time_label = ttk.Label(record_frame, text="30.0s")
        self.record_time_label.pack(side=tk.LEFT, padx=5)
        self.record_time_var.trace('w', self.update_record_time_label)
        
        # Abbruch-Zeit-Einstellung
        row += 1 
        ttk.Label(main_frame, text="Max. Unterschreitung Stoppegel: ").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        stop_time_frame = ttk.Frame(main_frame)
        stop_time_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.stop_time_var = tk.DoubleVar(value=0.5)
        self.stop_time_scale = ttk.Scale(stop_time_frame, from_=0.1, to=5.0,
                                        variable=self.stop_time_var, orient=tk.HORIZONTAL)
        self.stop_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stop_time_label = ttk.Label(stop_time_frame, text="0.5s")
        self.stop_time_label.pack(side=tk.LEFT, padx=5)
        self.stop_time_var.trace('w', self.update_stop_time_label)
        
        # Totzeit-Einstellung
        row += 1 
        ttk.Label(main_frame, text="Pause nach Wiedergabe:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        dead_time_frame = ttk.Frame(main_frame)
        dead_time_frame.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.dead_time_var = tk.DoubleVar(value=2.0)
        self.dead_time_scale = ttk.Scale(dead_time_frame, from_=0.0, to=10.0,
                                        variable=self.dead_time_var, orient=tk.HORIZONTAL)
        self.dead_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.dead_time_label = ttk.Label(dead_time_frame, text="2.0s")
        self.dead_time_label.pack(side=tk.LEFT, padx=5)
        self.dead_time_var.trace('w', self.update_dead_time_label)

        # Titel Audioeinstellungen
        row += 1 
        ttk.Label(main_frame, text="Audioeinstellungen:", font=('Arial', 12, 'bold')).grid(
            row=row, column=0, sticky=tk.W, pady=5)
        
        # Audio-Quelle Auswahl
        row += 1 
        ttk.Label(main_frame, text="Audio-Eingangsquelle:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.input_device_var = tk.StringVar()
        self.input_device_combo = ttk.Combobox(main_frame, textvariable=self.input_device_var,
                                              state='readonly', width=30)
        self.input_device_combo.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.input_device_combo.bind('<<ComboboxSelected>>', self.on_input_device_changed)
        
        # Audio-Ausgabe Auswahl
        row += 1 
        ttk.Label(main_frame, text="Audio-Ausgangsquelle:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.output_device_var = tk.StringVar()
        self.output_device_combo = ttk.Combobox(main_frame, textvariable=self.output_device_var,
                                               state='readonly', width=30)
        self.output_device_combo.grid(row=row, column=1, sticky=(tk.W, tk.E), pady=5)
        self.output_device_combo.bind('<<ComboboxSelected>>', self.on_output_device_changed)
        
        # Status-Anzeige
        row += 1 
        ttk.Label(main_frame, text="Status:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.status_label = ttk.Label(main_frame, text="Gestoppt", 
                                      font=('Arial', 10, 'bold'),
                                      foreground='red')
        self.status_label.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # Fortschrittsbalken (Aufnahme/Wiedergabe)
        row += 1 
        ttk.Label(main_frame, text="Aufnahme/Wiedergabe:").grid(
            row=row, column=0, sticky=tk.W, pady=5)
        self.progress = ttk.Progressbar(main_frame, mode='determinate', maximum=100)

        row += 1 
        self.progress.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Buttons
        row += 1 
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=20)
        
        self.start_button = ttk.Button(button_frame, text="Start", 
                                      command=self.start_repeater, width=15)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", 
                                     command=self.stop_repeater, width=15,
                                     state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # Grid-Konfiguration
        main_frame.columnconfigure(1, weight=1)
        
        # Event-Binding für Canvas-Resize
        self.level_canvas.bind('<Configure>', self.on_canvas_resize)
        
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
        """Wird aufgerufen wenn Canvas größe ändert"""
        self.update_threshold_lines()
        
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
        
    def load_audio_devices(self):
        """Lädt verfügbare Audio-Geräte"""
        input_devices = []
        output_devices = []
        
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            name = f"{i}: {info['name']}"
            
            if info['maxInputChannels'] > 0:
                input_devices.append((i, name))
            if info['maxOutputChannels'] > 0:
                output_devices.append((i, name))
        
        # Comboboxen füllen
        self.input_device_combo['values'] = [name for _, name in input_devices]
        self.output_device_combo['values'] = [name for _, name in output_devices]
        
        # Standard-Geräte auswählen
        if input_devices:
            self.input_device_combo.current(0)
        if output_devices:
            self.output_device_combo.current(0)
            
        # Geräte-IDs speichern
        self.input_devices = {name: idx for idx, name in input_devices}
        self.output_devices = {name: idx for idx, name in output_devices}
        
    def get_selected_input_device(self):
        """Gibt die ausgewählte Eingabe-Geräte-ID zurück"""
        device_name = self.input_device_var.get()
        return self.input_devices.get(device_name, None)
        
    def get_selected_output_device(self):
        """Gibt die ausgewählte Ausgabe-Geräte-ID zurück"""
        device_name = self.output_device_var.get()
        return self.output_devices.get(device_name, None)
    
    def on_input_device_changed(self, event=None):
        """Wird aufgerufen wenn Eingangsquelle geändert wird"""
        if self.running:
            self.restart_streams_flag = True
    
    def on_output_device_changed(self, event=None):
        """Wird aufgerufen wenn Ausgangsquelle geändert wird"""
        if self.running:
            self.restart_streams_flag = True
    
    def restart_audio_streams(self):
        """Trennt alte Streams und öffnet neue mit aktuellen Geräten"""
        with self.streams_lock:
            # Alte Streams schließen
            if self.stream_in:
                try:
                    self.stream_in.stop_stream()
                    self.stream_in.close()
                except Exception as e:
                    print(f"Fehler beim Schließen des Input-Streams: {e}")
                self.stream_in = None
            
            if self.stream_out:
                try:
                    self.stream_out.stop_stream()
                    self.stream_out.close()
                except Exception as e:
                    print(f"Fehler beim Schließen des Output-Streams: {e}")
                self.stream_out = None
            
            # Neue Streams öffnen
            input_device = self.get_selected_input_device()
            output_device = self.get_selected_output_device()
            
            if input_device is not None:
                try:
                    self.stream_in = self.p.open(
                        format=self.FORMAT,
                        channels=self.CHANNELS,
                        rate=self.RATE,
                        input=True,
                        input_device_index=input_device,
                        frames_per_buffer=self.CHUNK
                    )
                except Exception as e:
                    print(f"Fehler beim Öffnen des Input-Streams: {e}")
                    self.root.after(0, messagebox.showerror, "Fehler", 
                                  f"Eingangsquelle konnte nicht geöffnet werden: {str(e)}")
            
            if output_device is not None:
                try:
                    self.stream_out = self.p.open(
                        format=self.FORMAT,
                        channels=self.CHANNELS,
                        rate=self.RATE,
                        output=True,
                        output_device_index=output_device,
                        frames_per_buffer=self.CHUNK
                    )
                except Exception as e:
                    print(f"Fehler beim Öffnen des Output-Streams: {e}")
                    self.root.after(0, messagebox.showerror, "Fehler", 
                                  f"Ausgangsquelle konnte nicht geöffnet werden: {str(e)}")
        
    def start_repeater(self):
        """Startet den Repeater"""
        input_device = self.get_selected_input_device()
        output_device = self.get_selected_output_device()
        
        if input_device is None or output_device is None:
            messagebox.showerror("Fehler", "Bitte wählen Sie Ein- und Ausgabegeräte aus!")
            return
            
        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.update_status("Bereit - Warte auf Signal...", 'green')
        
        # Audio-Thread starten
        self.audio_thread = threading.Thread(target=self.audio_loop, daemon=True)
        self.audio_thread.start()
        
    def stop_repeater(self):
        """Stoppt den Repeater"""
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.update_status("Gestoppt", 'red')
        self.progress['value'] = 0
        # Konfiguration speichern
        self.save_config()
        
    def update_status(self, text, color='black'):
        """Aktualisiert den Status"""
        self.status_label.config(text=text, foreground=color)
        
    def update_level(self, level):
        """Aktualisiert die Pegel-Anzeige mit Attack/Release-Dämpfung"""
        current_time = time.time()
        time_elapsed = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # Dämpfungsparameter
        rise_time_ms = self.rise_time_var.get()
        fall_time_ms = self.fall_time_var.get()
        
        # Berechne gedämpften Pegel
        if level > self.current_damped_level:
            # Anstieg
            if rise_time_ms == 0:
                # Keine Dämpfung: Sofortige Anpassung
                self.current_damped_level = level
            else:
                # Dämpfung anwenden
                # Berechne maximale Änderung basierend auf Zeit und Dämpfung
                # Je höher rise_time_ms, desto langsamer der Anstieg
                max_change = (level - self.current_damped_level) * (time_elapsed * 1000 / rise_time_ms)
                self.current_damped_level = min(self.current_damped_level + max_change, level)
        else:
            # Abfall
            if fall_time_ms == 0:
                # Keine Dämpfung: Sofortige Anpassung
                self.current_damped_level = level
            else:
                # Dämpfung anwenden
                max_change = (self.current_damped_level - level) * (time_elapsed * 1000 / fall_time_ms)
                self.current_damped_level = max(self.current_damped_level - max_change, level)
        
        # Canvas-Darstellung
        canvas_width = self.level_canvas.winfo_width()
        if canvas_width <= 1:
            return
            
        canvas_height = 40
        max_level = 10000  # Maximum des Eingangspegels
        
        # Berechne Breite des Pegelbalkens (mit gedämpftem Pegel)
        bar_width = (self.current_damped_level / max_level) * canvas_width
        bar_width = min(bar_width, canvas_width)  # Nicht über Canvas hinaus
        
        # Lösche alten Balken
        if self.level_bar:
            self.level_canvas.delete(self.level_bar)
            
        # Zeichne neuen Balken
        self.level_bar = self.level_canvas.create_rectangle(
            0, 0, bar_width, canvas_height,
            fill='lightgray', outline='', tags='level')
        
        # Schwellwert-Linien in den Vordergrund
        self.level_canvas.tag_raise('start_threshold')
        self.level_canvas.tag_raise('stop_threshold')
        
    def audio_loop(self):
        """Haupt-Audio-Schleife"""
        try:
            # Streams initial öffnen
            self.restart_audio_streams()
            
            if self.stream_in is None or self.stream_out is None:
                self.root.after(0, messagebox.showerror, "Fehler", 
                              "Audio-Streams konnten nicht geöffnet werden!")
                self.root.after(0, self.stop_repeater)
                return
            
            # Stille-Puffer für Output (wenn nicht abgespielt wird)
            silence = np.zeros(self.CHUNK, dtype=np.int16).tobytes()
            
            while self.running:
                # Prüfe ob Streams neu gestartet werden müssen
                if self.restart_streams_flag:
                    self.restart_streams_flag = False
                    self.root.after(0, self.update_status, "Quellen werden gewechselt...", 'orange')
                    
                    # Warte bis Aufnahme/Wiedergabe beendet ist
                    while (self.is_recording or self.is_playing) and self.running:
                        time.sleep(0.1)
                    
                    # Streams neu starten
                    self.restart_audio_streams()
                    
                    if self.stream_in is None or self.stream_out is None:
                        self.root.after(0, messagebox.showerror, "Fehler", 
                                      "Audio-Streams konnten nicht gewechselt werden!")
                        break
                    
                    self.root.after(0, self.update_status, "Bereit - Warte auf Signal...", 'green')
                
                # Audio-Daten lesen
                try:
                    with self.streams_lock:
                        if self.stream_in is None:
                            break
                        data = self.stream_in.read(self.CHUNK, exception_on_overflow=False)
                    
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    
                    # Pegel berechnen
                    level = np.abs(audio_data).mean()
                    self.root.after(0, self.update_level, level)
                    
                    # Wenn nicht gerade abgespielt wird und nicht aufgenommen wird
                    if not self.is_playing and not self.is_recording:
                        # Stille ausgeben, um Stream aktiv zu halten
                        with self.streams_lock:
                            if self.stream_out:
                                self.stream_out.write(silence)
                        
                        # Prüfe ob wir noch in Totzeit sind
                        current_time = time.time()
                        if current_time < self.dead_time_end:
                            # Noch in Totzeit
                            remaining = self.dead_time_end - current_time
                            self.root.after(0, self.update_status, 
                                          f"Totzeit: {remaining:.1f}s verbleibend", 'orange')
                        elif self.current_damped_level > self.start_threshold_var.get():
                            # Verwende gedämpften Pegel für Trigger
                            self.start_recording()
                            
                except Exception as e:
                    print(f"Fehler beim Lesen: {e}")
                    time.sleep(0.01)
            
            # Streams schließen
            with self.streams_lock:
                if self.stream_in:
                    self.stream_in.stop_stream()
                    self.stream_in.close()
                    self.stream_in = None
                if self.stream_out:
                    self.stream_out.stop_stream()
                    self.stream_out.close()
                    self.stream_out = None
            
        except Exception as e:
            self.root.after(0, messagebox.showerror, "Fehler", 
                          f"Audio-Fehler: {str(e)}")
            self.root.after(0, self.stop_repeater)
            
    def start_recording(self):
        """Startet die Aufnahme"""
        self.is_recording = True
        self.audio_buffer.clear()
        self.root.after(0, self.update_status, "Aufnahme läuft...", 'orange')
        
        record_time = self.record_time_var.get()
        chunks_to_record = int(self.RATE / self.CHUNK * record_time)
        
        stop_threshold = self.stop_threshold_var.get()
        stop_time = self.stop_time_var.get()
        chunks_for_stop = int(self.RATE / self.CHUNK * stop_time)
        low_level_counter = 0
        
        # Aufnahme
        chunk_count = 0
        for _ in range(chunks_to_record):
            if not self.running:
                break
            try:
                with self.streams_lock:
                    if self.stream_in is None:
                        break
                    data = self.stream_in.read(self.CHUNK, exception_on_overflow=False)
                
                self.audio_buffer.append(data)
                chunk_count += 1
                
                # Fortschritt aktualisieren
                progress_percent = (chunk_count / chunks_to_record) * 100
                self.root.after(0, self.update_progress, progress_percent)
                
                # Pegel aktualisieren
                audio_data = np.frombuffer(data, dtype=np.int16)
                level = np.abs(audio_data).mean()
                self.root.after(0, self.update_level, level)
                
                # Prüfe ob gedämpfter Pegel unter Abbruch-Pegel
                # Verwende gedämpften Pegel für konsistente Triggerung
                if self.current_damped_level < stop_threshold:
                    low_level_counter += 1
                    # Wenn Pegel lange genug unter Schwelle, breche ab
                    if low_level_counter >= chunks_for_stop:
                        break
                else:
                    low_level_counter = 0
                    
            except Exception as e:
                print(f"Fehler bei Aufnahme: {e}")
                break
                
        self.is_recording = False
        
        # Sofort abspielen
        if self.running and len(self.audio_buffer) > 0:
            self.play_audio()
            
        self.root.after(0, self.update_progress, 0)
        self.root.after(0, self.update_status, "Bereit - Warte auf Signal...", 'green')
        
    def play_audio(self):
        """Spielt aufgenommenes Audio ab - verwendet den bereits geöffneten Stream"""
        self.is_playing = True
        self.root.after(0, self.update_status, "Wiedergabe läuft...", 'blue')
        
        try:
            # Audio abspielen über den bereits geöffneten Stream
            total_chunks = len(self.audio_buffer)
            played_chunks = 0
            
            while self.audio_buffer and self.running:
                data = self.audio_buffer.popleft()
                
                with self.streams_lock:
                    if self.stream_out is None:
                        break
                    self.stream_out.write(data)
                
                played_chunks += 1
                
                # Fortschritt aktualisieren (rückwärts von 100 zu 0)
                progress_percent = 100 - ((played_chunks / total_chunks) * 100)
                self.root.after(0, self.update_progress, progress_percent)
            
        except Exception as e:
            print(f"Fehler bei Wiedergabe: {e}")
            
        self.is_playing = False
        self.audio_buffer.clear()
        
        # Totzeit setzen
        dead_time = self.dead_time_var.get()
        self.dead_time_end = time.time() + dead_time
        
    def update_progress(self, value):
        """Aktualisiert den Fortschrittsbalken"""
        self.progress['value'] = value
    
    def load_config(self):
        """Lädt Konfiguration aus Datei"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                # Werte aus Konfiguration setzen
                self.start_threshold_var.set(config.get('start_threshold', 1000))
                self.stop_threshold_var.set(config.get('stop_threshold', 100))
                self.rise_time_var.set(config.get('rise_time', 0.0))
                self.fall_time_var.set(config.get('fall_time', 100.0))
                self.record_time_var.set(config.get('record_time', 30.0))
                self.stop_time_var.set(config.get('stop_time', 0.5))
                self.dead_time_var.set(config.get('dead_time', 2.0))
                
                # Audiogeräte aus Konfiguration setzen (falls vorhanden)
                input_device = config.get('input_device', '')
                output_device = config.get('output_device', '')
                
                if input_device and input_device in self.input_devices:
                    self.input_device_var.set(input_device)
                if output_device and output_device in self.output_devices:
                    self.output_device_var.set(output_device)
                    
            except Exception as e:
                print(f"Fehler beim Laden der Konfiguration: {e}")
        
        # Aktualisiere Schwellwert-Grenzen nach dem Laden der Konfiguration
        start_threshold = self.start_threshold_var.get()
        stop_threshold = self.stop_threshold_var.get()
        
        # Stelle sicher, dass Stoppegel nicht höher als Startpegel ist
        if stop_threshold > start_threshold:
            self.stop_threshold_var.set(start_threshold)
        
        # Setze Maximum des Stoppegel-Schiebereglers
        self.stop_threshold_scale.config(to=start_threshold)
        
        # Zeichne Schwellwert-Linien
        self.update_threshold_lines()
    
    def save_config(self):
        """Speichert Konfiguration in Datei"""
        try:
            config = {
                'start_threshold': self.start_threshold_var.get(),
                'stop_threshold': self.stop_threshold_var.get(),
                'rise_time': self.rise_time_var.get(),
                'fall_time': self.fall_time_var.get(),
                'record_time': self.record_time_var.get(),
                'stop_time': self.stop_time_var.get(),
                'dead_time': self.dead_time_var.get(),
                'input_device': self.input_device_var.get(),
                'output_device': self.output_device_var.get()
            }
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
        except Exception as e:
            print(f"Fehler beim Speichern der Konfiguration: {e}")
        
    def cleanup(self):
        """Aufräumen beim Schließen"""
        self.running = False
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        # Konfiguration speichern beim Beenden
        self.save_config()
        self.p.terminate()


def main():
    root = tk.Tk()
    app = SimplexRepeater(root)
    root.protocol("WM_DELETE_WINDOW", lambda: [app.cleanup(), root.destroy()])
    root.mainloop()


if __name__ == "__main__":
    main()
