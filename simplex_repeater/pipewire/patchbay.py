import os
import xml.etree.ElementTree as ET
import subprocess
import threading


class PipeWirePatchbayMixin:
    """Mixin zum automatischen Herstellen von PipeWire-Verbindungen
    anhand einer qpwgraph-Patchbay-Konfigurationsdatei."""

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

    def apply_pipewire_patchbay(self):
        """Stellt alle PipeWire-Verbindungen aus der Patchbay-Konfiguration her.
        Wird in einem Hintergrund-Thread ausgeführt, um die GUI nicht zu blockieren."""
        connections = self._parse_patchbay_connections()
        if not connections:
            return

        def connect():
            for output_port, input_port in connections:
                try:
                    result = subprocess.run(
                        ['pw-link', output_port, input_port],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        print(f"PipeWire verbunden: {output_port!r} → {input_port!r}")
                    else:
                        # Verbindung kann bereits bestehen – kein kritischer Fehler
                        stderr = result.stderr.strip()
                        if stderr:
                            print(f"pw-link [{output_port!r} → {input_port!r}]: {stderr}")
                except FileNotFoundError:
                    print("pw-link nicht gefunden – ist PipeWire installiert?")
                    return
                except subprocess.TimeoutExpired:
                    print(f"pw-link Timeout: {output_port!r} → {input_port!r}")

        threading.Thread(target=connect, daemon=True).start()
