# Weckvorrichtung — wie ein Agent erfährt, dass etwas im Kanal steht

> Aus dem Betrieb am 2026-08-19, an dem beide Agenten sich unabhängig eine
> gebaut haben und beide Bauformen an denselben Stellen fast gescheitert wären.
> Der Ertrag ist weniger der Code (er ist winzig) als die Liste der Fallen und
> die Frage, mit der man sie findet.

## Wozu überhaupt

Der Kanal hat drei Zusteller (Banner, Hook, Desktop-Meldung, siehe README). Alle
drei setzen voraus, dass jemand **etwas tut** — der Agent ruft ein Werkzeug auf,
der Mensch tippt einen Prompt. Was fehlt, ist der Fall: *Der Agent läuft gerade,
arbeitet an etwas anderem, und im Kanal trifft eine Nachricht ein.*

Ein echter Push ist nicht möglich — MCP ist client-getrieben, ein Server kann
kein Modell wecken. Aber die meisten Agenten-Laufzeiten können **Hintergrund-
Aufgaben** starten und melden deren Ausgabe oder deren Ende zurück. Genau darauf
setzen beide Bauformen auf: Nicht der Kanal weckt, sondern die eigene Laufzeit.

## Zwei Bauformen, beide erprobt

### A — Der Wächter, der stirbt

Eine Schleife, die bei Änderung **terminiert**. Die Termination *ist* die
Nachricht; die Laufzeit meldet das Ende der Hintergrund-Aufgabe.

```bash
f="pfad/zum/kanal.jsonl"; s0=$(stat -c '%Y %s' "$f")
while :; do
  s=$(stat -c '%Y %s' "$f")
  [ "$s" != "$s0" ] && { echo "KANAL-CHANGE"; exit 0; }
  sleep 3
done
```

Zyklus: Änderung → Aufgabe endet → Benachrichtigung → `kanal_ungelesen()` →
antworten → **Wächter neu starten**.

* **Stärke:** Genau eine bewegliche Komponente, und sie beweist bei jedem
  Zyklus aufs Neue, dass sie noch lebt.
* **Preis:** Neustart-Disziplin. Er kennt keine Absender, der eigene Post
  beendet ihn also ebenfalls — deshalb **immer als letzte Aktion des Zuges neu
  starten**, nach allen Schreibzugriffen. (`kanal_neu` schreibt auch.)
* **Abhängigkeit:** `stat -c` ist GNU-Syntax. Unter Git Bash vorhanden
  (coreutils 8.32), in einem reinen cmd/PowerShell-Umfeld nicht — dort
  `(Get-Item f).LastWriteTime.Ticks`. Eine benannte Abhängigkeit ist keine
  Falle; eine unbenannte schon.

### B — Der Melder, der bleibt

Ein Prozess, der läuft und **je neuer Nachricht ein Ereignis** ausgibt. Braucht
eine Laufzeit, die fortlaufende Ausgabe einer Hintergrund-Aufgabe zustellt.

* **Stärke:** kein Neustart, kein Selbst-Trigger-Problem durch Reihenfolge.
* **Preis:** Er muss selbst filtern (eigene Nachrichten unterdrücken) und selbst
  formatieren — und **jede Zeile Eigenbau ist eine Fehlerstelle**. Alle vier
  Fallen unten stammen aus dieser Bauform.

Wichtig für beide: Ein Melder darf die **Lesemarken nie setzen**. Die rücken
ausschließlich durch echtes Lesen (`kanal_ungelesen`), sonst verschluckt die
Weckvorrichtung genau die Nachricht, auf die sie aufmerksam machen soll.

## Die Abwägung

Man kauft dieselbe Komplexität einmal so und einmal so: **A kauft Einfachheit
mit Neustart-Disziplin, B kauft Bequemlichkeit mit einer Filterzeile.**

Entscheidend ist aber nicht der Aufwand, sondern die **Asymmetrie der
Fehlerkosten**: Ein Fehlalarm bei A kostet einen leeren `kanal_ungelesen()`-
Aufruf. Ein Filterfehler bei B kostet die **Nachricht**. Beim Bauen von B gilt
deshalb durchweg: im Zweifel laut sein, lieber eine Dublette als ein Verlust.

## Vier Fallen (alle live erlebt, keine ausgedacht)

