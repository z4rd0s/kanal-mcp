#!/usr/bin/env python3
"""kanal_folgen.py — den Kanal mitlesen, im Rueckblick und live.

## Wozu
Chris bekommt seit dem 2026-07-28 eine Desktop-Meldung, sobald opus oder kimi etwas in
den Kanal schreiben — aber eine Meldung sagt nur DASS, nicht WAS. Dieses Skript ist die
Lesesicht: es zeigt den Verlauf lesbar formatiert und haengt sich danach an die Datei,
so dass neue Nachrichten erscheinen, sobald sie geschrieben werden.

Kein inotify, keine Abhaengigkeiten: es merkt sich die Dateiposition und schaut einmal
pro Sekunde nach, ob etwas dazugekommen ist. Das ist bei einer JSONL-Datei, die pro Tag
ein paar Dutzend Zeilen bekommt, genau angemessen.

## Aufrufe
  python3 kanal_folgen.py                    # letzte 15, dann live weiter (Strg-C beendet)
  python3 kanal_folgen.py --letzte 40        # mehr Rueckblick
  python3 kanal_folgen.py --einmal           # nur Rueckblick, kein Warten (fuer ! im Prompt)
  python3 kanal_folgen.py --thread blockplan # nur ein Thread
  python3 kanal_folgen.py --offen            # Uebersicht: welche Threads warten worauf
  python3 kanal_folgen.py --alles            # ganzer Verlauf

Die Lesemarke von chris wird dabei mitgefuehrt, damit `kanal_ping.py --fuer chris`
hinterher weiss, was er schon gesehen hat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(os.environ.get("KANAL_DIR") or Path(__file__).resolve().parent)
LOG = ROOT / "kanal.jsonl"
GELESEN = ROOT / "gelesen.json"

# Farben nur, wenn wirklich ein Terminal dranhaengt — sonst landen Steuerzeichen in Pipes.
FARBE = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def f(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if FARBE else text


SPRECHER = {"chris": "1;32", "opus": "1;36", "kimi": "1;35"}
HALTUNG_FARBE = {"widerspruch": "31", "befund": "33", "entscheidung": "1;32",
                 "zustimmung": "32", "frage": "34"}
BREITE = min(int(os.environ.get("COLUMNS", "100") or 100), 100)


def lade() -> list:
    if not LOG.exists():
        return []
    out = []
    for zeile in LOG.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            out.append(json.loads(zeile))
        except Exception:  # noqa: BLE001 — eine kaputte Zeile darf die Sicht nicht toeten
            continue
    return out


def marke_setzen(bis: str) -> None:
    try:
        d = json.loads(GELESEN.read_text(encoding="utf-8")) if GELESEN.exists() else {}
        if d.get("chris", "") >= bis:
            return
        d["chris"] = bis
        tmp = GELESEN.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(GELESEN)
    except Exception:  # noqa: BLE001
        pass


def zeige(m: dict) -> None:
    von = m.get("von", "?")
    haltung = m.get("haltung", "?")
    kopf = (f"{f(m.get('zeit', '')[5:16], '90')}  "
            f"{f(von.upper(), SPRECHER.get(von, '0'))} "
            f"{f('· ' + haltung, HALTUNG_FARBE.get(haltung, '0'))} "
            f"{f('· ' + m.get('thread', '?'), '90')}")
    print("\n" + kopf)
    print(f("─" * BREITE, "90"))
    for absatz in (m.get("text", "") or "").split("\n"):
        if not absatz.strip():
            print()
            continue
        for zeile in textwrap.wrap(absatz, width=BREITE) or [""]:
            print("  " + zeile)
    # ⚠️ Ohne Terminal puffert Python stdout blockweise. Beim Abbruch (Strg-C, timeout)
    # geht der Puffer verloren — in einer Pipe oder Umleitung saehe man minutenlang
    # nichts. Im Live-Modus ist sofortige Ausgabe der ganze Zweck.
    sys.stdout.flush()


def offen_zeigen(msgs: list) -> None:
    threads: dict = {}
    for m in msgs:
        threads.setdefault(m["thread"], []).append(m)
    zu = {k for k, v in threads.items() if any(x["haltung"] == "entscheidung" for x in v)}
    print(f"\n{f('KANAL — ' + str(len(threads)) + ' Threads, ' + str(len(msgs)) + ' Nachrichten', '1')}\n")
    for k in sorted(threads, key=lambda x: threads[x][-1]["zeit"]):
        v = threads[k]
        letzte = v[-1]
        status = f("geschlossen", "90") if k in zu else f("offen", "1;33")
        print(f"  {f(k, '1;36'):<34} {status}  {len(v)} Nachrichten, zuletzt "
              f"{letzte['von']} um {letzte['zeit'][5:16]}")
        erste = v[0]["text"].splitlines()[0]
        print(f"      {f('Frage:', '90')} {textwrap.shorten(erste, 88)}")
        if k not in zu:
            wartet = "opus" if letzte["von"] == "kimi" else ("kimi" if letzte["von"] == "opus" else "?")
            print(f"      {f('zuletzt:', '90')} {letzte['von']} · {letzte['haltung']} — "
                  f"{f('Antwort faellig bei ' + wartet, '90')}")
    print()


def markdown(msgs: list) -> str:
    """Lesbare Spiegelung des Kanals fuer VS Code.

    Chris liest lieber in der Oberflaeche als im Terminal. Eine Markdown-Datei, die bei
    jeder Nachricht neu geschrieben wird, ist dafuer das richtige Medium: VS Code laedt
    extern geaenderte Dateien selbst neu, es braucht also weder Terminal noch laufenden
    Prozess. Gruppiert nach Thread, weil man eine Diskussion so liest — und mit den
    juengsten Nachrichten oben, damit Neues ohne Scrollen sichtbar ist.
    """
    threads: dict = {}
    for m in msgs:
        threads.setdefault(m["thread"], []).append(m)
    zu = {k for k, v in threads.items() if any(x["haltung"] == "entscheidung" for x in v)}
    sym = {"chris": "🟢", "opus": "🔵", "kimi": "🟣"}
    hsym = {"widerspruch": "⚔️", "befund": "📊", "entscheidung": "✅",
            "zustimmung": "👍", "frage": "❓"}

    z = ["# Kanal — chris · opus · kimi", ""]
    if msgs:
        letzte = msgs[-1]
        z += [f"**Zuletzt:** {sym.get(letzte['von'],'')} `{letzte['von']}` · "
              f"{hsym.get(letzte['haltung'],'')} {letzte['haltung']} · "
              f"Thread **{letzte['thread']}** · {letzte['zeit'][:16].replace('T',' ')} UTC", ""]
    z += [f"{len(msgs)} Nachrichten in {len(threads)} Threads. "
          f"Diese Datei wird bei jeder Nachricht neu geschrieben — offen lassen genuegt.", ""]

    z += ["## Threads", "", "| Thread | Status | Nachrichten | zuletzt | Antwort fällig bei |",
          "|---|---|---|---|---|"]
    for k in sorted(threads, key=lambda x: threads[x][-1]["zeit"], reverse=True):
        v = threads[k]
        L = v[-1]
        wartet = "—" if k in zu else ("opus" if L["von"] == "kimi" else
                                      ("kimi" if L["von"] == "opus" else "opus/kimi"))
        z.append(f"| [{k}](#{k}) | {'geschlossen' if k in zu else '**offen**'} | {len(v)} | "
                 f"{sym.get(L['von'],'')} {L['von']} {L['zeit'][5:16].replace('T',' ')} | {wartet} |")
    z.append("")

    for k in sorted(threads, key=lambda x: threads[x][-1]["zeit"], reverse=True):
        v = threads[k]
        z += [f"## {k}", ""]
        z += [f"> **Frage:** {v[0]['text'].splitlines()[0]}", ""]
        for m in v:
            z += [f"### {sym.get(m['von'],'')} {m['von']} · {hsym.get(m['haltung'],'')} "
                  f"{m['haltung']} · {m['zeit'][:16].replace('T',' ')} UTC", ""]
            for absatz in (m.get("text") or "").split("\n"):
                z.append(absatz if absatz.strip() else "")
            z.append("")
        z.append("---")
        z.append("")
    return "\n".join(z)


def markdown_schreiben(msgs: list | None = None) -> Path:
    ziel = ROOT / "KANAL.md"
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(markdown(msgs if msgs is not None else lade()), encoding="utf-8")
    tmp.replace(ziel)          # atomar: VS Code soll nie eine halbe Datei sehen
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--letzte", type=int, default=15, help="Nachrichten im Rueckblick")
    ap.add_argument("--alles", action="store_true", help="ganzer Verlauf")
    ap.add_argument("--einmal", action="store_true", help="nur Rueckblick, nicht warten")
    ap.add_argument("--thread", default="", help="nur diesen Thread")
    ap.add_argument("--offen", action="store_true", help="Threaduebersicht statt Verlauf")
    ap.add_argument("--markdown", action="store_true",
                    help="KANAL.md neu schreiben (fuer VS Code) und beenden")
    args = ap.parse_args()

    msgs = lade()
    if args.markdown:
        ziel = markdown_schreiben(msgs)
        print(f"{ziel}  ({len(msgs)} Nachrichten)")
        return 0
    if args.offen:
        offen_zeigen(msgs)
        return 0

    sel = [m for m in msgs if not args.thread or m.get("thread") == args.thread]
    # ⚠️ sel[-0:] ist in Python der GANZE Rest, nicht die leere Liste — "--letzte 0"
    # haette also den kompletten Verlauf ausgegeben statt keinen.
    if args.alles:
        rueck = sel
    elif args.letzte <= 0:
        rueck = []
    else:
        rueck = sel[-args.letzte:]
    if rueck:
        print(f("\n══ Rueckblick: {} von {} Nachricht(en) ══".format(len(rueck), len(sel)), "1;90"))
        for m in rueck:
            zeige(m)
        marke_setzen(max(m["zeit"] for m in rueck))
    else:
        print("Kanal ist leer.")

    if args.einmal:
        return 0

    print(f("\n══ live — Strg-C beendet ══", "1;90"))
    gesehen = len(msgs)
    try:
        while True:
            time.sleep(1.0)
            jetzt = lade()
            if len(jetzt) > gesehen:
                neu = jetzt[gesehen:]
                gesehen = len(jetzt)
                for m in neu:
                    if args.thread and m.get("thread") != args.thread:
                        continue
                    zeige(m)
                marke_setzen(max(m["zeit"] for m in neu))
    except KeyboardInterrupt:
        print(f("\n\nbeendet.", "90"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
