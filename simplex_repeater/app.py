import os
import tkinter as tk
import pyaudio
import threading
import time
from collections import deque

from .audio.engine import AudioEngineMixin
from .audio.devices import DevicesMixin
from .audio.processing import ProcessingMixin
from .equalizer.equalizer import EqualizerMixin
from .gui.main_window import GuiMixin
from .gui.callbacks import CallbacksMixin
from .config import ConfigMixin


class SimplexRepeater(AudioEngineMixin, DevicesMixin, ProcessingMixin,
                      EqualizerMixin, GuiMixin, CallbacksMixin, ConfigMixin):

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
        self.RATE = 44100
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

        # Equalizer-Einstellungen (6 Bänder)
        self.eq_bands = [150, 1000, 3000, 6000, 9000, 12000]  # Mittelpunkte in Hz
        self.eq_gains = {}  # Dictionary für Gain-Werte (dB)
        for band in self.eq_bands:
            self.eq_gains[band] = tk.DoubleVar(value=0.0)

        # Eingangsverstärker
        self.input_gain_var = tk.DoubleVar(value=0.0)

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

    def cleanup(self):
        """Aufräumen beim Schließen"""
        self.running = False
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        # Konfiguration speichern beim Beenden
        self.save_config()
        self.p.terminate()
