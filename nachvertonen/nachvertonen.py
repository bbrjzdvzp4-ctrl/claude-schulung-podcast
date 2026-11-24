"""Vertont die Skripte in diesem Ordner (hoechstens zwei pro Lauf) neu mit der Google-Stimme (nur Gemini, kein Florian) und traegt sie in den Feed ein.
Nutzung (im Repo-Ordner): python3 nachvertonen/nachvertonen.py /pfad/zu/stimme.json
Fertige Skripte werden geloescht. Hoert auf, sobald das Google-Kontingent fuer heute leer ist.
Letzte Zeile: "NACHVERTONT: n, OFFEN: m"."""
import glob, json, os, re, subprocess, sys, tempfile
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(R, "tts.py"), encoding="utf-8").read().rsplit("\nmain()", 1)[0]
exec(compile(src, "tts.py", "exec"))
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
MODELLE[:] = ["gemini-3.8-flash-lite-tts"]   # Achird; das Flash-Kontingent bleibt fuer die neue Folge am Morgen frei
MAX_PRO_LAUF = 2
liste = {f["nr"]: f for f in json.load(open(os.path.join(R, "folgen.json"), encoding="utf-8"))}
fertig = 0
for skript in sorted(glob.glob(os.path.join(R, "nachvertonen", "folge-*.txt")))[:MAX_PRO_LAUF]:
    nr = int(re.search(r"folge-(\d+)", skript).group(1))
    mp3 = os.path.join(tempfile.mkdtemp(), f"folge-{nr:02d}.mp3")
    try:
        gemini(lies(skript), cfg, mp3, tempfile.mkdtemp())
    except Exception as e:
        print(f"Folge {nr}: Google nicht verfuegbar ({e}), Rest morgen", file=sys.stderr)
        break
    f = liste[nr]
    t = os.path.join(tempfile.mkdtemp(), "teile.json")
    json.dump({"uebung": f.get("uebung", ""), "zusammenfassung": f.get("zusammenfassung", "")}, open(t, "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run(["python3", os.path.join(R, "feed.py"), R, mp3, str(nr), f["titel"], f["kurz"], f["datum"], t], capture_output=True, text=True)
    print(r.stdout.strip())
    os.remove(skript)
    fertig += 1
print(f"NACHVERTONT: {fertig}, OFFEN: {len(glob.glob(os.path.join(R, 'nachvertonen', 'folge-*.txt')))}")
