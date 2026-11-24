"""Macht aus einem Podcast-Skript eine MP3.
Nutzung: python3 tts.py skript.txt ausgabe.mp3 [stimme.json]

Hauptweg: Gemini TTS von Google (klingt wie ein Mensch). Braucht stimme.json mit dem Feld "schluessel".
Rueckfall: Edge-TTS, Stimme Florian. Greift automatisch, wenn der Schluessel fehlt oder Gemini nicht antwortet.
Im Skript trennt eine Leerzeile die Absaetze. Ein Absatz, in dem nur [PAUSE] steht, wird zu einer Denkpause.
Letzte Ausgabezeile: "FERTIG: weg=gemini ..." oder "FERTIG: weg=edge ...".
"""
import asyncio, base64, json, os, re, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.request

CA = "/root/.ccr/ca-bundle.crt"
MODELLE = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"]
STIL = ("A warm, relaxed male German podcast host in his thirties explaining something to a friend on the morning drive. "
        "Natural conversational rhythm, clear and unhurried, a slight smile in the voice. Not a news anchor, not an "
        "audiobook narrator. Speak standard German. Pronounce English product names such as Claude, Prompt or GitHub the English way.")
STUECK_W = 650            # Woerter pro Gemini-Anfrage (Gratis-Kontingent: nur 10 Anfragen pro Tag und Modell)
ABSTAND = int(os.environ.get("TTS_ABSTAND", 22))   # Sekunden zwischen Anfragen (Gratis-Kontingent: 3 pro Minute)
PAUSE_DENK, PAUSE_STUECK, PAUSE_ABSATZ = 2.5, 0.5, 0.6
EN = ["Claude Code", "Claude", "Anthropic", "Prompting", "Prompts", "Prompt", "Skills", "Skill", "Workflows", "Workflow",
      "GitHub", "Raspberry Pi", "Spotify", "Opus", "Sonnet", "Haiku", "Fable", "Container", "Tokens", "Token", "Slicer",
      "Gemini", "Google", "OpenAI", "ChatGPT", "Microsoft", "Python", "Markdown", "Dashboard", "Open Source", "Docker",
      "Linux", "Windows", "Home Assistant", "Few-Shot", "Cowork", "Excel"]
EN_RE = re.compile(r"(?<![\wÄÖÜäöüß\[])(" + "|".join(re.escape(e) for e in EN) + r")(?![a-zäöüß\]])")


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)

def dauer(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

def stille(p, sek):
    ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(sek), "-c:a", "pcm_s16le", p)

def lies(src):
    """Liefert eine Liste aus Absatz-Texten und None fuer jede Denkpause."""
    roh = open(src, encoding="utf-8").read().replace("\r", "")
    return [None if a.strip() == "[PAUSE]" else " ".join(a.split()) for a in re.split(r"\n\s*\n", roh) if a.strip()]

