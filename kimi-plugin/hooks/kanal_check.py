#!/usr/bin/env python3
"""kanal_check — Kimi-Code-Hook: ungelesene Kanal-Nachrichten melden.

TEAM-MODELL: Es gibt KEINEN globalen Kanal. Ein Kanal = ein Datenverzeichnis
(kanal.jsonl + gelesen.json), ein Team = ein Projekt. Ob und WO ein Projekt
einen Kanal hat, steht in dessen eigener <projekt>/.kimi-code/mcp.json, Fallback
<projekt>/.mcp.json (Claude Code), Server "kanal": env.KANAL_DIR waehlt den
Store (Default: neben dem kanal_mcp.py aus args), env.KANAL_WER die Team-Liste.
Die Identitaet des Fragenden kommt per --ich aus dem Aufruf (kimi-Plugin:
--ich kimi; Claude Code: --ich opus) — dasselbe Skript dient beide CLIs. Hat das Projekt keinen Kanal-Eintrag, steigt der Hook
lautlos aus — fremde Sessions bleiben garantiert unberuehrt, und es ist
unmoeglich, aus Versehen in fremden Threads zu landen: jeder Store enthaelt
nur die Threads seines Teams.

Liest den Kanal-Store DIREKT ueber kanal_lib (kein MCP-Protokoll, kein Schreiben
am Store). Die Ungelesen-Logik (Teilnahme, Lesemarken, Altformate) wird nicht
nachgebaut, sondern aus kanal_lib importiert — EINE Stelle, wie im Kanal-Projekt
ueblich. kanal_lib wertet KANAL_DIR/KANAL_WER/KANAL_MENSCH/KANAL_ICH beim IMPORT
aus — darum setzt der Hook die Umgebung VOR dem Import, und zwar VOLLSTAENDIG
(auch loeschen/defaults), damit nichts aus der Shell-Umgebung des CLI-Prozesses
in die Lib leckt (jeder Hook-Lauf ist ein frischer Prozess).

Pfade in der mcp.json: relativ wird gegen das PROJEKT aufgeloest (das Payload-
cwd), nie gegen den Plugin-Root; "~" wird expandiert. Absolute Pfade bleiben
die Empfehlung.

Events (Payload-Feld hook_event_name):
  UserPromptSubmit  Hinweis auf stdout -> landet im Kontext, exit 0 (nie blockieren).
  Stop              exit 2 + stderr, solange Ungelesenes anliegt — aber hoechstens
                    einmal je Nachrichtenstand und Session (Schleifen-Notaus, s.
                    schon_gemeldet): ein Modell, das trotz Block nicht liest, wird
                    beim naechsten Stop durchgelassen statt endlos weiterzulaufen.

Fail-open: JEDER Fehler (Store weg, Import kaputt, Payload muell, mcp.json mit
falschen Typen) -> exit 0 ohne Ausgabe und ohne Traceback. Der Hook blockiert
nur, wenn er positiv weiss: Ungelesenes liegt an UND fuer genau diesen Stand
wurde in dieser Session noch nicht blockiert.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

KANAL_SRC = os.environ.get("KANAL_SRC") or ""   # leer = nur der args-Weg zaehlt
                                                # (kein User-Pfad im oeffentlichen Repo)


def _str_wert(env: dict, key: str) -> str:
    """Nur echte Strings uebernehmen — ein dict/list/Zahl-Wert in der mcp.json
    wird wie 'fehlend' behandelt, statt per str() zu Muell-Identitaet oder
    Muell-Teamliste zu koersieren (stille Fehlkonfiguration, opus' Gegenroast)."""
    v = env.get(key)
    return v.strip() if isinstance(v, str) else ""


def kanal_server(cwd: str) -> dict | None:
    """Kanal-Server-Eintrag aus <cwd>/.kimi-code/mcp.json, Fallback <cwd>/.mcp.json
    (Claude-Code-Projekte) — das Opt-in des Projekts. None (=> still) bei: kein
    cwd, keine Datei, kein 'kanal'-Server, kaputtes JSON, falscher Typ."""
    if not cwd:
        return None
    for rel in ((".kimi-code", "mcp.json"), (".mcp.json",)):
        try:
            cfg = json.loads((Path(cwd).joinpath(*rel)).read_text(encoding="utf-8"))
            srv = (cfg.get("mcpServers") or {}).get("kanal")
            if isinstance(srv, dict):
                return srv
        except Exception:  # noqa: BLE001
            continue
    return None


def flag_ich() -> str | None:
    """--ich <name> aus der Kommandozeile. Die Identitaet kommt vom AUFRUFENDEN
    (kimi-Plugin: --ich kimi; Claude-Code-settings.json: --ich opus), nicht aus
    der Projektdatei — dasselbe Skript dient beide CLIs, und das KANAL_ICH der
    mcp.json gilt dem MCP-SERVER des Projekts, nicht zwingend diesem Aufruf."""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--ich" and i + 1 < len(argv):
            return argv[i + 1].strip().lower() or None
        if a.startswith("--ich="):
            return a.split("=", 1)[1].strip().lower() or None
    return None


def pfad(p: str, basis: str) -> str:
    """Absolut machen gegen das PROJEKT (basis = Payload-cwd), nie gegen den
    Plugin-Root; '~' wird expandiert."""
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        return p
    return str((Path(basis or "/") / p).resolve())


def ungelesen(ich: str, src: str, store: str, wer: str,
              mensch: str) -> list | None:
    """Ungelesene Nachrichten fuer `ich` aus `store` — None bei jedem Fehler
    (fail-open). Umgebung VOR dem Import VOLLSTAENDIG setzen: kanal_lib liest
    sie einmalig beim Import, und ein geerbter Wert aus der Shell (z. B. ein
    altes export KANAL_MENSCH=...) wuerde sonst still die Teilnahme-Regeln
    kippen (Router-Rolle, WER[0]-Falle)."""
    try:
        os.environ["KANAL_DIR"] = store
        os.environ["KANAL_WER"] = wer or "chris,opus,kimi"
        os.environ["KANAL_MENSCH"] = mensch or "chris"
        os.environ["KANAL_ICH"] = ich
        if src not in sys.path:
            sys.path.insert(0, src)
        import kanal_lib as lib
        return lib.ungelesen(ich)
    except Exception:  # noqa: BLE001
        return None


def schon_gemeldet(max_nr: int, session: str, store: str) -> bool:
    """True nur, wenn fuer GENAU diesen Nachrichtenstand in dieser Session und
    diesem Store schon blockiert wurde. Merker-Datei gehasht (keine Trennzeichen-
    Kollisionen zwischen Paaren, keine Ueberlaenge). alt > max_nr heisst: Store
    wurde zurueckgesetzt — Merker verwerfen, wieder blockieren. Schreiben atomar;
    Schreibfehler heisst 'noch nicht gemeldet' (einmal zu viel, nie zu wenig)."""
    if not session:
        return False     # ID-lose Sessions merken NIE — sonst verschluckt ein
                         # fremder ID-loser Lauf denselben Store-Stand (opus, nit b)
    tag = hashlib.sha256(f"{session}\0{store}".encode("utf-8")).hexdigest()[:16]
    zustand = Path(tempfile.gettempdir()) / f"nunaki-kanal-stop-{tag}.json"
    try:
        alt = json.loads(zustand.read_text(encoding="utf-8"))
        if isinstance(alt, dict) and int(alt.get("max_nr", -1)) == max_nr:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        tmp = zustand.with_suffix(".tmp")
        tmp.write_text(json.dumps({"max_nr": max_nr}), encoding="utf-8")
        tmp.replace(zustand)
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
    try:
        event = payload.get("hook_event_name", "")
        cwd = str(payload.get("cwd", "") or "")
        srv = kanal_server(cwd)
        if srv is None:
            return 0                  # Projekt ohne Kanal: lautlos durchwinken
        env = srv.get("env") if isinstance(srv.get("env"), dict) else {}
        args = srv.get("args") if isinstance(srv.get("args"), list) else []
        skript = pfad(str(args[0]), cwd) if args and isinstance(args[0], str) \
            and args[0].strip() else ""
        src = str(Path(skript).parent) if skript else KANAL_SRC
        if not src:
            return 0                  # kein kanal_lib auffindbar: lautlos aussteigen
        store = pfad(_str_wert(env, "KANAL_DIR"), cwd) if _str_wert(env, "KANAL_DIR") \
            else src
        ich = flag_ich() or _str_wert(env, "KANAL_ICH").lower()
        if not ich:
            return 0                  # keine Identitaet bestimmbar (weder --ich noch
                                      # env.KANAL_ICH): nicht raten, lautlos aussteigen
        wer = _str_wert(env, "KANAL_WER")
        mensch = _str_wert(env, "KANAL_MENSCH")

        msgs = ungelesen(ich, src, store, wer, mensch)
        if not msgs:
            return 0                  # nichts ungelesen ODER Fehler: still durchwinken

        threads = ", ".join(sorted({str(m.get("thread", "?")) for m in msgs}))
        if event == "Stop":
            max_nr = max(int(m.get("nr", 0)) for m in msgs)
            if schon_gemeldet(max_nr, str(payload.get("session_id", "")), store):
                return 0              # Schleifen-Notaus: einmal gemahnt reicht
            sys.stderr.write(
                f"[kanal] {len(msgs)} ungelesene Nachricht(en) in {threads} — lies sie "
                f"mit kanal_ungelesen(), bevor du die Runde beendest.\n")
            return 2

        # UserPromptSubmit (und jedes andere Event): nur in den Kontext, nie blockieren.
        sys.stdout.write(
            f"[kanal] {len(msgs)} ungelesene Nachricht(en) in {threads}. "
            f"Lies mit kanal_ungelesen() bevor du antwortest.\n")
        return 0
    except Exception:  # noqa: BLE001
        return 0                      # Fail-open, auch bei Typ-Muell in der mcp.json


if __name__ == "__main__":
    sys.exit(main())
