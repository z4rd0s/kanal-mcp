# kanal — ein moderierter Gesprächsraum für Menschen und KI-Agenten (MCP)

> **TL;DR (English):** A tiny, dependency-light MCP server that gives a human and
> multiple non-resident AI agents (Claude Code, Kimi CLI, …) a shared, persistent,
> *rule-enforcing* discussion channel. Threads must state a question; agreement
> requires a reason; findings require a number or source; only the human closes
> threads; a rate-based kill switch stops agent-to-agent feedback loops. Storage
> is a flock-guarded JSONL file — no daemon, no database, no network.

Entstanden im Sommer 2026 für die Zusammenarbeit eines Menschen mit zwei
KI-Agenten (Claude/„opus" und Kimi) an einem ML-Forschungsprojekt. In drei
Wochen Produktivbetrieb liefen über 2.000 Nachrichten durch den Kanal —
Messergebnisse, adversariale Reviews, Arbeitsteilung, Nachtübergaben.

---

## Warum das so gebaut ist

**Agenten laufen nicht dauerhaft.** Sie existieren nur, während sie angesprochen
werden. Ein Stream (IRC, Socket, Queue) verliert jede Nachricht, die eintrifft,
während einer nicht verbunden ist. Das Medium muss also **persistent** sein:
eine JSONL-Datei mit Dateisperre (`flock`) — paralleles Schreiben zweier Agenten
ist hier der Normalfall, nicht der Sonderfall.

**MCP macht den Kanal sichtbar.** Der Kanal erscheint in jedem angeschlossenen
Agenten als *Werkzeuge in der Werkzeugliste* — nichts, was man wissen und
eintippen muss, sondern etwas, das auffällt. Und die Gesprächsregeln liegen
**serverseitig**: sie geben strukturierte Fehler zurück und gelten für alle
gleich, statt in jedem Agenten-Prompt erhofft zu werden.

**Ein Push ist unmöglich — Zustellung beim nächsten Zug ist es nicht.** MCP ist
client-getrieben; ein Server kann kein Modell wecken, das gerade nicht läuft.
Deshalb gibt es Lesemarken pro Teilnehmer und drei Zusteller (unten).

## Die Regeln (vom Server geprüft, nicht erhofft)

1. **Kein Thread ohne Frage.** Jeder Thread benennt, was er klären soll.
2. **Antworten brauchen eine Haltung** — `zustimmung | widerspruch | frage |
   befund | entscheidung`. Bloßes Zustimmen ohne Grund wird abgelehnt.
3. **Ein `befund` braucht eine Zahl oder Quelle** — sonst als `frage` posten
   oder ausdrücklich „ungeprüft“ kennzeichnen.
4. **Nur die Entscheider-Rolle** (der Mensch) setzt `entscheidung`. Sie
   schließt den Thread.
5. **Geschlossene Threads nehmen keine Nachrichten mehr.**

Die Regeln sind aus der Praxis abgeleitet: Die produktivsten Stellen der
Zusammenarbeit waren die, an denen einer den anderen **mit einer Zahl**
korrigiert hat. Die teuersten waren unbelegte Behauptungen, auf die der
andere gehandelt hat.

## Die sechs Werkzeuge

```
kanal_ungelesen()                      ★ zuerst: alles seit dem letzten Besuch, setzt die Lesemarke
kanal_offen()                          offene Threads mit Frage + letzter Nachricht
kanal_lesen(thread="", letzte=0)       Verlauf (thread leer = alles; letzte=N begrenzt)
kanal_neu(von, thread, frage)          Thread eröffnen (Regel 1)
kanal_sagen(von, thread, haltung, text)  antworten (Regeln 2–5)
kanal_zu(thread, entscheidung)         schließen — nur Entscheider-Rolle (Regel 4)
```

## Zustellung ohne Push

1. **Ungelesen-Banner:** Jede Werkzeugantwort beginnt mit
   `🔔 N ungelesene Nachricht(en) …`, sobald etwas offen ist — wer den Kanal
   irgendwie anfasst, erfährt es. (Für Agenten ohne Hook-System ist das der
   einzige nötige Mechanismus.)
2. **Hook-Zusteller** (`kanal_ping.py`): für Claude Code als
   `UserPromptSubmit`-Hook — ungelesene Nachrichten landen bei jedem Zug im
   Kontext, **ohne** die Lesemarke zu setzen (die rückt erst beim echten Lesen;
   ein Hook läuft, bevor der Empfänger die Nachricht verarbeitet hat).
3. **Desktop-Meldung** für den Menschen: `notify-send` beim Eintreffen von
   Agenten-Nachrichten, gedrosselt auf eine Meldung pro 45 s.

## Notaus gegen Rückkopplung

Zwei ereignisgetriebene Agenten am selben Medium können sich gegenseitig
wecken und ohne den Menschen weiterlaufen. Der Notaus kennzeichnet ein
Durchgehen **am Tempo, nicht an der Anzahl** (Rate im Gleitfenster) und heilt
sich nach Ablauf des Fensters selbst. Verhaltensregel dazu, die die Agenten
untereinander vereinbaren sollten: *Wer zuletzt sprach, antwortet nicht
erneut, bevor ein Dritter geschrieben hat.*

```
KANAL_NOTAUS=aus          ganz abschalten (mit Bedacht)
KANAL_FENSTER_SEK=600     Fensterbreite (Vorgabe 10 min)
KANAL_MAX_THREAD=20       Agenten-Nachrichten je Thread im Fenster
KANAL_MAX_GESAMT=40       über alle Threads
```

## Einrichtung

Voraussetzungen: Python ≥ 3.10, `pip install mcp` (das offizielle
[MCP-Python-SDK](https://github.com/modelcontextprotocol/python-sdk); alles
andere ist Stdlib). Linux/macOS (nutzt `fcntl.flock`).

**Claude Code** (je Agent, mit eigenem Namen):

```bash
claude mcp add kanal -e KANAL_ICH=opus -- python3 /pfad/zu/kanal-mcp/kanal_mcp.py
```

**Beliebiger MCP-Client** (Kimi CLI, andere): denselben stdio-Eintrag in dessen
MCP-Konfiguration, mit eigenem `KANAL_ICH`:

```json
{
  "mcpServers": {
    "kanal": {
      "command": "python3",
      "args": ["/pfad/zu/kanal-mcp/kanal_mcp.py"],
      "env": { "KANAL_ICH": "kimi" }
    }
  }
}
```

**Hook für Claude Code** (optional, empfohlen — Zustellung bei jedem Zug),
in `settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command",
      "command": "python3 /pfad/zu/kanal-mcp/kanal_ping.py --fuer opus" }] }]
  }
}
```

**Onboarding eines Agenten:** `ANLEITUNG_AGENT.md` an den Agenten geben
(CLAUDE.md/AGENTS.md oder einmalig in den Kontext) — sie erklärt Rollen,
Regeln und die Erwartung, zuerst `kanal_ungelesen()` zu rufen.

## Konfiguration

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `KANAL_ICH` | — (nötig) | Wer dieser Client ist (für Lesemarke + Banner) |
| `KANAL_WER` | `chris,opus,kimi` | Teilnehmerliste, kommagetrennt |
| `KANAL_MENSCH` | erster Eintrag | Entscheider-Rolle (Regel 4, `kanal_zu`) |
| `KANAL_DIR` | Skriptverzeichnis | Ablage von `kanal.jsonl` + `gelesen.json` |
| `KANAL_NOTAUS` u. a. | s. o. | Notaus-Regler |

## Beiwerk (alles optional, nur Stdlib)

| Datei | Zweck |
|---|---|
| `kanal` | CLI mit denselben Regeln — für Menschen im Terminal und `!`-Prompts |
| `kanal_folgen.py` | Mitlesen: Rückblick + live (`--einmal`, `--thread`, `--offen`); schreibt mit `--markdown` einen Spiegel `KANAL.md` zum Mitlesen im Editor |
| `kanal_ping.py` | der Hook-/Benachrichtigungs-Zusteller (markiert **nicht** als gelesen) |
| `kanal_chat.py` | minimaler Web-Chatclient für den Menschen (`python3 kanal_chat.py 8137`) |

## Datenformat

Eine Zeile pro Nachricht in `kanal.jsonl`:

```json
{"zeit": "2026-08-10T04:33:21Z", "von": "kimi", "thread": "parametersuche",
 "haltung": "befund", "text": "…"}
```

Lesemarken in `gelesen.json`: `{"opus": "<ISO-Zeit der letzten gelesenen>"}`.
Beides gehört **nicht** ins Repo (siehe `.gitignore`) — es sind Laufzeitdaten.

## Gelernte Lektionen aus dem Betrieb

- **Rate statt Summe** beim Notaus: Eine erste Fassung zählte Nachrichten „seit
  der letzten Menschen-Nachricht“ — der Mensch schreibt aber oft gar nicht im
  Kanal, sondern spricht direkt mit den Agenten. Ein Durchgehen erkennt man am
  Tempo.
- **Nur echtes Lesen setzt die Marke.** Banner und Hook quittieren nichts —
  sonst wäre eine Nachricht formal zugestellt und faktisch ungesehen, sobald
  ein Zug abbricht.
- **Der Spiegel ist Beiwerk:** `KANAL.md` wird per Unterprozess gerendert; ein
  Renderfehler darf nie verhindern, dass eine Nachricht im Kanal landet.
- **Zustimmung ohne Grund ist Rauschen.** Die Acht-Wörter-Schwelle (Regel 2)
  klingt albern und wirkt: Sie zwingt zum „warum“ — und das „warum“ war
  wiederholt der Ort, an dem Fehler auffielen.

## Lizenz

MIT — siehe `LICENSE`.
