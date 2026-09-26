import tkinter as tk
from tkinter import ttk


class GuiMixin:

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

        self._build_input_panel(left_frame)
        self._build_output_panel(right_frame)

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

        self.refresh_devices_button = ttk.Button(button_frame, text="Geräte aktualisieren",
                                                 command=self.refresh_audio_devices, width=20)
        self.refresh_devices_button.pack(side=tk.LEFT, padx=5)

        self.about_button = ttk.Button(button_frame, text="Info",
                                       command=self.show_about_dialog, width=10)
        self.about_button.pack(side=tk.LEFT, padx=5)

        # Grid-Konfiguration
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Event-Binding für Canvas-Resize
        self.level_canvas.bind('<Configure>', self.on_canvas_resize)

    def _build_input_panel(self, left_frame):
        """Baut die linke Spalte (Eingangsbereich) auf"""
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

        # Monitoring aktivieren (Checkbox)
        row_left += 1
        self.monitoring_var = tk.BooleanVar(value=False)
        self.monitoring_checkbox = ttk.Checkbutton(left_frame, text="Simplex Monitoring aktivieren (Duplex-Modus)",
                                                    variable=self.monitoring_var,
                                                    command=self.on_monitoring_toggle)
        self.monitoring_checkbox.grid(row=row_left, column=0, columnspan=2, sticky=tk.W, pady=5)

        # Eingangsverstärker-Regler (direkt über dem Pegelbalken)
        row_left += 1
        ttk.Label(left_frame, text="Eingangsverstärker:").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        input_gain_frame = ttk.Frame(left_frame)
        input_gain_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        self.input_gain_scale = ttk.Scale(input_gain_frame, from_=-20.0, to=20.0,
                                          variable=self.input_gain_var, orient=tk.HORIZONTAL)
        self.input_gain_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_gain_scale.bind('<Double-Button-1>',
                                   lambda e: self.on_slider_double_click(self.input_gain_var))
        self.input_gain_label = ttk.Label(input_gain_frame, text="0.0 dB")
        self.input_gain_label.pack(side=tk.LEFT, padx=5)
        self.input_gain_var.trace('w', self.update_input_gain_label)

        # Eingangspegel-Einstellung (Start Threshold)
        row_left += 1
        ttk.Label(left_frame, text="Startpegel (rot):").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        self.start_threshold_var = tk.IntVar(value=1000)
        threshold_frame = ttk.Frame(left_frame)
        threshold_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        # tk.Scale statt ttk.Scale, da ttk-Themes den Griff nicht einfärben lassen
        self.threshold_scale = tk.Scale(threshold_frame, from_=0, to=10000,
                                        variable=self.start_threshold_var, orient=tk.HORIZONTAL,
                                        command=self.on_threshold_change, showvalue=False,
                                        troughcolor='#e0e0e0', bg='#cc3333', activebackground='#ff5555',
                                        highlightthickness=0, bd=1)
        self.threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.threshold_label = ttk.Label(threshold_frame, text="1000")
        self.threshold_label.pack(side=tk.LEFT, padx=5)
        self.start_threshold_var.trace_add('write', self.update_threshold_label)

        # Abbruch-Pegel-Einstellung (Stop Threshold)
        row_left += 1
        ttk.Label(left_frame, text="Stoppegel (grün):").grid(
            row=row_left, column=0, sticky=tk.W, pady=5)
        self.stop_threshold_var = tk.IntVar(value=100)
        stop_threshold_frame = ttk.Frame(left_frame)
        stop_threshold_frame.grid(row=row_left, column=1, sticky=(tk.W, tk.E), pady=5)
        # tk.Scale statt ttk.Scale, da ttk-Themes den Griff nicht einfärben lassen
        self.stop_threshold_scale = tk.Scale(stop_threshold_frame, from_=0, to=10000,
                                             variable=self.stop_threshold_var, orient=tk.HORIZONTAL,
                                             showvalue=False,
                                             troughcolor='#e0e0e0', bg='#33aa33', activebackground='#55dd55',
                                             highlightthickness=0, bd=1)
        self.stop_threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stop_threshold_label = ttk.Label(stop_threshold_frame, text="100")
        self.stop_threshold_label.pack(side=tk.LEFT, padx=5)
        self.stop_threshold_var.trace_add('write', self.update_stop_threshold_label)

        # Canvas für Pegelanzeige
        row_left += 1
        self.level_canvas = tk.Canvas(left_frame, height=40, bg='white',
                                      highlightthickness=1, highlightbackground='gray')
        self.level_canvas.grid(row=row_left, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Elemente für Level-Anzeige
        self.level_bar = None
        self.threshold_line = None
        self.stop_threshold_line = None

        # Schwellwert-Linien im Canvas per Maus verschiebbar machen
        self._dragging_threshold = None  # 'start', 'stop' oder None
        self.level_canvas.bind('<ButtonPress-1>', self.on_level_canvas_press)
        self.level_canvas.bind('<B1-Motion>', self.on_level_canvas_drag)
        self.level_canvas.bind('<ButtonRelease-1>', self.on_level_canvas_release)
        self.level_canvas.bind('<Motion>', self.on_level_canvas_motion)

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
        self.rise_time_var.trace_add('write', self.update_rise_time_label)

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
        self.fall_time_var.trace_add('write', self.update_fall_time_label)

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
        self.record_time_var.trace_add('write', self.update_record_time_label)

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
        self.stop_time_var.trace_add('write', self.update_stop_time_label)

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
        self.dead_time_var.trace_add('write', self.update_dead_time_label)

    def _build_output_panel(self, right_frame):
        """Baut die rechte Spalte (Ausgangsbereich) auf"""
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

        # Abtastrate: fest auf 48000 Hz - siehe repo-Notizen/README: bei diesem
        # PortAudio/ALSA-Setup funktionieren andere Abtastraten mit manchen
        # USB-Audiogeräten (v.a. bei raw "hw:X,Y"-Zugriff) nicht korrekt und
        # verursachen Aufnahmen/Wiedergaben mit falscher Geschwindigkeit.
        row_right += 1
        ttk.Label(right_frame, text="Abtastrate:").grid(
            row=row_right, column=0, sticky=tk.W, pady=5)
        ttk.Label(right_frame, text=f"{self.RATE} Hz (fest)").grid(
            row=row_right, column=1, sticky=tk.W, pady=5)

        # Hinweis zur festen Abtastrate
        row_right += 1
        perf_hint = ttk.Label(right_frame,
                             text="⚠ Abtastrate ist fest auf 48000 Hz, da andere Werte bei\n"
                                  "manchen USB-Audiogeräten zu falscher Geschwindigkeit führen.",
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
        self.gain_scale.bind('<Double-Button-1>',
                             lambda e: self.on_slider_double_click(self.gain_var))
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


        # Hinweis Equalizer ist performance hungrig
        row_right += 1
        perf_hint_eq = ttk.Label(right_frame,
                                 text="⚠ Der Equalizer kann die Performance beeinträchtigen.",
                                 font=('Arial', 8, 'italic'),
                                 foreground='#666666',
                                 justify=tk.LEFT)
        perf_hint_eq.grid(row=row_right, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

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
            eq_scale = ttk.Scale(eq_frame, from_=-60.0, to=60.0,
                                variable=self.eq_gains[band], orient=tk.HORIZONTAL)
            eq_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
            eq_scale.bind('<Double-Button-1>',
                          lambda e, b=band: self.on_slider_double_click(self.eq_gains[b]))
            self.eq_scales[band] = eq_scale

            # Label für aktuellen Wert
            eq_label = ttk.Label(eq_frame, text="0.0 dB")
            eq_label.pack(side=tk.LEFT, padx=5)
            self.eq_labels[band] = eq_label

            # Trace für Label-Update
            self.eq_gains[band].trace('w', lambda *args, b=band: self.update_eq_label(b))
