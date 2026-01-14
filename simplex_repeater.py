#!/usr/bin/env python3
"""
Simplex/Duplex Repeater - Audio Repeater mit GUI und Equalizer
Nimmt Audio auf wenn ein Schwellwert überschritten wird und spielt es danach ab.
Unterstützt Simplex (abwechselnd) und Duplex (gleichzeitig) Modi.
"""

import os
# Setze PipeWire/ALSA Umgebungsvariablen für Stereo-Unterstützung
os.environ['PIPEWIRE_LATENCY'] = '512/48000'
os.environ['PIPEWIRE_QUANTUM'] = '1024/48000'

import tkinter as tk
from tkinter import ttk, messagebox
import pyaudio
import numpy as np
import scipy.signal as signal
import threading
import time
import json
import os
from collections import deque


class SimplexRepeater:
    def __init__(self, root):
        self.root = root
        self.root.title("Simplex/Duplex Repeater")
        self.root.geometry("1200x800")
        
        # Audio-Parameter
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 2  # Standard: Stereo (wird beim Stream-Öffnen aktualisiert)
        self.input_channels = 2  # Tatsächliche Anzahl Eingangskanäle
        self.output_channels = 2  # Tatsächliche Anzahl Ausgangskanäle
        self.RATE = 44000 
        # Equalizer-Aktivierung
        self.equalizer_enabled = True
        
        # Konfigurationsdatei
        self.config_file = os.path.join(os.path.expanduser("~"), ".simplex_repeater_config.json")
        
        # Modus (simplex oder duplex)
        self.is_duplex_mode = False
        
        # Monitoring-Status (für Simplex-Modus)
        self.monitoring_enabled = False
        
        # Status
        self.running = False
        self.is_recording = False
        self.is_playing = False
        self.audio_buffer = deque()
        self.dead_time_end = 0  # Zeitpunkt wenn Totzeit endet
        self.current_damped_level = 0  # Aktueller gedämpfter Pegel
        self.last_update_time = time.time()  # Zeitpunkt der letzten Pegel-Aktualisierung
        
        # Performance-Optimierung: Rate-Limiting für GUI-Updates
        self.last_gui_update_time = 0
        
        # Equalizer-Einstellungen (5 Bänder)
        self.eq_bands = [150, 1000, 3000, 6000, 9000, 12000]  # Mittelpunkte in Hz
        self.eq_gains = {}  # Dictionary für Gain-Werte (dB)
        for band in self.eq_bands:
            self.eq_gains[band] = tk.DoubleVar(value=0.0)
        
        # Wiedergabeverzögerung (für Duplex-Modus)
        self.playback_delay_ms = 0  # in Millisekunden
        
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
        
        # Equalizer-Filter-Zustände (für kontinuierliche Verarbeitung ohne Knacksen)
        self.eq_filter_states = {}
        self.eq_filter_sos = {}
        self._init_equalizer_filters()
    
    def convert_channels(self, data, from_channels, to_channels):
        """Konvertiert Audio zwischen Mono und Stereo
        
        Args:
            data: Audio-Daten als bytes
            from_channels: Anzahl Quellkanäle (1 oder 2)
            to_channels: Anzahl Zielkanäle (1 oder 2)
        
        Returns:
            Konvertierte Audio-Daten als bytes
        """
        if from_channels == to_channels:
            return data
        
        audio_np = np.frombuffer(data, dtype=np.int16)
        
        if from_channels == 2 and to_channels == 1:
            # Stereo zu Mono: Durchschnitt beider Kanäle
            audio_np = audio_np.reshape(-1, 2)
            mono = audio_np.mean(axis=1).astype(np.int16)
            return mono.tobytes()
        elif from_channels == 1 and to_channels == 2:
            # Mono zu Stereo: Dupliziere Kanal
            stereo = np.column_stack([audio_np, audio_np]).flatten()
            return stereo.tobytes()
        
        return data
    
    def calculate_level(self, data):
        """Berechnet Pegel aus Audio-Daten (Mono/Stereo-kompatibel)
        
        Bei Stereo: Nimmt das Maximum beider Kanäle
        """
        audio_np = np.frombuffer(data, dtype=np.int16)
        
        if self.input_channels == 2:
            # Stereo: Reshape zu (samples, 2) und nimm Maximum beider Kanäle
            audio_np = audio_np.reshape(-1, 2)
            # Berechne RMS pro Kanal und nimm Maximum
            level_left = np.abs(audio_np[:, 0]).mean()
            level_right = np.abs(audio_np[:, 1]).mean()
            return max(level_left, level_right)
        else:
            # Mono: Direkt Mean der Absolutwerte
            return np.abs(audio_np).mean()
        
    def _init_equalizer_filters(self):
        """Initialisiert die Peaking-EQ-Filter für den Equalizer"""
        # Nyquist-Frequenz
        nyquist = self.RATE / 2.0
        
        for band in self.eq_bands:
            # Überspringe Bänder über Nyquist-Frequenz
            # if band >= nyquist * 0.95:  # Sicherheitsabstand von 5%
            #     print(f"Warnung: EQ-Band {band}Hz übersprungen (über Nyquist-Frequenz {nyquist}Hz)")
            #     self.eq_filter_states[band] = None
            #     self.eq_filter_sos[band] = None
            #     continue
            
            # Initialer Zustand für sosfilt mit 1 Section: Form (1, 2)
            self.eq_filter_states[band] = np.zeros((1, 2))
            # Erstelle initiale SOS-Koeffizienten (Bypass-Filter bei 0 dB)
            self._update_peaking_filter(band, 0.0)
    
    def _update_peaking_filter(self, freq, gain_db):
        """Erstellt einen Peaking-EQ-Filter als Second-Order Section
        
        Verwendet Audio EQ Cookbook Formeln mit korrekter Implementierung
        """
        # Übersprüfe Nyquist-Frequenz
        nyquist = self.RATE / 2.0
        if freq >= nyquist * 0.95:
            # Filter deaktivieren für zu hohe Frequenzen
            self.eq_filter_sos[freq] = None
            return
        
        # Wenn Gain nahe 0, verwende Bypass-Filter
        if abs(gain_db) < 0.01:
            # Bypass: y = x (Koeffizienten: [b0, b1, b2, a0, a1, a2])
            self.eq_filter_sos[freq] = np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
            return
        
        try:
            # Q-Faktor für etwa 1 Oktave Bandbreite
            Q = 1.41
            
            # Normalisierte Frequenz (0 bis pi)
            w0 = 2.0 * np.pi * freq / self.RATE
            
            # Sicherheitsprüfung
            if w0 <= 0 or w0 >= np.pi:
                raise ValueError(f"w0 außerhalb gültigem Bereich: {w0}")
            
            cos_w0 = np.cos(w0)
            sin_w0 = np.sin(w0)
            alpha = sin_w0 / (2.0 * Q)
            
            # Amplitude (Gain-Faktor)
            A = 10.0 ** (gain_db / 40.0)  # /40 für Peaking EQ (nicht /20)
            
            # Biquad-Koeffizienten für Peaking EQ (Audio EQ Cookbook)
            b0 = 1.0 + alpha * A
            b1 = -2.0 * cos_w0
            b2 = 1.0 - alpha * A
            a0 = 1.0 + alpha / A
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha / A
            
            # Normalisiere auf a0=1 und erstelle SOS-Array
            sos = np.array([[
                b0/a0, b1/a0, b2/a0, 
                1.0, a1/a0, a2/a0
            ]])
            
            # Prüfe auf ungültige Werte
            if np.any(np.isnan(sos)) or np.any(np.isinf(sos)):
                raise ValueError("Ungültige Filterkoeffizienten (NaN/Inf)")
            
            # Stabilitätsprüfung: Pole müssen innerhalb des Einheitskreises liegen
            # Für Biquad: Stabilität wenn |a1/2| < 1 und |a2| < 1
            if abs(a1/a0/2.0) >= 1.0 or abs(a2/a0) >= 1.0:
                raise ValueError("Instabiler Filter (Pole außerhalb Einheitskreis)")
            
            self.eq_filter_sos[freq] = sos
            
        except Exception as e:
            print(f"Fehler beim Erstellen des Filters für {freq}Hz: {e}")
            # Fallback: Bypass-Filter
            self.eq_filter_sos[freq] = np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
    
    def apply_equalizer(self, audio_data):
        """Wendet den Equalizer auf Audio-Daten an (Stereo-kompatibel)
        
        Verwendet scipy.signal.sosfilt für stabile, kontinuierliche Filterung
        ohne numerische Instabilitäten oder Artefakte.
        Verarbeitet bei Stereo jeden Kanal separat.
        """
        # Früh-Ausstieg wenn Equalizer deaktiviert ist
        if not self.equalizer_enabled:
            return audio_data
        
        # Konvertiere bytes zu numpy array wenn nötig
        if isinstance(audio_data, bytes):
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float64)
        else:
            audio_np = audio_data.astype(np.float64)
        
        # Prüfe ob alle Gains auf 0 sind
        all_zero = all(self.eq_gains[band].get() == 0.0 for band in self.eq_bands)
        if all_zero:
            # Keine Filterung nötig
            if isinstance(audio_data, bytes):
                return audio_data
            else:
                return np.clip(audio_np, -32768, 32767).astype(np.int16).tobytes()
        
        # Stereo: Reshape zu (samples, channels) falls mehr als 1024 Samples
        # Bei Stereo: Array ist [L, R, L, R, ...] -> reshape zu [[L, R], [L, R], ...]
        is_stereo = self.input_channels == 2 and len(audio_np) > self.CHUNK
        if is_stereo:
            audio_np = audio_np.reshape(-1, 2)
        
        # Starte mit Originalsignal
        if is_stereo:
            # Verarbeite jeden Kanal separat
            filtered_left = audio_np[:, 0].copy()
            filtered_right = audio_np[:, 1].copy()
            
            # Wende jeden EQ-Band kaskadiert an (in Serie) - pro Kanal
            for band in self.eq_bands:
                # Überspringe deaktivierte Bänder (über Nyquist)
                if self.eq_filter_sos[band] is None:
                    continue
                
                gain_db = self.eq_gains[band].get()
                
                # Überspringe Bänder mit 0 dB Gain (Optimierung)
                if abs(gain_db) < 0.1:
                    continue
                
                # Aktualisiere Filter-Koeffizienten wenn Gain geändert wurde
                self._update_peaking_filter(band, gain_db)
                
                # Überspringe wenn Filter deaktiviert wurde
                if self.eq_filter_sos[band] is None:
                    continue
                
                try:
                    # Linker Kanal
                    filtered_left, zi_left = signal.sosfilt(
                        self.eq_filter_sos[band], 
                        filtered_left, 
                        zi=self.eq_filter_states[band]
                    )
                    
                    # Rechter Kanal (mit eigenem Zustand)
                    # Für Stereo brauchen wir separate States pro Kanal
                    if not hasattr(self, 'eq_filter_states_right'):
                        self.eq_filter_states_right = {}
                        for b in self.eq_bands:
                            self.eq_filter_states_right[b] = np.zeros((1, 2))
                    
                    filtered_right, zi_right = signal.sosfilt(
                        self.eq_filter_sos[band], 
                        filtered_right, 
                        zi=self.eq_filter_states_right[band]
                    )
                    
                    # Speichere States
                    self.eq_filter_states[band] = zi_left
                    self.eq_filter_states_right[band] = zi_right
                    
                    # Prüfe auf ungültige Werte
                    if (np.any(np.isnan(filtered_left)) or np.any(np.isinf(filtered_left)) or
                        np.any(np.isnan(filtered_right)) or np.any(np.isinf(filtered_right))):
                        print(f"Warnung: Ungültige Werte nach Filter {band}Hz - überspringe")
                        filtered_left = audio_np[:, 0].copy()
                        filtered_right = audio_np[:, 1].copy()
                        self.eq_filter_states[band] = np.zeros((1, 2))
                        self.eq_filter_states_right[band] = np.zeros((1, 2))
                        break
                        
                except Exception as e:
                    print(f"Fehler bei Filter {band}Hz: {e}")
                    self.eq_filter_states[band] = np.zeros((1, 2))
                    if hasattr(self, 'eq_filter_states_right'):
                        self.eq_filter_states_right[band] = np.zeros((1, 2))
                    continue
            
            # Kombiniere Kanäle zurück
            filtered = np.column_stack([filtered_left, filtered_right]).flatten()
        else:
            # Mono-Verarbeitung (wie bisher)
            filtered = audio_np.copy()
            
            for band in self.eq_bands:
                if self.eq_filter_sos[band] is None:
                    continue
                
                gain_db = self.eq_gains[band].get()
                if abs(gain_db) < 0.1:
                    continue
                
                self._update_peaking_filter(band, gain_db)
                if self.eq_filter_sos[band] is None:
                    continue
                
                try:
                    filtered, self.eq_filter_states[band] = signal.sosfilt(
                        self.eq_filter_sos[band], 
                        filtered, 
                        zi=self.eq_filter_states[band]
                    )
                    
                    if np.any(np.isnan(filtered)) or np.any(np.isinf(filtered)):
                        print(f"Warnung: Ungültige Werte nach Filter {band}Hz - überspringe")
                        filtered = audio_np.copy()
                        self.eq_filter_states[band] = np.zeros((1, 2))
                        break
                        
                except Exception as e:
                    print(f"Fehler bei Filter {band}Hz: {e}")
                    self.eq_filter_states[band] = np.zeros((1, 2))
                    continue
        
        # Sanftes Clipping zur Vermeidung von Verzerrungen
        # Prüfe auf NaN/Inf vor Clipping
        if np.any(np.isnan(filtered)) or np.any(np.isinf(filtered)):
            print("Warnung: Ungültige Werte im EQ - verwende Original")
            filtered = audio_np.copy()
        
        # Normalisiere wenn Signal zu laut
        max_val = np.max(np.abs(filtered))
        if max_val > 32767:
            filtered = filtered * (32000.0 / max_val)  # Lasse etwas Headroom
        
        # Final Clipping
        filtered = np.clip(filtered, -32768, 32767).astype(np.int16)
        
        if isinstance(audio_data, bytes):
            return filtered.tobytes()
        else:
            return filtered.tobytes()
    
    def create_gui(self):
        # Hauptframe
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        row = 0
        
        # Titel (zentriert)
        self.title_label = ttk.Label(main_frame, text="Simplex Repeater", 
                               font=('Arial', 16, 'bold'))
        self.title_label.grid(row=row, column=0, columnspan=2, pady=10)
        
        # Modus-Umschalter (zentriert)
        row += 1
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=row, column=0, columnspan=2, pady=10)
        
        self.mode_button = ttk.Button(mode_frame, text="Zu Duplex wechseln", 
                                      command=self.toggle_mode, width=20)
        self.mode_button.pack()
        
        # Trennlinie
        row += 1
        ttk.Separator(main_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # === Zwei Spalten: Links Input, Rechts Output ===
        row += 1
        
        # Linke Spalte (Input)
        left_frame = ttk.LabelFrame(main_frame, text="Eingangsbereich", padding="10")
        left_frame.grid(row=row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        
        # Rechte Spalte (Output)  
        right_frame = ttk.LabelFrame(main_frame, text="Ausgangsbereich", padding="10")
        right_frame.grid(row=row, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        
        # === LINKE SPALTE (INPUT) ===
        row_left = 0

        # Audio-Quelle Auswahl
        ttk.Label(left_frame, text="Audioeinstellungen:", font=('Arial', 11, 'bold')).grid(
            row=row_left, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        row_left += 1
        ttk.Label(left_frame, text="Audio-Eingabe:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        self.input_device_var = tk.StringVar()
        self.input_device_combo = ttk.Combobox(left_frame, textvariable=self.input_device_var,
                                              state='readonly', width=25)
        self.input_device_combo.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.input_device_combo.bind('<<ComboboxSelected>>', self.on_input_device_changed)
        
        # Titel Pegeleinstellungen
        row_left += 1
        ttk.Label(left_frame, text="Pegeleinstellungen:", font=('Arial', 11, 'bold')).grid(
            row=row_left, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        # Eingangspegel-Einstellung (Start Threshold)
        row_left += 1
        ttk.Label(left_frame, text="Startpegel (rot):").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        self.start_threshold_var = tk.IntVar(value=1000)
        threshold_frame = ttk.Frame(left_frame)
        threshold_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.threshold_scale = ttk.Scale(threshold_frame, from_=0, to=10000,
                                        variable=self.start_threshold_var, orient=tk.HORIZONTAL,
                                        command=self.on_threshold_change)
        self.threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.threshold_label = ttk.Label(threshold_frame, text="1000")
        self.threshold_label.pack(side=tk.LEFT, padx=5)
        self.start_threshold_var.trace('w', self.update_threshold_label)
        
        # Abbruch-Pegel-Einstellung (Stop Threshold)
        row_left += 1
        ttk.Label(left_frame, text="Stoppegel (grün):").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        self.stop_threshold_var = tk.IntVar(value=100)
        stop_threshold_frame = ttk.Frame(left_frame)
        stop_threshold_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.stop_threshold_scale = ttk.Scale(stop_threshold_frame, from_=0, to=10000,
                                             variable=self.stop_threshold_var, orient=tk.HORIZONTAL)
        self.stop_threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stop_threshold_label = ttk.Label(stop_threshold_frame, text="100")
        self.stop_threshold_label.pack(side=tk.LEFT, padx=5)
        self.stop_threshold_var.trace('w', self.update_stop_threshold_label)

        # Monitoring aktivieren (Checkbox)
        row_left += 1
        self.monitoring_var = tk.BooleanVar(value=False)
        self.monitoring_checkbox = ttk.Checkbutton(left_frame, text="Simplex Monitoring aktivieren (Duplex-Modus)",
                                                    variable=self.monitoring_var,
                                                    command=self.on_monitoring_toggle)
        self.monitoring_checkbox.grid(row=row_left, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # Canvas für Pegelanzeige
        row_left += 1
        self.level_canvas = tk.Canvas(left_frame, height=40, bg='white', 
                                      highlightthickness=1, highlightbackground='gray')
        self.level_canvas.grid(row=row_left, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Elemente für Level-Anzeige
        self.level_bar = None
        self.threshold_line = None
        self.stop_threshold_line = None
        
        # Titel Pegeldämpfung
        row_left += 1
        ttk.Label(left_frame, text="Pegeldämpfung:", font=('Arial', 11, 'bold')).grid(
            row=row_left, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        # Anstiegsdämpfung-Einstellung (Attack in ms)
        row_left += 1
        ttk.Label(left_frame, text="Anstiegsdämpfung:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        rise_time_frame = ttk.Frame(left_frame)
        rise_time_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.rise_time_var = tk.DoubleVar(value=0.0)
        self.rise_time_scale = ttk.Scale(rise_time_frame, from_=0.0, to=1000.0,
                                        variable=self.rise_time_var, orient=tk.HORIZONTAL)
        self.rise_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.rise_time_label = ttk.Label(rise_time_frame, text="Aus")
        self.rise_time_label.pack(side=tk.LEFT, padx=5)
        self.rise_time_var.trace('w', self.update_rise_time_label)
        
        # Abfalldämpfung-Einstellung (Release in ms)
        row_left += 1
        ttk.Label(left_frame, text="Abfalldämpfung:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        fall_time_frame = ttk.Frame(left_frame)
        fall_time_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.fall_time_var = tk.DoubleVar(value=100.0)
        self.fall_time_scale = ttk.Scale(fall_time_frame, from_=0.0, to=1000.0,
                                        variable=self.fall_time_var, orient=tk.HORIZONTAL)
        self.fall_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.fall_time_label = ttk.Label(fall_time_frame, text="100.0 ms")
        self.fall_time_label.pack(side=tk.LEFT, padx=5)
        self.fall_time_var.trace('w', self.update_fall_time_label)

        # Titel Zeiteinstellungen
        row_left += 1
        ttk.Label(left_frame, text="Zeiteinstellungen:", font=('Arial', 11, 'bold')).grid(
            row=row_left, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        # Maximale Aufnahmezeit-Einstellung
        row_left += 1
        ttk.Label(left_frame, text="Max. Aufnahmezeit:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        record_frame = ttk.Frame(left_frame)
        record_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.record_time_var = tk.DoubleVar(value=30.0)
        self.record_time_scale = ttk.Scale(record_frame, from_=1.0, to=120.0,
                                          variable=self.record_time_var, orient=tk.HORIZONTAL)
        self.record_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.record_time_label = ttk.Label(record_frame, text="30.0s")
        self.record_time_label.pack(side=tk.LEFT, padx=5)
        self.record_time_var.trace('w', self.update_record_time_label)
        
        # Abbruch-Zeit-Einstellung
        row_left += 1
        ttk.Label(left_frame, text="Max. Unterschreitung:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        stop_time_frame = ttk.Frame(left_frame)
        stop_time_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.stop_time_var = tk.DoubleVar(value=0.5)
        self.stop_time_scale = ttk.Scale(stop_time_frame, from_=0.1, to=5.0,
                                        variable=self.stop_time_var, orient=tk.HORIZONTAL)
        self.stop_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stop_time_label = ttk.Label(stop_time_frame, text="0.5s")
        self.stop_time_label.pack(side=tk.LEFT, padx=5)
        self.stop_time_var.trace('w', self.update_stop_time_label)
        
        # Totzeit-Einstellung (nur im Simplex-Modus relevant)
        row_left += 1
        ttk.Label(left_frame, text="Pause nach Wiedergabe:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        dead_time_frame = ttk.Frame(left_frame)
        dead_time_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.dead_time_var = tk.DoubleVar(value=2.0)
        self.dead_time_scale = ttk.Scale(dead_time_frame, from_=0.0, to=10.0,
                                        variable=self.dead_time_var, orient=tk.HORIZONTAL)
        self.dead_time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.dead_time_label = ttk.Label(dead_time_frame, text="2.0s")
        self.dead_time_label.pack(side=tk.LEFT, padx=5)
        self.dead_time_var.trace('w', self.update_dead_time_label)
        
        # === RECHTE SPALTE (OUTPUT) ===
        row_right = 0

        # Titel Audioeinstellungen
        ttk.Label(right_frame, text="Audioeinstellungen:", font=('Arial', 11, 'bold')).grid(
            row=row_right, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        # Audio-Ausgabe Auswahl
        row_right += 1
        ttk.Label(right_frame, text="Audio-Ausgabe:").grid(
            row=row_right, column=0, sticky=tk.W, pady=5)
        self.output_device_var = tk.StringVar()
        self.output_device_combo = ttk.Combobox(right_frame, textvariable=self.output_device_var,
                                               state='readonly', width=25)
        self.output_device_combo.grid(row=row_right, column=1, sticky=(tk.W, tk.E), pady=5)
        self.output_device_combo.bind('<<ComboboxSelected>>', self.on_output_device_changed)
        
        # Abtastrate-Auswahl
        row_right += 1
        ttk.Label(right_frame, text="Abtastrate:").grid(
            row=row_right, column=0, sticky=tk.W, pady=5)
        self.sample_rate_var = tk.IntVar(value=22000)
        sample_rate_frame = ttk.Frame(right_frame)
        sample_rate_frame.grid(row=row_right, column=1, sticky=(tk.W, tk.E), pady=5)
        self.sample_rate_combo = ttk.Combobox(sample_rate_frame, 
                                              textvariable=self.sample_rate_var,
                                              values=[8000, 16000, 22000, 32000, 44100],
                                              state='readonly', width=10)
        self.sample_rate_combo.pack(side=tk.LEFT)
        self.sample_rate_combo.bind('<<ComboboxSelected>>', self.on_sample_rate_changed)
        ttk.Label(sample_rate_frame, text="Hz").pack(side=tk.LEFT, padx=5)
        
        # Performance-Hinweis
        row_right += 1
        perf_hint = ttk.Label(right_frame, 
                             text="⚠ Höhere Abtastraten können die Performance\nbeeinträchtigen, besonders mit Equalizer.",
                             font=('Arial', 8, 'italic'),
                             foreground='#666666',
                             justify=tk.LEFT)
        perf_hint.grid(row=row_right, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        # Wiedergabeverzögerung-Einstellung (nur im Duplex-Modus relevant)
        row_right += 1
        ttk.Label(right_frame, text="Wiedergabeverzögerung:").grid(
            row=row_right, column=0, sticky=tk.W, pady=5)
        playback_delay_frame = ttk.Frame(right_frame)
        playback_delay_frame.grid(row=row_right, column=1, sticky=(tk.W, tk.E), pady=5)
        self.playback_delay_var = tk.IntVar(value=0)
        self.playback_delay_scale = ttk.Scale(playback_delay_frame, from_=0, to=1000,
                                        variable=self.playback_delay_var, orient=tk.HORIZONTAL,
                                        command=self.on_playback_delay_change)
        self.playback_delay_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.playback_delay_label = ttk.Label(playback_delay_frame, text="0 ms")
        self.playback_delay_label.pack(side=tk.LEFT, padx=5)
        self.playback_delay_var.trace('w', self.update_playback_delay_label)
        
        # Titel Equalizer
        row_right += 1
        ttk.Label(right_frame, text="Equalizer:", font=('Arial', 11, 'bold')).grid(
            row=row_right, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))

        
        # Verstärkungsfaktor-Einstellung
        row_right += 1
        ttk.Label(right_frame, text="Master:").grid(
            row=row_right, column=0, sticky=tk.W, pady=5)
        
        gain_frame = ttk.Frame(right_frame)
        gain_frame.grid(row=row_right, column=1, sticky=(tk.W, tk.E), pady=5)
        self.gain_var = tk.DoubleVar(value=0.0)
        self.gain_scale = ttk.Scale(gain_frame, from_=-20.0, to=20.0,
                                    variable=self.gain_var, orient=tk.HORIZONTAL)
        self.gain_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.gain_label = ttk.Label(gain_frame, text="0.0 dB")
        self.gain_label.pack(side=tk.LEFT, padx=5)
        self.gain_var.trace('w', self.update_gain_label)
        
        # Equalizer Aktivieren/Deaktivieren
        row_right += 1
        self.equalizer_enabled_var = tk.BooleanVar(value=True)
        self.equalizer_checkbox = ttk.Checkbutton(right_frame, text="Equalizer aktivieren",
                                                   variable=self.equalizer_enabled_var,
                                                   command=self.on_equalizer_toggle)
        self.equalizer_checkbox.grid(row=row_right, column=0, columnspan=2, sticky=tk.W, pady=(5, 10))
        
        # Equalizer-Bänder (5 Bänder)
        self.eq_scales = {}
        self.eq_labels = {}
        
        for band in self.eq_bands:
            row_right += 1
            
            # Band-Label
            if band < 1000:
                label_text = f"{band} Hz:"
            else:
                label_text = f"{band/1000:.1f} kHz:"
            
            ttk.Label(right_frame, text=label_text).grid(
                row=row_right, column=0, sticky=tk.W, pady=5)
            
            # Slider-Frame
            eq_frame = ttk.Frame(right_frame)
            eq_frame.grid(row=row_right, column=1, sticky=(tk.W, tk.E), pady=5)
            
            # Slider
            eq_scale = ttk.Scale(eq_frame, from_=-30.0, to=30.0,
                                variable=self.eq_gains[band], orient=tk.HORIZONTAL)
            eq_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.eq_scales[band] = eq_scale
            
            # Label für aktuellen Wert
            eq_label = ttk.Label(eq_frame, text="0.0 dB")
            eq_label.pack(side=tk.LEFT, padx=5)
            self.eq_labels[band] = eq_label
            
            # Trace für Label-Update
            self.eq_gains[band].trace('w', lambda *args, b=band: self.update_eq_label(b))
        
        
        # Spalten-Konfiguration
        left_frame.columnconfigure(1, weight=1)
        right_frame.columnconfigure(1, weight=1)
        
        # === STATUS UND STEUERUNG (unter beiden Spalten) ===
        row += 1
        
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=row, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))
        
        # Status-Anzeige
        status_frame = ttk.Frame(control_frame)
        status_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(status_frame, text="Gestoppt", 
                                      font=('Arial', 10, 'bold'),
                                      foreground='red')
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # Fortschrittsbalken (Aufnahme/Wiedergabe)
        progress_frame = ttk.Frame(control_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(progress_frame, text="Simplex Aufnahme/Wiedergabe:").pack(side=tk.LEFT, padx=5)
        self.progress = ttk.Progressbar(progress_frame, mode='determinate', maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=10)
        
        self.start_button = ttk.Button(button_frame, text="Start", 
                                      command=self.start_repeater, width=15)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", 
                                     command=self.stop_repeater, width=15,
                                     state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # Grid-Konfiguration
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
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
        
    def update_playback_delay_label(self, *args):
        value = self.playback_delay_var.get()
        self.playback_delay_label.config(text=f"{value} ms")
        
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
    
    def update_eq_label(self, band):
        """Aktualisiert das Label für ein Equalizer-Band"""
        value = self.eq_gains[band].get()
        self.eq_labels[band].config(text=f"{value:+.1f} dB")
    
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
            
            if info['maxInputChannels'] > 0:
                # Teste ob das Gerät wirklich Stereo unterstützt
                channels = min(info['maxInputChannels'], 2)
                
                # Versuche zu testen, ob Stereo funktioniert (ohne Stream zu starten)
                # PipeWire/Pulse-Geräte sollten Stereo unterstützen
                device_name_lower = info['name'].lower()
                likely_stereo = any(keyword in device_name_lower for keyword in ['pipewire', 'pulse', 'default'])
                
                # Wenn es ein wahrscheinlich Stereo-fähiges Gerät ist und maxChannels >= 2, zeige Stereo an
                if channels == 2 or (likely_stereo and info['maxInputChannels'] >= 2):
                    channels = 2
                    channel_info = "Stereo"
                else:
                    channels = 1
                    channel_info = "Mono"
                    
                name = f"{i}: {info['name']} ({channel_info})"
                input_devices.append((i, name, channels))
                
            if info['maxOutputChannels'] > 0:
                # Zeige Kanalanzahl für Ausgänge (begrenzt auf 2 für Stereo)
                channels = min(info['maxOutputChannels'], 2)
                channel_info = "Stereo" if channels == 2 else "Mono"
                name = f"{i}: {info['name']} ({channel_info})"
                output_devices.append((i, name, channels))
        
        # Sortiere Geräte: Stereo zuerst, dann Mono
        input_devices.sort(key=lambda x: (0 if x[2] == 2 else 1, x[1]))
        output_devices.sort(key=lambda x: (0 if x[2] == 2 else 1, x[1]))
        
        # Comboboxen füllen
        self.input_device_combo['values'] = [name for _, name, _ in input_devices]
        self.output_device_combo['values'] = [name for _, name, _ in output_devices]
        
        # Standard-Geräte auswählen (bevorzuge Stereo-Geräte)
        if input_devices:
            # Suche nach "pipewire", "pulse" oder "default" Stereo-Gerät
            default_idx = 0
            for idx, (_, name, channels) in enumerate(input_devices):
                if channels == 2 and any(keyword in name.lower() for keyword in ['pipewire', 'pulse', 'default']):
                    default_idx = idx
                    break
            self.input_device_combo.current(default_idx)
            
        if output_devices:
            # Suche nach "pipewire", "pulse" oder "default" Stereo-Gerät
            default_idx = 0
            for idx, (_, name, channels) in enumerate(output_devices):
                if channels == 2 and any(keyword in name.lower() for keyword in ['pipewire', 'pulse', 'default']):
                    default_idx = idx
                    break
            self.output_device_combo.current(default_idx)
            
        # Geräte-IDs und Kanalanzahl speichern
        self.input_devices = {name: (idx, channels) for idx, name, channels in input_devices}
        self.output_devices = {name: (idx, channels) for idx, name, channels in output_devices}
        
    def get_selected_input_device(self):
        """Gibt die ausgewählte Eingabe-Geräte-ID und Kanalanzahl zurück"""
        device_name = self.input_device_var.get()
        device_info = self.input_devices.get(device_name, None)
        if device_info is None:
            return None, 1  # Fallback zu Mono
        return device_info  # (device_id, channels)
        
    def get_selected_output_device(self):
        """Gibt die ausgewählte Ausgabe-Geräte-ID und Kanalanzahl zurück"""
        device_name = self.output_device_var.get()
        device_info = self.output_devices.get(device_name, None)
        if device_info is None:
            return None, 1  # Fallback zu Mono
        return device_info  # (device_id, channels)
    
    def on_input_device_changed(self, event=None):
        """Wird aufgerufen wenn Eingangsquelle geändert wird"""
        # Quellenwechsel nur im Stillstand erlaubt (Dropdown ist während Betrieb deaktiviert)
        pass
    
    def on_output_device_changed(self, event=None):
        """Wird aufgerufen wenn Ausgangsquelle geändert wird"""
        # Quellenwechsel nur im Stillstand erlaubt (Dropdown ist während Betrieb deaktiviert)
        pass
    
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
            input_device_id, input_channels = self.get_selected_input_device()
            output_device_id, output_channels = self.get_selected_output_device()
            
            # Speichere die tatsächlichen Kanalanzahlen
            self.input_channels = input_channels
            self.output_channels = output_channels
            
            if input_device_id is not None:
                try:
                    # Versuche mit der angegebenen Kanalanzahl zu öffnen
                    # Bei Fehlschlag versuche mit weniger Kanälen
                    opened = False
                    for try_channels in [input_channels, 2, 1]:  # Versuche gewünschte, dann Stereo, dann Mono
                        if opened:
                            break
                        try:
                            self.stream_in = self.p.open(
                                format=self.FORMAT,
                                channels=try_channels,
                                rate=self.RATE,
                                input=True,
                                input_device_index=input_device_id,
                                frames_per_buffer=self.CHUNK
                            )
                            self.input_channels = try_channels
                            opened = True
                            print(f"Input-Stream geöffnet: {try_channels} Kanal(Kanäle)")
                            if try_channels != input_channels:
                                print(f"HINWEIS: Gerät unterstützt nur {try_channels} Kanal(Kanäle), nicht {input_channels}")
                            break
                        except Exception as e:
                            if try_channels == 1:  # Letzter Versuch fehlgeschlagen
                                raise e
                            else:
                                print(f"Versuch mit {try_channels} Kanälen fehlgeschlagen, versuche weniger...")
                                continue
                except Exception as e:
                    print(f"Fehler beim Öffnen des Input-Streams: {e}")
                    self.root.after(0, messagebox.showerror, "Fehler", 
                                  f"Eingangsquelle konnte nicht geöffnet werden: {str(e)}")
            
            if output_device_id is not None:
                try:
                    self.stream_out = self.p.open(
                        format=self.FORMAT,
                        channels=output_channels,  # Verwende tatsächliche Kanalanzahl des Geräts
                        rate=self.RATE,
                        output=True,
                        output_device_index=output_device_id,
                        frames_per_buffer=self.CHUNK
                    )
                    print(f"Output-Stream geöffnet: {output_channels} Kanäle")
                except Exception as e:
                    print(f"Fehler beim Öffnen des Output-Streams: {e}")
                    self.root.after(0, messagebox.showerror, "Fehler", 
                                  f"Ausgangsquelle konnte nicht geöffnet werden: {str(e)}")
        
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
            except:
                # Balken existiert nicht mehr, erstelle neu
                self.level_bar = None
        
        if not self.level_bar:
            self.level_bar = self.level_canvas.create_rectangle(
                0, 0, bar_width, canvas_height,
                fill='lightgray', outline='', tags='level')
            # Schwellwert-Linien in den Vordergrund (nur beim ersten Mal)
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
            
            # Duplex oder Simplex Modus
            if self.is_duplex_mode:
                self.audio_loop_duplex()
            else:
                self.audio_loop_simplex()
            
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
    
    def calculate_delayed_buffer_size(self):
        """Berechnet die Zielgröße des Duplex-Wiedergabe-Buffers basierend auf der Verzögerung"""
        delay_ms = self.playback_delay_var.get()
        delay_chunks = int((delay_ms / 1000.0) * self.RATE / self.CHUNK)
        delay_chunks = max(2, delay_chunks)
        self.delayed_playback_buffer_size = delay_chunks

    def audio_loop_duplex(self):
        """Audio-Schleife für Duplex-Modus (gleichzeitig aufnehmen und abspielen)
        Kontinuierliches Streaming ohne Trigger-Logik mit konstanter Verzögerung
        """
        # Ring-Buffer für verzögertes Wiedergabe-Streaming
        
        # WICHTIG: Kein maxlen - wir wollen einen konstanten Puffer für permanente Verzögerung
        self.delayed_playback_buffer = deque()
        self.duplex_recording = True
        self.calculate_delayed_buffer_size()
        
        # Stille für initialen Buffer (nutzt output_channels für Wiedergabe)
        silence = np.zeros(self.CHUNK * self.output_channels, dtype=np.int16).tobytes()
        
        # Fülle Buffer initial mit Verzögerung
        for _ in range(self.delayed_playback_buffer_size):
            self.delayed_playback_buffer.append(silence)
        
        self.root.after(0, self.update_status, 
                       f"Duplex: Aktiv ({self.playback_delay_var.get()}ms Verzögerung)", 'green')
        
        # Thread für kontinuierliche Aufnahme
        def record_thread():
            
            while self.running and self.duplex_recording:
                
                try:
                    # Warte bis genug Platz im Buffer ist
                    self.calculate_delayed_buffer_size()
                    while len(self.delayed_playback_buffer) > self.delayed_playback_buffer_size:
                        time.sleep(0.001)
                        
                    # Aufnahme
                    data = self.stream_in.read(self.CHUNK, exception_on_overflow=False)
                    
                    # Sofort zum Wiedergabe-Buffer hinzufügen (Performance-kritisch!)
                    self.delayed_playback_buffer.append(data)

                    level = self.calculate_level(data)
                    self._update_level_gui(level)
                    
                except Exception as e:
                    print(f"Fehler beim Lesen (Duplex): {e}")
                    time.sleep(0.001)
        
        # Thread für kontinuierliche Wiedergabe
        def playback_thread():
            """Kontinuierliche Wiedergabe aus Buffer mit konstanter Verzögerung"""
            # Warte bis Buffer gefüllt ist
            while len(self.delayed_playback_buffer) < self.delayed_playback_buffer_size and self.running:
                time.sleep(0.01)
            
            while self.running:
                try:

                    # Spiele ab, sobald mindestens die Ziel-Verzögerung erreicht ist
                    if len(self.delayed_playback_buffer) >= self.delayed_playback_buffer_size:
                        with self.streams_lock:
                            if self.stream_out is None:
                                break
                            # Hole Daten aus dem Buffer 
                            data = self.delayed_playback_buffer.popleft()
                            while len(self.delayed_playback_buffer) >= self.delayed_playback_buffer_size:
                                data += self.delayed_playback_buffer.popleft()
                        
                            # Equalizer anwenden (wird übersprungen wenn deaktiviert)
                            data = self.apply_equalizer(data)

                            # Verstärkung anwenden
                            data = self.apply_gain(data)

                            # Konvertiere Kanäle falls nötig (z.B. Stereo-Input zu Mono-Output)
                            data_for_output = self.convert_channels(data, self.input_channels, self.output_channels)

                            self.stream_out.write(data_for_output)
                    else:
                        # Buffer leer, warte kurz
                        time.sleep(0.001)
                        
                except Exception as e:
                    print(f"Fehler bei Wiedergabe (Duplex): {e}")
                    time.sleep(0.001)
            
            self.delayed_playback_buffer.clear()
        

        # Starte beide Threads
        playback_t = threading.Thread(target=playback_thread, daemon=True)
        record_t = threading.Thread(target=record_thread, daemon=True)
        
        playback_t.start()
        record_t.start()
        
        # Warte auf Beendigung
        while self.running:
            time.sleep(0.1)
        
        self.duplex_recording = False
        record_t.join(timeout=1.0)
        playback_t.join(timeout=1.0)
        
        # Buffer leeren
        self.delayed_playback_buffer.clear()
    
    def audio_loop_simplex(self):
        """Audio-Schleife für Simplex-Modus (klassischer Modus)"""
        
        # Ring-Buffer für verzögerte Wiedergabe (verhindert Rückkopplungen)
        self.delayed_playback_buffer = deque()
        self.calculate_delayed_buffer_size()
        
        # Stille für initialen Buffer (nutzt output_channels für Wiedergabe)
        silence = np.zeros(self.CHUNK * self.output_channels, dtype=np.int16).tobytes()
        
        # Fülle Buffer initial mit Verzögerung
        for _ in range(self.delayed_playback_buffer_size):
            self.delayed_playback_buffer.append(silence)
        
        # Thread für kontinuierliche Wiedergabe aus Buffer
        self.simplex_playback_running = True
        
        def simplex_playback_thread():
            """Kontinuierliche Wiedergabe aus verzögertem Buffer (für Monitoring und Aufnahme)"""
            # Warte bis Buffer gefüllt ist
            while len(self.delayed_playback_buffer) < self.delayed_playback_buffer_size and self.running:
                time.sleep(0.01)
            
            while self.running and self.simplex_playback_running:
                try:
                    # Spiele nur wenn Monitoring aktiviert ist, NICHT während Wiedergabe einer Aufnahme
                    if self.monitoring_enabled and not self.is_playing and len(self.delayed_playback_buffer) >= self.delayed_playback_buffer_size:
                        # Hole Daten aus dem Buffer
                        data = self.delayed_playback_buffer.popleft()
                        # Entferne überschüssige Daten um Buffer-Größe konstant zu halten
                        while len(self.delayed_playback_buffer) >= self.delayed_playback_buffer_size:
                            data += self.delayed_playback_buffer.popleft()

                        # Equalizer anwenden (wird übersprungen wenn deaktiviert)
                        data = self.apply_equalizer(data)

                        # Verstärkung anwenden
                        data = self.apply_gain(data)
                        
                        # Konvertiere Kanäle falls nötig für Wiedergabe
                        data_for_output = self.convert_channels(data, self.input_channels, self.output_channels)

                        self.stream_out.write(data_for_output)
                    else:
                        # Monitoring deaktiviert, Wiedergabe läuft oder Buffer leer
                        time.sleep(0.001)
                        
                except Exception as e:
                    print(f"Fehler bei verzögerter Wiedergabe (Simplex): {e}")
                    time.sleep(0.001)
        
        # Starte Wiedergabe-Thread
        playback_t = threading.Thread(target=simplex_playback_thread, daemon=True)
        playback_t.start()

        while self.running:
            # Audio-Daten lesen
            try:
                # Sperre für Stream-Zugriff
                with self.streams_lock:
                    if self.stream_in is None:
                        break

                    # Aufnahme
                    data = self.stream_in.read(self.CHUNK, exception_on_overflow=False)

                    # Füge zum verzögerten Wiedergabe-Buffer hinzu nur wenn Monitoring aktiviert
                    if self.monitoring_enabled:
                        # Aktualisiere Buffer-Größe falls Verzögerung geändert wurde
                        self.calculate_delayed_buffer_size()
                        # Warte falls Buffer zu voll ist
                        while len(self.delayed_playback_buffer) > self.delayed_playback_buffer_size + 5:
                            time.sleep(0.001)
                        # Konvertiere Kanäle falls nötig für Wiedergabe
                        data_for_output = self.convert_channels(data, self.input_channels, self.output_channels)
                        self.delayed_playback_buffer.append(data_for_output)
                
                    # Pegel aktualisieren
                    level = self.calculate_level(data)
                    self.update_level(level)
                
                # Wenn nicht gerade abgespielt wird und nicht aufgenommen wird
                if not self.is_playing and not self.is_recording:
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
        
        # Beende Wiedergabe-Thread
        self.simplex_playback_running = False
        playback_t.join(timeout=1.0)
        
        # Buffer leeren
        self.delayed_playback_buffer.clear()
            
    def start_recording(self):
        """Startet die Aufnahme"""
        self.is_recording = True
        self.audio_buffer.clear()
        self.root.after(0, self.update_status, "Aufnahme läuft...", 'orange')
        
        
        stop_threshold = self.stop_threshold_var.get()
        stop_time = self.stop_time_var.get()
        chunks_for_stop = int(self.RATE / self.CHUNK * stop_time)
        low_level_counter = 0

        def get_chunks_to_record():
            record_time = self.record_time_var.get()
            return int(self.RATE / self.CHUNK * record_time)
        
        # Aufnahme
        chunk_count = 0
        for _ in range(get_chunks_to_record()):
            if not self.running:
                break
            chunks_to_record = get_chunks_to_record()
            try:

                with self.streams_lock:
                    if self.stream_in is None:
                        break
                    
                    if chunk_count >= chunks_to_record:
                        break

                    data = self.stream_in.read(self.CHUNK, exception_on_overflow=False)
                    chunk_count += 1

                    self.audio_buffer.append(data)

                    # Füge zum verzögerten Wiedergabe-Buffer hinzu nur wenn Monitoring aktiviert
                    if self.monitoring_enabled:
                        # Aktualisiere Buffer-Größe falls Verzögerung geändert wurde
                        self.calculate_delayed_buffer_size()
                        # Warte falls Buffer zu voll ist
                        while len(self.delayed_playback_buffer) > self.delayed_playback_buffer_size + 5:
                            time.sleep(0.001)
                        # Konvertiere Kanäle falls nötig für Wiedergabe
                        data_for_output = self.convert_channels(data, self.input_channels, self.output_channels)
                        self.delayed_playback_buffer.append(data_for_output)
                
                
                progress_percent = (chunk_count / chunks_to_record) * 100
                self.root.after(0, self.update_progress, progress_percent)

                level = self.calculate_level(data)
                self.update_level(level)
                
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
        
    def apply_gain(self, data):
        """Wendet Verstärkung auf Audio-Daten an (Stereo-kompatibel)"""
        gain_db = self.gain_var.get()
        
        # Wenn Verstärkung 0 dB ist, gib Originaldaten zurück
        if gain_db == 0.0:
            return data
        
        # Konvertiere dB zu linearem Faktor: gain_linear = 10^(gain_dB / 20)
        gain_linear = 10.0 ** (gain_db / 20.0)
        
        # Konvertiere Bytes zu numpy Array (funktioniert für Mono und Stereo)
        audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        
        # Wende Verstärkung an (auf alle Kanäle)
        audio_data *= gain_linear
        
        # Clipping vermeiden (begrenze auf int16 Bereich)
        audio_data = np.clip(audio_data, -32768, 32767)
        
        # Zurück zu int16 konvertieren
        return audio_data.astype(np.int16).tobytes()
    
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
                    
                # Equalizer anwenden (wird übersprungen wenn deaktiviert)
                data = self.apply_equalizer(data)

                # Verstärkung anwenden
                data = self.apply_gain(data)
                
                # Konvertiere Kanäle falls nötig für Wiedergabe
                data_for_output = self.convert_channels(data, self.input_channels, self.output_channels)
                
                self.stream_out.write(data_for_output)
                
                played_chunks += 1

                level = self.calculate_level(data)
                self.update_level(level)
                
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
                self.gain_var.set(config.get('gain', 0.0))
                
                # Equalizer-Einstellungen laden
                eq_config = config.get('equalizer', {})
                for band in self.eq_bands:
                    if str(band) in eq_config:
                        self.eq_gains[band].set(eq_config[str(band)])
                
                # Modus laden
                saved_duplex_mode = config.get('duplex_mode', False)
                if saved_duplex_mode != self.is_duplex_mode:
                    self.toggle_mode()
                
                # Wiedergabeverzögerung laden
                self.playback_delay_var.set(config.get('playback_delay', 0))
                self.playback_delay_ms = config.get('playback_delay', 0)
                
                # Equalizer-Aktivierung laden
                equalizer_enabled = config.get('equalizer_enabled', True)
                self.equalizer_enabled_var.set(equalizer_enabled)
                self.equalizer_enabled = equalizer_enabled
                
                # Abtastrate laden
                saved_rate = config.get('sample_rate', 22000)
                if saved_rate in [8000, 16000, 22000, 32000, 44100]:
                    self.RATE = saved_rate
                    self.sample_rate_var.set(saved_rate)
                
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
        
        # Aktualisiere Equalizer-Slider-Status basierend auf Aktivierung
        state = tk.NORMAL if self.equalizer_enabled else tk.DISABLED
        for band in self.eq_bands:
            self.eq_scales[band].config(state=state)
    
    def save_config(self):
        """Speichert Konfiguration in Datei"""
        try:
            # Equalizer-Einstellungen sammeln
            eq_config = {}
            for band in self.eq_bands:
                eq_config[str(band)] = self.eq_gains[band].get()
            
            config = {
                'start_threshold': self.start_threshold_var.get(),
                'stop_threshold': self.stop_threshold_var.get(),
                'rise_time': self.rise_time_var.get(),
                'fall_time': self.fall_time_var.get(),
                'record_time': self.record_time_var.get(),
                'stop_time': self.stop_time_var.get(),
                'dead_time': self.dead_time_var.get(),
                'gain': self.gain_var.get(),
                'playback_delay': self.playback_delay_var.get(),
                'equalizer': eq_config,
                'equalizer_enabled': self.equalizer_enabled_var.get(),
                'sample_rate': self.RATE,
                'duplex_mode': self.is_duplex_mode,
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