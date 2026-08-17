#!/usr/bin/env python3
"""kanal_lib — gemeinsame Kernlogik des Kanals (Speicher, Teilnahme, Marken, Regeln).

## Warum dieses Modul existiert
Die Teilnahme-Logik (Beteiligte, Lesemarken, Regelpruefung) lag nach der Einfuehrung des
Subscription-Modells in VIER Kopien vor (MCP-Server, CLI, Ping, Folgen) — wortgleich,
mit dem Kommentar "Spiegel der Logik in kanal_mcp.py". Genau das Auseinanderlaufen, das
der Kanal sonst verhindert, drohte dann im eigenen Code. Hier ist die EINE Stelle.

## Sperrkonzept (zwei Ebenen, feste Reihenfolge — wer beides braucht: erst SPERRE)
  * SPERRE (.kanal.lock): serialisiert PRUEFUNG + SCHREIBEN als eine atomare Einheit.
    Ohne sie ist jede Regelpruefung ein TOCTOU-Fenster: zwischen "Thread offen?" und
    dem Append kann der Entscheider den Thread schliessen. Alle Schreibpfade
    (MCP-Server, CLI, Chat) nehmen SPERRE um validate+append.
  * LOG (kanal.jsonl): LOCK_SH beim Lesen, LOCK_EX beim Append — damit auch Schreiber
    ohne SPERRE (alte Skripte) keine Zeilen verlieren.
  * Marken (gelesen.json): read-modify-write unter SPERRE. Ohne Sperre verlieren zwei
    parallele Leser gegenseitig ihre Marken — und schon Gelesenes taucht wieder auf.

## Datenformat
  Nachricht:   {"nr", "zeit", "von", "thread", "haltung", "text"}
  Eröffnung:   + optional "teilnehmer": [...]  (fehlend/leer = öffentlich)
  Meta-Eintrag: {"nr", "zeit", "von", "thread", "art": "beitritt"|"verlassen",
                 "durch"?: <wer geholt hat>, "text": ""}
  nr: monotone Sequenznummer, unter dem Lock vergeben. Altbestand ohne nr: die Datei
  ist append-only, die Position (unter den nicht-leeren Zeilen) IST die Nummer.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(os.environ.get("KANAL_DIR") or Path(__file__).resolve().parent)
LOG = ROOT / "kanal.jsonl"
GELESEN = ROOT / "gelesen.json"
SPERRE = ROOT / ".kanal.lock"

WER = tuple(w.strip().lower() for w in
            (os.environ.get("KANAL_WER") or "chris,opus,kimi").split(",") if w.strip())
MENSCH = (os.environ.get("KANAL_MENSCH") or WER[0]).strip().lower()
HALTUNG = ("zustimmung", "widerspruch", "frage", "befund", "entscheidung")
ICH = (os.environ.get("KANAL_ICH") or "").strip().lower() or None


def jetzt() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---- Speicher ------------------------------------------------------------------

def lade() -> list:
    """Alle Eintraege, Sequenznummer garantiert. Eine kaputte Zeile darf den Kanal
    nicht blockieren: sie wird uebersprungen, zaehlt aber bei der Positionsnummer mit,
    damit nr stabil bleibt."""
    if not LOG.exists():
        return []
    with LOG.open(encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            zeilen = f.readlines()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    msgs = []
    nr = 0
    for z in zeilen:
        if not z.strip():
            continue
        nr += 1
        try:
            m = json.loads(z)
        except Exception:  # noqa: BLE001
            continue
        m.setdefault("nr", nr)
        msgs.append(m)
    return msgs


def anhaengen(rec: dict) -> dict:
    """Einen Eintrag schreiben (nr unter dem Lock). Reines Append — Benachrichtigung
    und Spiegel sind Sache des Aufrufers, damit die Sperre kurz bleibt."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            rec["nr"] = sum(1 for z in f if z.strip()) + 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")  # "a": immer ans Ende
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return rec


@contextmanager
def gesperrt():
    """Exklusive Kanal-Sperre fuer pruefen-und-schreiben als EINE Einheit (TOCTOU).

    Reihenfolge beachten: wer SPERRE haelt, darf noch LOG sperren — nie umgekehrt,
    sonst droht mit einem Alt-Schreiber (nur LOG) ein Deadlock ... nicht ganz: ein
    LOG-only-Schreiber haelt LOG nur fuer das Append und will SPERRE nie. Kritisch
    waere nur die Umkehrung; die kommt in diesem Code nicht vor.
    """
    SPERRE.parent.mkdir(parents=True, exist_ok=True)
    with SPERRE.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---- Teilnahme -----------------------------------------------------------------

