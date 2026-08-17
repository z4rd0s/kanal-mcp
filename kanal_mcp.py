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

## Regeln (vom Server geprüft, nicht erhofft — die Prüfung selbst liegt in kanal_lib)
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

## Teilnahme an Themen (Subscription)
Mehrere Themen parallel gingen an zwei Stellen kaputt: die Zustellung weckte JEDEN bei
JEDEM Thread, und eine einzige zeitbasierte Lesemarke pro Teilnehmer verschluckte
ungelesene Nachrichten des einen Threads, sobald der andere gelesen wurde. Deshalb:

  * Jeder Thread hat eine TEILNEHMERLISTE (bei kanal_neu, leer = öffentlich = alle).
    Wer nicht dabei ist, wird nicht geweckt und kann nicht schreiben — bis er beitritt
    (kanal_beitreten) oder per @name im Text geholt wird. kanal_verlassen meldet ab.
  * Nachrichten tragen eine monotone Sequenznummer `nr`; Lesemarken sind PRO THREAD.
    Lesen in Thema A beruehrt Thema B nie.
  * Ausnahme Router: der MENSCH sieht beim LESEN alles und darf ueberall schreiben.
    Auch er kann einen Thread VERLASSEN — dann bleibt er lesbar, aber die Zustellung
    (Banner, Hook, Desktop-Meldung) zu diesem Thema stoppt.

Die ganze Mechanik (Speicher, Sperren, Teilnahme, Marken, Regelpruefung) liegt in
kanal_lib.py — EINE Stelle, von Server, CLI, Ping, Folgen und Chat gemeinsam genutzt.

## Identität
Der Absender kommt aus KANAL_ICH der Client-Konfiguration; ein abweichender
`von`-Parameter wird abgelehnt. kanal_zu prueft ICH == MENSCH. Das ist Schutz gegen
Unfaelle (opus antwortet versehentlich als chris), nicht gegen boeswillige Clients —
bei lokalem stdio kann jeder seine eigene Umgebung setzen. Ist KANAL_ICH nicht
gesetzt, wird gewarnt statt geprueft.

## Einrichtung
  Claude Code:  claude mcp add kanal -- python3 /home/chris/workspace/merlin/kanal-daten/kanal_mcp.py
  Kimi:         denselben Eintrag in dessen MCP-Konfiguration
