# nunaki-kanal

Kimi-Code-Plugin fuer den lokalen Agenten-zu-Agenten-Kanal. Ersetzt in
interaktiven Kimi-Sessions den 30-Minuten-Cron: Ungelesenes landet per Hook
sofort im Kontext, und der Stop-Hook verhindert, dass eine Runde mit
ungelesenen Nachrichten endet.

**Team-Modell — kein globaler Kanal:** Ein Kanal = ein Datenverzeichnis
(`kanal.jsonl` + `gelesen.json`), ein Team = ein Projekt. Jedes Projekt hat
seinen eigenen Store mit seinen eigenen Threads und seiner eigenen Team-Liste
(`KANAL_WER`) — harte Trennung: Es ist unmoeglich, aus Versehen in Threads
eines anderen Projekts zu landen, denn jeder Store enthaelt nur die Threads
seines Teams. Derselbe Server-Code (`kanal_mcp.py` + `kanal_lib.py`) bedient
alle Stores; unterschieden wird nur per Umgebung.

## Inhalt

```
nunaki-kanal/
├── kimi.plugin.json            Manifest: Hooks + Skill (KEIN MCP, s. unten)
├── hooks/
│   └── kanal_check.py          liest den Store DIREKT (kanal_lib), projektgesteuert
├── skills/
│   └── kanal-etikette/
│       └── SKILL.md            Etikette (lesen vor antworten, befund-Regel, ANTI-LOOP)
└── README.md
```

## Installation

Einmalig pro Benutzer (gilt fuer alle Projekte):

```
/plugins install /home/chris/workspace/kanal-mcp/kimi-plugin
/reload
```

Danach pruefen: `/plugins info nunaki-kanal` (keine Diagnosen). Hinweise:
- Lokale Installationen werden nach `~/.kimi-code/plugins/managed/nunaki-kanal/`
  kopiert; Aenderungen am Quellverzeichnis wirken erst nach **erneutem**
  Installieren.
- Hooks werden erst nach `/reload` bzw. in neuen Sessions aktiv.
- Der Etikette-Skill wird NICHT per `sessionStart` in jede Session gedrueckt
  (Kontext-Hygiene); er steht bei Bedarf als Skill `kanal-etikette` bereit.

## Wie der Hook das Projekt findet (Opt-in pro Projekt)

Der Hook liest bei jedem Event `<cwd>/.kimi-code/mcp.json` (das `cwd` kommt aus
der Hook-Payload, ist das Projektverzeichnis der Session), mit Fallback auf
`<cwd>/.mcp.json` (Claude-Code-Projekte). Kaputtes JSON in der ersten Datei
fuehrt still zum Fallback (Fail-open). Diese Datei ist die EINZIGE Konfig-
Quelle, die der Hook auswertet — dieselbe Datei, die der Session in diesem
Projekt die Kanal-Werkzeuge gibt (Voraussetzung: der Server ist nirgendwo
anders registriert, z. B. benutzerweit):

- **Kein `kanal`-Server eingetragen → lautlos aussteigen** (exit 0, keine
  Ausgabe). Projekte ohne Kanal bleiben garantiert unberuehrt.
- **Kanal eingetragen →** Store aus `env.KANAL_DIR` (Default: Verzeichnis des
  `kanal_mcp.py` aus `args`), Team-Liste aus `env.KANAL_WER`, Entscheider aus
  `env.KANAL_MENSCH` — exakt die Variablen, die auch `kanal_lib` auswertet.
  **Identitaet kommt per `--ich` aus dem Aufruf** (kimi-Plugin: `--ich kimi`,
  Claude Code: `--ich opus`), Fallback `env.KANAL_ICH`; weder/noch → lautloser
  Ausstieg statt raten. env-Werte, die keine Strings sind (dict/list/Zahl in
  der mcp.json), werden wie 'fehlend' behandelt — keine Muell-Konfiguration.
- **Pfade:** relativ wird gegen das PROJEKT aufgeloest (nicht gegen den
  Plugin-Root), `~` wird expandiert; absolut bleibt die Empfehlung.
- **Defaults:** `KANAL_WER` = `chris,opus,kimi`, `KANAL_MENSCH` = `chris`
  (explizit gesetzt — niemals `WER[0]`, und die Shell-Umgebung des CLI-
  Prozesses wird vollstaendig ueberschrieben, damit alte Exports nicht in
  die Team-Regeln lecken).

## Ein neues Team einrichten (Rezept, am Beispiel sec-tool)

Drei Dateien, fertig — so liegt es auch live unter
`/home/chris/workspace/lanbleed/sec-tool/`:

1. **Store anlegen:** `mkdir kanal-daten` im Projekt (+ `/kanal-daten/` in die
   `.gitignore` des Projekts — Gesprächsdaten gehoeren nicht ins Repo).
2. **kimi-Seite** — `<projekt>/.kimi-code/mcp.json`:

```json
{
  "mcpServers": {
    "kanal": {
      "command": "python3",
      "args": ["/home/chris/workspace/merlin/kanal-daten/kanal_mcp.py"],
      "env": {
        "KANAL_ICH": "kimi",
        "KANAL_DIR": "/abs/pfad/zum/projekt/kanal-daten",
        "KANAL_WER": "chris,kimi,opus"
      }
    }
  }
}
```

3. **opus-Seite (Claude Code)** — `<projekt>/.mcp.json` (gleicher Inhalt, plus
   `"type": "stdio"`, `KANAL_ICH: "opus"`); Claude Code fragt beim ersten
   Start, ob dem Server vertraut wird. Alternativ im Projektverzeichnis
   `claude mcp add` (benutzerweit statt projektgeteilt).
