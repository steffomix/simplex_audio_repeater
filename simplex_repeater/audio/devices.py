from tkinter import messagebox


class DevicesMixin:

    def get_device_channels(self, device_index):
        """Ermittelt die maximale Anzahl von Ein- und Ausgangskanälen für ein Gerät."""
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            input_channels = device_info.get('maxInputChannels', 0)
            output_channels = device_info.get('maxOutputChannels', 0)
            return input_channels, output_channels
        except IOError:
            return 0, 0

    def load_audio_devices(self):
        """Lädt verfügbare Audio-Geräte"""
        input_devices = []
        output_devices = []

        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)

            if info['maxInputChannels'] > 0:
                # Teste ob das Gerät wirklich Stereo unterstützt
                channels = min(info['maxInputChannels'], 2)

                # PipeWire/Pulse-Geräte sollten Stereo unterstützen
                device_name_lower = info['name'].lower()
                likely_stereo = any(keyword in device_name_lower for keyword in ['pipewire', 'pulse', 'default'])

                if channels == 2 or (likely_stereo and info['maxInputChannels'] >= 2):
                    channels = 2
                    channel_info = "Stereo"
                else:
                    channels = 1
                    channel_info = "Mono"

                name = f"{i}: {info['name']} ({channel_info})"
                input_devices.append((i, name, channels))

            if info['maxOutputChannels'] > 0:
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
            default_idx = 0
            for idx, (_, name, channels) in enumerate(input_devices):
                if channels == 2 and any(keyword in name.lower() for keyword in ['pipewire', 'pulse', 'default']):
                    default_idx = idx
                    break
            self.input_device_combo.current(default_idx)

        if output_devices:
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