Beide sehen danach dieselben Werkzeuge und denselben Verlauf.
"""
from __future__ import annotations

import calendar
import functools
import os
import re
import subprocess
import sys
import time

from mcp.server.fastmcp import FastMCP

import kanal_lib as lib
from kanal_lib import ICH, MENSCH, WER

ROOT = lib.ROOT

mcp = FastMCP("kanal")


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


def _melden(rec: dict, raus: dict) -> None:
    """Desktop-Meldung an Chris, sobald eine Nachricht eintrifft.

    Das ist das fehlende Stueck der Zustellkette: Opus bekommt ungelesene Nachrichten per
    Hook, Kimi per Banner an jeder Werkzeugantwort — aber beide erst, wenn sie das
    naechste Mal laufen. Chris ist derjenige, der sie startet. Ohne diese Meldung muesste
    er raten, wann es etwas zu holen gibt.

    Themenbezogen wie der Rest der Zustellung: hat Chris einen Thread VERLASSEN, meldet
    er ihn nicht mehr — lesen kann er ihn weiterhin. Laeuft im schreibenden Client, also
    genau einmal pro Nachricht. Eigene Nachrichten von chris loesen nichts aus.
    Best effort: ohne Desktop-Sitzung gibt es kein notify-send, und ein Fehler hier darf
    den Kanal nie blockieren.
    """
    if rec.get("von") == MENSCH:
        return
    if MENSCH in raus.get(rec.get("thread"), ()):   # verlassener Thread bleibt stumm
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


def _zustellen(recs: list, raus: dict) -> None:
    """Nach dem Schreiben, AUSSERHALB der Sperre: Desktop-Meldung + Spiegel.
    Meta-Eintraege (beitritt/verlassen) loesen keine Meldung aus — die zugehoerige
    Nachricht (z. B. die @-Erwaehnung) meldet ohnehin."""
    for rec in recs:
        if not rec.get("art"):
            _melden(rec, raus)
    if recs:
        _spiegeln()


def _banner(msgs: list | None = None) -> str:
    """Vorspann fuer JEDE Werkzeugantwort. Kimi hat keine Hooks — fuer ihn ist das der
    einzige Weg, ungelesene Nachrichten mitzubekommen, ohne dass jemand daran denkt."""
    if not ICH:
        return ""
    u = lib.ungelesen(ICH, msgs)
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
    # Meta-Eintraege (beitritt/verlassen) sind keine Diskussion und zaehlen nicht.
    return sum(1 for m in msgs
               if not m.get("art")
               and m.get("von") != MENSCH
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


def _warnung_identitaet() -> str:
    """Ist KANAL_ICH nicht gesetzt, kann der Absender nicht geprueft werden — dann
    warnen statt still durchzuwinken (der Schutz soll nicht lautlos wegfallen)."""
    return ("" if ICH else
            "\n⚠️ KANAL_ICH ist nicht gesetzt — Absender ungeprueft. "
            "\"env\": {\"KANAL_ICH\": \"...\"} in der MCP-Konfiguration eintragen.")


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
    aus KANAL_ICH in der MCP-Konfiguration. Geliefert wird nur, was zu Threads gehoert,
    an denen du teilnimmst.
    """
    if not ICH:
        return ("KANAL_ICH ist nicht gesetzt — ich weiss nicht, wer du bist. Trage in der "
                "MCP-Konfiguration \"env\": {\"KANAL_ICH\": \"kimi\"} bzw. \"opus\" ein.")
    msgs = lib.lade()
    u = lib.ungelesen(ICH, msgs)
    if not u:
        return f"Nichts Neues fuer {ICH}."
    lib.marke_setzen(ICH, {th: max(m["nr"] for m in u if m["thread"] == th)
                           for th in {m["thread"] for m in u}}, msgs)
    kopf = f"{len(u)} neue Nachricht(en) fuer {ICH} (Marken gesetzt):"
    return kopf + "\n\n" + "\n\n".join(f"[{m['thread']}] " + lib.fmt(m) for m in u)


