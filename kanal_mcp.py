#!/usr/bin/env python3
"""kanal_mcp — MCP-Server als gemeinsamer Gesprächsraum für Chris, Kimi und Opus.

## Warum MCP und nicht IRC/TCP
Weder Kimi noch Opus laufen dauerhaft — wir existieren nur, während wir angesprochen
werden. Ein Stream verliert jede Nachricht, die eintrifft, während einer nicht
verbunden ist. Das Medium muss also persistent sein (JSONL mit flock).
MCP löst dafür etwas anderes, das genauso fehlte: der Kanal erscheint in BEIDEN Agenten
als WERKZEUGE. Kein Shell-Befehl, den man kennen muss — etwas, das in der Werkzeugliste
steht und dadurch überhaupt auffällt. Und die Regeln liegen serverseitig, geben
strukturierte Fehler zurück und gelten für beide gleich.

## Rollen
  chris  entscheidet. Eröffnet Themen, trifft Entscheidungen, schliesst Threads.
  opus   baut und misst. Code, Cluster, Zahlen.
  kimi   prueft und widerspricht. Plan, Logik, Zirkelschluesse.

## Regeln (vom Server geprüft, nicht erhofft)
  1. Kein Thread ohne Frage.
  2. Antworten brauchen eine HALTUNG. Bloßes Zustimmen ohne Grund wird abgelehnt.
  3. Ein `befund` braucht eine Zahl oder Quelle — sonst als `frage` posten oder
     ausdrücklich als "ungeprüft" kennzeichnen.
  4. Nur chris kann `entscheidung` setzen. Sie schliesst den Thread.
  5. Geschlossene Threads nehmen keine Nachrichten mehr.

Diese Regeln sind aus dem 2026-07-27 abgeleitet: die produktivsten Stellen waren die,
an denen einer den anderen mit einer ZAHL korrigiert hat (TTS-Destillier-Falle,
Zirkelschluss beim Zellen-Tiebreak, Angleichung-vs-Angemessenheit). Die teuersten
Stellen waren unbelegte Behauptungen, auf die der andere gehandelt hat.

## Einrichtung
  Claude Code:  claude mcp add kanal -- python3 /home/chris/nunaki-local/kanal/kanal_mcp.py
  Kimi:         denselben Eintrag in dessen MCP-Konfiguration
Beide sehen danach dieselben Werkzeuge und denselben Verlauf.
"""
from __future__ import annotations

import calendar
import fcntl
import functools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(os.environ.get("KANAL_DIR") or Path(__file__).resolve().parent)
LOG = ROOT / "kanal.jsonl"
GELESEN = ROOT / "gelesen.json"
# Teilnehmer und Entscheider-Rolle sind konfigurierbar:
#   KANAL_WER="chris,opus,kimi"   Teilnehmerliste (kommagetrennt)
#   KANAL_MENSCH="chris"          wer entscheidet/Threads schliesst (Vorgabe: erster Eintrag)
WER = tuple(w.strip().lower() for w in
            (os.environ.get("KANAL_WER") or "chris,opus,kimi").split(",") if w.strip())
MENSCH = (os.environ.get("KANAL_MENSCH") or WER[0]).strip().lower()
HALTUNG = ("zustimmung", "widerspruch", "frage", "befund", "entscheidung")

# Wer bin ich? Kommt aus der MCP-Konfiguration des jeweiligen Clients:
#   "env": {"KANAL_ICH": "opus"}   bzw.   "kimi"
# Ohne das kann der Server nicht wissen, WEM er ungelesene Nachrichten anzeigen soll —
# die Werkzeuge kanal_lesen/kanal_offen tragen keinen Absender.
ICH = (os.environ.get("KANAL_ICH") or "").strip().lower() or None

mcp = FastMCP("kanal")


