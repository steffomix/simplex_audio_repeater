from tkinter import messagebox
import pyaudio


class DevicesMixin:

    # ALSA-Kompatibilitäts-/Alias-Geräte, die unter PipeWire meist nicht
    # funktionieren oder nur ein redundantes Duplikat einer bereits als
    # "hw:X,Y" gelisteten echten Karte sind. Werden aus den Comboboxen entfernt,
    # damit die Liste übersichtlich bleibt und dem entspricht, was System-
    # Klangeinstellungen (z.B. "Klang"-Dialog) tatsächlich als Gerät anzeigen.
    _LOW_VALUE_DEVICE_NAMES = {'oss', 'dsp', '/dev/dsp', 'hdmi'}

    # PipeWire/Pulse/ALSA stellen für den Systemstandard mehrere Alias-Namen
    # bereit, die alle auf dasselbe aktuell aktive Gerät zeigen. Statt sie
    # einzeln (und damit dreifach redundant) aufzulisten, wird nur der laut
    # dieser Prioritätsreihenfolge erste gefundene Alias zu einem einzigen,
    # klar beschrifteten "System-Standard"-Eintrag zusammengefasst.
    _SYSTEM_DEFAULT_ALIASES = ['pipewire', 'pulse', 'default']

    def get_device_channels(self, device_index):
        """Ermittelt die maximale Anzahl von Ein- und Ausgangskanälen für ein Gerät."""
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            input_channels = device_info.get('maxInputChannels', 0)
            output_channels = device_info.get('maxOutputChannels', 0)
            return input_channels, output_channels
        except IOError:
            return 0, 0

    def load_audio_devices(self, preserve_selection=False):
        """Lädt verfügbare Audio-Geräte.

        Args:
            preserve_selection: Wenn True, wird versucht die aktuell ausgewählten
                Geräte anhand ihres (indexunabhängigen) Namens in der neu geladenen
                Liste wiederzufinden, statt das Standardgerät auszuwählen. Wird beim
                manuellen Aktualisieren der Geräteliste verwendet.
        """
        previous_input_raw = self.input_device_raw_names.get(self.input_device_var.get()) \
            if preserve_selection else None
        previous_output_raw = self.output_device_raw_names.get(self.output_device_var.get()) \
            if preserve_selection else None

        input_devices = []
        output_devices = []
        # Kandidaten für den zusammengefassten "System-Standard"-Eintrag: alias -> (index, raw_name, channels)
        input_default_aliases = {}
        output_default_aliases = {}

        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            raw_name = info['name']
            name_key = raw_name.strip().lower()

            if name_key in self._LOW_VALUE_DEVICE_NAMES:
                continue

            if info['maxInputChannels'] > 0:
                channels = 2 if info['maxInputChannels'] >= 2 else 1
                if name_key in self._SYSTEM_DEFAULT_ALIASES:
                    input_default_aliases[name_key] = (i, raw_name, channels)
                else:
                    channel_info = "Stereo" if channels == 2 else "Mono"
                    name = f"{i}: {raw_name} ({channel_info})"
                    input_devices.append((i, name, channels, raw_name))

            if info['maxOutputChannels'] > 0:
                channels = 2 if info['maxOutputChannels'] >= 2 else 1
                if name_key in self._SYSTEM_DEFAULT_ALIASES:
                    output_default_aliases[name_key] = (i, raw_name, channels)
                else:
                    channel_info = "Stereo" if channels == 2 else "Mono"
                    name = f"{i}: {raw_name} ({channel_info})"
                    output_devices.append((i, name, channels, raw_name))

        self._add_system_default_entry(input_devices, input_default_aliases)
        self._add_system_default_entry(output_devices, output_default_aliases)

        # Sortiere Geräte: System-Standard zuerst, dann Stereo, dann Mono
        input_devices.sort(key=self._device_sort_key)
        output_devices.sort(key=self._device_sort_key)

        # Comboboxen füllen
        self.input_device_combo['values'] = [name for _, name, _, _ in input_devices]
        self.output_device_combo['values'] = [name for _, name, _, _ in output_devices]

        # Geräte-IDs, Kanalanzahl und Rohnamen speichern
        # (Rohname = Gerätename ohne PortAudio-Index, für stabilen Abgleich über
        # Neustarts/Refreshs hinweg, da sich der Index z.B. beim Ein-/Ausstecken
        # von USB-Soundkarten verschieben kann)
        self.input_devices = {name: (idx, channels) for idx, name, channels, _ in input_devices}
        self.output_devices = {name: (idx, channels) for idx, name, channels, _ in output_devices}
        self.input_device_raw_names = {name: raw for _, name, _, raw in input_devices}
        self.output_device_raw_names = {name: raw for _, name, _, raw in output_devices}

        # Vorherige Auswahl wiederherstellen (Refresh) oder Standard-Gerät bestimmen
        if not (preserve_selection and
                self._select_device_by_raw_name(self.input_device_combo, input_devices, previous_input_raw)):
            self._select_default_device(self.input_device_combo, input_devices)

        if not (preserve_selection and
                self._select_device_by_raw_name(self.output_device_combo, output_devices, previous_output_raw)):
            self._select_default_device(self.output_device_combo, output_devices)

    def _add_system_default_entry(self, devices, aliases):
        """Fügt genau einen "System-Standard"-Eintrag hinzu, sofern mindestens
        einer der PipeWire/Pulse/ALSA-Standard-Aliase gefunden wurde."""
        for alias in self._SYSTEM_DEFAULT_ALIASES:
            if alias in aliases:
                i, raw_name, channels = aliases[alias]
                channel_info = "Stereo" if channels == 2 else "Mono"
                name = f"{i}: System-Standard ({raw_name}) ({channel_info})"
                devices.append((i, name, channels, raw_name))
                return

    @staticmethod
    def _device_sort_key(device_entry):
        _, name, channels, _ = device_entry
        is_system_default = 0 if "System-Standard" in name else 1
        is_stereo = 0 if channels == 2 else 1
        return (is_system_default, is_stereo, name)

    def _select_default_device(self, combo, devices):
        """Wählt das Standardgerät aus: bevorzugt den "System-Standard"-Eintrag,
        sonst das erste Stereo-Gerät, sonst das erste verfügbare Gerät."""
        if not devices:
            return
        for idx, (_, name, _channels, _raw) in enumerate(devices):
            if "System-Standard" in name:
                combo.current(idx)
                return
        for idx, (_, _name, channels, _raw) in enumerate(devices):
            if channels == 2:
                combo.current(idx)
                return
        combo.current(0)

    def _select_device_by_raw_name(self, combo, devices, raw_name):
        """Sucht ein Gerät anhand seines indexunabhängigen Rohnamens und wählt es aus.

        Gibt True zurück, wenn ein Treffer gefunden und ausgewählt wurde.
        """
        if not raw_name:
            return False
        for idx, (_, _name, _channels, raw) in enumerate(devices):
            if raw == raw_name:
                combo.current(idx)
                return True
        return False

    def refresh_audio_devices(self):
        """Scannt die Audio-Geräte neu, ohne das Programm neu starten zu müssen.

        PortAudio erfasst die verfügbaren Geräte nur einmal beim Initialisieren.
        Wird z.B. eine USB-Soundkarte erst nach dem Programmstart angeschlossen,
        taucht sie deshalb nicht automatisch in den Comboboxen auf - hier wird
        PyAudio deshalb neu initialisiert, damit neu angeschlossene Geräte
        sichtbar werden."""
        if self.running:
            messagebox.showwarning("Warnung",
                "Bitte stoppen Sie den Repeater, bevor Sie die Audio-Geräte aktualisieren!")
            return

        try:
            self.p.terminate()
        except Exception as e:
            print(f"Fehler beim Beenden von PyAudio: {e}")

        self.p = pyaudio.PyAudio()
        self.load_audio_devices(preserve_selection=True)

        if not self.input_device_combo['values'] or not self.output_device_combo['values']:
            messagebox.showwarning("Warnung", "Es wurden keine Audio-Geräte gefunden.")

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

                    self.get_device_channels(input_device_id)  # Aktualisiere Kanalanzahl basierend auf Geräteliste

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
