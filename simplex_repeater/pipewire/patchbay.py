import os
import re
import xml.etree.ElementTree as ET
import subprocess

# Erkennt PipeWire-interne ALSA-Nodes die vom Python-Prozess geöffnet wurden.
# PipeWire benennt ALSA-Streams nach dem Prozessnamen, z.B. alsa_capture.python3.12
_PYTHON_ALSA_RE = re.compile(r'alsa_(capture|playback)\.python', re.IGNORECASE)


class PipeWirePatchbayMixin:
    """Mixin zum automatischen Herstellen von PipeWire-Verbindungen
    anhand einer qpwgraph-Patchbay-Konfigurationsdatei.

    Beim Aufruf von apply_pipewire_patchbay() werden zuerst alle vom
    System automatisch erstellten Verbindungen zu den Python-ALSA-Nodes
    getrennt, danach werden nur die gewünschten Verbindungen aus der
    Konfigurationsdatei hergestellt."""

    # Pfad zur Konfigurationsdatei (relativ zu dieser Datei)
    _PATCHBAY_CONFIG = os.path.join(os.path.dirname(__file__), 'pipewire.qpwgraph.conf')

    def _parse_patchbay_connections(self):
        """Liest die qpwgraph XML-Konfiguration und gibt eine Liste von
        (output_port, input_port)-Tupeln zurück."""
        connections = []

        if not os.path.exists(self._PATCHBAY_CONFIG):
            print(f"Patchbay-Konfiguration nicht gefunden: {self._PATCHBAY_CONFIG}")
            return connections

        try:
            tree = ET.parse(self._PATCHBAY_CONFIG)
            root = tree.getroot()

            for item in root.findall('.//item'):
                output = item.find('output')
                input_ = item.find('input')
                if output is not None and input_ is not None:
                    output_port = output.get('port')
                    input_port = input_.get('port')
                    if output_port and input_port:
                        connections.append((output_port, input_port))

        except ET.ParseError as e:
            print(f"Fehler beim Parsen der Patchbay-Konfiguration: {e}")

        return connections

    def _get_current_pw_connections(self):
        """Liest alle aktiven PipeWire-Verbindungen via pw-link -l.

        Gibt ein Set von (output_port, input_port)-Tupeln zurück.
        Die Port-Namen entsprechen dem internen PipeWire-Format
        (z.B. 'alsa_capture.python3.12:input_FL').
        """
        connections = set()
        try:
            result = subprocess.run(
                ['pw-link', '-l'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return connections

            current_port = None
            for line in result.stdout.splitlines():
                if line.startswith('  |->'):
                    # Verbindungslinie: '  |-> target_port'
                    if current_port is not None:
                        target = line.strip()[3:].strip()  # '|->' + whitespace entfernen
                        connections.add((current_port, target))
                elif line.startswith('  |<-'):
                    # Umgekehrte Pfeilrichtung – überspringen (würde Duplikate erzeugen)
                    pass
                elif line.strip():
                    # Port-Zeile ohne führende Leerzeichen: 'node_name:port_name'
                    current_port = line.strip()
                else:
                    current_port = None

        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return connections

    def apply_pipewire_patchbay(self):
        """Trennt alle automatisch erstellten Verbindungen zu den Python-ALSA-Nodes
        und stellt danach nur die gewünschten Verbindungen aus der Konfiguration her.

        Läuft synchron im aufrufenden Thread (Audio-Thread), damit der Audio-Loop
        erst nach vollständig eingerichteten Verbindungen startet."""
        desired = self._parse_patchbay_connections()
        if not desired:
            return

        # ── Schritt 1: Alle bestehenden Verbindungen zu unseren Python-ALSA-Nodes trennen ──
        current = self._get_current_pw_connections()
        for out_port, in_port in current:
            if _PYTHON_ALSA_RE.search(out_port) or _PYTHON_ALSA_RE.search(in_port):
                try:
                    result = subprocess.run(
                        ['pw-link', '-d', out_port, in_port],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        print(f"PipeWire getrennt:  {out_port!r} → {in_port!r}")
                    else:
                        stderr = result.stderr.strip()
                        if stderr:
                            print(f"pw-link -d [{out_port!r} → {in_port!r}]: {stderr}")
                except FileNotFoundError:
                    print("pw-link nicht gefunden – ist PipeWire installiert?")
                    return
                except subprocess.TimeoutExpired:
                    print(f"pw-link -d Timeout: {out_port!r} → {in_port!r}")

        # ── Schritt 2: Gewünschte Verbindungen herstellen ────────────────────────────────
        for out_port, in_port in desired:
            try:
                result = subprocess.run(
                    ['pw-link', out_port, in_port],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    print(f"PipeWire verbunden: {out_port!r} → {in_port!r}")
                else:
                    stderr = result.stderr.strip()
                    if stderr:
                        print(f"pw-link [{out_port!r} → {in_port!r}]: {stderr}")
            except FileNotFoundError:
                print("pw-link nicht gefunden – ist PipeWire installiert?")
                return
            except subprocess.TimeoutExpired:
                print(f"pw-link Timeout: {out_port!r} → {in_port!r}")
