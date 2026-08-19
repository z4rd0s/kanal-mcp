#!/usr/bin/env python3
# kanal_watcher.py — Push statt Polling: blockiert, bis fuer den Kanal-Teilnehmer
# neue Nachrichten da sind, druckt sie auf stdout und beendet sich mit exit 0.
# Gedacht als Hintergrund-Task in Kimi Code: die Completion-Notification weckt
# den Agenten mit dem Inhalt — danach wird der Watcher sofort neu gestartet.
#
# Umgebung:
#   KANAL_ICH   — wer gewartet wird (Default "kimi")
#   KANAL_SRC   — Pfad zum kanal_lib.py-Verzeichnis (Default: Live-Installation)
#   KANAL_DIR   — wird von kanal_lib selbst ausgewertet (Store-Ort; Test-Override)
#   KANAL_POLL  — Sekunden zwischen Pruefungen (Default 10)
#
# Fail-open: jeder Fehler fuehrt zu weiterem Warten, nie zu einem Absturz.
import os
import sys
import time

WER = os.environ.get("KANAL_ICH", "kimi")
POLL = float(os.environ.get("KANAL_POLL", "10"))

# KANAL_SRC: Pfad zum kanal_lib.py-Verzeichnis (Default: neben diesem Skript)
_src = os.environ.get("KANAL_SRC")
if not _src:
    _src = os.path.dirname(os.path.abspath(__file__))
SRC = _src
sys.path.insert(0, SRC)

try:
    import kanal_lib as lib
except Exception as e:  # Lib nicht ladbar — kein Watcher moeglich
    print(f"kanal_watcher: kanal_lib nicht ladbar aus {SRC}: {e}", file=sys.stderr)
    sys.exit(0)  # fail-open: exit 0, damit kein Alarm entsteht

def main() -> None:
    while True:
        try:
            neu = lib.ungelesen(WER)
        except Exception:
            neu = []  # weiter warten, niemals crashen
        if neu:
            threads = sorted({m.get("thread", "?") for m in neu})
            print(f"KANAL-PUSH an {WER}: {len(neu)} neue Nachricht(en) in: {', '.join(threads)}")
            for m in neu:
                print(f"\n--- [{m.get('thread','?')}] {m.get('von','?')} · {m.get('haltung','?')} · {m.get('zeit','?')}")
                print((m.get("text") or "")[:2000])
            sys.exit(0)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