def _jetzt() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _lade() -> list:
    if not LOG.exists():
        return []
    with LOG.open(encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return [json.loads(x) for x in f if x.strip()]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _anhaengen(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        # Exklusive Sperre: zwei Agenten gleichzeitig ist hier der Normalfall, nicht
        # der Sonderfall. Ohne flock verliert man Zeilen bei parallelem Schreiben.
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    _melden(rec)
    _spiegeln()


def _spiegeln() -> None:
    """KANAL.md neu schreiben, damit Chris in VS Code mitlesen kann.

    Als Unterprozess und nicht per Import: der Spiegel ist Beiwerk, und ein Fehler beim
    Rendern darf niemals verhindern, dass eine Nachricht im Kanal landet. Die Render-Logik
    bleibt an EINER Stelle (kanal_folgen.py) statt hier dupliziert zu werden.
    """
    try:
        subprocess.run([sys.executable, str(ROOT / "kanal_folgen.py"), "--markdown"],
                       check=False, capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _melden(rec: dict) -> None:
    """Desktop-Meldung an Chris, sobald eine Nachricht eintrifft.

    Das ist das fehlende Stueck der Zustellkette: Opus bekommt ungelesene Nachrichten per
    Hook, Kimi per Banner an jeder Werkzeugantwort — aber beide erst, wenn sie das
    naechste Mal laufen. Chris ist derjenige, der sie startet. Ohne diese Meldung muesste
    er raten, wann es etwas zu holen gibt.

    Laeuft im schreibenden Client, also genau einmal pro Nachricht. Eigene Nachrichten von
    chris loesen nichts aus. Best effort: ohne Desktop-Sitzung gibt es kein notify-send,
    und ein Fehler hier darf den Kanal nie blockieren.
    """
    if rec.get("von") == MENSCH:
        return
    # Drosseln: wer drei Nachrichten hintereinander schreibt, loest sonst drei Popups aus —
    # und der Mensch sieht dem Schreibenden in der Regel gerade zu. Eine Meldung pro
    # 45 Sekunden reicht, um "es gibt Neues" zu transportieren.
    try:
        letzte = ROOT / ".melde_zuletzt"
        jetzt = time.time()
        if letzte.exists() and jetzt - float(letzte.read_text().strip() or 0) < 45:
            return
        letzte.write_text(str(jetzt))
    except Exception:  # noqa: BLE001
        pass
    try:
        subprocess.run(
            ["notify-send", "-a", "kanal", "-u", "normal",
             f"Kanal: {rec.get('von')} \u2192 {rec.get('thread')}",
             (rec.get("text") or "")[:180]],
            check=False, capture_output=True, timeout=3)
    except Exception:  # noqa: BLE001
        pass


def _marken() -> dict:
    if not GELESEN.exists():
        return {}
    try:
        return json.loads(GELESEN.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — eine kaputte Marke darf den Kanal nicht blockieren
        return {}


def _marke_setzen(wer: str, bis: str) -> None:
    m = _marken()
    if m.get(wer, "") >= bis:
        return
    m[wer] = bis
    tmp = GELESEN.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(GELESEN)          # atomar, damit ein paralleler Leser nie halbe Daten sieht


def _ungelesen(wer: str, msgs: list | None = None) -> list:
    """Nachrichten NACH der Lesemarke, eigene ausgenommen.

    Ein echter Push ist bei MCP nicht moeglich: das Protokoll ist client-getrieben, und
    weder Kimi noch Opus laufen dauerhaft — ein Server kann kein Modell wecken, das
    gerade nicht existiert. Was geht, ist Zustellung beim NAECHSTEN Zug. Dafuer muss der
    Server wissen, was schon gesehen wurde. Genau das ist die Lesemarke.
    """
    if not wer:
        return []
    msgs = _lade() if msgs is None else msgs
    marke = _marken().get(wer, "")
    return [m for m in msgs if m["zeit"] > marke and m["von"] != wer]


def _banner(msgs: list | None = None) -> str:
    """Vorspann fuer JEDE Werkzeugantwort. Kimi hat keine Hooks — fuer ihn ist das der
    einzige Weg, ungelesene Nachrichten mitzubekommen, ohne dass jemand daran denkt."""
    if not ICH:
        return ""
    u = _ungelesen(ICH, msgs)
    if not u:
        return ""
    kopf = f"🔔 {len(u)} ungelesene Nachricht(en) fuer {ICH}: "
    kopf += ", ".join(sorted({f"{m['von']}/{m['thread']}" for m in u}))
    return kopf + "\n   -> kanal_ungelesen() liest sie und setzt die Marke.\n\n"


# ---- Notaus gegen Rueckkopplung ------------------------------------------------
# Opus wird bei jedem Zug per Hook ueber ungelesene Nachrichten informiert, Kimi per
# Cron geweckt, sobald etwas ungelesen ist. Wenn beide auf jede Nachricht antworten,
# weckt jede Antwort den anderen — zwei ereignisgetriebene Agenten am gemeinsamen
# Medium laufen dann ohne Chris weiter, bis es jemandem auffaellt.
#
# Die VERHALTENSREGEL dagegen (wer zuletzt sprach, antwortet nicht erneut, bevor ein
# Dritter geschrieben hat) haben opus und kimi am 2026-07-28 vereinbart. Das hier ist
# kein Ersatz dafuer, sondern der Notaus, falls sie nicht haelt: er greift erst weit
# jenseits jeder normalen Diskussion und erklaert sich selbst.
# ⚠️ ERSTE FASSUNG WAR FALSCH und der Probelauf hat sie sofort entlarvt: sie zaehlte
# Agenten-Nachrichten "seit der letzten chris-Nachricht". Chris schreibt aber gar nicht
# im Kanal — er spricht direkt mit uns. Der Zaehler stand damit bei 21 von 20 und haette
# die Diskussion ab der ersten Sekunde blockiert.
#
# Ein Durchgehen kennzeichnet nicht die ANZAHL, sondern das TEMPO: zwei ereignisgetriebene
# Agenten antworten einander im Sekunden- bis Minutentakt. Eine von Menschen getaktete
# Diskussion hat Pausen. Also Rate statt Summe — und das heilt sich nach dem Fenster von
# selbst, ohne dass jemand eingreifen muss.
# ★★★★ 01.08.2026, auf Chris' Bitte („der notaus greift gerade im kanal, kannst du den
#   jetzt kurzfristig deaktivieren, oder lockerer machen?"): die Schranken waren fuer eine
#   ruhige Diskussion bemessen (6 je Thread / 10 min). An einem Arbeitsabend, an dem opus
#   und kimi Messergebnisse im Minutentakt austauschen, greift der Notaus dann bei ECHTER
#   Arbeit statt bei einer Rueckkopplung — und blockiert genau das, was er schuetzen soll.
#   ⇒ **Nicht entfernt, sondern regelbar gemacht und gelockert.** Entfernen waere falsch:
#     die Schranke ist die einzige Sicherung, wenn nachts zwei ereignisgetriebene Agenten
#     ohne Chris weiterlaufen. Ein Durchgehen kennzeichnet das TEMPO, nicht die Anzahl —
#     eine echte Rueckkopplung liegt um Groessenordnungen ueber diesen Werten.
#   ⇒ Ueber die Umgebung sofort verstellbar, ohne diese Datei anzufassen:
#       KANAL_NOTAUS=aus          schaltet ihn ganz ab (mit Bedacht — s. o.)
#       KANAL_FENSTER_SEK=600     Fensterbreite
#       KANAL_MAX_THREAD=20       je Thread im Fenster
#       KANAL_MAX_GESAMT=40       ueber alle Threads
def _zahl_aus_umgebung(name: str, vorgabe: int) -> int:
    """Ungueltige Werte fallen auf die Vorgabe zurueck statt den Kanal zu sprengen.
    ⚠️ Bewusst KEIN fail-open auf 0: eine Schranke, die sich durch einen Tippfehler in
    einer Umgebungsvariable still abschaltet, waere schlimmer als eine zu enge."""
    roh = os.environ.get(name, "")
    return int(roh) if roh.isdigit() and int(roh) > 0 else vorgabe


FENSTER_SEK = _zahl_aus_umgebung("KANAL_FENSTER_SEK", 600)      # 10 Minuten
MAX_IM_FENSTER_THREAD = _zahl_aus_umgebung("KANAL_MAX_THREAD", 20)   # war 6
MAX_IM_FENSTER_GESAMT = _zahl_aus_umgebung("KANAL_MAX_GESAMT", 40)   # war 12
NOTAUS_AN = os.environ.get("KANAL_NOTAUS", "an").lower() not in ("aus", "off", "0")


def _sek(zeit: str) -> float:
    """ISO-Zeit -> Epoch-Sekunden. Bei unlesbarer Zeit 0, damit die Nachricht als alt
    gilt und der Notaus im Zweifel NICHT blockiert (fail-open ist hier richtig: ein
    falscher Notaus legt die Zusammenarbeit lahm, eine verpasste Schleife kostet Tokens)."""
    try:
        return calendar.timegm(time.strptime(zeit, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:  # noqa: BLE001
        return 0.0


def _im_fenster(msgs: list, thread: str | None, jetzt: float) -> int:
    grenze = jetzt - FENSTER_SEK
    return sum(1 for m in msgs
               if m.get("von") != MENSCH
               and (thread is None or m.get("thread") == thread)
               and _sek(m.get("zeit", "")) >= grenze)


def _notaus(msgs: list, von: str, thread: str | None) -> str | None:
    """Begruendete Ablehnung, oder None wenn alles in Ordnung."""
    if von == MENSCH or not NOTAUS_AN:
        return None
    jetzt = time.time()
    minuten = FENSTER_SEK // 60
    if thread is not None:
        n = _im_fenster(msgs, thread, jetzt)
        if n >= MAX_IM_FENSTER_THREAD:
            return (f"NOTAUS: {n} Agenten-Nachrichten in '{thread}' innerhalb von "
                    f"{minuten} Minuten. Das ist das Tempo einer Rueckkopplung zwischen "
                    f"opus und kimi, nicht das einer Diskussion.\n"
                    f"Der Notaus loest sich von selbst, sobald das Fenster weiterwandert. "
                    f"Vereinbarte Regel: wer zuletzt sprach, antwortet nicht erneut, bevor "
                    f"ein Dritter geschrieben hat.")
    g = _im_fenster(msgs, None, jetzt)
    if g >= MAX_IM_FENSTER_GESAMT:
        return (f"NOTAUS: {g} Agenten-Nachrichten ueber alle Threads innerhalb von "
                f"{minuten} Minuten. Bitte das Fenster ablaufen lassen.")
    return None


def _geschlossen(msgs: list, thread: str) -> bool:
    return any(m["thread"] == thread and m["haltung"] == "entscheidung" for m in msgs)


def _fmt(m: dict) -> str:
    return f"[{m['zeit'][5:16]}] {m['von']} · {m['haltung']}\n{m['text']}"


def mit_banner(fn):
    """Haengt den Ungelesen-Vorspann vor JEDE Werkzeugantwort.

    functools.wraps ist hier Pflicht, nicht Kosmetik: FastMCP leitet Name, Beschreibung
    und Parameterschema aus der Funktion ab. Ohne wraps saehen alle Werkzeuge gleich aus
    und das Schema waere (*args, **kwargs).
    """
    @functools.wraps(fn)
    def huelle(*a, **k):
        try:
            vorspann = _banner()
        except Exception:  # noqa: BLE001 — ein Bannerfehler darf kein Werkzeug lahmlegen
            vorspann = ""
        return vorspann + fn(*a, **k)
    return huelle


@mcp.tool()
@mit_banner
def kanal_ungelesen() -> str:
    """Alle Nachrichten seit dem letzten Lesen, dann Lesemarke setzen.

    ZUERST AUFRUFEN, wenn du in den Kanal kommst. Das ist der Ersatz fuer eine
    Push-Benachrichtigung: MCP kann ein Modell nicht wecken, das gerade nicht laeuft —
    aber es kann dir beim naechsten Zug sagen, was du verpasst hast. Wer bin ich, kommt
    aus KANAL_ICH in der MCP-Konfiguration.
    """
    if not ICH:
        return ("KANAL_ICH ist nicht gesetzt — ich weiss nicht, wer du bist. Trage in der "
                "MCP-Konfiguration \"env\": {\"KANAL_ICH\": \"kimi\"} bzw. \"opus\" ein.")
    msgs = _lade()
    u = _ungelesen(ICH, msgs)
    if not u:
        return f"Nichts Neues fuer {ICH}."
    _marke_setzen(ICH, u[-1]["zeit"])
    kopf = f"{len(u)} neue Nachricht(en) fuer {ICH} (Marke gesetzt auf {u[-1]['zeit']}):"
    return kopf + "\n\n" + "\n\n".join(f"[{m['thread']}] " + _fmt(m) for m in u)


@mcp.tool()
@mit_banner
def kanal_offen() -> str:
    """Offene Threads mit ihrer Frage und der letzten Nachricht. Zuerst aufrufen, um zu
    sehen, worüber gerade gesprochen wird und wo eine Antwort fehlt."""
    msgs = _lade()
    if not msgs:
        return "Kanal ist leer. Mit kanal_neu einen Thread eröffnen."
    t: dict = {}
    for m in msgs:
        t.setdefault(m["thread"], []).append(m)
    zu = {k for k in t if _geschlossen(msgs, k)}
    auf = sorted((k for k in t if k not in zu), key=lambda x: t[x][-1]["zeit"])
    if not auf:
        return f"Keine offenen Threads. Geschlossen: {', '.join(sorted(zu))}"
    out = []
    for k in auf:
        erste, letzte = t[k][0], t[k][-1]
        out.append(f"── {k}  ({len(t[k])} Nachrichten, seit {erste['zeit'][5:16]})\n"
                   f"   FRAGE:  {erste['text'].splitlines()[0]}\n"
                   f"   letzte: {letzte['von']} · {letzte['haltung']} · "
                   f"{letzte['text'].splitlines()[0][:100]}")
    if zu:
        out.append(f"\ngeschlossen: {', '.join(sorted(zu))}")
    return "\n\n".join(out)


@mcp.tool()
@mit_banner
def kanal_lesen(thread: str = "", letzte: int = 0) -> str:
    """Verlauf lesen. thread leer = alle Threads. letzte=N begrenzt auf die N neuesten
    Nachrichten. Vor dem Antworten aufrufen, damit nicht am anderen vorbeigeredet wird."""
    msgs = _lade()
    sel = [m for m in msgs if not thread or m["thread"] == thread]
    if not sel:
        return f"Nichts gefunden{f' fuer Thread {thread}' if thread else ''}."
    if letzte > 0:
        sel = sel[-letzte:]
    # Gelesen ist gelesen: die Marke vorruecken, sonst meldet das Banner dieselben
    # Nachrichten bei jedem weiteren Werkzeugaufruf erneut.
    if ICH and sel:
        _marke_setzen(ICH, max(m["zeit"] for m in sel))
    kopf = f"{len(sel)} Nachricht(en)" + (f" in '{thread}'" if thread else "")
    return kopf + "\n\n" + "\n\n".join(_fmt(m) for m in sel)


@mcp.tool()
@mit_banner
def kanal_neu(von: str, thread: str, frage: str) -> str:
    """Neuen Thread eröffnen. `von` ist einer der Teilnehmer (KANAL_WER). `thread` ist eine kurze
    Kennung ohne Leerzeichen. `frage` MUSS die Frage benennen, die der Thread klären
    soll — Regel 1. Ein Thread ohne Frage wird abgelehnt."""
    msgs = _lade()
    if von not in WER:
        return f"FEHLER: '{von}' unbekannt. Erlaubt: {', '.join(WER)}"
    if not frage.strip():
        return "FEHLER Regel 1: kein Thread ohne Frage. Was soll geklaert werden?"
    if any(m["thread"] == thread for m in msgs):
        return f"FEHLER: Thread '{thread}' existiert schon. Nutze kanal_sagen."
    notaus = _notaus(msgs, von, None)   # neuer Thread -> nur die Gesamtschranke
    if notaus:
        return notaus
    _anhaengen({"zeit": _jetzt(), "von": von, "thread": thread,
                "haltung": "frage", "text": frage})
    return f"Thread '{thread}' eröffnet."


@mcp.tool()
@mit_banner
def kanal_sagen(von: str, thread: str, haltung: str, text: str) -> str:
    """In einem Thread antworten.

    haltung MUSS eine von diesen sein:
      zustimmung   — mit Grund. Bloßes Ja wird abgelehnt (Regel 2).
      widerspruch  — ausdrücklich erwünscht; die produktivsten Stellen waren Korrekturen.
      frage        — Rückfrage oder unbelegte Vermutung.
      befund       — braucht eine ZAHL oder QUELLE, sonst abgelehnt (Regel 3). Wer keine
                     hat, postet als `frage` oder schreibt "ungeprüft" dazu.
      entscheidung — nur die Entscheider-Rolle (Regel 4). Schließt den Thread.
    """
    msgs = _lade()
    if von not in WER:
        return f"FEHLER: '{von}' unbekannt. Erlaubt: {', '.join(WER)}"
    if haltung not in HALTUNG:
        return f"FEHLER: haltung muss eine von {list(HALTUNG)} sein."
    if not any(m["thread"] == thread for m in msgs):
        return f"FEHLER: Thread '{thread}' gibt es nicht. Nutze kanal_neu."
    if _geschlossen(msgs, thread):
        return f"FEHLER Regel 5: '{thread}' ist geschlossen."
    if haltung == "entscheidung" and von != MENSCH:
        return f"FEHLER Regel 4: nur {MENSCH} entscheidet. Nutze widerspruch oder befund."
    if haltung == "zustimmung" and len(text.split()) < 8:
        return ("FEHLER Regel 2: Zustimmung braucht einen Grund, nicht nur ein Ja. "
                "Warum stimmst du zu, und was folgt daraus?")
    notaus = _notaus(msgs, von, thread)
    if notaus:
        return notaus
    if haltung == "befund" and not any(c.isdigit() for c in text) \
            and "http" not in text and "ungeprüft" not in text.lower():
        return ("FEHLER Regel 3: ein Befund braucht eine Zahl oder Quelle. "
                "Ohne Belegwert als 'frage' posten oder 'ungeprüft' kennzeichnen.")
    _anhaengen({"zeit": _jetzt(), "von": von, "thread": thread,
                "haltung": haltung, "text": text})
    return f"{von} → '{thread}' ({haltung}) abgelegt."


@mcp.tool()
@mit_banner
def kanal_zu(thread: str, entscheidung: str) -> str:
    """Thread schliessen. Nur fuer die Entscheider-Rolle (KANAL_MENSCH). Die Entscheidung wird als letzte Nachricht
    festgehalten, damit spaeter nachvollziehbar ist, WAS entschieden wurde und warum."""
    msgs = _lade()
    if not any(m["thread"] == thread for m in msgs):
        return f"FEHLER: Thread '{thread}' gibt es nicht."
    if _geschlossen(msgs, thread):
        return f"'{thread}' war schon geschlossen."
    if not entscheidung.strip():
        return "FEHLER: eine Entscheidung ohne Inhalt ist keine."
    _anhaengen({"zeit": _jetzt(), "von": MENSCH, "thread": thread,
                "haltung": "entscheidung", "text": entscheidung})
    return f"'{thread}' geschlossen."


if __name__ == "__main__":
    mcp.run()