def zusammen(teile, dst, tmp):
    """Fuegt WAV-Stuecke aneinander, gleicht die Lautstaerke an und schreibt die MP3."""
    lst = os.path.join(tmp, "liste.txt")
    open(lst, "w").write("".join(f"file '{t}'\n" for t in teile))
    ff("-f", "concat", "-safe", "0", "-i", lst, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000", "-ac", "1", "-b:a", "64k", dst)


# ---------- Hauptweg: Gemini ----------
class GeminiAus(Exception):
    pass

def gemini_anfrage(text, cfg, modell):
    url = os.environ.get("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta/models/") + modell + ":generateContent"
    body = {"contents": [{"role": "user", "parts": [{"text": text, "speech_metadata": {"style": cfg.get("stil") or STIL}}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"voice": cfg.get("stimme") or "Achird"}}}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": cfg["schluessel"]})
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) and url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
        d = json.load(r)
    for p in d["candidates"][0]["content"]["parts"]:
        blob = p.get("inlineData") or p.get("inline_data")
        if blob:
            return base64.b64decode(blob["data"])
    raise ValueError("Antwort ohne Audio")

def gemini_stueck(text, cfg, modell, ziel, tmp):
    """Vertont ein Stueck. Prueft, ob die Laenge zum Text passt (sonst wurde gekuerzt oder dazugedichtet)."""
    w = len(text.split())
    for versuch in range(4):
        try:
            daten = gemini_anfrage(text, cfg, modell)
            roh = os.path.join(tmp, "roh.bin")
            open(roh, "wb").write(daten)
            if daten[:4] == b"RIFF":
                ff("-i", roh, "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", ziel)
            else:
                ff("-f", "s16le", "-ar", "24000", "-ac", "1", "-i", roh, "-c:a", "pcm_s16le", ziel)
            d = dauer(ziel)
            if w * 0.22 <= d <= w * 0.75 + 4:
                return
            print(f"Laenge unplausibel ({d:.0f} s fuer {w} Woerter), neuer Versuch", file=sys.stderr)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            print(f"Gemini meldet {e.code}: {msg}", file=sys.stderr)
            if e.code in (400, 401, 403, 404) or (e.code == 429 and re.search(r"per ?day|PerDay|daily", msg, re.I)):
                raise GeminiAus(f"HTTP {e.code}")
            time.sleep(65 if e.code == 429 else min(15, ABSTAND + 1))
            continue
        except Exception as e:
            print("Gemini-Fehler:", e, file=sys.stderr)
            if "Tunnel connection failed" in str(e):
                raise GeminiAus("Adresse generativelanguage.googleapis.com ist nicht freigegeben")
        time.sleep(ABSTAND)
    raise GeminiAus("vier Versuche ohne brauchbares Audio")

def gemini(absaetze, cfg, dst, tmp):
    stuecke, akt = [], []          # Stuecke aus Absaetzen bilden; eine Denkpause trennt immer
    for a in absaetze + [None]:
        if a is None or sum(len(x.split()) for x in akt) + len(a.split()) > STUECK_W:
            if akt:
                stuecke.append("\n\n".join(akt))
            akt = []
            if a is None:
                stuecke.append(None)
                continue
        akt.append(a)
    stuecke = stuecke[:-1]
    sp, sd = os.path.join(tmp, "p_stueck.wav"), os.path.join(tmp, "p_denk.wav")
    stille(sp, PAUSE_STUECK); stille(sd, PAUSE_DENK)
    letzter = None
    for modell in ([cfg["modell"]] if cfg.get("modell") else []) + MODELLE:
        try:
            teile = []
            for i, s in enumerate(stuecke):
                if s is None:
                    teile.append(sd)
                    continue
                ziel = os.path.join(tmp, f"g{i:02d}.wav")
                gemini_stueck(s, cfg, modell, ziel, tmp)
                teile += [ziel, sp]
                print(f"Stueck {i + 1} von {len(stuecke)} fertig", file=sys.stderr)
                if any(x for x in stuecke[i + 1:]):
                    time.sleep(ABSTAND)
            zusammen(teile, dst, tmp)
            return modell
        except GeminiAus as e:
            letzter = e
            print(f"Modell {modell} geht nicht: {e}", file=sys.stderr)
            if not any(c in str(e) for c in ("404", "400", "429")):
                break   # bei unbekanntem Modell oder leerem Tageskontingent das naechste Modell versuchen
    raise GeminiAus(str(letzter))


# ---------- Rueckfall: Edge-TTS ----------
async def edge(absaetze, dst, tmp):
    import certifi
    if os.path.exists(CA):
        certifi.where = lambda: CA   # Proxy-Zertifikat vertrauen, Pruefung bleibt aktiv
    import edge_tts

    async def sprich(text, out, wav):
        for _ in range(4):
            try:
                await edge_tts.Communicate(text, "de-DE-FlorianMultilingualNeural", rate="-5%").save(out)
                if os.path.getsize(out) > 500:
                    f = "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
                    ff("-i", out, "-af", f, "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", wav)
                    return
            except Exception as e:
                print("Wiederhole Abschnitt:", e, file=sys.stderr)
            await asyncio.sleep(3)
        raise RuntimeError(f"Abschnitt konnte nicht vertont werden: {text[:60]}")

    sw, sa, sd = (os.path.join(tmp, n) for n in ("e_wort.wav", "e_absatz.wav", "e_denk.wav"))
    stille(sw, 0.08); stille(sa, PAUSE_ABSATZ); stille(sd, PAUSE_DENK)
    teile = []
    for i, a in enumerate(absaetze):
        if a is None:
            teile.append(sd)
            continue
        # Englische Begriffe einzeln vertonen, damit Florian sie englisch spricht und sonst beim Deutschen bleibt
        segs = [s.strip() for s in re.split(r"\[\[(.+?)\]\]", EN_RE.sub(r"[[\1]]", a))]
        segs = [s for s in segs if re.search(r"\w", s)]
        for j, s in enumerate(segs):
            wav = os.path.join(tmp, f"e{i:03d}_{j:02d}.wav")
            await sprich(s, wav + ".mp3", wav)
            teile += [wav, sw]
        teile[-1] = sa
    zusammen(teile, dst, tmp)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    cfg = {}
    if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
        try:
            cfg = json.load(open(sys.argv[3], encoding="utf-8"))
        except Exception as e:
            print("stimme.json nicht lesbar:", e, file=sys.stderr)
    absaetze, tmp, grund = lies(src), tempfile.mkdtemp(), "kein Schluessel hinterlegt"
    if (cfg.get("schluessel") or "").strip():
        cfg["schluessel"] = cfg["schluessel"].strip()
        try:
            modell = gemini(absaetze, cfg, dst, tmp)
            print(f"FERTIG: weg=gemini modell={modell} stimme={cfg.get('stimme') or 'Achird'} dauer={dauer(dst):.0f}")
            return
        except Exception as e:
            grund = f"Gemini ausgefallen ({e})"
    asyncio.run(edge(absaetze, dst, tmp))
    print(f"FERTIG: weg=edge stimme=Florian dauer={dauer(dst):.0f} grund={grund}")


main()