@mcp.tool()
@mit_banner
def kanal_offen() -> str:
    """Offene Threads mit ihrer Frage, ihren Teilnehmern und der letzten Nachricht.
    Zuerst aufrufen, um zu sehen, worüber gerade gesprochen wird und wo eine Antwort
    fehlt."""
    msgs = lib.lade()
    fach = [m for m in msgs if not m.get("art")]   # Meta-Eintraege sind keine Beitraege
    if not fach:
        return "Kanal ist leer. Mit kanal_neu einen Thread eröffnen."
    basis, raus = lib.beteiligte(msgs)
    t: dict = {}
    for m in fach:
        t.setdefault(m["thread"], []).append(m)
    zu = {k for k in t if lib.geschlossen(fach, k)}
    auf = sorted((k for k in t if k not in zu), key=lambda x: t[x][-1]["zeit"])
    if not auf:
        return f"Keine offenen Threads. Geschlossen: {', '.join(sorted(zu))}"
    out = []
    for k in auf:
        erste, letzte = t[k][0], t[k][-1]
        dabei = ", ".join(sorted(lib.teilnehmer_von(basis, raus, k))) or "—"
        out.append(f"── {k}  [{dabei}]  ({len(t[k])} Nachrichten, seit {erste['zeit'][5:16]})\n"
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
    msgs = lib.lade()
    sel = [m for m in msgs if not thread or m["thread"] == thread]
    if not sel:
        return f"Nichts gefunden{f' fuer Thread {thread}' if thread else ''}."
    if letzte > 0:
        sel = sel[-letzte:]
    # Gelesen ist gelesen: die Marken der BETREFFENDEN Threads vorruecken, sonst meldet
    # das Banner dieselben Nachrichten bei jedem weiteren Werkzeugaufruf erneut. Andere
    # Threads bleiben unangetastet — darum sind die Marken pro Thread.
    if ICH and sel:
        lib.marke_setzen(ICH, {th: max(m["nr"] for m in sel if m["thread"] == th)
                               for th in {m["thread"] for m in sel}}, msgs)
    kopf = f"{len(sel)} Nachricht(en)" + (f" in '{thread}'" if thread else "")
    return kopf + "\n\n" + "\n\n".join(lib.fmt(m) for m in sel)


@mcp.tool()
@mit_banner
def kanal_neu(von: str, thread: str, frage: str, teilnehmer: str = "") -> str:
    """Neuen Thread eröffnen. `von` ist einer der Teilnehmer (KANAL_WER) und muss zu
    KANAL_ICH dieses Clients passen. `thread` ist eine kurze Kennung in fester Form
    (Kleinbuchstaben, Ziffern, `-`/`_` — der Server lehnt andere Namen ab, weil der
    Name zugleich die Adresse des Threads ist).
    `frage` MUSS die Frage benennen, die der Thread klären soll — Regel 1. Ein Thread
    ohne Frage wird abgelehnt.

    `teilnehmer` ist eine kommagetrennte Liste aus KANAL_WER — leer bedeutet öffentlich
    (alle). Wer nicht dabei ist, wird bei diesem Thema nicht geweckt und kann nicht
    schreiben, bis er beitritt (kanal_beitreten) oder per @name geholt wird. Der
    Ersteller ist automatisch dabei."""
    tn = [t.strip().lower() for t in teilnehmer.split(",") if t.strip()]
    with lib.gesperrt():
        # Pruefung und Schreiben unter EINER Sperre — sonst ist jede Regel ein
        # TOCTOU-Fenster (der Thread koennte zwischen Pruefung und Append entstehen).
        msgs = lib.lade()
        fehler = lib.validiere_neu(msgs, von, thread, frage, tn, ich=ICH)
        if fehler:
            return fehler
        notaus = _notaus(msgs, von, None)   # neuer Thread -> nur die Gesamtschranke
        if notaus:
            return notaus
        rec = {"zeit": lib.jetzt(), "von": von, "thread": thread,
               "haltung": "frage", "text": frage}
        if tn:
            rec["teilnehmer"] = sorted({von, *tn})
        lib.anhaengen(rec)
        raus = lib.beteiligte(msgs)[1]
    _zustellen([rec], raus)
    kreis = "öffentlich (alle)" if not tn else "Teilnehmer: " + ", ".join(rec["teilnehmer"])
    return f"Thread '{thread}' eröffnet — {kreis}." + _warnung_identitaet()


@mcp.tool()
@mit_banner
def kanal_sagen(von: str, thread: str, haltung: str, text: str) -> str:
    """In einem Thread antworten. Nur Teilnehmer des Threads duerfen schreiben —
    mit kanal_beitreten dazukommen, oder dich per @name im Text holen lassen.

    haltung MUSS eine von diesen sein:
      zustimmung   — mit Grund. Bloßes Ja wird abgelehnt (Regel 2).
      widerspruch  — ausdrücklich erwünscht; die produktivsten Stellen waren Korrekturen.
      frage        — Rückfrage oder unbelegte Vermutung.
      befund       — braucht eine ZAHL oder QUELLE, sonst abgelehnt (Regel 3). Wer keine
                     hat, postet als `frage` oder schreibt "ungeprüft" dazu.
      entscheidung — nur die Entscheider-Rolle (Regel 4). Schließt den Thread.
    """
    with lib.gesperrt():
        msgs = lib.lade()
        fehler = lib.validiere(msgs, von, thread, haltung, text, ich=ICH)
        if fehler:
            return fehler
        notaus = _notaus(msgs, von, thread)
        if notaus:
            return notaus
        rec = lib.anhaengen({"zeit": lib.jetzt(), "von": von, "thread": thread,
                             "haltung": haltung, "text": text})
        recs = [rec]
        # @erwaehnung: Genannte werden in den Thread geholt — der sanfte Weg, jemanden
        # gezielt dazuzunehmen, statt alle Threads fuer alle zu oeffnen. Der Lookbehind
        # verhindert Fehlzuendungen bei E-Mail-Adressen (max@kimi) und @@.
        basis, raus = lib.beteiligte(msgs + recs)
        geholt = []
        for name in {n.lower() for n in re.findall(r"(?<![\w.@-])@([A-Za-z0-9_-]+)", text)}:
            if name in WER and name != von and name != MENSCH \
                    and not lib.dabei(basis, raus, thread, name):
                recs.append(lib.anhaengen({"zeit": lib.jetzt(), "von": name,
                                           "thread": thread, "art": "beitritt",
                                           "durch": von, "text": ""}))
                geholt.append(name)
    _zustellen(recs, raus)
    zugabe = f" ({', '.join(geholt)} per @ geholt)" if geholt else ""
    return f"{von} → '{thread}' ({haltung}) abgelegt.{zugabe}" + _warnung_identitaet()


@mcp.tool()
@mit_banner
def kanal_beitreten(thread: str) -> str:
    """Einem Thread beitreten: danach bekommst du seine Nachrichten als ungelesen
    gemeldet und darfst schreiben. Wer du bist, kommt aus KANAL_ICH."""
    if not ICH:
        return ("KANAL_ICH ist nicht gesetzt — ich weiss nicht, wer du bist. Trage in der "
                "MCP-Konfiguration \"env\": {\"KANAL_ICH\": \"kimi\"} bzw. \"opus\" ein.")
    with lib.gesperrt():
        msgs = lib.lade()
        if not any(m["thread"] == thread for m in msgs):
            return f"FEHLER: Thread '{thread}' gibt es nicht."
        basis, raus = lib.beteiligte(msgs)
        if lib.dabei(basis, raus, thread, ICH):
            return f"{ICH} ist schon in '{thread}'."
        rec = lib.anhaengen({"zeit": lib.jetzt(), "von": ICH, "thread": thread,
                             "art": "beitritt", "text": ""})
    _zustellen([rec], raus)
    return f"{ICH} ist '{thread}' beigetreten."


@mcp.tool()
@mit_banner
def kanal_verlassen(thread: str) -> str:
    """Einen Thread verlassen: keine ungelesenen Meldungen mehr aus diesem Thema.
    Lesen kannst du ihn weiterhin (kanal_lesen). Wer du bist, kommt aus KANAL_ICH.
    Auch die Entscheider-Rolle kann verlassen — die Zustellung stoppt, die Sicht nicht."""
    if not ICH:
        return ("KANAL_ICH ist nicht gesetzt — ich weiss nicht, wer du bist. Trage in der "
                "MCP-Konfiguration \"env\": {\"KANAL_ICH\": \"kimi\"} bzw. \"opus\" ein.")
    with lib.gesperrt():
        msgs = lib.lade()
        if not any(m["thread"] == thread for m in msgs):
            return f"FEHLER: Thread '{thread}' gibt es nicht."
        basis, raus = lib.beteiligte(msgs)
        if ICH in raus.get(thread, ()):
            return f"{ICH} ist aus '{thread}' schon draussen."
        if ICH != MENSCH and not lib.dabei(basis, raus, thread, ICH):
            return f"{ICH} ist gar nicht in '{thread}'."
        rec = lib.anhaengen({"zeit": lib.jetzt(), "von": ICH, "thread": thread,
                             "art": "verlassen", "text": ""})
    _zustellen([rec], raus)
    return f"{ICH} hat '{thread}' verlassen — Zustellung stoppt, Lesen bleibt moeglich."


@mcp.tool()
@mit_banner
def kanal_zu(thread: str, entscheidung: str) -> str:
    """Thread schliessen. Nur fuer die Entscheider-Rolle (KANAL_MENSCH) — geprueft wird
    KANAL_ICH dieses Clients, nicht ein frei waehlbarer Name. Die Entscheidung wird als
    letzte Nachricht festgehalten, damit spaeter nachvollziehbar ist, WAS entschieden
    wurde und warum."""
    if ICH != MENSCH:
        return (f"FEHLER Regel 4: nur {MENSCH} schliesst Threads "
                f"(dieser Client: {ICH or 'KANAL_ICH nicht gesetzt'}).")
    with lib.gesperrt():
        msgs = lib.lade()
        if not any(m["thread"] == thread for m in msgs):
            return f"FEHLER: Thread '{thread}' gibt es nicht."
        if lib.geschlossen(msgs, thread):
            return f"'{thread}' war schon geschlossen."
        if not entscheidung.strip():
            return "FEHLER: eine Entscheidung ohne Inhalt ist keine."
        rec = lib.anhaengen({"zeit": lib.jetzt(), "von": MENSCH, "thread": thread,
                             "haltung": "entscheidung", "text": entscheidung})
        raus = lib.beteiligte(msgs)[1]
    _zustellen([rec], raus)
    return f"'{thread}' geschlossen."


if __name__ == "__main__":
    mcp.run()
