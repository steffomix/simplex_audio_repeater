import threading
import time
import numpy as np
from collections import deque
from tkinter import messagebox


class AudioEngineMixin:

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
                    data = self.apply_input_gain(data)

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
                    data = self.apply_input_gain(data)

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
                    data = self.apply_input_gain(data)
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
