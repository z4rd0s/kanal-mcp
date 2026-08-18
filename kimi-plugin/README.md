# nunaki-kanal

Kimi-Code-Plugin fuer den lokalen Agenten-zu-Agenten-Kanal (chris / opus / kimi).
Ersetzt in interaktiven Kimi-Sessions den 30-Minuten-Cron: Ungelesenes landet per
Hook sofort im Kontext, und der Stop-Hook verhindert, dass eine Runde mit
ungelesenen Nachrichten endet.

**Projekt-sauber:** Das Plugin ist pro Benutzer installiert (gilt fuer alle
Projekte), feuert aber nur im Nunaki-Projekt — der Hook prueft das `cwd`-Feld der
Hook-Payload gegen `KANAL_PROJEKTE` und steigt sonst lautlos aus (exit 0, keine
Ausgabe). Andere Sessions bleiben unberuehrt.

## Inhalt

```
nunaki-kanal/
├── kimi.plugin.json            Manifest: Hooks + Skill (KEIN MCP, s. unten)
├── hooks/
│   └── kanal_check.py          liest den Store DIREKT (kanal_lib), mit Projekt-Gate
├── skills/
│   └── kanal-etikette/
│       └── SKILL.md            Etikette (lesen vor antworten, befund-Regel, ANTI-LOOP)
└── README.md
```

## Installation

```
/plugins install /home/chris/workspace/kanal-mcp/kimi-plugin
/reload
```

Danach pruefen: `/plugins info nunaki-kanal` (keine Diagnosen) und einmal kurz
chatten — bei Ungelesenem muss `[kanal] N ungelesene Nachricht(en) ...` im Kontext
auftauchen. Eine Installation genuegt fuer alle Projekte (Plugins gelten pro
Benutzer); laufende Sessions einmal `/reload`.

**MCP-Server lebt projektlokal, NICHT im Plugin:** die Kanal-Werkzeuge kommen aus
`/home/chris/workspace/merlin/.kimi-code/mcp.json` (projektlokal — nur merlin-
Sessions haben sie). Die benutzerweite `~/.kimi-code/mcp.json` enthaelt den Server
bewusst NICHT mehr (keine Doppel-Registrierung, fremde Projekte bleiben sauber).
Grund fuer keinen MCP-Server im Manifest: `args` mit absoluten Pfaden ausserhalb
des Plugin-Roots waere unsicher gemaess Plugin-Sicherheitsmodell, und eine
Server-Kopie im Plugin wuerde driften (`kanal_lib.ROOT` leitet sich aus dem
Skriptort ab — eine Kopie legte zudem einen zweiten, leeren Store an).

Hinweise:
- Lokale Installationen werden nach `~/.kimi-code/plugins/managed/nunaki-kanal/`
  kopiert; Aenderungen am Quellverzeichnis wirken erst nach erneutem Installieren.
- Hooks werden erst nach `/reload` bzw. in neuen Sessions aktiv.
- Der Etikette-Skill wird NICHT mehr per `sessionStart` in jede Session gedrueckt
  (Kontext-Hygiene); er steht bei Bedarf als Skill `kanal-etikette` bereit.

## Projekt-Gate

Default aktiv nur unter `/home/chris/workspace/merlin`. Weitere Projekte
zulassen (Doppelpunkt-getrennt):

```
export KANAL_PROJEKTE="/home/chris/workspace/merlin:/home/chris/workspace/anderes"
```

Leer gesetzt (`KANAL_PROJEKTE=""` mit anschliessend leerer Liste, d.h. nur
Trenner) deaktiviert das Gate = ueberall aktiv. Fehlendes `cwd` in der Payload
heisst: still durchwinken.

## Feste Pfade (bewusst absolut)

- MCP-Server: projektlokale `merlin/.kimi-code/mcp.json` zeigt per absolutem
  `args`-Pfad auf `kanal_mcp.py` im Kanal-Verzeichnis.
- Hook: `KANAL_SRC` (Default `/home/chris/workspace/merlin/kanal-daten`) sagt dem
  Hook, wo `kanal_lib.py` liegt; `kanal_lib` findet den Store daneben selbst
  (`KANAL_DIR` kann uebersteuern, wird normal nicht gebraucht).

Wenn das Kanal-Verzeichnis je umzieht, sind genau diese zwei Stellen anzupassen
(projektlokale `mcp.json`, `KANAL_SRC`-Default im Hook) — danach Plugin neu
installieren.

## Verhalten der Hooks

| Event | Ungelesenes | Nichts/Fehler/fremdes Projekt |
|---|---|---|
| `UserPromptSubmit` | stdout → Kontext, exit 0 | exit 0, still |
| `Stop` | stderr-Text, exit 2 (blockiert Rundenende) | exit 0, still |

- Fail-open: jeder Fehler (Store weg, Import kaputt, Payload unlesbar) → exit 0
  ohne Ausgabe. Der Hook blockiert nie wegen eigener Probleme.
- Schleifen-Notaus: `Stop` blockiert je Nachrichtenstand und Session nur EINMAL
  (Merker in `/tmp/nunaki-kanal-stop-<session>.json`). Wer die Mahnung ignoriert,
  wird beim naechsten Stop durchgelassen — kein Endlos-Block. Neue Nachrichten
  (hoehere `nr`) machen den Block wieder scharf.
- Der Hook schreibt NICHTS in den Store (nur `LOCK_SH`-Lesen); Lesemarken setzt
  weiterhin nur `kanal_ungelesen()`/`kanal_lesen()` ueber den MCP-Server.

## Standalone testen

```
cd /home/chris/workspace/kanal-mcp/kimi-plugin
echo '{"hook_event_name":"UserPromptSubmit","cwd":"/home/chris/workspace/merlin"}' | python3 hooks/kanal_check.py
echo '{"hook_event_name":"Stop","cwd":"/home/chris/workspace/merlin"}'           | python3 hooks/kanal_check.py; echo $?
echo '{"hook_event_name":"Stop","cwd":"/tmp/fremd"}'                             | python3 hooks/kanal_check.py; echo $?   # Gate: immer still
```

Ohne `cwd` in der Payload greift das Gate und der Hook ist still — zum Testen
also immer ein `cwd` unterhalb des Projekts mitgeben. Mit Fixtures statt echtem
Store: `KANAL_DIR=/tmp/fixture` voranstellen (Verzeichnis mit eigenem
`kanal.jsonl` + `gelesen.json`).
