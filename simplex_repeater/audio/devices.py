import json
import os
import re
import subprocess
import sys
from tkinter import messagebox
import pyaudio

_PULSE_PREFIX = "pulse:"


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

    # Unter PipeWire/PulseAudio sind die echten ALSA-Karten ("hw:X,Y") meist vom
    # Soundserver belegt: PortAudio meldet sie dann ohne Kanäle (Gerät fehlt in der
    # Liste, z.B. das im System-Klangdialog gewählte) oder kann sie nicht öffnen.
    # Deshalb werden die Geräte des Soundservers (Sinks/Sources) per "pactl"
    # ermittelt und über das PortAudio-Gerät "pulse" angesprochen. Die Auswahl des
    # konkreten Geräts erfolgt über PULSE_SINK / PULSE_SOURCE.
    _PULSE_ENV = {'output': 'PULSE_SINK', 'input': 'PULSE_SOURCE'}
    _ORIGINAL_PULSE_ENV = {var: os.environ.get(var) for var in _PULSE_ENV.values()}

    @staticmethod
    def _query_pulse_nodes(kind):
        """Liefert [(node_name, beschreibung, kanäle)] der Sinks ('output') bzw.
        Sources ('input', ohne Monitore). Leere Liste, wenn pactl nicht verfügbar ist."""
        try:
            result = subprocess.run(
                ['pactl', '-f', 'json', 'list', 'sinks' if kind == 'output' else 'sources'],
                capture_output=True, timeout=5,
                env={**os.environ, 'LC_ALL': 'C.UTF-8'})
            if result.returncode != 0:
                return []
            entries = json.loads(result.stdout.decode('utf-8', errors='replace'))
        except Exception:
            return []

        nodes = []
        for entry in entries:
            node = entry.get('name', '')
            if not node:
                continue
            is_monitor = (entry.get('properties', {}).get('device.class') == 'monitor'
                          or node.endswith('.monitor'))
            if kind == 'input' and is_monitor:
                continue
            match = re.search(r'(\d+)ch', entry.get('sample_specification', ''))
            channels = 2 if match and int(match.group(1)) >= 2 else 1
            nodes.append((node, entry.get('description') or node, channels))
        return nodes

    def _add_pulse_entries(self, devices, kind, pulse_index):
        """Ersetzt die rohen ALSA-Hardwaregeräte durch die Geräte des Soundservers.
        Gibt False zurück, wenn keine Soundserver-Geräte verfügbar sind."""
        if pulse_index is None:
            return False
        nodes = self._query_pulse_nodes(kind)
        if not nodes:
            return False
        devices[:] = [d for d in devices if "System-Standard" in d[1]]
        used_names = {d[1] for d in devices}
        for node, description, channels in nodes:
            channel_info = "Stereo" if channels == 2 else "Mono"
            name = f"{description} ({channel_info})"
            if name in used_names:
                name = f"{description} [{node}] ({channel_info})"
            used_names.add(name)
            devices.append((pulse_index, name, channels, _PULSE_PREFIX + node))
        return True

    @staticmethod
    def _pulse_node_from_raw(raw_name):
        if raw_name and raw_name.startswith(_PULSE_PREFIX):
            return raw_name[len(_PULSE_PREFIX):]
        return None

    def _apply_pulse_node(self, kind, raw_name):
        """Setzt bzw. entfernt PULSE_SINK/PULSE_SOURCE, bevor ein Stream geöffnet wird."""
        var = self._PULSE_ENV[kind]
        node = self._pulse_node_from_raw(raw_name)
        if node is None:
            node = self._ORIGINAL_PULSE_ENV[var]
        if node is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = node

    # Unter Windows listet PortAudio jedes Gerät einmal pro Host-API (MME,
    # DirectSound, WASAPI, WDM-KS). Es wird nur eine davon verwendet; die
    # Reihenfolge entspricht der Eignung: DirectSound (volle Gerätenamen,
    # automatische Abtastratenumrechnung), dann MME. WASAPI (Shared-Modus)
    # lehnt abweichende Abtastraten ab und wird deshalb nur als letzter
    # Ausweg genommen.
    _WINDOWS_HOST_API_PRIORITY = ['directsound', 'mme', 'wasapi']

    def _select_windows_host_api(self):
        """Gibt unter Windows (index, defaultInputDevice, defaultOutputDevice) der
        gewählten Host-API zurück, sonst None (andere Plattformen)."""
        if not sys.platform.startswith('win'):
            return None
        try:
            apis = [self.p.get_host_api_info_by_index(i) for i in range(self.p.get_host_api_count())]
        except Exception:
            return None
        for wanted in self._WINDOWS_HOST_API_PRIORITY:
            for api in apis:
                if wanted in api.get('name', '').lower():
                    return api['index'], api.get('defaultInputDevice', -1), api.get('defaultOutputDevice', -1)
        return None

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

        windows_api = self._select_windows_host_api()

        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            raw_name = info['name']
            name_key = raw_name.strip().lower()

            if name_key in self._LOW_VALUE_DEVICE_NAMES:
                continue

            if windows_api is not None:
                if info.get('hostApi') != windows_api[0]:
                    continue
                if info['maxInputChannels'] > 0:
                    input_devices.append(self._windows_device_entry(
                        i, raw_name, info['maxInputChannels'], i == windows_api[1]))
                if info['maxOutputChannels'] > 0:
                    output_devices.append(self._windows_device_entry(
                        i, raw_name, info['maxOutputChannels'], i == windows_api[2]))
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

        self._add_pulse_entries(input_devices, 'input', input_default_aliases.get('pulse', (None,))[0])
        self._add_pulse_entries(output_devices, 'output', output_default_aliases.get('pulse', (None,))[0])

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

    @staticmethod
    def _windows_device_entry(index, raw_name, max_channels, is_default):
        channels = 2 if max_channels >= 2 else 1
        channel_info = "Stereo" if channels == 2 else "Mono"
        label = f"System-Standard ({raw_name})" if is_default else raw_name
        return (index, f"{index}: {label} ({channel_info})", channels, raw_name)

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
            self._apply_pulse_node('input', self.input_device_raw_names.get(self.input_device_var.get()))
            self._apply_pulse_node('output', self.output_device_raw_names.get(self.output_device_var.get()))

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
