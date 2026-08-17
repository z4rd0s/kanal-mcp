#!/usr/bin/env python3
"""test_kanal — Regressionstests fuer den Kanal (Speicher, Teilnahme, Marken, Regeln).

Laeuft komplett in einem temporaeren KANAL_DIR, ruehrt echte Daten nie an:

    python3 test_kanal.py

Deckt ab: themenbezogene Zustellung, Schreibschutz, Beitritt/Verlassen,
@-Erwaehnung (inkl. Fehlzuendung bei E-Mail), pro-Thread-Lesemarken,
Altformat-Migration (Zeitmarke + CLI-"bis"), Identitaetspruefung, kaputte Zeilen,
monotone Sequenznummern und paralleles Marken-Setzen (Race-Schutz).
"""
from __future__ import annotations

import atexit
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="kanal-test-"))
atexit.register(shutil.rmtree, TMP, True)   # auch bei sys.exit() hinter sich aufräumen
os.environ["KANAL_DIR"] = str(TMP)
os.environ["KANAL_WER"] = "chris,opus,kimi"
os.environ.pop("KANAL_ICH", None)

import kanal_lib  # noqa: E402
import kanal_mcp  # noqa: E402

_ok = 0


def check(name: str, cond, extra: str = "") -> None:
    global _ok
    if not cond:
        print(f"  ✗ {name}  {extra}")
        sys.exit(1)
    _ok += 1
    print(f"  ✓ {name}")


def als(wer: str | None) -> dict:
    """Module mit einer anderen Identitaet neu laden (jeder MCP-Client ist ein
    eigener Prozess mit eigenem KANAL_ICH — das bildet das nach)."""
    if wer is None:
        os.environ.pop("KANAL_ICH", None)
    else:
        os.environ["KANAL_ICH"] = wer
    importlib.reload(kanal_lib)
    importlib.reload(kanal_mcp)
    ns = {"lib": kanal_lib}
    for name in ("kanal_neu", "kanal_sagen", "kanal_offen", "kanal_lesen",
                 "kanal_ungelesen", "kanal_beitreten", "kanal_verlassen", "kanal_zu"):
        t = getattr(kanal_mcp, name)
        ns[name] = getattr(t, "fn", t)
    return ns


def log() -> list:
    return [json.loads(z) for z in (TMP / "kanal.jsonl").read_text().splitlines() if z.strip()]


# ---- Aufbau -------------------------------------------------------------------
opus = als("opus")
r = opus["kanal_neu"]("opus", "thema-a", "Welche Architektur?", teilnehmer="opus,kimi")
check("eingeschraenkter Thread angelegt", "Teilnehmer: kimi, opus" in r, r)
opus["kanal_neu"]("opus", "solo", "Interne Frage von opus", teilnehmer="opus")
opus["kanal_neu"]("opus", "offen-frage", "Oeffentliche Frage an alle")
opus["kanal_sagen"]("opus", "solo", "befund", "Erste Zahl 42 aus Job 7")
opus["kanal_sagen"]("opus", "offen-frage", "befund", "Wert 3.14 gemessen")

# ---- Themenbezogene Zustellung -------------------------------------------------
kimi = als("kimi")
lib = kimi["lib"]
threads_kimi = {m["thread"] for m in lib.ungelesen("kimi")}
check("kimi sieht thema-a und offen-frage", {"thema-a", "offen-frage"} <= threads_kimi, str(threads_kimi))
check("kimi sieht solo NICHT", "solo" not in threads_kimi, str(threads_kimi))
chris = als("chris")
check("chris (Router) sieht auch solo",
      "solo" in {m["thread"] for m in chris["lib"].ungelesen("chris")})

# ---- Schreibschutz + Beitritt ---------------------------------------------------
kimi = als("kimi")
r = kimi["kanal_sagen"]("kimi", "solo", "frage", "Darf ich hier schreiben?")
check("Schreiben ohne Teilnahme abgelehnt", "nicht Teilnehmer" in r, r)
check("Beitritt klappt", "beigetreten" in kimi["kanal_beitreten"]("solo"))
r = kimi["kanal_sagen"]("kimi", "solo", "frage", "Jetzt bin ich dabei, ok?")
check("Schreiben nach Beitritt klappt", "abgelegt" in r, r)

