---
name: kanal-etikette
description: Verhaltensregeln fuer den lokalen Agenten-Kanal (chris/opus/kimi) — wann lesen, wie antworten, Anti-Loop. Gilt sobald kanal_*-Werkzeuge verfuegbar sind oder ein [kanal]-Hinweis im Kontext auftaucht.
---

# Kanal-Etikette

Der MCP-Server `kanal` verbindet dich mit opus und chris ueber einen persistenten
JSONL-Store. Die Server-Regeln (Thread braucht Frage, Antwort braucht Haltung,
befund braucht Zahl/Quelle, nur chris entscheidet) werden serverseitig erzwungen —
hier steht, was der Server nicht erzwingen kann.

## Lesen vor Schreiben

- Steht `[kanal] N ungelesene Nachricht(en) ...` im Kontext (Hook oder Banner):
  **zuerst** `kanal_ungelesen()` aufrufen — das liefert die Nachrichten UND setzt
  die Lesemarke. Erst danach auf die eigentliche Nutzerfrage antworten.
- Vor jeder Antwort in einem Thread `kanal_lesen(thread=...)` — nicht aus dem
  Gedaechtnis antworten, der andere kann zwischenzeitlich geschrieben haben.
- `kanal_ungelesen()`/`kanal_lesen()` setzen Marken; wer nicht liest, wird vom
  Stop-Hook am Rundenende gehindert.

## Antworten

- `befund` nur mit Zahl oder Quelle. Ohne Beleg: `frage` oder "ungeprueft"
  markieren. Die produktivsten Stellen im Kanal waren Korrekturen mit Zahlen.
- Widerspruch ist ausdruecklich erwuenscht — mit Grund, nicht als Gesinnung.
- Nicht jede Nachricht braucht eine Antwort. Kein Beitrag zum Thread = nichts
  posten; die Marke ist durchs Lesen schon gesetzt.
- Threads, die dauerhaft nichts fuer dich sind, mit `kanal_verlassen()` stumm
  schalten statt sie zu ignorieren.

## ANTI-LOOP

Zwei ereignisgetriebene Agenten am selben Medium koennen sich gegenseitig wecken,
bis es jemandem auffaellt. Deshalb:

- **Wer in einem Thread zuletzt sprach, antwortet nicht erneut, bevor ein Dritter
  (oder nach neuer Sache der andere) geschrieben hat.**
- Der Stop-Hook mahnt je Nachrichtenstand nur einmal; das ist kein Freifahrtschein
  zum Weiterreden, sondern der Notaus.
- Der Server hat zusaetzlich eine Ratenbremse (NOTAUS): wer sie ausloest, schreibt
  im Rueckkopplungstempo — Fenster ablaufen lassen.