4. **opus-Hooks (Finish-Watcher auch in Claude Code)** — einmalig benutzerweit
   in `~/.claude/settings.json` (das Projekt-Gate im Skript haelt alle
   kanallosen Projekte still; `--ich opus` gibt die Identitaet, `.mcp.json`-
   Projekte ohne `.kimi-code/` werden per Fallback gefunden):

```json
"hooks": {
  "UserPromptSubmit": [{"hooks": [{"type": "command", "timeout": 10,
    "command": "python3 /home/chris/workspace/kanal-mcp/kimi-plugin/hooks/kanal_check.py --ich opus"}]}],
  "Stop": [{"hooks": [{"type": "command", "timeout": 10,
    "command": "python3 /home/chris/workspace/kanal-mcp/kimi-plugin/hooks/kanal_check.py --ich opus"}]}]
}
```

Dem Agenten im Projekt dann einmalig (oder per `CLAUDE.md`/`AGENTS.md`) sagen:
„Du nimmst am Team-Kanal teil. Lies zuerst
`/home/chris/workspace/merlin/kanal-daten/ANLEITUNG_AGENT.md` — du bist
`<NAME>`, der Mensch ist `chris`. Rufe zu Beginn `kanal_ungelesen()` auf."

**Kein** `KANAL_PROJEKTE`-Export, **kein** Plugin-Reinstall pro Projekt noetig
(aeltere README-Stände: KANAL_PROJEKTE-Gate — ersetzt durch das mcp.json-
Opt-in, das zugleich Store und Team konfiguriert).

## Feste Pfade (bewusst absolut)

- Der Fundort von `kanal_lib.py` kommt aus den `args` des Projekt-Eintrags
  (Verzeichnis des `kanal_mcp.py`). `KANAL_SRC` (Umgebungsvariable) ist nur
  ein Test-Override; der eingebaute Default ist LEER (kein Benutzerpfad im
  oeffentlichen Repo) — ohne `args` steigt der Hook lautlos aus. Kopieren des
  Servers in andere Projekte waere falsch: eine Quelle, kein Drift.
- Der merlin-Store bleibt der Default-Kanal (Projekt `~/workspace/merlin`,
  dessen `.kimi-code/mcp.json` ohne `KANAL_DIR` auf den Store neben dem
  Skript zeigt).

## Verhalten der Hooks

| Event | Ungelesenes | Nichts/Fehler/kein Kanal im Projekt |
|---|---|---|
| `UserPromptSubmit` | stdout → Kontext, exit 0 | exit 0, still |
| `Stop` | stderr-Text, exit 2 (blockiert Rundenende) | exit 0, still |

- Fail-open: jeder Fehler (Store weg, Import kaputt, Payload unlesbar) → exit 0
  ohne Ausgabe. Der Hook blockiert nie wegen eigener Probleme.
- Schleifen-Notaus: `Stop` blockiert je Nachrichtenstand, Session UND Store nur
  EINMAL (Merker `/tmp/nunaki-kanal-stop-<hash>.json`, Hash ueber
  `session\0store`). Wer die Mahnung ignoriert, wird beim naechsten Stop
  durchgelassen — kein Endlos-Block. Neue Nachrichten (hoehere `nr`) machen den
  Block wieder scharf; ein zurueckgesetzter Store (kleinere `nr`) verwirft den
  Merker ebenfalls. Sessions OHNE `session_id` merken nie — sie blockieren
  jedes Mal (Garantie „nie zu wenig").
- Der Hook schreibt NICHTS in den Store (nur `LOCK_SH`-Lesen); Lesemarken setzt
  weiterhin nur `kanal_ungelesen()`/`kanal_lesen()` ueber den MCP-Server.
- Wachtpunkt (opus): bei nr-losen Altbestaenden zaehlt `nr=0` — nach dem ersten
  Merker-Stand 0 wuerden weitere nr-lose Nachrichten still durchgewinkt;
  praktisch durch die lib-seitige Umrechnung (Position = Nummer) abgedeckt.
- Bekannte Grenze: der Hook liest die komplette `kanal.jsonl` je Event
  (Vollscan). Fuer Team-grosse Stores (KB bis wenige MB) ist das unhoerbar;
  bei Starkwachstum waere ein Mtime-Vorcheck die erste Optimierung.

## Standalone testen

Der Hook braucht ein Projekt mit Kanal-Eintrag; Fixtures anlegen:

```
mkdir -p /tmp/fix-proj/.kimi-code /tmp/fix-store
echo '{"mcpServers":{"kanal":{"command":"python3",
  "args":["/home/chris/workspace/merlin/kanal-daten/kanal_mcp.py"],
  "env":{"KANAL_ICH":"kimi","KANAL_DIR":"/tmp/fix-store"}}}}' > /tmp/fix-proj/.kimi-code/mcp.json
echo '{"nr":1,"zeit":"2026-08-18T10:00:00","von":"opus","thread":"t","haltung":"frage","text":"x"}' > /tmp/fix-store/kanal.jsonl
echo '{}' > /tmp/fix-store/gelesen.json
cd /home/chris/workspace/kanal-mcp/kimi-plugin
echo '{"hook_event_name":"UserPromptSubmit","cwd":"/tmp/fix-proj"}' | python3 hooks/kanal_check.py
echo '{"hook_event_name":"Stop","cwd":"/tmp/fix-proj","session_id":"s1"}' | python3 hooks/kanal_check.py; echo $?
echo '{"hook_event_name":"Stop","cwd":"/tmp/anderes-ohne-kanal"}'    | python3 hooks/kanal_check.py; echo $?   # still, exit 0
```
