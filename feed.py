"""Traegt eine Folge in den Podcast-Feed ein und schreibt feed.xml neu.
Nutzung: python3 feed.py REPO-ORDNER folge-XX.mp3 NR "Titel" "Kurzbeschreibung" JJJJ-MM-TT
Kopiert die MP3 nach REPO-ORDNER/folgen/folge-XX.mp3, pflegt REPO-ORDNER/folgen.json und schreibt REPO-ORDNER/feed.xml.
Letzte Ausgabezeile: "FEED OK: n Folgen".
"""
import json, os, shutil, subprocess, sys
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

BASIS = "https://bbrjzdvzp4-ctrl.github.io/claude-schulung-podcast/"
repo, mp3, nr, titel, kurz, datum = sys.argv[1:7]
nr = int(nr)
name = f"folge-{nr:02d}.mp3"
os.makedirs(os.path.join(repo, "folgen"), exist_ok=True)
ziel = os.path.join(repo, "folgen", name)
if os.path.abspath(mp3) != os.path.abspath(ziel):
    shutil.copyfile(mp3, ziel)
dauer = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", ziel],
                             capture_output=True, text=True).stdout.strip())

liste_pfad = os.path.join(repo, "folgen.json")
liste = json.load(open(liste_pfad, encoding="utf-8")) if os.path.exists(liste_pfad) else []
liste = [f for f in liste if f["nr"] != nr]
liste.append({"nr": nr, "titel": titel, "kurz": kurz, "datum": datum, "datei": name,
              "bytes": os.path.getsize(ziel), "dauer": round(dauer)})
liste.sort(key=lambda f: f["nr"], reverse=True)
json.dump(liste, open(liste_pfad, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def zeit(datum):   # Erscheinungszeit: 5:30 Uhr deutscher Zeit, in UTC als 4:30
    return format_datetime(datetime.strptime(datum, "%Y-%m-%d").replace(hour=4, minute=30, tzinfo=timezone.utc))

items = []
for f in liste:
    d = f["dauer"]
    items.append(f"""  <item>
   <title>{f['nr']}. {escape(f['titel'])}</title>
   <description>{escape(f['kurz'])}</description>
   <enclosure url="{BASIS}folgen/{f['datei']}" length="{f['bytes']}" type="audio/mpeg"/>
   <guid isPermaLink="false">claude-schulung-folge-{f['nr']:02d}</guid>
   <pubDate>{zeit(f['datum'])}</pubDate>
   <itunes:duration>{d // 60}:{d % 60:02d}</itunes:duration>
   <itunes:episode>{f['nr']}</itunes:episode>
   <itunes:explicit>false</itunes:explicit>
  </item>""")

xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
 <channel>
  <title>Claude-Schulung</title>
  <link>{BASIS}</link>
  <atom:link href="{BASIS}feed.xml" rel="self" type="application/rss+xml"/>
  <description>Hannes' persönliche KI-Schulung: zehn Minuten Claude für den Arbeitsweg.</description>
  <language>de-de</language>
  <itunes:author>Claude-Schulung</itunes:author>
  <itunes:image href="{BASIS}cover.jpg"/>
  <image><url>{BASIS}cover.jpg</url><title>Claude-Schulung</title><link>{BASIS}</link></image>
  <itunes:category text="Education"/>
  <itunes:explicit>false</itunes:explicit>
  <itunes:type>episodic</itunes:type>
  <itunes:block>Yes</itunes:block>
{chr(10).join(items)}
 </channel>
</rss>
"""
open(os.path.join(repo, "feed.xml"), "w", encoding="utf-8").write(xml)
print(f"FEED OK: {len(liste)} Folgen")