# ---- @-Erwaehnung ---------------------------------------------------------------
opus = als("opus")
opus["kanal_neu"]("opus", "thema-c", "Dritte Frage", teilnehmer="opus")
r = opus["kanal_sagen"]("opus", "thema-c", "frage", "@kimi was meinst du dazu?")
check("@-Erwaehnung holt in den Thread", "kimi per @ geholt" in r, r)
r = opus["kanal_sagen"]("opus", "thema-c", "frage", "Schreib an max@kimi.example, nicht ins System.")
check("E-Mail loest KEINE Erwaehnung aus",
      sum(1 for m in log() if m.get("art") == "beitritt" and m["thread"] == "thema-c") == 1)
kimi = als("kimi")
check("kimi sieht thema-c nach @-Erwaehnung",
      any(m["thread"] == "thema-c" and not m.get("art")
          for m in kimi["lib"].ungelesen("kimi")))

# ---- Pro-Thread-Marken -----------------------------------------------------------
kimi = als("kimi")
u = kimi["lib"].ungelesen("kimi")
kimi["kanal_lesen"]("thema-c")
u2 = kimi["lib"].ungelesen("kimi")
check("Lesen in thema-c laesst andere Threads ungelesen",
      {m["thread"] for m in u2} == ({m["thread"] for m in u} - {"thema-c"}),
      f"{[m['thread'] for m in u]} -> {[m['thread'] for m in u2]}")

# ---- Verlassen -------------------------------------------------------------------
check("Verlassen klappt", "verlassen" in kimi["kanal_verlassen"]("offen-frage"))
opus = als("opus")
opus["kanal_sagen"]("opus", "offen-frage", "befund", "Neue Zahl 2.71 nachgereicht")
kimi = als("kimi")
check("nach Verlassen keine Meldung aus offen-frage",
      "offen-frage" not in {m["thread"] for m in kimi["lib"].ungelesen("kimi")})
r = kimi["kanal_beitreten"]("offen-frage")
check("Rueckkehr nach Verlassen klappt", "beigetreten" in r, r)
check("nach Rueckkehr wieder ungelesen",
      "offen-frage" in {m["thread"] for m in kimi["lib"].ungelesen("kimi")})

# ---- MENSCH: verlassen stoppt Zustellung, nicht Sicht -----------------------------
chris = als("chris")
check("chris kann ebenfalls verlassen", "verlassen" in chris["kanal_verlassen"]("solo"))
opus = als("opus")
opus["kanal_sagen"]("opus", "solo", "befund", "Noch eine Zahl: 7")
chris = als("chris")
check("verlassener Thread bleibt fuer chris stumm",
      "solo" not in {m["thread"] for m in chris["lib"].ungelesen("chris")})
r = chris["kanal_lesen"]("solo")
check("lesen kann chris den Thread weiterhin", "Noch eine Zahl" in r, r[:80])

# ---- kanal_offen zeigt die WIRKLICHEN Teilnehmer ----------------------------------
opus = als("opus")
r = opus["kanal_offen"]()
zeile = [z for z in r.splitlines() if z.startswith("── offen-frage")]
check("offen zeigt Teilnehmer nach Rueckkehr korrekt",
      zeile and "kimi" in zeile[0] and "opus" in zeile[0], zeile[0] if zeile else r[:120])

# ---- Identitaet + Schliessen -------------------------------------------------------
opus = als("opus")
r = opus["kanal_sagen"]("chris", "thema-a", "entscheidung", "gefaehrlich")
check("opus kann nicht als chris schreiben", "Identitaet" in r, r)
r = opus["kanal_zu"]("thema-a", "opus will schliessen")
check("opus kann nicht schliessen", "Regel 4" in r, r)
chris = als("chris")
r = chris["kanal_zu"]("thema-a", "So wird es gebaut.")
check("chris schliesst", "geschlossen" in r, r)
r = chris["kanal_sagen"]("chris", "thema-a", "frage", "zu spaet")
check("geschlossener Thread nimmt nichts mehr an", "geschlossen" in r, r)

