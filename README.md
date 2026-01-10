# Simplex Repeater

Ein einfacher Audio-Repeater mit grafischer Benutzeroberfläche, der Audio aufnimmt wenn ein Schwellwert überschritten wird und es danach sofort wieder abspielt.

## Funktionen

- **Einstellbarer Eingangspegel**: Schwellwert für die Aktivierung der Aufnahme
- **Einstellbare Aufnahmezeit**: 1-30 Sekunden Aufnahmedauer
- **Auswählbare Audio-Quellen**: Wahl des Eingabe- und Ausgabegeräts
- **Echtzeit-Pegelanzeige**: Visualisierung des aktuellen Audiopegels
- **Status-Anzeige**: Anzeige des aktuellen Betriebszustands
- **Kein Speichern**: Audio wird nur im Speicher gehalten und nach Wiedergabe gelöscht

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

1. **Eingangspegel einstellen**: Schieberegler für den Schwellwert (100-10000)
2. **Aufnahmezeit einstellen**: Schieberegler für die Dauer (1-30 Sekunden)
3. **Audio-Geräte auswählen**: Eingabe- und Ausgabequelle aus den Dropdown-Menüs
4. **Start klicken**: Repeater aktivieren
5. Der Repeater wartet nun auf ein Signal über dem eingestellten Schwellwert
6. Bei Signaldetektion: Aufnahme für die eingestellte Zeit
7. Sofortige Wiedergabe nach Aufnahme
8. Während der Wiedergabe keine neue Aufnahme möglich

## Technische Details

- **Audio-Format**: 16-bit PCM
- **Samplerate**: 44100 Hz
- **Kanäle**: Mono (1)
- **Puffergröße**: 1024 Frames
- **Threading**: Separate Threads für GUI und Audio-Verarbeitung

## Hinweise

- Während der Wiedergabe wird nicht aufgenommen (Simplex-Betrieb)
- Das Audio wird nicht gespeichert und nach der Wiedergabe gelöscht
- Die Pegel-Anzeige zeigt den durchschnittlichen Absolutwert der Audio-Samples
