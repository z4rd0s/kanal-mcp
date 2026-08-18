#!/usr/bin/env python3
"""kanal_check — Kimi-Code-Hook: ungelesene Kanal-Nachrichten melden.

TEAM-MODELL: Es gibt KEINEN globalen Kanal. Ein Kanal = ein Datenverzeichnis
(kanal.jsonl + gelesen.json), ein Team = ein Projekt. Ob und WO ein Projekt
einen Kanal hat, steht in dessen eigener <projekt>/.kimi-code/mcp.json
(Server "kanal"): env.KANAL_DIR waehlt den Store (Default: neben dem
kanal_mcp.py aus args), env.KANAL_WER die Team-Liste, env.KANAL_ICH die
eigene Identitaet. Hat das Projekt keinen Kanal-Eintrag, steigt der Hook
lautlos aus — fremde Sessions bleiben garantiert unberuehrt, und es ist
unmoeglich, aus Versehen in fremden Threads zu landen: jeder Store enthaelt
nur die Threads seines Teams.

Liest den Kanal-Store DIREKT ueber kanal_lib (kein MCP-Protokoll, kein Schreiben
am Store). Die Ungelesen-Logik (Teilnahme, Lesemarken, Altformate) wird nicht
nachgebaut, sondern aus kanal_lib importiert — EINE Stelle, wie im Kanal-Projekt
ueblich. KANAL_SRC zeigt als Fallback auf das Verzeichnis mit kanal_lib.py;
normal kommt der Ort aus den args des Projekt-Server-Eintrags. kanal_lib wertet
KANAL_DIR/KANAL_WER/KANAL_MENSCH beim IMPORT aus — darum setzt der Hook die
Umgebung VOR dem Import (jeder Hook-Lauf ist ein frischer Prozess).

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


def kanal_server(cwd: str) -> dict | None:
    """Kanal-Server-Eintrag aus <cwd>/.kimi-code/mcp.json — das Opt-in des
    Projekts. None (=> still) bei: kein cwd, keine Datei, kein 'kanal'-Server,
    kaputtes JSON."""
    if not cwd:
        return None
    try:
        cfg = json.loads((Path(cwd) / ".kimi-code" / "mcp.json").read_text(encoding="utf-8"))
        srv = (cfg.get("mcpServers") or {}).get("kanal")
        return srv if isinstance(srv, dict) else None
    except Exception:  # noqa: BLE001
        return None


def ungelesen(ich: str, src: str, store: str, wer: str | None,
              mensch: str | None) -> list | None:
    """Ungelesene Nachrichten fuer `ich` aus `store` — None bei jedem Fehler
    (fail-open). Umgebung VOR dem Import setzen (kanal_lib liest sie einmalig)."""
    try:
        os.environ["KANAL_DIR"] = store
        if wer:
            os.environ["KANAL_WER"] = wer
        if mensch:
            os.environ["KANAL_MENSCH"] = mensch
        if src not in sys.path:
            sys.path.insert(0, src)
        import kanal_lib as lib
        return lib.ungelesen(ich)
    except Exception:  # noqa: BLE001
        return None


def schon_gemeldet(max_nr: int, session: str, store: str) -> bool:
    """True, wenn fuer diesen Nachrichtenstand in dieser Session schon blockiert
    wurde. Zustand als Mini-Datei im tmp — Lesefehler heisst 'noch nicht gemeldet'
    (dann wird eben einmal zu viel blockiert, nie zu wenig). Der Store geht in den
    Dateinamen ein, damit Teams sich den Merker nicht teilen."""
    tag = re.sub(r"[^A-Za-z0-9_-]", "_", f"{session}-{store}" or "default")
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

    srv = kanal_server(str(payload.get("cwd", "")))
    if srv is None:
        return 0                      # Projekt ohne Kanal: lautlos durchwinken
    env = srv.get("env") or {}
    args = srv.get("args") or []
    src = str(Path(args[0]).resolve().parent) if args else KANAL_SRC
    store = str(env.get("KANAL_DIR") or src)   # kanal_lib-Default: Store neben Skript
    ich = (env.get("KANAL_ICH") or ICH).strip().lower()

    msgs = ungelesen(ich, src, store, env.get("KANAL_WER"), env.get("KANAL_MENSCH"))
    if not msgs:
        return 0                      # nichts ungelesen ODER Fehler: still durchwinken

    threads = ", ".join(sorted({str(m.get("thread", "?")) for m in msgs}))
    if event == "Stop":
        max_nr = max(int(m.get("nr", 0)) for m in msgs)
        if schon_gemeldet(max_nr, str(payload.get("session_id", "")), store):
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
