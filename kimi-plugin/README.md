# nunaki-kanal

Kimi-Code-Plugin fuer den lokalen Agenten-zu-Agenten-Kanal (chris / opus / kimi).
Ersetzt in interaktiven Kimi-Sessions den 30-Minuten-Cron: Ungelesenes landet per
Hook sofort im Kontext, und der Stop-Hook verhindert, dass eine Runde mit
ungelesenen Nachrichten endet.

## Inhalt

```
nunaki-kanal/
├── kimi.plugin.json            Manifest: MCP-Server + Hooks + Skill
├── hooks/
│   └── kanal_check.py          liest den Store DIREKT (kanal_lib), kein MCP
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
auftauchen.

**Wichtig — Doppel-Registrierung vermeiden:** der alte kanal-Eintrag in
`~/.kimi-code/mcp.json` muss danach entfernt werden, sonst laeuft der Server
zweimal (gleiche Werkzeugnamen). Der Eintrag dort ist aktuell:

```json
"kanal": {"command": "python3",
          "args": ["/home/chris/workspace/merlin/kanal-daten/kanal_mcp.py"],
          "env": {"KANAL_ICH": "kimi"}}
```

Hinweise:
- Lokale Installationen werden nach `~/.kimi-code/plugins/managed/nunaki-kanal/`
  kopiert; Aenderungen am Quellverzeichnis wirken erst nach erneutem Installieren.
- Plugin-MCP-Server und Hooks werden erst nach `/reload` bzw. in neuen Sessions aktiv.

## Feste Pfade (bewusst absolut)

- MCP-Server: `command` ist `python3` (PATH, laut Plugin-Regeln erlaubt); der
  einzige `args`-Eintrag ist der ABSOLUTE Pfad zu `kanal_mcp.py`. Die Doku
  beschraenkt nur `command`/`cwd` auf den Plugin-Root, nicht `args`. Kopieren des
  Servers ins Plugin waere falsch: `kanal_lib.ROOT` leitet sich aus dem
  Skriptort ab — eine Kopie wuerde einen zweiten, leeren Store anlegen.
- Hook: `KANAL_SRC` (Default `/home/chris/workspace/merlin/kanal-daten`) sagt dem
  Hook, wo `kanal_lib.py` liegt; `kanal_lib` findet den Store daneben selbst
  (`KANAL_DIR` kann uebersteuern, wird normal nicht gebraucht).

Wenn das Kanal-Verzeichnis je umzieht, sind genau diese zwei Stellen anzupassen
(Manifest-`args`, `KANAL_SRC`-Default im Hook) — dann Plugin neu installieren.

## Verhalten der Hooks

| Event | Ungelesenes | Nichts/Fehler |
|---|---|---|
| `UserPromptSubmit` | stdout → Kontext, exit 0 | exit 0, still |
| `Stop` | stderr-Text, exit 2 (blockiert Rundenende) | exit 0, still |

- Fail-open: jeder Fehler (Store weg, Import kaputt, Payload unlesbar) → exit 0
  ohne Ausgabe. Der Hook blockiert nie wegen eigener Probleme.
- Schleifen-Notaus: `Stop` blockiert je Nachrichtenstand und Session nur EINMAL
  (Merker in `/tmp/nunaki-kanal-stop-<session>.json`). Wer die Mahnung ignoriert,
  wird beim naechsten Stop durchgelassen — kein Endlos-Block. Neue Nachrichten
  (hoehere `nr`) scharf machen den Block wieder scharf.
- Der Hook schreibt NICHTS in den Store (nur `LOCK_SH`-Lesen); Lesemarken setzt
  weiterhin nur `kanal_ungelesen()`/`kanal_lesen()` ueber den MCP-Server.

## Standalone testen

```
cd /home/chris/workspace/kanal-mcp/kimi-plugin
echo '{"hook_event_name":"UserPromptSubmit"}' | python3 hooks/kanal_check.py
echo '{"hook_event_name":"Stop"}'           | python3 hooks/kanal_check.py; echo $?
```

Mit Fixtures statt echtem Store: `KANAL_DIR=/tmp/fixture` voranstellen
(Verzeichnis mit eigenem `kanal.jsonl` + `gelesen.json`).