def beteiligte(msgs: list) -> tuple[dict, dict]:
    """thread -> basis (None = oeffentlich, sonst Teilnehmer-Menge) und
    thread -> Menge derer, die einen oeffentlichen Thread verlassen haben."""
    basis: dict = {}
    raus: dict = {}
    for m in msgs:
        th = m.get("thread")
        if not th:
            continue
        art = m.get("art")
        if art == "beitritt":
            if m["von"] in raus.get(th, ()):
                raus[th].discard(m["von"])       # Rueckkehr nach Abmeldung
            elif basis.get(th):                  # eingeschraenkter Thread: dazukommen
                basis[th].add(m["von"])
        elif art == "verlassen":
            if basis.get(th) and m["von"] in basis[th]:
                basis[th].discard(m["von"])
            else:                                # oeffentlich oder Nicht-Mitglied
                raus.setdefault(th, set()).add(m["von"])  # (z. B. MENSCH stumm schalten)
        elif th not in basis:
            tl = m.get("teilnehmer")       # nur die Eroeffnungsnachricht traegt das Feld
            basis[th] = set(tl) if tl else None
    return basis, raus


def dabei(basis: dict, raus: dict, thread: str, wer: str) -> bool:
    if wer in raus.get(thread, ()):
        return False
    b = basis.get(thread)
    return True if b is None else wer in b


def teilnehmer_von(basis: dict, raus: dict, thread: str) -> set:
    """Aufgeloeste Teilnehmermenge (oeffentlich = WER), Abgemeldete abgezogen."""
    b = basis.get(thread)
    s = set(WER) if b is None else set(b)
    return s - raus.get(thread, set())


def geschlossen(msgs: list, thread: str) -> bool:
    return any(m["thread"] == thread and m.get("haltung") == "entscheidung" for m in msgs)


# ---- Lesemarken ----------------------------------------------------------------
# Pro Teilnehmer UND Thread, als Sequenznummer: {"kimi": {"thema-a": 42, "*": 30}}.
# "*" ist die Basis fuer Threads ohne eigene Marke. Altformate werden beim Lesen
# umgerechnet: eine ISO-Zeitmarke pro Teilnehmer — und fuer den MENSCH zusaetzlich der
# alte CLI-Schluessel "bis".

