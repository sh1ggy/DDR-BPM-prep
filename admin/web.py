"""
The console page: `make admin`. Served on 127.0.0.1 only; the URL printed at
start carries a token that becomes a SameSite=Strict cookie, and every POST
must come from this origin, so no other site can drive it.
"""

import html
import json
import secrets
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import diff, jobs, paths, release, seeds, status, util

TOKEN = secrets.token_urlsafe(24)
e = lambda s: html.escape(str(s if s is not None else ""))

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--line:#e3e1db;--ink:#1d1d1b;--mut:#5f5e5a;--acc:#185fa5;--accbg:#e6f1fb;
--ok:#3b6d11;--okbg:#eaf3de;--warn:#854f0b;--warnbg:#faeeda;--bad:#a32d2d;--badbg:#fcebeb}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1e;--line:#353533;--ink:#ecebe6;--mut:#a9a8a1;
--acc:#85b7eb;--accbg:#0c2a4a;--ok:#97c459;--okbg:#1f330c;--warn:#ef9f27;--warnbg:#3a2604;--bad:#f09595;--badbg:#401414}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,system-ui,sans-serif}
a{color:var(--acc)}nav{display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card)}
nav b{margin-right:12px}nav a{padding:5px 10px;border-radius:6px;color:var(--mut);text-decoration:none}nav a.on{background:var(--bg);color:var(--ink);font-weight:600}
main{max-width:1080px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 12px}h2{font-size:15px;margin:20px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.row{display:flex;gap:10px;align-items:center;padding:8px 0;border-top:1px solid var(--line);flex-wrap:wrap}.row:first-child{border-top:0}
.grow{flex:1;min-width:200px}.mut{color:var(--mut);font-size:13px}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.pill{font-size:12px;padding:2px 8px;border-radius:6px;white-space:nowrap}.ok{background:var(--okbg);color:var(--ok)}
.warn{background:var(--warnbg);color:var(--warn)}.bad{background:var(--badbg);color:var(--bad)}.acc{background:var(--accbg);color:var(--acc)}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;min-height:34px}
button:hover{border-color:var(--mut)}button.primary{background:var(--acc);color:var(--card);border-color:var(--acc)}button.danger{color:var(--bad)}
input,textarea,select{font:inherit;padding:6px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
textarea{width:100%}label{font-weight:600}.steps{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px}.steps span{padding:4px 10px;border-radius:6px;color:var(--mut);font-size:13px}
pre{white-space:pre-wrap;background:var(--bg);border-radius:8px;padding:10px;max-height:420px;overflow:auto;font-size:12px}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);max-width:90vw;padding:10px 14px;border-radius:8px;display:none}
.scroll{overflow-x:auto}
"""

JS = """
const T=document.getElementById('toast');
function toast(m,bad){T.textContent=m;T.className=bad?'bad':'ok';T.style.display='block';setTimeout(()=>T.style.display='none',bad?9000:3000)}
async function act(name,body,then){
  const b=document.activeElement;if(b&&b.tagName==='BUTTON'){b.disabled=true}
  try{const r=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const j=await r.json();if(!r.ok)throw new Error(j.error);toast('Done');
    if(then)then(j.result);else setTimeout(()=>location.reload(),400)}
  catch(err){toast(err.message,true)}finally{if(b)b.disabled=false}}
function val(id){return document.getElementById(id).value}
function checked(cls){return [...document.querySelectorAll('.'+cls+':checked')].map(x=>x.value)}
function job(name,params){act('job',{name,params:params||{}},r=>location.href='/job/'+r.id)}
async function tail(id){let from=0;const pre=document.getElementById('log');
  for(;;){const r=await fetch('/api/joblog?id='+encodeURIComponent(id)+'&from='+from);const j=await r.json();
    if(j.text){pre.textContent+=j.text;from+=new TextEncoder().encode(j.text).length;pre.scrollTop=pre.scrollHeight}
    if(!j.running){document.getElementById('jobstate').textContent=j.status;break}
    await new Promise(r=>setTimeout(r,1000))}}
