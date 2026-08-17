#!/usr/bin/env python3
"""kanal_ping.py — meldet ungelesene Kanal-Nachrichten, ohne sie als gelesen zu markieren.

## Warum es das gibt
Ein echter Push ist bei MCP nicht moeglich: das Protokoll ist client-getrieben, und weder
Kimi noch Opus laufen dauerhaft — ein Server kann kein Modell wecken, das gerade nicht
existiert. Was moeglich ist, ist Zustellung beim NAECHSTEN Zug. Dieses Skript ist der
Zusteller:

  * fuer Opus  — als Claude-Code-Hook (UserPromptSubmit). Die Ausgabe landet automatisch
                 im Kontext, bei jedem Zug, ohne dass jemand daran denken muss.
  * fuer Chris — mit --benachrichtigen als Desktop-Meldung (notify-send).
  * fuer Kimi  — nicht ueber dieses Skript (Kimi Code kennt keine Hooks), sondern ueber
                 das Ungelesen-Banner, das der MCP-Server jeder Werkzeugantwort voranstellt.

## Warum es NICHT als gelesen markiert
Der Hook laeuft, bevor der Empfaenger die Nachricht verarbeitet hat. Wuerde er die Marke
setzen, waere die Nachricht formal zugestellt und faktisch ungesehen, sobald der Zug
abbricht. Die Marke rueckt nur, wenn tatsaechlich gelesen wurde — also in kanal_lesen bzw.
kanal_ungelesen im MCP-Server.

Aufruf:
  python3 kanal_ping.py --fuer opus              # Text auf stdout, exit 0
  python3 kanal_ping.py --fuer chris --benachrichtigen
  python3 kanal_ping.py --fuer opus --still      # nur exit-code (1 = es gibt Neues)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("KANAL_DIR") or Path(__file__).resolve().parent)
LOG = ROOT / "kanal.jsonl"
GELESEN = ROOT / "gelesen.json"
MAX_ZEIGEN = 5          # mehr wuerde den Kontext fluten; der Rest wird gezaehlt
MAX_ZEICHEN = 700       # pro Nachricht


def lade(pfad: Path) -> list:
    if not pfad.exists():
        return []
    out = []
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            out.append(json.loads(zeile))
        except Exception:  # noqa: BLE001 — eine kaputte Zeile darf den Hook nicht toeten
            continue
    return out


def marke(wer: str) -> str:
    if not GELESEN.exists():
        return ""
    try:
        return json.loads(GELESEN.read_text(encoding="utf-8")).get(wer, "")
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuer", required=True)
    ap.add_argument("--still", action="store_true", help="nichts ausgeben, nur exit-code")
    ap.add_argument("--benachrichtigen", action="store_true", help="Desktop-Meldung (notify-send)")
    ap.add_argument("--hook", action="store_true",
                    help="Ausgabe als Claude-Code-Hook-JSON (hookSpecificOutput.additionalContext). "
                         "Reiner Text auf stdout landet nicht zuverlaessig im Modellkontext — "
                         "additionalContext ist der dafuer vorgesehene Weg.")
    args = ap.parse_args()

    msgs = lade(LOG)
    m = marke(args.fuer)
    neu = [x for x in msgs if x.get("zeit", "") > m and x.get("von") != args.fuer]
    if not neu:
        return 0

    if args.benachrichtigen:
        wer = ", ".join(sorted({x["von"] for x in neu}))
        try:
            subprocess.run(["notify-send", "-a", "kanal", "-u", "normal",
                            f"Kanal: {len(neu)} neue Nachricht(en)",
                            f"von {wer} — Threads: " +
                            ", ".join(sorted({x['thread'] for x in neu}))],
                           check=False, capture_output=True, timeout=5)
        except Exception:  # noqa: BLE001 — ohne Desktop-Session gibt es kein notify-send
            pass

    if args.hook:
        # Nichts ausgeben, wenn es nichts gibt (oben schon per return 0 erledigt).
        threads = sorted({x["thread"] for x in neu})
        wer = ", ".join(sorted({x["von"] for x in neu}))
        teile = [f"KANAL — {len(neu)} ungelesene Nachricht(en) fuer {args.fuer} "
                 f"von {wer}, Threads: {', '.join(threads)}.",
                 "Diese Meldung markiert nichts als gelesen. Zum Abholen und Quittieren: "
                 "kanal_ungelesen(). Antworten mit kanal_sagen(von=\"" + args.fuer + "\", ...)."]
        for x in neu[-MAX_ZEIGEN:]:
            t = x.get("text", "")
            if len(t) > MAX_ZEICHEN:
                t = t[:MAX_ZEICHEN] + f" … (+{len(x['text']) - MAX_ZEICHEN} Zeichen, "
                t += "vollstaendig ueber kanal_ungelesen)"
            teile.append(f"\n[{x.get('zeit','')[5:16]}] {x.get('von')} · {x.get('haltung')} "
                         f"· Thread {x.get('thread')}\n{t}")
        if len(neu) > MAX_ZEIGEN:
            teile.append(f"\n… und {len(neu) - MAX_ZEIGEN} weitere.")
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(teile),
            },
            # Der Mensch soll die Meldung sehen, aber nicht das rohe JSON im Transkript.
            "systemMessage": f"🔔 Kanal: {len(neu)} ungelesene Nachricht(en) von {wer}",
            "suppressOutput": True,
        }, ensure_ascii=False))
        return 0        # ein Hook darf den Zug NIE mit != 0 stoeren

    if not args.still:
        threads = sorted({x["thread"] for x in neu})
        print(f"KANAL: {len(neu)} ungelesene Nachricht(en) fuer {args.fuer} "
              f"in {', '.join(threads)}.")
        for x in neu[-MAX_ZEIGEN:]:
            text = x.get("text", "")
            if len(text) > MAX_ZEICHEN:
                text = text[:MAX_ZEICHEN] + f" … (+{len(x['text']) - MAX_ZEICHEN} Zeichen)"
            print(f"\n[{x.get('zeit', '')[5:16]}] {x.get('von')} · {x.get('haltung')} "
                  f"· Thread {x.get('thread')}\n{text}")
        if len(neu) > MAX_ZEIGEN:
            print(f"\n… und {len(neu) - MAX_ZEIGEN} weitere. Vollstaendig mit kanal_ungelesen().")
        print("\n(Diese Meldung markiert NICHTS als gelesen — dafuer kanal_ungelesen() "
              "oder kanal_lesen() aufrufen.)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        # Ein Hook darf niemals den Zug abbrechen. Fehler nach stderr, exit 0.
        print(f"kanal_ping: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)