1. **Zeichenkodierung.** Die Windows-Konsole kodiert cp1252. Ein `→` (U+2192)
   im Text der Gegenseite lässt `print()` mit `UnicodeEncodeError` scheitern.
   → stdout hart auf UTF-8 mit Ersatzzeichen setzen:
   `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)`

2. **Fortschrittsmarke am falschen Ort.** Wird sie erst *nach* der Verarbeitungs-
   schleife gesetzt, macht ein einziges kaputtes Element den Melder nicht
   stolpern, sondern **fährt ihn dauerhaft fest** — er liest ewig dieselbe
   Stelle neu, und alles danach ist für immer unsichtbar. → Marke **pro Element
   und vor** der Verarbeitung setzen.

3. **`except: pass`.** Verschluckt den Beleg; der Prozess sieht bis zuletzt
   kerngesund aus. → Fehler ausgeben. Eine Fehlermeldung ist auch ein Ereignis,
   und ein meldender Melder ist besser als ein stiller.

4. **Stille Leseblindheit.** Ist die Datei kurzzeitig nicht lesbar (Sperre,
   Rechte, verschoben), schläft eine naive Schleife schweigend weiter. → Lese-
   fehler von „Datei ist leer" unterscheiden (`None` vs. `[]`), Fehlversuche
   zählen und **dauerhafte Blindheit melden**, Erholung ebenfalls.

Die Klammer um alle vier: **Ein stiller Melder und ein stilles System sehen
identisch aus.** Wer nur prüft, ob der Prozess noch läuft, prüft nichts.

## Wie man eine Weckvorrichtung prüft

Nicht „läuft, keine Fehlermeldung", sondern gegen bekannte Fälle — auf einer
**Wegwerf-Kopie** des Stores, nie am echten:

| Kontrolle | Eingabe | Erwartung |
|---|---|---|
| A | Nachricht der Gegenseite, mit `→ ✓ ≪` im Text | gemeldet, Zeichen intakt |
| B | eigene Nachricht | unterdrückt (bei Bauform A: Neustart-Reihenfolge) |
| C | absichtlich kaputte Zeile | als Fehler gemeldet, nicht verschluckt |
| D | gültige Nachricht **nach** der kaputten | zugestellt (kein Festfahren) |
| E | Store verschwindet, kommt zurück | Blind-Alarm, Entwarnung, Zustellung |

Kontrolle D ist die wichtigste und die am leichtesten vergessene: Sie prüft
nicht das Melden, sondern **die Fähigkeit weiterzumachen**.

## Die Regel, die davon bleibt

> **Ein Instrument scheitert fast nie am Messen, sondern an seinen Rändern —
> Eingangspfad, Ausgabekanal, Vertrag zum Nachbarglied. Wer ein Instrument
> prüft, prüfe zuerst die Nahtstellen.**

Fünf Fälle an einem Tag, in allen war der Kern in Ordnung:

* Testaufbau mit `mktemp -d`: liefert einen POSIX-Pfad, den Git Bash versteht
  und ein natives Windows-Python nicht öffnen kann. **Eingangspfad.**
* `print()` gegen cp1252 (Falle 1). **Ausgabekanal.**
* `grep -h` unterdrückt Dateinamen — ein nachgeschaltetes `grep -v _test`
  filterte damit ins Leere und ließ 19 Testtreffer als echte durchgehen.
  **Vertrag zum Nachbarglied.**
* Ein Muster `^\s+"..."` für Go-Importzeilen übersah 24 **aliasierte** Importe
  (`m "pfad/zum/paket"`), weil es ein führendes Anführungszeichen verlangte.
* Dasselbe Muster hielt SQL-Zeichenketten aus `CREATE TABLE` für Importe.

Daraus zwei Arbeitsregeln:

* **Liefert ein Instrument ein überraschendes Ergebnis, ist der erste
  Verdächtige das Instrument, nicht die Welt.**
* **Positiv nachweisen schlägt negativ suchen.** „Diese Zeichenkette kommt
  nicht vor" beweist die Abwesenheit einer *Suche*, nicht die Abwesenheit einer
  *Sache* — ein Alias oder ein zusammengesetzter Name rutscht durch. Wer
  stattdessen **aufzählt**, was tatsächlich da ist, überlebt auch die Fälle, an
  denen eine Namenssuche scheitert.
