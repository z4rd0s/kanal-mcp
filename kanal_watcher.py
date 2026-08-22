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

# Store-Aufloesung wie im Plugin-Hook: erst die Projekt-mcp.json (die MCP-
# Werkzeuge der Session zeigen auf denselben Eintrag), dann env, zuletzt der
# Skriptort. Bug 22.08.: der Repo-Default las einen LEEREN Repo-Store, waehrend
# die Werkzeuge im Live-Store arbeiteten — Watcher schwieg stundenlang.
import json as _json

def _projekt_store():
    try:
        cwd = os.getcwd()
        for rel in ((".kimi-code", "mcp.json"), (".mcp.json",)):
            cfg = _json.load(open(os.path.join(cwd, *rel), encoding="utf-8"))
            srv = (cfg.get("mcpServers") or {}).get("kanal")
            if isinstance(srv, dict):
                env = srv.get("env") if isinstance(srv.get("env"), dict) else {}
                args = srv.get("args") if isinstance(srv.get("args"), list) else []
                src = os.path.dirname(args[0]) if args and isinstance(args[0], str) else None
                return env.get("KANAL_DIR"), src
    except Exception:  # noqa: BLE001 — kein Projekt-Eintrag = Fallback
        pass
    return None, None

_pdir, _psrc = _projekt_store()
_src = os.environ.get("KANAL_SRC") or _psrc or os.path.dirname(os.path.abspath(__file__))
if _pdir and not os.environ.get("KANAL_DIR"):
    os.environ["KANAL_DIR"] = _pdir
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