# ---- Thread-Namen sind Adressen, kein Freitext -----------------------------------
opus = als("opus")
r = opus["kanal_neu"]("opus", "", "Frage ohne Namen?")
check("leerer Thread-Name abgelehnt", "ungueltig" in r or "ungültig" in r, r)
r = opus["kanal_neu"]("opus", "Mein Thema", "Frage mit Leerzeichen?")
check("Leerzeichen abgelehnt, mit Vorschlag", "mein-thema" in r, r)
r = opus["kanal_neu"]("opus", "Thema-A", "Grossschreibung?")
check("Grossschreibung abgelehnt", "ungueltig" in r or "ungültig" in r, r)

# ---- Identitaetswarnung ohne KANAL_ICH ---------------------------------------------
anonym = als(None)
r = anonym["kanal_sagen"]("opus", "offen-frage", "befund", "Wert 6.28 ohne Identitaet")
check("ohne KANAL_ICH: Warnung statt lautlosem Durchwinken",
      "KANAL_ICH ist nicht gesetzt" in r and "abgelegt" in r, r)

# ---- Regeln 2 und 3 (ueber die gemeinsame validiere) --------------------------------
lib = als("opus")["lib"]
msgs = lib.lade()
check("Regel 2: Zustimmung ohne Grund abgelehnt",
      lib.validiere(msgs, "opus", "offen-frage", "zustimmung", "ja klar") is not None)
check("Regel 3: Befund ohne Zahl abgelehnt",
      lib.validiere(msgs, "opus", "offen-frage", "befund", "sieht gut aus") is not None)
check("Regel 3: Befund mit Zahl ok",
      lib.validiere(msgs, "opus", "offen-frage", "befund", "n=5 Messungen") is None)

# ---- Altformate der Marken ----------------------------------------------------------
roh = json.loads((TMP / "gelesen.json").read_text())
roh["kimi"] = "9999-01-01T00:00:00Z"          # altes String-Format
roh["bis"] = "9999-01-01T00:00:00Z"           # alter CLI-Schluessel des Menschen
(TMP / "gelesen.json").write_text(json.dumps(roh))
kimi = als("kimi")
check("Altformat-Zeitmarke wird umgerechnet", kimi["lib"].ungelesen("kimi") == [])
chris = als("chris")
check('CLI-Altbestand "bis" gilt als Marke des Menschen',
      chris["lib"].ungelesen("chris") == [],
      str([m["thread"] for m in chris["lib"].ungelesen("chris")]))

# ---- Robustheit: kaputte Zeile, monotone nr, Race ------------------------------------
with (TMP / "kanal.jsonl").open("a") as f:
    f.write('{"kaputte zeile"\n')              # kein valides JSON
lib = als("opus")["lib"]
msgs = lib.lade()
check("kaputte Zeile blockiert den Kanal nicht", any(m.get("thread") == "solo" for m in msgs))
vorher = max(m["nr"] for m in msgs)
rec = lib.anhaengen({"zeit": lib.jetzt(), "von": "opus", "thread": "offen-frage",
                     "haltung": "befund", "text": "Zahl 4711"})
check("Sequenznummer steigt monoton", rec["nr"] > vorher, f"{vorher} -> {rec['nr']}")
nrs = [m["nr"] for m in lib.lade()]
check("Sequenznummern sind eindeutig", len(nrs) == len(set(nrs)))

# Paralleles Marken-Setzen: ohne Sperre verloren sich zwei Leser gegenseitig die Marken.
lib.marke_setzen("opus", {}, msgs)             # Datei anlegen/normalisieren
fehler = []

def setze(wer, th, n):
    try:
        for i in range(1, n + 1):
            lib.marke_setzen(wer, {th: i}, msgs)
    except Exception as e:  # noqa: BLE001
        fehler.append(e)

t1 = threading.Thread(target=setze, args=("opus", "thema-x", 20))
t2 = threading.Thread(target=setze, args=("kimi", "thema-y", 20))
t1.start(); t2.start(); t1.join(); t2.join()
mk = json.loads((TMP / "gelesen.json").read_text())
check("parallele Marken-Updates verlieren nichts",
      not fehler and mk["opus"]["thema-x"] == 20 and mk["kimi"]["thema-y"] == 20,
      str(mk))

print(f"\n{_ok} Tests bestanden")
