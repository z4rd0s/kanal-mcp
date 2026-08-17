#!/usr/bin/env python3
"""kanal_check — Kimi-Code-Hook: ungelesene Kanal-Nachrichten melden.

Liest den Kanal-Store DIREKT ueber kanal_lib (kein MCP-Protokoll, kein Schreiben
am Store). Die Ungelesen-Logik (Teilnahme, Lesemarken, Altformate) wird nicht
nachgebaut, sondern aus kanal_lib importiert — EINE Stelle, wie im Kanal-Projekt
ueblich. KANAL_SRC zeigt auf das Verzeichnis mit kanal_lib.py; KANAL_DIR (von
kanal_lib selbst ausgewertet) kann den Datenort uebersteuern.

Events (Payload-Feld hook_event_name):
  UserPromptSubmit  Hinweis auf stdout -> landet im Kontext, exit 0 (nie blockieren).
  Stop              exit 2 + stderr, solange Ungelesenes anliegt — aber hoechstens
                    einmal je Nachrichtenstand und Session (Schleifen-Notaus, s.
                    schon_gemeldet): ein Modell, das trotz Block nicht liest, wird
                    beim naechsten Stop durchgelassen statt endlos weiterzulaufen.

Fail-open: JEDER Fehler (Store weg, Import kaputt, Payload muell) -> exit 0 ohne
Ausgabe. Der Hook blockiert nur, wenn er positiv weiss: Ungelesenes liegt an UND
fuer genau diesen Stand wurde in dieser Session noch nicht blockiert.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

KANAL_SRC = os.environ.get("KANAL_SRC") or "/home/chris/workspace/merlin/kanal-daten"
ICH = (os.environ.get("KANAL_ICH") or "kimi").strip().lower()


def ungelesen() -> list | None:
    """Ungelesene Nachrichten fuer ICH — None bei jedem Fehler (fail-open)."""
    try:
        if KANAL_SRC not in sys.path:
            sys.path.insert(0, KANAL_SRC)
        import kanal_lib as lib
        return lib.ungelesen(ICH)
    except Exception:  # noqa: BLE001
        return None


def schon_gemeldet(max_nr: int, session: str) -> bool:
    """True, wenn fuer diesen Nachrichtenstand in dieser Session schon blockiert
    wurde. Zustand als Mini-Datei im tmp — Lesefehler heisst 'noch nicht gemeldet'
    (dann wird eben einmal zu viel blockiert, nie zu wenig)."""
    tag = re.sub(r"[^A-Za-z0-9_-]", "_", session or "default")
    zustand = Path(tempfile.gettempdir()) / f"nunaki-kanal-stop-{tag}.json"
    try:
        alt = json.loads(zustand.read_text(encoding="utf-8"))
        if isinstance(alt, dict) and int(alt.get("max_nr", 0)) >= max_nr:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        zustand.write_text(json.dumps({"max_nr": max_nr}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    event = payload.get("hook_event_name", "")

    msgs = ungelesen()
    if not msgs:
        return 0                      # nichts ungelesen ODER Fehler: still durchwinken

    threads = ", ".join(sorted({str(m.get("thread", "?")) for m in msgs}))
    if event == "Stop":
        max_nr = max(int(m.get("nr", 0)) for m in msgs)
        if schon_gemeldet(max_nr, str(payload.get("session_id", ""))):
            return 0                  # Schleifen-Notaus: einmal gemahnt reicht
        sys.stderr.write(
            f"[kanal] {len(msgs)} ungelesene Nachricht(en) in {threads} — lies sie "
            f"mit kanal_ungelesen(), bevor du die Runde beendest.\n")
        return 2

    # UserPromptSubmit (und jedes andere Event): nur in den Kontext, nie blockieren.
    sys.stdout.write(
        f"[kanal] {len(msgs)} ungelesene Nachricht(en) in {threads}. "
        f"Lies mit kanal_ungelesen() bevor du antwortest.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
