# Simplex/Duplex Repeater

Ein flexibler Audio-Repeater mit grafischer Benutzeroberfläche, der Audio aufnimmt wenn ein Schwellwert überschritten wird und es danach sofort wieder abspielt. Unterstützt sowohl Simplex- (abwechselnd) als auch Duplex-Betrieb (gleichzeitig).

## Funktionen

### Allgemeine Funktionen
- **Einstellbarer Eingangspegel**: Schwellwert für die Aktivierung der Aufnahme
- **Einstellbarer Abbruchpegel**: Pegel zum automatischen Stoppen der Aufnahme
- **Pegeldämpfung**: Attack/Release-Parameter für weichere Pegelübergänge
- **Einstellbare Aufnahmezeit**: 1-120 Sekunden Aufnahmedauer
- **Auswählbare Audio-Quellen**: Wahl des Eingabe- und Ausgabegeräts
- **Echtzeit-Pegelanzeige**: Visualisierung des aktuellen Audiopegels mit Schwellwert-Linien
- **Persistente Konfiguration**: Alle Einstellungen werden automatisch gespeichert
- **Kein Speichern von Audio**: Audio wird nur im Speicher gehalten

### Equalizer (Ausgangsbereich)
- **5-Band-Equalizer**: Frequenzbänder bei 60Hz, 230Hz, 910Hz, 3.6kHz, 14kHz
- **Verstärkungsbereich**: -12 dB bis +12 dB pro Band
- **Echtzeit-Verarbeitung**: Equalizer wird während der Wiedergabe angewendet
- **Butterworth-Filter**: Hochwertige Bandpass-Filter für saubere Frequenztrennung

### Modi
- **Simplex-Modus**: Klassischer Repeater-Betrieb (abwechselnd aufnehmen und abspielen)
  - Totzeit nach Wiedergabe einstellbar (0-10 Sekunden)
  - Keine Aufnahme während der Wiedergabe
  
- **Duplex-Modus**: Gleichzeitiges Aufnehmen und Abspielen
  - Aufnahme wird nicht durch Wiedergabe unterbrochen
  - Kontinuierliche Wiedergabe aufgenommener Signale
  - Ideal für Echo-Effekte oder Live-Monitoring

## Installation

1. Python 3.x muss installiert sein

2. Abhängigkeiten installieren:
```bash
pip install -r requirements.txt
```

Unter Linux benötigen Sie möglicherweise zusätzlich PortAudio:
```bash
sudo apt-get install portaudio19-dev python3-pyaudio
```

## Verwendung

Starten Sie das Programm:
```bash
python simplex_repeater.py
```

### Bedienung

#### Eingangsbereich (links)
1. **Startpegel einstellen**: Schwellwert zum Auslösen der Aufnahme (0-10000)
2. **Stoppegel einstellen**: Schwellwert zum automatischen Beenden der Aufnahme (0-Startpegel)
3. **Pegeldämpfung**: Attack/Release für weiche Pegelübergänge (0-1000 ms)
4. **Zeiteinstellungen**: Max. Aufnahmezeit, Unterschreitungszeit, Totzeit
5. **Audio-Eingabe**: Auswahl des Aufnahmegeräts

#### Ausgangsbereich (rechts)
1. **Equalizer**: 5 Frequenzbänder mit jeweils -12 bis +12 dB Verstärkung
   - 60 Hz: Tiefe Bässe
   - 230 Hz: Obere Bässe
   - 910 Hz: Untere Mitten
   - 3.6 kHz: Obere Mitten/Präsenz
   - 14 kHz: Höhen
2. **Audio-Ausgabe**: Auswahl des Wiedergabegeräts
3. **Wiedergabeverstärkung**: Globale Verstärkung -20 bis +20 dB

#### Modus-Umschaltung
- **Zu Duplex wechseln**: Wechselt zum gleichzeitigen Aufnahme-/Wiedergabebetrieb
- **Zu Simplex wechseln**: Wechselt zum abwechselnden Betrieb
- Modus kann nur im gestoppten Zustand gewechselt werden

## Technische Details

- **Audio-Format**: 16-bit PCM
- **Samplerate**: 44100 Hz
- **Kanäle**: Mono (1)
- **Puffergröße**: 1024 Frames
- **Equalizer**: 4. Ordnung Butterworth Bandpass/Lowpass/Highpass Filter
- **Threading**: Separate Threads für GUI und Audio-Verarbeitung
  - Simplex: Ein Audio-Thread mit sequenzieller Aufnahme/Wiedergabe
  - Duplex: Zwei parallele Threads für kontinuierliche Aufnahme und Wiedergabe

## Hinweise

### Simplex-Modus
- Während der Wiedergabe wird nicht aufgenommen
- Totzeit nach Wiedergabe verhindert sofortiges erneutes Triggern
- Klassischer Repeater-Betrieb für Durchsagen

### Duplex-Modus
- Aufnahme und Wiedergabe laufen gleichzeitig
- Keine Totzeit, kontinuierlicher Betrieb
- **Wichtig**: Elektrische Entkopplung zwischen Lautsprecher und Mikrofon erforderlich, um Rückkopplungsschleifen zu vermeiden

### Equalizer
- Wird nur auf die Wiedergabe angewendet, nicht auf die Aufnahme
- Funktioniert sowohl im Simplex- als auch im Duplex-Modus
- Bei 0 dB (Standard) ist keine Filterung aktiv (optimale Performance)

## Bekannte Einschränkungen

- **Rückkopplung im Duplex-Modus**: Ohne elektrische Entkopplung zwischen Ausgang und Eingang entsteht eine Aufnahme-Wiedergabe-Schleife. Dies lässt sich nicht durch Software vermeiden.
- **Equalizer-Latenz**: Der Equalizer fügt eine minimale Verarbeitungslatenz hinzu
- **CPU-Last**: Der Duplex-Modus mit aktivem Equalizer benötigt mehr CPU-Ressourcen

## Lizenz

Siehe LICENSE Datei
