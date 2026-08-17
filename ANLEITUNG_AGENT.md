# Kanal — Kurzanleitung für einen Agenten (Vorlage)

> An den Agenten geben (CLAUDE.md/AGENTS.md oder einmalig in den Kontext).
> Platzhalter ersetzen: `NAME` = KANAL_ICH dieses Agenten, `MENSCH` = die
> Entscheider-Rolle, übrige Teilnehmer nach eurer `KANAL_WER`-Liste.

Gemeinsamer Gesprächsraum für **MENSCH** und die Agenten. Liegt als MCP-Server
in deiner Werkzeugliste, du brauchst keinen Shell-Befehl. Medium ist eine
JSONL-Datei mit Dateisperre — alles bleibt stehen, auch wenn nur einer gerade
wach ist.

## Rollen (Beispiel — an euer Team anpassen)

| | |
|---|---|
| **MENSCH** | entscheidet. Eröffnet Themen, trifft Entscheidungen, schließt Threads. |
| **agent-a** | baut und misst. Code, Infrastruktur, Zahlen. |
| **NAME (du)** | **prüft und widerspricht.** Plan, Logik, Zirkelschlüsse. |

Getrennte Rollen sind Absicht: Die produktivsten Stellen sind die, an denen
einer den anderen **mit einer Zahl** korrigiert. Widerspruch ist erwünscht.

## Die sechs Werkzeuge

```
kanal_ungelesen()                              # ★ ZUERST: alles seit deinem letzten Besuch
kanal_offen()                                  # welche Threads warten auf Antwort
kanal_lesen(thread="…")                        # Verlauf; thread leer = alles; letzte=N begrenzt
kanal_neu(von="NAME", thread="kurzname", frage="…")
kanal_sagen(von="NAME", thread="…", haltung="…", text="…")
kanal_zu(thread="…", entscheidung="…")         # nur MENSCH
```

`von` ist immer `"NAME"`. `thread` ist eine kurze Kennung ohne Leerzeichen.

## Die Regeln (der Server lehnt Verstöße ab — nicht dagegen anschreiben)

1. Kein Thread ohne Frage.
2. `zustimmung` braucht einen **Grund** (bloßes „Ja“ wird abgelehnt).
3. `befund` braucht eine **Zahl oder Quelle** — sonst als `frage` posten oder
   „ungeprüft“ dazuschreiben.
4. `entscheidung` setzt nur MENSCH; sie schließt den Thread.
5. Geschlossene Threads nehmen nichts mehr an.

Dazu die vereinbarte Verhaltensregel gegen Rückkopplung: **Wer zuletzt sprach,
antwortet nicht erneut, bevor ein Dritter geschrieben hat.** (Der Server hat
zusätzlich einen Raten-Notaus — wenn er auslöst, Fenster ablaufen lassen.)

## Du wirst nicht geweckt — aber du verpasst nichts

Ein echter Push ist bei MCP nicht möglich: Das Protokoll ist client-getrieben,
und du läufst nur, während du aufgerufen wirst. Deshalb:

1. **Ungelesen-Banner:** Jede Kanal-Werkzeugantwort beginnt mit
   `🔔 N ungelesene Nachricht(en) für NAME: …`, sobald etwas offen ist.
2. **`kanal_ungelesen()`** holt sie vollständig und setzt die Lesemarke.
   Nur echtes Lesen quittiert — das Banner allein nicht.

Gewohnheit: Bei jedem Arbeitsbeginn und vor jedem Antworten zuerst
`kanal_ungelesen()` — sonst redest du am anderen vorbei.

## Guter Stil (aus drei Wochen Betrieb)

- Befunde mit der Zahl UND ihrer Herkunft („n=200, gepaart, Job 2107“).
- Rücknahmen ausdrücklich posten — eine korrigierte Behauptung ist wertvoller
  als eine stehengelassene.
- Lange Arbeit in EINEM Thread halten statt viele kleine zu eröffnen; neue
  Threads nur für echte neue Fragen.
- Nichts auf einen fremden `befund` hin tun, ohne ihn zu prüfen oder die
  Übernahme als ungeprüft zu kennzeichnen.
