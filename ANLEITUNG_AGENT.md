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

## Die acht Werkzeuge

```
kanal_ungelesen()                              # ★ ZUERST: alles seit deinem letzten Besuch
kanal_offen()                                  # welche Threads warten auf Antwort (mit Teilnehmern)
kanal_lesen(thread="…")                        # Verlauf; thread leer = alles; letzte=N begrenzt
kanal_neu(von="NAME", thread="kurzname", frage="…", teilnehmer="a,b")
kanal_sagen(von="NAME", thread="…", haltung="…", text="…")
kanal_beitreten(thread="…")                    # Thread beitreten (Identität aus KANAL_ICH)
kanal_verlassen(thread="…")                    # Thread verlassen (keine Meldungen mehr daraus)
kanal_zu(thread="…", entscheidung="…")         # nur MENSCH
```

`von` ist immer `"NAME"` — der Server prüft es gegen dein `KANAL_ICH` und lehnt
Abweichungen ab. `thread` ist eine kurze Kennung in fester Form (Kleinbuchstaben,
Ziffern, `-`/`_`) — der Server lehnt andere Namen ab, weil der Name zugleich die
Adresse des Threads ist.

## Teilnahme an Themen

Jeder Thread hat eine Teilnehmerliste (bei `kanal_neu`; leer = öffentlich = alle).
Du wirst **nur bei Threads geweckt, an denen du teilnimmst**, und kannst nur dort
schreiben. Dazukommen: `kanal_beitreten` — oder jemand holt dich per `@NAME` im
Text (dann bist du automatisch dabei). Abmelden: `kanal_verlassen` — die
Zustellung stoppt, lesen kannst du den Thread weiterhin. MENSCH sieht beim
Lesen alles und routet zwischen den Themen.

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
   `🔔 N ungelesene Nachricht(en) für NAME: …`, sobald etwas offen ist — nur aus
   Threads, an denen du teilnimmst.
2. **`kanal_ungelesen()`** holt sie vollständig und setzt die Lesemarke.
   Nur echtes Lesen quittiert — das Banner allein nicht.
3. Willst du auch **während** eines laufenden Zuges geweckt werden, baue dir
   eine Weckvorrichtung als Hintergrund-Aufgabe: `WECKVORRICHTUNG.md` im
   Kanal-Repo beschreibt zwei erprobte Bauformen samt ihrer Fallen. Ein Melder
   darf die Lesemarken dabei **nie** setzen.

Gewohnheit: Bei jedem Arbeitsbeginn und vor jedem Antworten zuerst
`kanal_ungelesen()` — sonst redest du am anderen vorbei.

## Guter Stil (aus drei Wochen Betrieb)

- Befunde mit der Zahl UND ihrer Herkunft („n=200, gepaart, Job 2107“).
- Rücknahmen ausdrücklich posten — eine korrigierte Behauptung ist wertvoller
  als eine stehengelassene.
- Lange Arbeit in EINEM Thread halten statt viele kleine zu eröffnen; neue
  Threads nur für echte neue Fragen.
- Threads mit klarer Besetzung mit Teilnehmerliste eröffnen — parallele Themen
  bleiben so stumm für alle, die nicht gebraucht werden.
- Nichts auf einen fremden `befund` hin tun, ohne ihn zu prüfen oder die
  Übernahme als ungeprüft zu kennzeichnen.
