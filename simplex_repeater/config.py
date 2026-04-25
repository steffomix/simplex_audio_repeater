import os
import json
import tkinter as tk


class ConfigMixin:

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
                self.input_gain_var.set(config.get('input_gain', 0.0))

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
                'input_gain': self.input_gain_var.get(),
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