function filter(q){q=q.toLowerCase();document.querySelectorAll('[data-name]').forEach(r=>r.style.display=r.dataset.name.toLowerCase().includes(q)?'':'none')}
"""

NAV = [("/", "Home"), ("/inbox", "Inbox"), ("/songs", "Songs"), ("/release", "Release"),
       ("/history", "History"), ("/maintenance", "Maintenance"), ("/activity", "Activity")]


def page(title, body, active="/"):
    nav = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{n}</a>' for h, n in NAV)
    running = jobs.current()
    banner = (f'<div class="card warn" style="margin:12px 16px 0">Running: <a href="/job/{e(running["id"])}">'
              f'{e(running["label"])}</a></div>') if running else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{e(title)} · Release console</title>'
            f'<style>{CSS}</style></head><body><nav><b>Release console</b>{nav}</nav>{banner}'
            f'<main>{body}</main><div id="toast" role="status"></div><script>{JS}</script></body></html>')


def pill(text, kind="acc"):
    return f'<span class="pill {kind}">{e(text)}</span>'


def short(sha, n=7):
    return e((sha or "")[:n])


# ---------------------------------------------------------------- pages

def home(q):
    s = release.state()
    rec = s["live_record"] or {}
    live = (f'<div class="mut">Live on every app</div><div class="mono" style="font-size:18px">{e(s["live_id"])}</div>'
            f'<div class="mut">{e(rec.get("title", "No release record yet"))}</div>'
            + (pill("Confirmed", "ok") if s["confirmed"] else pill("Not confirmed", "warn")))
    stg = (f'<div class="mut">Staging host</div><div class="mono" style="font-size:18px">{e(s["staging_id"])}</div>'
           f'<div class="mut">{e((s["draft"] or {}).get("title") or "No release in progress")}</div>'
           + (pill(s["stage"].capitalize()) if s["stage"] else pill("Idle", "acc")))
    needs = []
    if s["unreleased_commit"]:
        needs.append(("bad", "Master has content that wasn't released through the console",
                      f'Commit {short(s["unreleased_commit"])}. Once CI enforces releases it won\'t publish.', "/history", "History"))
    mr = s["master_run"]
    if mr and mr.get("conclusion") not in (None, "success"):
        needs.append(("bad", "Last production run failed", "Nothing changed for players.", mr["url"], "Open run"))
    if s["stage"]:
        needs.append(("acc", f'Release waiting: {s["stage"]}', (s["draft"] or {}).get("title", ""), "/release", "Open"))
    ib = status.inbox()
    if ib["no_simfile"]:
        needs.append(("acc", f'{len(ib["no_simfile"])} songs in the game with no simfile', "From Konami's song list", "/inbox", "Inbox"))
    if ib["built_not_live"] or ib["changed"]:
        needs.append(("acc", f'{len(ib["built_not_live"])} built songs not live, {len(ib["changed"])} built songs that differ from live',
                      "Draft a release to ship them", "/inbox", "Inbox"))
    need_html = "".join(f'<div class="row"><span class="pill {k}">●</span><div class="grow">{e(t)}<div class="mut">{e(d)}</div></div>'
                        f'<a href="{e(h)}">{e(b)}</a></div>' for k, t, d, h, b in needs) or '<div class="mut">Nothing waiting</div>'
    ready = "".join(
        f'<div class="row">{pill("OK", "ok") if r["ok"] else pill("Check", "warn")}<div class="grow">{e(r["name"])}'
        f'<div class="mut">{e(r["detail"])}</div></div>{_fix(r)}</div>' for r in status.readiness())
    act_html = "".join(f'<div class="row"><span class="mono mut">{e(a["at"][5:16])}</span><div class="grow">{e(a["action"])} '
                       f'<span class="mut">{e(_brief(a))}</span></div></div>' for a in util.activity(8))
    return page("Home", f'<div class="grid"><div class="card">{live}</div><div class="card">{stg}</div></div>'
                f'<h2>Needs you</h2><div class="card">{need_html}</div><h2>Readiness</h2><div class="card">{ready}</div>'
                f'<h2>Recent activity</h2><div class="card">{act_html or "<div class=mut>None yet</div>"}</div>')


def _fix(r):
    f = r.get("fix")
    if r["ok"] or not f:
        return ""
    if f == "cookie":
        return '<a href="/maintenance#cookie">Update</a>'
    return f'<button onclick="job(\'{f}\')">Run</button>'


def _brief(a):
    return " · ".join(str(v) for k, v in a.items() if k not in ("at", "action") and v not in (None, "", [], {}))[:140]


def inbox_page(q):
    ib = status.inbox()
    ns = "".join(f'<div class="row"><div class="grow">{e(r["title"])}<div class="mut">Zenius {e(r.get("zenius_id") or "unknown")}</div></div>'
                 f'<label for="z{i}" class="mut">Simfile ID</label><input id="z{i}" size="7" value="{e(r.get("zenius_id") or "")}">'
                 f'<input id="v{i}" size="6" value="WORLD" aria-label="Version folder">'
                 f'<button onclick="act(\'add_simfile\',{{simfile_id:val(\'z{i}\'),version:val(\'v{i}\'),title:{e(json.dumps(r["title"]))}}},r=>location.href=\'/job/\'+r.id)">Scrape</button></div>'
                 for i, r in enumerate(ib["no_simfile"]))
    built = "".join(f'<div class="row"><input type="checkbox" class="pick" value="{e(n)}" aria-label="Pick {e(n)}">'
                    f'<div class="grow"><a href="/song/{urllib.parse.quote(n)}">{e(n)}</a><div class="mut">Built, not live</div></div>'
                    f'<button onclick="act(\'exclude\',{{song:{e(json.dumps(n))},message:prompt(\'Why exclude it?\')||\'\'}})">Exclude</button></div>'
                    for n in ib["built_not_live"])
    changed = "".join(f'<div class="row"><input type="checkbox" class="pick" value="{e(c["name"])}" aria-label="Pick {e(c["name"])}">'
                      f'<div class="grow"><a href="/song/{urllib.parse.quote(c["name"])}">{e(c["name"])}</a>'
                      f'<div class="mut">{e("; ".join(c["changes"]))}</div>'
                      + "".join(f'<div class="pill warn" style="display:inline-block;margin:2px 4px 0 0">{e(w)}</div>' for w in c["warnings"])
                      + '</div></div>' for c in ib["changed"])
    gone = "".join(f'<div class="row"><div class="grow"><a href="/song/{urllib.parse.quote(n)}">{e(n)}</a>'
                   f'<div class="mut">Live, but not linked to any song in Konami\'s list</div></div></div>' for n in ib["live_not_in_game"])
    d = status.drift()
    drift = (f'<div class="row"><div class="grow">Last nightly dry run {e(d["createdAt"][:10])}: '
             f'{e(json.dumps(d["report"])[:200]) if d["report"] else "no report (CI doesn&#39;t make one yet)"}</div>'
             f'<a href="{e(d["url"])}">Run</a></div>') if d else ""
    form = _draft_form("Pick songs above, then draft")
    return page("Inbox", f'<h1>Inbox</h1><h2>In the game, no simfile yet ({len(ib["no_simfile"])})</h2><div class="card">{ns or "<div class=mut>None</div>"}</div>'
                f'<h2>Built, not live ({len(ib["built_not_live"])})</h2><div class="card">{built or "<div class=mut>None</div>"}</div>'
                f'<h2>Built, differs from live ({len(ib["changed"])})</h2><div class="card">{changed or "<div class=mut>None</div>"}</div>'
                f'{form}<h2>Live, not in Konami\'s list ({len(ib["live_not_in_game"])})</h2><div class="card">{gone or "<div class=mut>None</div>"}</div>'
                f'<h2>Generators</h2><div class="card">{drift or "<div class=mut>No nightly run found</div>"}'
                f'<div class="row"><div class="grow">Release ddr-md master\'s generators</div>'
                f'<button onclick="act(\'draft_pin\',{{kind:\'engine\',title:\'Generators from ddr-md master\'}},()=>location.href=\'/release\')">Draft engine release</button></div></div>'
                f'<p class="mut">Last pack scrape: {e(ib["last_scrape"] or "never")}</p>', "/inbox")


def _draft_form(hint):
    return (f'<div class="card"><label for="dt">Release title</label><div class="mut">{e(hint)}</div>'
            '<input id="dt" style="width:100%;margin:6px 0" placeholder="2 new songs and 1 chart fix">'
            '<textarea id="dn" rows="2" placeholder="Notes for the history (optional)" aria-label="Notes"></textarea>'
            '<div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">'
            '<label for="dk">Kind</label><select id="dk"><option>add</option><option>fix</option></select>'
            '<button class="primary" onclick="act(\'draft\',{songs:checked(\'pick\'),removes:[],title:val(\'dt\'),notes:val(\'dn\'),kind:val(\'dk\')},()=>location.href=\'/release\')">Draft release</button></div></div>')


def songs_page(q):
    built, live = diff.names(paths.BUILD), diff.names(paths.CONTENT)
    rows = "".join(f'<div class="row" data-name="{e(n)}"><div class="grow"><a href="/song/{urllib.parse.quote(n)}">{e(n)}</a></div>'
                   + (pill("Live", "ok") if n in live else pill("Not live", "warn"))
                   + ("" if n in built else pill("Not built", "bad")) + '</div>' for n in sorted(built | live))
    return page("Songs", f'<h1>Songs</h1><input placeholder="Search" oninput="filter(this.value)" style="width:100%;margin-bottom:10px" aria-label="Search songs">'
                f'<div class="card">{rows}</div>', "/songs")


def song_page(q, name):
    c = diff.song_change(name, paths.CONTENT, paths.BUILD)
    built = diff._json(paths.BUILD / "songs" / f"{name}.json") or {}
    live = diff._json(paths.CONTENT / "songs" / f"{name}.json")
    data = "".join(f'<div class="row"><div class="grow">{e(k.replace("_", " "))}</div>'
                   + (pill("Present", "ok") if k in built else pill("Missing", "warn")) + '</div>' for k in diff.OPTIONAL)
    order = ["beginner", "easy", "medium", "hard", "challenge"]
    levels = " · ".join(f'{m.upper()} ' + " ".join(f'{d[:3]} {v}' for d, v in sorted(
        (built.get(m) or {}).items(), key=lambda x: order.index(x[0]) if x[0] in order else 9) if v)
                        for m in ("sp", "dp") if built.get(m))
    changes = "".join(f'<div class="row"><div class="grow">{e(x)}</div></div>' for x in c.changes) or \
        '<div class="mut">Same as live</div>' if live else '<div class="mut">Not live yet</div>'
    warns = "".join(f'<div class="row">{pill("Warning", "warn")}<div class="grow">{e(w)}</div></div>' for w in c.warnings)
    jn = json.dumps(name)
    rows = [r for r in status.konami_rows() if r.get("name") == name or not r.get("name")]
    ksel = "".join(f'<option value="{e(r["konami_id"])}" {"selected" if r.get("name") == name else ""}>{e(r["title"])}</option>' for r in rows)
    return page(name, f'<h1>{e(built.get("title") or name)}</h1><div class="mut">{e(built.get("artist"))} · {e(built.get("version"))} · {e(levels)}</div>'
                f'<div class="grid" style="margin-top:12px"><div class="card"><b>Build vs live</b>{changes}{warns}</div>'
                f'<div class="card"><b>Data</b>{data}</div></div>'
                f'<div class="card"><b>Actions</b><div class="row">'
                f'<button onclick="act(\'draft\',{{songs:[{e(jn)}],removes:[],title:{e(json.dumps(("Fix " if live else "Add ") + name))},kind:\'{"fix" if live else "add"}\'}},()=>location.href=\'/release\')">Draft release with this song</button>'
                f'<button onclick="job(\'song\',{{song:{e(jn)}}})">Rebuild its data</button>'
                f'<a href="/seed/chart_patches">Edit chart patches</a>'
                f'<button onclick="act(\'exclude\',{{song:{e(jn)},message:prompt(\'Why exclude it from the app?\')||\'\'}})">Exclude from prep</button>'
                + (f'<button class="danger" onclick="if(confirm(\'Remove {e(name)} from every app? Players lose the scores, notes and footing edits tied to it.\'))'
                   f'act(\'remove_song\',{{song:{e(jn)}}},()=>location.href=\'/release\')">Remove from the app</button>' if live else "")
                + f'</div><div class="row"><label for="ks">Konami song</label><select id="ks"><option value="">None</option>{ksel}</select>'
                f'<button onclick="act(\'konami_link\',{{konami_id:val(\'ks\'),name:{e(jn)}}})">Link</button>'
                f'<span class="mut">Then rebuild its data.</span></div></div>', "/songs")


def release_page(q):
    s = release.state()
    if not s["stage"]:
        return page("Release", '<h1>Release</h1><div class="card">No release in progress. Pick songs in the '
                    '<a href="/inbox">inbox</a> or on a song page.</div>'
                    + '<div class="card"><b>Releases without song changes</b><div class="row"><input id="ac" placeholder="ddr-md commit (default: master)" aria-label="ddr-md commit" class="grow">'
                    '<button onclick="act(\'draft_pin\',{kind:\'engine\',title:\'Generators \'+(val(\'ac\')||\'from master\'),app_commit:val(\'ac\')||null},()=>location.reload())">Engine release</button>'
                    '<button onclick="act(\'draft_pin\',{kind:\'site\',title:\'Privacy page and app links\'},()=>location.reload())">Site release</button></div></div>', "/release")
    order = ["checks", "ready to stage", "staging", "sign off"]
    stage = s["stage"]
    idx = order.index(stage) if stage in order else 2
    names = ["Draft", "Checks", "Staging", "Sign off", "Live", "Confirmed"]
    steps = "".join(f'<span class="{"ok" if i <= idx else ("acc" if i == idx + 1 else "")}">{n}</span>' for i, n in enumerate(names))
    rec = s["draft"] or {}
    ch = "".join(f'<div class="row"><div class="grow"><b>{e(c["name"])}</b> {pill(c["status"].capitalize(), "ok" if c["status"] == "new" else "bad" if c["status"] == "removed" else "acc")}'
                 f'<div class="mut">{e("; ".join(c["changes"]))}</div>'
                 + "".join(f'<div class="pill warn" style="display:inline-block;margin:2px 4px 0 0">{e(w)}</div>' for w in c["warnings"])
                 + '</div></div>' for c in s["changes"]) or f'<div class="mut">No song files change ({e(rec.get("kind"))} release)</div>'
    chk = s["checks"]
    chk_html = ("".join(f'<div class="row">{pill("Problem", "bad")}<div class="grow">{e(p)}</div></div>' for p in chk["problems"])
                + ("" if chk["problems"] else f'<div class="row">{pill("Passed", "ok")}<div class="grow">Console checks</div></div>')) if chk else \
        '<div class="mut">Not run yet</div>'
    run = s["staging_run"]
    run_html = (f'<div class="row">{pill(run["conclusion"] or run["status"], "ok" if run["conclusion"] == "success" else "warn")}'
                f'<div class="grow">Staging CI</div><a href="{e(run["url"])}">Open run</a></div>') if run else ""
    actions = {
        "checks": '<button class="primary" onclick="act(\'checks\')">Run checks</button>',
        "ready to stage": '<button class="primary" onclick="act(\'stage\')">Publish to staging</button>',
        "staging": '<div class="mut">Staging CI is publishing it (about 5 minutes). Reload to check.</div>',
        "staging failed": '<div class="mut">Staging CI failed. Open the run, fix the cause, then discard and draft again.</div>',
        "sign off": ('<label for="tn">Tested on your phone</label><div class="mut">Switch the app\'s song updates to staging '
                     '(long-press Song Updates), check the changes, then sign off.</div>'
                     '<textarea id="tn" rows="2" placeholder="Played both on iPhone, charts and jackets look right"></textarea>'
                     '<button class="primary" style="margin-top:8px" onclick="act(\'sign_off\',{note:val(\'tn\')})">Sign off and go live</button>'),
    }.get(stage, "")
    rb = ('<div class="row"><input id="rbc" placeholder="Type: roll back" aria-label="Confirm rollback">'
          '<button class="danger" onclick="act(\'promote_rollback\',{confirm:val(\'rbc\')})">Roll back now, skipping staging</button></div>'
          if rec.get("kind") == "rollback" and rec.get("expected_id") and stage == "ready to stage" else "")
    return page("Release", f'<div class="steps">{steps}</div><h1>{e(rec.get("title"))}</h1>'
                f'<div class="mut">{e(rec.get("kind"))} · generators <span class="mono">{short(rec.get("app_commit"))}</span>'
                f' · prep <span class="mono">{short(rec.get("prep_commit"))}</span> · draft <span class="mono">{short(s["draft_commit"])}</span></div>'
                f'<h2>What changes for players</h2><div class="card">{ch}</div>'
                f'<h2>Checks</h2><div class="card">{chk_html}{run_html}'
                + "".join(f'<div class="row">{pill("Warning", "warn")}<div class="grow">{e(w)}</div></div>' for w in (chk or {}).get("warnings", []))
                + f'</div><div class="card">{actions}{rb}</div>'
                '<button class="danger" onclick="if(confirm(\'Discard this release? Staging goes back to what is live.\'))act(\'discard\')">Discard release</button>', "/release")


def history_page(q):
    items = release.history()
    rows = "".join(f'<div class="row"><div class="grow"><b>{e(r["title"])}</b> {pill(r["kind"])}'
                   f'<div class="mut"><span class="mono">{e(r.get("expected_id"))}</span> · {e(r["date"])} · Tested: {e((r.get("tested") or {}).get("note"))}</div>'
                   f'<div class="mut">{e(", ".join(r["songs"]["added"] + r["songs"]["changed"] + r["songs"]["removed"])[:200])}</div></div>'
                   + (f'<button onclick="if(confirm(\'Draft a rollback to this release? You review it before it goes anywhere.\'))'
                      f'act(\'rollback\',{{to:\'{e(r["commit"])}\'}},()=>location.href=\'/release\')">Roll back to this</button>' if i else pill("Live", "ok"))
                   + '</div>' for i, r in enumerate(items))
    return page("History", f'<h1>History</h1><div class="card">{rows or "<div class=mut>No releases recorded yet</div>"}</div>', "/history")


def maintenance_page(q):
    groups = [("Prepare", ["prepare", "parse", "simfile_sync", "arcade_sync", "arcade_timesigs", "tiers", "jackets"]),
              ("Scrape and Konami", ["scrape_packs", "konami_fetch", "konami_relink"]),
              ("Slow or rare", ["simfile_sync_full", "arcade_sync_force", "noteskin", "scoring_restore"]),
              ("App builds", ["fetch_content"])]
    body = ""
    for title, names in groups:
        body += f'<h2>{e(title)}</h2><div class="card">' + "".join(
            f'<div class="row"><div class="grow">{e(jobs.CATALOG[n][0])}</div><button onclick="job(\'{n}\')">Run</button></div>' for n in names)
        if title == "App builds":
            body += ('<div class="row"><div class="grow">Store build (fetches live content first)</div>'
                     '<button onclick="job(\'store_build\',{target:\'ipa\'})">iOS</button>'
                     '<button onclick="job(\'store_build\',{target:\'appbundle\'})">Android</button></div>'
                     '<div class="row"><div class="grow">Lite build</div><button onclick="job(\'lite_build\')">Run</button></div>')
        body += '</div>'
    seed_rows = "".join(f'<div class="row"><div class="grow">{e(k.replace("_", " "))} <span class="mut mono">{e(v)}</span></div>'
                        f'<a href="/seed/{e(k)}">Edit</a></div>' for k, v in paths.SEEDS.items())
    hist = "".join(f'<div class="row"><span class="mono mut">{e(j["started"][5:16])}</span><div class="grow"><a href="/job/{e(j["id"])}">{e(j["label"])}</a></div>'
                   + pill(j["status"], "ok" if j["status"] == "done" else "bad") + '</div>' for j in jobs.history())
    cookie = ('<h2 id="cookie">E-amusement cookie</h2><div class="card"><div class="mut">Sign in on p.eagate.573.jp in a browser and copy the '
              'session cookie. It goes straight to the Keychain.</div><div class="row"><input id="ck" type="password" class="grow" '
              'aria-label="Cookie value" autocomplete="off"><button onclick="act(\'cookie\',{value:val(\'ck\')})">Store</button></div></div>')
    return page("Maintenance", f'<h1>Maintenance</h1>{body}<h2>Seed files</h2><div class="card">{seed_rows}'
                '<div class="row"><div class="grow">Push prep, so releases can name the commit that built them</div>'
                '<button onclick="act(\'push_prep\')">Push prep</button></div></div>'
                f'{cookie}<h2>Recent jobs</h2><div class="card">{hist or "<div class=mut>None yet</div>"}</div>', "/maintenance")


def seed_page(q, name):
    text = seeds.read(name)
    return page(name, f'<h1>{e(name.replace("_", " "))}</h1><div class="mut mono">{e(paths.SEEDS.get(name))}</div>'
                f'<textarea id="st" rows="24" class="mono" style="margin-top:8px" aria-label="File contents">{e(text)}</textarea>'
                '<div class="row"><input id="sm" class="grow" placeholder="Why (the commit message)" aria-label="Commit message">'
                f'<button onclick="act(\'seed_preview\',{{name:\'{e(name)}\',text:val(\'st\')}},r=>{{document.getElementById(\'sd\').textContent=(r.problems.join(\'\\n\')||\'No problems\')+\'\\n\\n\'+r.diff}})">Preview</button>'
                f'<button class="primary" onclick="act(\'seed_save\',{{name:\'{e(name)}\',text:val(\'st\'),message:val(\'sm\')}})">Save and commit</button></div>'
                '<pre id="sd"></pre>', "/maintenance")


def job_page(q, job_id):
    cur = jobs.current()
    rec = next((j for j in jobs.history(200) if j["id"] == job_id), None) or (cur if cur and cur["id"] == job_id else None)
    if not rec:
        return page("Job", '<div class="card">No such job</div>', "/maintenance")
    stop = '<button class="danger" onclick="act(\'stop_job\')">Stop</button>' if cur and cur["id"] == job_id else ""
    return page(rec["label"], f'<h1>{e(rec["label"])}</h1><div class="mut">Started {e(rec["started"])} · '
                f'<span id="jobstate">{e(rec["status"])}</span> {stop}</div><pre id="log"></pre><script>addEventListener("load",()=>tail({json.dumps(job_id)}))</script>', "/maintenance")


def activity_page(q):
    rows = "".join(f'<div class="row"><span class="mono mut">{e(a["at"])}</span><div class="grow">{e(a["action"])} <span class="mut">{e(_brief(a))}</span></div></div>'
                   for a in util.activity(300))
    return page("Activity", f'<h1>Activity</h1><div class="card">{rows or "<div class=mut>None yet</div>"}</div>', "/activity")


# ---------------------------------------------------------------- actions

def _exclude(b):
    return seeds.add_line("removed", b["song"], b.get("message") or f"exclude {b['song']}")


def _remove(b):
    if b["song"] in {p.name for p in paths.DATA.glob("*/*")} and b["song"] not in seeds.read("removed").splitlines():
        seeds.add_line("removed", b["song"], f"remove {b['song']}: no longer in the game")
    return release.draft([], [b["song"]], f"Remove {b['song']}", kind="remove")


def _add_simfile(b):
    sid, version = str(b["simfile_id"]).strip(), b["version"].strip()
    if not sid.isdigit():
        raise util.Refused("The simfile ID is the number in the Zenius viewsimfile URL")
    if not (paths.DATA / version).is_dir():
        raise util.Refused(f"No version folder {version}")
    if not any(l.startswith(sid + "\t") for l in seeds.read("songs").splitlines()):
        seeds.add_line("songs", f"{sid}\t{version}\t{b.get('title', '')}", f"scrape {b.get('title') or sid}")
    return jobs.start("scrape_song", {"simfile_id": sid, "version": version})


ACTIONS = {
    "job": lambda b: jobs.start(b["name"], b.get("params") or {}),
    "stop_job": lambda b: jobs.stop(),
    "draft": lambda b: release.draft(b.get("songs") or [], b.get("removes") or [], b.get("title") or "",
                                     b.get("notes") or "", b.get("kind") or "add", bool(b.get("replace"))),
    "draft_pin": lambda b: release.draft_pin(b["kind"], b.get("title") or "", b.get("notes") or "", b.get("app_commit")),
    "checks": lambda b: release.checks(),
    "stage": lambda b: release.stage(),
    "sign_off": lambda b: release.sign_off(b.get("note") or ""),
    "discard": lambda b: release.discard(),
    "rollback": lambda b: release.rollback(b["to"]),
    "promote_rollback": lambda b: release.promote_rollback(b.get("confirm") or ""),
    "seed_preview": lambda b: seeds.preview(b["name"], b["text"]),
    "seed_save": lambda b: seeds.save(b["name"], b["text"], b.get("message") or ""),
    "exclude": _exclude,
    "remove_song": _remove,
    "cookie": lambda b: status.set_cookie(b.get("value") or ""),
    "konami_link": lambda b: _konami_link(b["konami_id"], b["name"]),
    "push_prep": lambda b: seeds.push_prep(),
    "add_simfile": _add_simfile,
}


def _konami_link(konami_id, name):
    """Point the song at one Konami entry (or none), clearing any other link it had."""
    for r in status.konami_rows():
        if r.get("name") == name and r["konami_id"] != konami_id:
            status.set_konami_name(r["konami_id"], "")
    if konami_id:
        status.set_konami_name(konami_id, name)


ROUTES = [("/song/", song_page), ("/seed/", seed_page), ("/job/", job_page)]
PAGES = {"/": home, "/inbox": inbox_page, "/songs": songs_page, "/release": release_page,
         "/history": history_page, "/maintenance": maintenance_page, "/activity": activity_page}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        host = self.headers.get("Host", "")
        if host.split(":")[0] not in ("127.0.0.1", "localhost"):
            return False
        cookies = dict(c.strip().split("=", 1) for c in self.headers.get("Cookie", "").split(";") if "=" in c)
        return secrets.compare_digest(cookies.get("rc", ""), TOKEN)

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if q.get("t", [""])[0] == TOKEN:
            return self._send(303, "", extra={"Location": url.path,
                                              "Set-Cookie": f"rc={TOKEN}; HttpOnly; SameSite=Strict; Path=/"})
        if not self._authed():
            return self._send(403, "Open the console with the link `make admin` printed.", "text/plain")
        try:
            if url.path == "/api/joblog":
                job_id = q.get("id", [""])[0]
                cur = jobs.current()
                running = bool(cur and cur["id"] == job_id)
                rec = next((j for j in jobs.history(200) if j["id"] == job_id), {})
                return self._send(200, json.dumps({"text": jobs.log_text(job_id, int(q.get("from", ["0"])[0])),
                                                   "running": running, "status": "running" if running else rec.get("status", "")}),
                                  "application/json")
            path = urllib.parse.unquote(url.path)
            for prefix, fn in ROUTES:
                if path.startswith(prefix):
                    return self._send(200, fn(q, path[len(prefix):]))
            if path in PAGES:
                return self._send(200, PAGES[path](q))
            self._send(404, page("Not found", '<div class="card">Not found</div>'))
        except Exception as ex:
            traceback.print_exc()
            self._send(500, page("Error", f'<div class="card bad">{e(ex)}</div>'))

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if not self._authed() or origin not in (f"http://{host}",):
            return self._send(403, json.dumps({"error": "Not allowed"}), "application/json")
        name = self.path.removeprefix("/api/")
        if name not in ACTIONS:
            return self._send(404, json.dumps({"error": "No such action"}), "application/json")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            result = ACTIONS[name](body)
            self._send(200, json.dumps({"result": result}, default=str), "application/json")
        except util.Refused as ex:
            self._send(400, json.dumps({"error": str(ex)}), "application/json")
        except KeyError as ex:
            self._send(400, json.dumps({"error": f"Missing {ex.args[0]}"}), "application/json")
        except Exception as ex:
            traceback.print_exc()
            self._send(500, json.dumps({"error": f"{type(ex).__name__}: {ex}"}), "application/json")


def serve(port=8767):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Release console: http://127.0.0.1:{port}/?t={TOKEN}", flush=True)
    util.log("console.start", port=port)
    srv.serve_forever()
