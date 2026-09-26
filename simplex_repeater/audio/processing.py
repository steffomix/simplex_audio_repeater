import time
import numpy as np


class ProcessingMixin:

    # Auto-Pegel (AGC): Zielbereich und Nachregelgeschwindigkeit, gemeinsam für
    # Eingangsverstärker und Master verwendet (Werte auf der calculate_level()-Skala,
    # dieselbe Skala wie Start-/Stoppegel)
    AUTO_LEVEL_TARGET_LOW = 1500
    AUTO_LEVEL_TARGET_HIGH = 5000
    AUTO_LEVEL_SPEED_DB_PER_SEC = 6.0

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
            # Mono zu Stereo: Dupliziere Mono-Kanal
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

    def _adjust_auto_gain(self, gain_var, level, last_time_attr):
        """Regelt gain_var (dB) automatisch nach, um level im Zielbereich zu halten"""
        now = time.time()
        elapsed = now - getattr(self, last_time_attr, now)
        setattr(self, last_time_attr, now)

        # Große Sprünge (z.B. direkt nach dem Aktivieren) ignorieren statt aufzuholen
        if elapsed <= 0 or elapsed > 1.0:
            return

        max_step_db = self.AUTO_LEVEL_SPEED_DB_PER_SEC * elapsed
        current_gain = gain_var.get()

        if level > self.AUTO_LEVEL_TARGET_HIGH:
            gain_var.set(round(max(-20.0, current_gain - max_step_db), 1))
        elif level < self.AUTO_LEVEL_TARGET_LOW:
            gain_var.set(round(min(20.0, current_gain + max_step_db), 1))

    def apply_gain(self, data):
        """Wendet Verstärkung auf Audio-Daten an (Stereo-kompatibel)"""
        gain_db = self.gain_var.get()

        # Wenn Verstärkung 0 dB ist, gib Originaldaten zurück
        if gain_db == 0.0:
            result = data
        else:
            # Konvertiere dB zu linearem Faktor: gain_linear = 10^(gain_dB / 20)
            gain_linear = 10.0 ** (gain_db / 20.0)

            # Konvertiere Bytes zu numpy Array (funktioniert für Mono und Stereo)
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)

            # Wende Verstärkung an (auf alle Kanäle)
            audio_data *= gain_linear

            # Clipping vermeiden (begrenze auf int16 Bereich)
            audio_data = np.clip(audio_data, -32768, 32767)

            result = audio_data.astype(np.int16).tobytes()

        if self.output_auto_level_var.get():
            self._adjust_auto_gain(self.gain_var, self.calculate_level(result), '_output_agc_last_time')

        return result

    def apply_input_gain(self, data):
        """Wendet Eingangsverstärkung auf rohe Aufnahmedaten an"""
        gain_db = self.input_gain_var.get()

        if gain_db == 0.0:
            result = data
        else:
            gain_linear = 10.0 ** (gain_db / 20.0)
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            audio_data *= gain_linear
            audio_data = np.clip(audio_data, -32768, 32767)
            result = audio_data.astype(np.int16).tobytes()

        if self.input_auto_level_var.get():
            self._adjust_auto_gain(self.input_gain_var, self.calculate_level(result), '_input_agc_last_time')

        return result

