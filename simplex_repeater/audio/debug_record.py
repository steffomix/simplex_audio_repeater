import os
import time
import wave
import threading

# .../simplex_repeater/audio/debug_record.py -> repo root is 3 levels up
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEBUG_RECORD_DIR = os.path.join(_REPO_ROOT, "debug_record")


class DebugRecordMixin:
    """Schreibt ein- und ausgehende Roh-Audiodaten inkl. Zeitstempel nach
    ./debug_record, um Timing-/Drop-Probleme (z.B. zu schnelle Wiedergabe)
    nachträglich analysieren zu können. Wird niemals zum Abbruch der
    eigentlichen Audio-Verarbeitung führen, falls das Schreiben fehlschlägt.
    """

    def start_debug_recording(self):
        self._debug_record_enabled = False
        self._debug_wave_in = None
        self._debug_wave_out = None
        self._debug_log_file = None
        self._debug_log_lock = threading.Lock()
        self._debug_start_time = time.time()

        try:
            os.makedirs(DEBUG_RECORD_DIR, exist_ok=True)
            session_id = time.strftime("%Y%m%d_%H%M%S")

            self._debug_wave_in = wave.open(
                os.path.join(DEBUG_RECORD_DIR, f"input_{session_id}.wav"), 'wb')
            self._debug_wave_in.setnchannels(self.input_channels)
            self._debug_wave_in.setsampwidth(self.p.get_sample_size(self.FORMAT))
            self._debug_wave_in.setframerate(self.RATE)

            self._debug_wave_out = wave.open(
                os.path.join(DEBUG_RECORD_DIR, f"output_{session_id}.wav"), 'wb')
            self._debug_wave_out.setnchannels(self.output_channels)
            self._debug_wave_out.setsampwidth(self.p.get_sample_size(self.FORMAT))
            self._debug_wave_out.setframerate(self.RATE)

            self._debug_log_file = open(
                os.path.join(DEBUG_RECORD_DIR, f"timestamps_{session_id}.csv"), 'w')
            self._debug_log_file.write("direction,t_seconds_since_start,frames,bytes,read_seconds\n")

            self._debug_record_enabled = True
            print(f"Debug-Aufzeichnung aktiv: {DEBUG_RECORD_DIR} (Session {session_id})")
        except Exception as e:
            print(f"Debug-Aufzeichnung konnte nicht gestartet werden: {e}")
            self._debug_record_enabled = False

    def stop_debug_recording(self):
        self._debug_record_enabled = False
        for wav in (self._debug_wave_in, self._debug_wave_out):
            if wav is not None:
                try:
                    wav.close()
                except Exception:
                    pass
        if self._debug_log_file is not None:
            try:
                self._debug_log_file.close()
            except Exception:
                pass

    def _debug_log(self, direction, frames, num_bytes, read_seconds=0.0):
        with self._debug_log_lock:
            t = time.time() - self._debug_start_time
            self._debug_log_file.write(f"{direction},{t:.6f},{frames},{num_bytes},{read_seconds:.6f}\n")

    def debug_record_input(self, data, channels, read_seconds=0.0):
        """Zeichnet rohe, vom Mikrofon gelesene PCM-Daten auf (vor Gain/Konvertierung).
        read_seconds ist die reine Blockierzeit von stream_in.read() (ohne
        Verarbeitung drumherum), um Treiber-/Hardware-Stalls von
        Anwendungs-Overhead unterscheiden zu können."""
        if not self._debug_record_enabled:
            return
        try:
            frames = len(data) // (2 * channels)
            self._debug_wave_in.writeframes(data)
            self._debug_log('in', frames, len(data), read_seconds)
        except Exception as e:
            print(f"Fehler beim Schreiben der Debug-Eingangsdaten: {e}")

    def debug_record_output(self, data, channels):
        """Zeichnet die tatsächlich an den Output-Stream geschriebenen PCM-Daten auf"""
        if not self._debug_record_enabled:
            return
        try:
            frames = len(data) // (2 * channels)
            self._debug_wave_out.writeframes(data)
            self._debug_log('out', frames, len(data))
        except Exception as e:
            print(f"Fehler beim Schreiben der Debug-Ausgangsdaten: {e}")
