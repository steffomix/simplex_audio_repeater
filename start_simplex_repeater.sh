#!/usr/bin/env bash
# Simplex Audio Repeater - Starter für Linux
#
# Richtet bei Bedarf eine virtuelle Python-Umgebung ein, installiert alle
# benötigten Abhängigkeiten (inkl. Systempakete wie PortAudio/Tkinter) und
# startet danach das Programm. Gedacht für Benutzer ohne Python-Erfahrung:
# einfach per Doppelklick ("Im Terminal ausführen") oder mit
# `./start_simplex_repeater.sh` starten.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR" || exit 1

RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"; BOLD="\033[1m"; RESET="\033[0m"

pause_on_exit() {
    echo
    read -rp "Drücken Sie die Eingabetaste, um dieses Fenster zu schließen..." _
}
trap pause_on_exit EXIT

echo -e "${BOLD}================================================================================${RESET}"
echo -e "${BOLD}                       Simplex Audio Repeater - Starter${RESET}"
echo -e "${BOLD}================================================================================${RESET}"
echo

# ──────────────────────────────────────────────────────────────────────────
# Schritt 1: Python-Installation prüfen
# ──────────────────────────────────────────────────────────────────────────
echo "[1/5] Überprüfe Python-Installation..."
echo

PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[FEHLER] Python 3 wurde nicht gefunden!${RESET}"
    echo
    echo "Bitte installieren Sie Python 3 über die Paketverwaltung Ihrer Distribution:"
    echo "  Ubuntu/Debian : sudo apt install python3 python3-venv python3-pip python3-tk"
    echo "  Fedora        : sudo dnf install python3 python3-tkinter"
    echo "  Arch Linux    : sudo pacman -S python python-pip tk"
    echo
    exit 1
fi

echo "[OK] $("$PYTHON_BIN" --version) gefunden."
echo

# ──────────────────────────────────────────────────────────────────────────
# Schritt 2: Python-Version prüfen
# ──────────────────────────────────────────────────────────────────────────
echo "[2/5] Prüfe Python-Version..."
echo

if ! "$PYTHON_BIN" -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo -e "${YELLOW}[WARNUNG] Python 3.8 oder höher wird empfohlen (gefunden: $("$PYTHON_BIN" --version)).${RESET}"
    read -rp "Trotzdem fortfahren? (j/N): " continue_choice
    if [[ ! "$continue_choice" =~ ^[jJyY]$ ]]; then
        exit 1
    fi
else
    echo "[OK] Python-Version ist kompatibel."
fi
echo

# ──────────────────────────────────────────────────────────────────────────
# Schritt 3: Tkinter (grafische Oberfläche) prüfen
# ──────────────────────────────────────────────────────────────────────────
echo "[3/5] Überprüfe grafische Oberfläche (Tkinter)..."
echo

if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
    echo -e "${YELLOW}[WARNUNG] Das Systempaket für Tkinter fehlt - es wird für die grafische Oberfläche benötigt.${RESET}"
    echo "Installationsbefehl je nach Distribution:"
    echo "  Ubuntu/Debian : sudo apt install python3-tk"
    echo "  Fedora        : sudo dnf install python3-tkinter"
    echo "  Arch Linux    : sudo pacman -S tk"
    echo
    read -rp "Jetzt automatisch installieren? (benötigt Ihr Sudo-Passwort) (j/N): " tk_choice
    if [[ "$tk_choice" =~ ^[jJyY]$ ]]; then
        if command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y python3-tk
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y python3-tkinter
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm tk
        else
            echo -e "${RED}Unbekannte Paketverwaltung - bitte das passende Paket manuell installieren.${RESET}"
        fi
    fi
    if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
        echo -e "${RED}[FEHLER] Tkinter ist weiterhin nicht verfügbar. Programmstart abgebrochen.${RESET}"
        exit 1
    fi
fi
echo "[OK] Tkinter ist verfügbar."
echo

# ──────────────────────────────────────────────────────────────────────────
# Schritt 4: Virtuelle Umgebung einrichten und Abhängigkeiten installieren
# ──────────────────────────────────────────────────────────────────────────
echo "[4/5] Richte virtuelle Umgebung ein und installiere Abhängigkeiten..."
echo

PY="$PYTHON_BIN"

if [ ! -d "venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    "$PYTHON_BIN" -m venv venv
fi

if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    PY="python"
    echo "[OK] Virtuelle Umgebung aktiviert."
else
    echo -e "${YELLOW}[WARNUNG] Keine virtuelle Umgebung verfügbar - installiere Pakete für den aktuellen Benutzer.${RESET}"
fi
echo

"$PY" -m pip install --upgrade pip >/dev/null 2>&1

if ! "$PY" -m pip install -r requirements.txt; then
    echo
    echo -e "${RED}[FEHLER] Installation der Abhängigkeiten fehlgeschlagen!${RESET}"
    echo
    echo "Häufige Ursache: Die PortAudio-Entwicklungsdateien fehlen (werden für PyAudio benötigt)."
    echo "Installationsbefehl je nach Distribution:"
    echo "  Ubuntu/Debian : sudo apt install portaudio19-dev"
    echo "  Fedora        : sudo dnf install portaudio-devel"
    echo "  Arch Linux    : sudo pacman -S portaudio"
    echo
    read -rp "Jetzt automatisch installieren? (benötigt Ihr Sudo-Passwort) (j/N): " pa_choice
    if [[ "$pa_choice" =~ ^[jJyY]$ ]]; then
        if command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y portaudio19-dev
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y portaudio-devel
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm portaudio
        fi
        if ! "$PY" -m pip install -r requirements.txt; then
            echo -e "${RED}Installation weiterhin fehlgeschlagen. Bitte manuell installieren (siehe README.md).${RESET}"
            exit 1
        fi
    else
        exit 1
    fi
fi

echo
echo "[OK] Alle Abhängigkeiten installiert."
echo

# ──────────────────────────────────────────────────────────────────────────
# Schritt 5: Programm starten
# ──────────────────────────────────────────────────────────────────────────
echo "================================================================================"
echo "                        Starte Simplex Audio Repeater..."
echo "================================================================================"
echo

"$PY" simplex_repeater.py
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo
    echo -e "${RED}[FEHLER] Das Programm wurde mit einem Fehler beendet (Code: $exit_code).${RESET}"
fi

exit $exit_code
