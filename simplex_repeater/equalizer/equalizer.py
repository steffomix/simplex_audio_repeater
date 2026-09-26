import numpy as np
import scipy.signal as signal


class EqualizerMixin:

    def _init_equalizer_filters(self):
        """Initialisiert die EQ-Filter für den Equalizer"""
        for band in self.eq_bands:
            # Initialer Zustand für sosfilt mit 1 Section: Form (1, 2)
            self.eq_filter_states[band] = np.zeros((1, 2))
            # Erstelle initiale SOS-Koeffizienten (Bypass-Filter bei 0 dB)
            self._update_band_filter(band, 0.0)

    def _update_band_filter(self, freq, gain_db):
        """Erstellt den EQ-Filter für ein Band als Second-Order Section

        Das unterste Band (niedrigste Frequenz in eq_bands) wird als Low-Shelf
        und das oberste Band (höchste Frequenz) als High-Shelf ausgeführt, damit
        deren Wirkung nicht wie bei einem Peaking-Filter zu den Rändern des
        Spektrums hin abfällt, sondern flach in Richtung 0 Hz bzw. Nyquist
        weitergeführt wird. Alle Bänder dazwischen bleiben Peaking-Filter
        (Glockenkurve). Verwendet Audio EQ Cookbook Formeln.
        """
        # Überprüfe Nyquist-Frequenz
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
            # Normalisierte Frequenz (0 bis pi)
            w0 = 2.0 * np.pi * freq / self.RATE

            # Sicherheitsprüfung
            if w0 <= 0 or w0 >= np.pi:
                raise ValueError(f"w0 außerhalb gültigem Bereich: {w0}")

            cos_w0 = np.cos(w0)
            sin_w0 = np.sin(w0)

            # Amplitude (Gain-Faktor)
            A = 10.0 ** (gain_db / 40.0)  # /40 für Peaking/Shelf-EQ (nicht /20)

            is_low_shelf = freq == min(self.eq_bands)
            is_high_shelf = freq == max(self.eq_bands)

            if is_low_shelf or is_high_shelf:
                # Shelf-Slope S=1: steilste Flanke ohne Überschwinger im Übergang
                S = 1.0
                alpha = sin_w0 / 2.0 * np.sqrt((A + 1.0/A) * (1.0/S - 1.0) + 2.0)
                sqrt_A = np.sqrt(A)

                if is_low_shelf:
                    b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha)
                    b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
                    b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha)
                    a0 = (A + 1.0) + (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha
                    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
                    a2 = (A + 1.0) + (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha
                else:
                    b0 = A * ((A + 1.0) + (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha)
                    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w0)
                    b2 = A * ((A + 1.0) + (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha)
                    a0 = (A + 1.0) - (A - 1.0) * cos_w0 + 2.0 * sqrt_A * alpha
                    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cos_w0)
                    a2 = (A + 1.0) - (A - 1.0) * cos_w0 - 2.0 * sqrt_A * alpha
            else:
                # Peaking-EQ (Glockenkurve) für die mittleren Bänder
                Q = 1.41  # etwa 1 Oktave Bandbreite
                alpha = sin_w0 / (2.0 * Q)

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
                self._update_band_filter(band, gain_db)

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

                self._update_band_filter(band, gain_db)
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

        return filtered.tobytes()