def marken_roh() -> dict:
    if not GELESEN.exists():
        return {}
    try:
        return json.loads(GELESEN.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — eine kaputte Marke darf den Kanal nicht blockieren
        return {}


def marken(msgs: list, wer: str) -> dict:
    roh = marken_roh()
    v = roh.get(wer)
    if isinstance(v, dict):
        m = {str(k): int(x) for k, x in v.items()
             if isinstance(x, int) or (isinstance(x, str) and x.isdigit())}
    elif isinstance(v, str):             # Altformat: ISO-Zeit -> letzte nr davor
        m = {"*": max((x["nr"] for x in msgs if x.get("zeit", "") <= v), default=0)}
    else:
        m = {}
    if wer == MENSCH and isinstance(roh.get("bis"), str):
        # CLI-Altbestand: gilt zusaetzlich zur eigenen Marke als Basis — beide
        # Formate koennen nach der Umstellung eine Weile nebeneinander existieren.
        alt = max((x["nr"] for x in msgs if x.get("zeit", "") <= roh["bis"]), default=0)
        if alt > m.get("*", 0):
            m["*"] = alt
    return m


def marke_setzen(wer: str, paare: dict, msgs: list) -> None:
    """Marken mehrerer Threads auf einmal vorruecken (nie zurueck) — unter SPERRE:
    read-modify-write ohne Lock verliert bei zwei parallelen Lesern eine der Marken."""
    if not wer or not paare:
        return
    with gesperrt():
        roh = marken_roh()
        m = marken(msgs, wer)
        for th, nr in paare.items():
            if nr > m.get(th, 0):
                m[th] = nr
        roh[wer] = m
        tmp = GELESEN.with_suffix(".tmp")
        tmp.write_text(json.dumps(roh, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(GELESEN)      # atomar: ein paralleler Leser sieht nie halbe Daten


# ---- Ungelesen -----------------------------------------------------------------

def ungelesen(wer: str, msgs: list | None = None) -> list:
    """Nachrichten hinter der Lesemarke, eigene ausgenommen — nur aus Threads, an
    denen `wer` teilnimmt. Der MENSCH sieht alles (Router), aber ein VERLASSENER
    Thread bleibt auch fuer ihn stumm: lesen kann er weiterhin alles, nur die
    Zustellung stoppt."""
    if not wer:
        return []
    msgs = lade() if msgs is None else msgs
    basis, raus = beteiligte(msgs)
    mk = marken(msgs, wer)
    out = []
    for m in msgs:
        if m["von"] == wer:
            continue
        if m["nr"] <= max(mk.get(m["thread"], 0), mk.get("*", 0)):
            continue
        if dabei(basis, raus, m["thread"], wer) \
                or (wer == MENSCH and wer not in raus.get(m["thread"], ())):
            out.append(m)
    return out


# ---- Darstellung ---------------------------------------------------------------

def fmt(m: dict) -> str:
    if m.get("art") == "beitritt":
        durch = f" — geholt von {m['durch']}" if m.get("durch") else ""
        return f"[{m['zeit'][5:16]}] → {m['von']} ist dem Thread beigetreten{durch}"
    if m.get("art") == "verlassen":
        return f"[{m['zeit'][5:16]}] ← {m['von']} hat den Thread verlassen"
    return f"[{m['zeit'][5:16]}] {m['von']} · {m['haltung']}\n{m['text']}"


# ---- Regeln --------------------------------------------------------------------

def validiere(msgs: list, von: str, thread: str, haltung: str, text: str,
              ich: str | None = None) -> str | None:
    """Regeln 1–5 + Teilnahme fuer eine Nachricht. Begruendete Ablehnung oder None.
    `ich` ist die Client-Identitaet (KANAL_ICH) — None bei Werkzeugen ohne eigene
    Identitaet (CLI/Chat des Menschen), dann entfaellt der Identitaetsabgleich."""
    if von not in WER:
        return f"FEHLER: '{von}' unbekannt. Erlaubt: {', '.join(WER)}"
    if ich and von != ich:
        return (f"FEHLER: Identitaet — dieser Client ist '{ich}', nicht '{von}'. "
                f"`von` muss zu KANAL_ICH der eigenen Konfiguration passen.")
    if haltung not in HALTUNG:
        return f"FEHLER: haltung muss eine von {list(HALTUNG)} sein."
    if not any(m["thread"] == thread for m in msgs):
        return f"FEHLER: Thread '{thread}' gibt es nicht. Nutze kanal_neu."
    if geschlossen(msgs, thread):
        return f"FEHLER Regel 5: '{thread}' ist geschlossen."
    if haltung == "entscheidung" and von != MENSCH:
        return f"FEHLER Regel 4: nur {MENSCH} entscheidet. Nutze widerspruch oder befund."
    basis, raus = beteiligte(msgs)
    if von != MENSCH and not dabei(basis, raus, thread, von):
        return (f"FEHLER: du bist nicht Teilnehmer von '{thread}'. "
                f"Mit kanal_beitreten(thread=\"{thread}\") dazukommen.")
    if haltung == "zustimmung" and len(text.split()) < 8:
        return ("FEHLER Regel 2: Zustimmung braucht einen Grund, nicht nur ein Ja. "
                "Warum stimmst du zu, und was folgt daraus?")
    if haltung == "befund" and not any(c.isdigit() for c in text) \
            and "http" not in text and "ungeprüft" not in text.lower():
        return ("FEHLER Regel 3: ein Befund braucht eine Zahl oder Quelle. "
                "Ohne Belegwert als 'frage' posten oder 'ungeprüft' kennzeichnen.")
    return None


def validiere_neu(msgs: list, von: str, thread: str, frage: str,
                  teilnehmer: list, ich: str | None = None) -> str | None:
    """Regeln fuer das Eroeffnen eines Threads. Ablehnung oder None."""
    if von not in WER:
        return f"FEHLER: '{von}' unbekannt. Erlaubt: {', '.join(WER)}"
    if ich and von != ich:
        return (f"FEHLER: Identitaet — dieser Client ist '{ich}', nicht '{von}'. "
                f"`von` muss zu KANAL_ICH der eigenen Konfiguration passen.")
    # Thread-Namen sind Adressen: sie tauchen in kanal_lesen/ping/URLs auf. Leer,
    # Leerzeichen oder Grossschreibung machten sie mehrdeutig ("Thema-A" vs "thema-a"
    # waeren zwei Threads) — deshalb eine feste Form statt Freitext.
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", thread or ""):
        vorschlag = re.sub(r"[^a-z0-9_-]+", "-", (thread or "").lower()).strip("-")
        return (f"FEHLER: Thread-Name '{thread}' ungueltig. Erlaubt: Kleinbuchstaben, "
                f"Ziffern, '-' und '_', beginnend mit Buchstabe/Ziffer."
                + (f" Vorschlag: '{vorschlag}'" if vorschlag else ""))
    if not frage.strip():
        return "FEHLER Regel 1: kein Thread ohne Frage. Was soll geklaert werden?"
    if any(m["thread"] == thread for m in msgs):
        return f"FEHLER: Thread '{thread}' existiert schon. Nutze kanal_sagen."
    fremd = [t for t in teilnehmer if t not in WER]
    if fremd:
        return f"FEHLER: unbekannte Teilnehmer: {', '.join(fremd)}. Erlaubt: {', '.join(WER)}"
    return None
