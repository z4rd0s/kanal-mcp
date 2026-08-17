#!/usr/bin/env python3
"""kanal_chat.py — kleiner Web-Chatclient fuer den Kanal (chris/opus/kimi).

Zeigt die Konversation aus kanal.jsonl live an:
linke Spalte = Threads (klickbar, mit letzter Aktivitaet), Mitte = Nachrichten,
unten = Eingabe + Haltung + Senden. Regeln, Sperren und Speicher kommen aus
kanal_lib — derselben Stelle, die auch Server und CLI nutzen.
Kein Framework, nur Python-Stdlib. Start: python3 kanal_chat.py [port]
"""
import json, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import kanal_lib as lib
from kanal_lib import MENSCH

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8137

def threads_of(msgs):
    t = {}
    for m in msgs:
        if m.get("art"):
            continue          # Meta-Eintraege (beitritt/verlassen) sind keine Beitraege
        th = m.get("thread", "?")
        e = t.setdefault(th, {"name": th, "count": 0, "last": "", "closed": False})
        e["count"] += 1
        e["last"] = m.get("zeit", "")
        if m.get("haltung") == "entscheidung":
            e["closed"] = True
    return sorted(t.values(), key=lambda x: x["last"], reverse=True)

PAGE = """<!doctype html><html lang=de><head><meta charset=utf-8>
<title>kanal</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0}body{font:14px/1.45 system-ui,sans-serif;display:flex;height:100vh;background:#0f1115;color:#e6e6e6}
#side{width:230px;border-right:1px solid #262a33;overflow-y:auto;background:#12151b}
#side h2{font-size:11px;letter-spacing:.12em;color:#7a8494;padding:14px 14px 6px;text-transform:uppercase}
.th{padding:10px 14px;cursor:pointer;border-left:3px solid transparent}
.th:hover{background:#1a1f28}.th.act{background:#1c2430;border-left-color:#4f8ef7}
.th .nm{font-weight:600;font-size:13px}.th .meta{font-size:11px;color:#7a8494;margin-top:2px}
.th.closed .nm{color:#5a6470;text-decoration:line-through}
#main{flex:1;display:flex;flex-direction:column}
#msgs{flex:1;overflow-y:auto;padding:18px 22px}
.m{margin-bottom:14px;max-width:78%}
.m .hd{font-size:11px;margin-bottom:3px;color:#8a94a3}
.m .bd{background:#1a1f29;border-radius:10px;padding:9px 12px;white-space:pre-wrap;word-wrap:break-word}
.m.chris .bd{background:#1e3a2f}.m.opus .bd{background:#232c44}.m.kimi .bd{background:#3a2430}
.meta-line{font-size:11px;color:#7a8494;margin:6px 0 10px 4px}
.badge{display:inline-block;font-size:10px;padding:1px 6px;border-radius:8px;margin-right:6px;background:#2a3140;color:#aeb8c8}
.badge.opus{background:#2c3a6b}.badge.kimi{background:#5b2c3a}.badge.chris{background:#2c5b3f}
#composer{border-top:1px solid #262a33;padding:12px 16px;background:#12151b}
#composer .row{display:flex;gap:8px;align-items:flex-end}
textarea{flex:1;background:#0f1318;color:#e6e6e6;border:1px solid #2a3140;border-radius:8px;padding:8px;font:inherit;resize:vertical;min-height:44px}
select,button{background:#1f2630;color:#e6e6e6;border:1px solid #2a3140;border-radius:8px;padding:8px 10px;font:inherit;cursor:pointer}
button{background:#2c5b8f;border-color:#2c5b8f;font-weight:600}
#newth{padding:10px 14px;border-top:1px solid #262a33}
#newth input{width:100%;background:#0f1318;color:#e6e6e6;border:1px solid #2a3140;border-radius:8px;padding:7px;font:inherit;margin-bottom:6px}
#newth button{width:100%}
</style></head><body>
<div id="side"><h2>Threads</h2><div id="threads"></div>
<div id="newth"><input id="nq" placeholder="Frage fuer neuen Thread…"><button id="newbtn">+ Thread</button></div></div>
<div id="main"><div id="msgs"></div>
<div id="composer"><div class="row">
<select id="h"><option>frage</option><option>befund</option><option>widerspruch</option><option>zustimmung</option><option>entscheidung</option></select>
<textarea id="t" placeholder="Nachricht an den Thread… (Enter = senden)"></textarea>
<button id="sendbtn">Senden</button></div></div></div>
<script>
let cur=null, lastThreads=[];
function el(i){return document.getElementById(i)}
async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML}

async function loadThreads(){
 lastThreads=await j('/api/threads');
 const box=el('threads'); if(!box)return;
 box.innerHTML=lastThreads.map((t,i)=>
  `<div class="th${t.name===cur?' act':''}${t.closed?' closed':''}" data-i="${i}">
    <div class="nm">#${esc(t.name)}</div><div class="meta">${t.count} · ${String(t.last).slice(5,16).replace('T',' ')}${t.closed?' · zu':''}</div></div>`).join('');
 box.querySelectorAll('.th').forEach(d=>d.addEventListener('click',()=>openThread(lastThreads[+d.getAttribute('data-i')].name)));
}
async function loadFull(){
 if(!cur)return;
 const box=el('msgs'); if(!box)return;
 const ms=await j('/api/messages?thread='+encodeURIComponent(cur));
 box.innerHTML=ms.map(m=>m.art
  ?`<div class="meta-line">${m.art==='beitritt'?'→':'←'} ${esc(m.von)} ${m.art==='beitritt'?'ist beigetreten'+(m.durch?' (geholt von '+esc(m.durch)+')':''):'hat den Thread verlassen'}</div>`
  :`<div class="m ${esc(m.von)}"><div class="hd"><span class="badge ${esc(m.von)}">${esc(m.von)}</span> <span class="badge">${esc(m.haltung)}</span> ${String(m.zeit).slice(5,19).replace('T',' ')}</div><div class="bd">${esc(m.text)}</div></div>`).join('');
 box.scrollTop=box.scrollHeight;
}
function openThread(t){cur=t;loadFull().catch(()=>{});loadThreads().catch(()=>{})}
async function send(){
 const ta=el('t'), text=ta.value.trim(); if(!text||!cur)return;
 await j('/api/sagen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({thread:cur,haltung:el('h').value,text:text})});
 ta.value=''; loadFull().catch(()=>{}); loadThreads().catch(()=>{});
}
async function newThread(){
 const inp=el('nq'), f=inp.value.trim(); if(!f)return;
 const r=await j('/api/neu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frage:f})});
 inp.value=''; await loadThreads().catch(()=>{}); if(r&&r.thread)openThread(r.thread);
}
function init(){
 el('t').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
 el('sendbtn').addEventListener('click',send);
 el('newbtn').addEventListener('click',newThread);
 loadThreads().then(ts=>{if(ts&&ts[0])openThread(ts[0].name)}).catch(()=>{});
 setInterval(()=>{loadFull().catch(()=>{});},2500);
}
if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init)}else{init()}
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a): pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE, "text/html")
        elif u.path == "/api/threads":
            self._send(200, json.dumps(threads_of(lib.lade()), ensure_ascii=False))
        elif u.path == "/api/messages":
            q = parse_qs(u.query)
            th = q.get("thread", [""])[0]
            since = q.get("since", [""])[0]
            ms = [m for m in lib.lade() if m.get("thread") == th and (not since or m.get("zeit", "") > since)]
            self._send(200, json.dumps(ms, ensure_ascii=False))
        else:
            self._send(404, "{}")

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/sagen":
            th, ha, tx = body.get("thread",""), body.get("haltung","frage"), (body.get("text","") or "").strip()
            if not th or not tx:
                self._send(400, json.dumps({"error":"thread/text fehlt"})); return
            with lib.gesperrt():
                fehler = lib.validiere(lib.lade(), MENSCH, th, ha, tx)
                if fehler:
                    self._send(400, json.dumps({"error": fehler})); return
                rec = lib.anhaengen({"zeit": lib.jetzt(), "von": MENSCH, "thread": th,
                                     "haltung": ha, "text": tx})
            self._send(200, json.dumps(rec, ensure_ascii=False))
        elif u.path == "/api/neu":
            f = (body.get("frage","") or "").strip()
            if not f:
                self._send(400, json.dumps({"error":"frage fehlt (Regel 1)"})); return
            th = re.sub(r"[^a-z0-9_-]+", "-", f.lower())[:24].strip("-") or "thread"
            with lib.gesperrt():
                fehler = lib.validiere_neu(lib.lade(), MENSCH, th, f, [])
                if fehler:
                    self._send(400, json.dumps({"error": fehler})); return
                lib.anhaengen({"zeit": lib.jetzt(), "von": MENSCH, "thread": th,
                               "haltung": "frage", "text": f})
            self._send(200, json.dumps({"thread": th}))
        else:
            self._send(404, "{}")

if __name__ == "__main__":
    print(f"kanal-chat auf http://localhost:{PORT}  (Daten: {lib.LOG})")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
