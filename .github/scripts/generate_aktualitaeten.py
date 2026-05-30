"""
ABU Aktualitäten Generator
──────────────────────────
Liest RSS-Feeds, ordnet Artikel den SLP-Themen zu,
generiert AVIVA-Varianten [E] [TH] [UE] und schreibt aktualitaeten.json
"""

import os
import json
import re
import datetime
import feedparser
import anthropic

# ── Konfiguration ────────────────────────────────────────────────────

RSS_FEEDS = [
    {"url": "https://www.srf.ch/news/rss",              "source": "SRF"},
    {"url": "https://www.nzz.ch/wirtschaft.rss",        "source": "NZZ"},
    {"url": "https://www.20min.ch/rss/rss.tmpl",        "source": "20min"},
    {"url": "https://www.srf.ch/news/wirtschaft.rss",   "source": "SRF Wirtschaft"},
]

# SLP-Themen mit Schlüsselbegriffen für Zuordnung
THEMEN = {
    1: {
        "name": "Mein Lehrbeginn",
        "keywords": ["Lehrstelle", "Lehrvertrag", "Berufsbildung", "Apprentice",
                     "Ausbildung", "Berufslehre", "KV", "EFZ", "Jugendliche",
                     "Arbeitsrecht", "Kündigungsschutz", "Probezeit"]
    },
    2: {
        "name": "Mein Geld",
        "keywords": ["Lohn", "Gehalt", "Budget", "Konsum", "Kaufvertrag",
                     "Schulden", "Kredit", "Zinsen", "SNB", "Leitzins",
                     "Inflation", "Teuerung", "Sparen", "Investition",
                     "Kreditkarte", "Raten", "Werbung", "Preis", "Rabatt"]
    },
    3: {
        "name": "Meine Gesundheit",
        "keywords": ["Gesundheit", "Krankheit", "Krankenversicherung", "KVG",
                     "Prämien", "Burnout", "Stress", "Sucht", "Alkohol",
                     "Drogen", "Mental Health", "Psyche", "Arzt", "Spital",
                     "Selbstfürsorge", "Work-Life-Balance", "Übergewicht"]
    },
    4: {
        "name": "Unsere Schweiz",
        "keywords": ["Demokratie", "Abstimmung", "Volksinitiative", "Referendum",
                     "Parlament", "Bundesrat", "Wahlen", "Medien", "Fake News",
                     "Integration", "Ausländer", "Migration", "Schweizer",
                     "Kantone", "Föderalismus", "Neutralität"]
    },
    5: {
        "name": "Unser Zusammenleben",
        "keywords": ["Familie", "Ehe", "Partnerschaft", "Scheidung", "Kinder",
                     "Diskriminierung", "Gleichstellung", "Gender", "LGBTQ",
                     "Wohnen", "Miete", "Nachbarschaft", "Konflikt",
                     "Sozialversicherung", "AHV", "IV"]
    },
    6: {
        "name": "Unsere Welt",
        "keywords": ["Klimawandel", "Umwelt", "Nachhaltigkeit", "CO2",
                     "Energie", "Erneuerbar", "Solar", "Krieg", "Frieden",
                     "Globalisierung", "Handel", "Armut", "Entwicklung",
                     "Menschenrechte", "UNO", "Europa", "EU"]
    },
    7: {
        "name": "Meine Zukunft",
        "keywords": ["Berufswahl", "Weiterbildung", "Karriere", "Digitalisierung",
                     "KI", "Künstliche Intelligenz", "Automatisierung", "Jobs",
                     "Arbeitsmarkt", "Altersvorsorge", "Pensionskasse",
                     "Rente", "AHV-Reform", "Zukunft"]
    },
}

MAX_ARTICLES_PER_THEME = 3   # max. Artikel pro Thema
MAX_TOTAL_ARTICLES = 15      # max. Artikel total pro Durchlauf
MIN_ARTICLES_PER_THEME = 1   # mind. 1 Artikel pro Thema pro Woche


# ── RSS-Feeds lesen ──────────────────────────────────────────────────

def fetch_articles():
    articles = []
    for feed_cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                url = entry.get("link", "")
                # Datum
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    date = datetime.date(*published[:3]).strftime("%d.%m.")
                else:
                    date = datetime.date.today().strftime("%d.%m.")

                if title and len(title) > 10:
                    articles.append({
                        "title": title,
                        "summary": summary[:300] if summary else "",
                        "url": url,
                        "source": feed_cfg["source"],
                        "date": date,
                    })
        except Exception as e:
            print(f"  Fehler bei {feed_cfg['url']}: {e}")
    print(f"  {len(articles)} Artikel aus RSS geladen")
    return articles


# ── Themen-Zuordnung (regelbasiert + KI) ────────────────────────────

def assign_theme_simple(title, summary):
    """Schnelle regelbasierte Zuordnung anhand Keywords."""
    text = (title + " " + summary).lower()
    scores = {}
    for theme_id, theme in THEMEN.items():
        score = sum(1 for kw in theme["keywords"] if kw.lower() in text)
        if score > 0:
            scores[theme_id] = score
    if scores:
        return max(scores, key=scores.get)
    return None


def assign_themes_with_ai(articles, client):
    """KI ordnet Artikel zu Themen zu (Batch für Effizienz)."""
    if not articles:
        return {}

    themen_str = "\n".join([
        f"Thema {tid}: {t['name']} – Stichworte: {', '.join(t['keywords'][:6])}"
        for tid, t in THEMEN.items()
    ])

    articles_str = "\n".join([
        f"[{i}] {a['title']} ({a['source']}): {a['summary'][:150]}"
        for i, a in enumerate(articles)
    ])

    prompt = f"""Du bist ein ABU-Lehrer (Allgemeinbildender Unterricht, Schweizer Berufsschule).
Ordne jeden Artikel einem der folgenden SLP-Themen zu.
Antworte NUR mit JSON: {{"0": 2, "1": 4, "2": null, ...}}
null = passt zu keinem Thema.

Themen:
{themen_str}

Artikel:
{articles_str}

JSON:"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # JSON extrahieren
        m = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"  KI-Zuordnung Fehler: {e}")
    return {}


# ── AVIVA-Varianten generieren ───────────────────────────────────────

def generate_variants(article, theme_name, client):
    """Generiert [E], [TH], [UE] Varianten für einen Artikel."""

    prompt = f"""Du bist ein ABU-Lehrer (Allgemeinbildender Unterricht, Schweizer Berufsschule).
Erstelle für diesen Nachrichtenartikel drei kurze Unterrichts-Varianten für das Thema "{theme_name}".
Zielgruppe: Lernende im 1.–4. Lehrjahr.

Artikel: {article['title']}
Quelle: {article['source']}
Zusammenfassung: {article['summary'][:200]}

Erstelle genau dieses JSON (keine Erklärungen davor/danach):
{{
  "E": "Einstiegsfrage für Diskussion (1 Satz, provokativ/neugierig)",
  "TH": "Theorie-Einordnung: Welches Lernziel/Konzept wird hier sichtbar? (2 Sätze)",
  "UE": "Übungsaufgabe mit direktem Bezug zum Artikel (1 konkreter Auftrag)"
}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return [
                {"phase": "E",   "text": data.get("E", "")},
                {"phase": "TH",  "text": data.get("TH", "")},
                {"phase": "UE",  "text": data.get("UE", "")},
            ]
    except Exception as e:
        print(f"  Varianten-Fehler für '{article['title'][:40]}': {e}")

    # Fallback: einfache Platzhalter
    return [
        {"phase": "E",  "text": f"Was denkst du zu: «{article['title']}»?"},
        {"phase": "TH", "text": f"Dieser Artikel zeigt: {article['summary'][:100]}"},
        {"phase": "UE", "text": f"Recherchiere: Welche Auswirkungen hat das auf deinen Alltag?"},
    ]


# ── Hauptlogik ───────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("FEHLER: ANTHROPIC_API_KEY nicht gesetzt")
        exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    print("🗞 ABU Aktualitäten Generator startet...")

    # 1. Bestehende JSON laden (für Archiv)
    output_file = "aktualitaeten.json"
    existing = {}
    if os.path.exists(output_file):
        try:
            with open(output_file) as f:
                existing = json.load(f)
        except:
            existing = {}

    # 2. Artikel laden
    print("\n📡 RSS-Feeds lesen...")
    articles = fetch_articles()
    if not articles:
        print("Keine Artikel gefunden.")
        return

    # 3. Themen zuordnen
    print("\n🎯 Themen zuordnen...")
    # Erst regelbasiert
    assigned = {}
    unassigned = []
    for i, art in enumerate(articles[:MAX_TOTAL_ARTICLES]):
        theme_id = assign_theme_simple(art["title"], art["summary"])
        if theme_id:
            assigned[i] = theme_id
        else:
            unassigned.append(i)

    # Unzugeordnete via KI
    if unassigned:
        ai_assignments = assign_themes_with_ai(
            [articles[i] for i in unassigned], client
        )
        for local_idx, theme_id in ai_assignments.items():
            if theme_id:
                global_idx = unassigned[int(local_idx)]
                assigned[global_idx] = theme_id

    # 4. Pro Thema Varianten generieren
    print("\n✍️  Varianten generieren...")
    result = {}
    theme_counts = {tid: 0 for tid in THEMEN}

    for art_idx, theme_id in sorted(assigned.items()):
        if theme_counts[theme_id] >= MAX_ARTICLES_PER_THEME:
            continue

        article = articles[art_idx]
        theme_name = THEMEN[theme_id]["name"]
        print(f"  [{theme_id}] {article['title'][:50]}...")

        varianten = generate_variants(article, theme_name, client)

        entry = {
            "id": f"art-{datetime.date.today().strftime('%Y%m%d')}-{art_idx:02d}",
            "date": article["date"],
            "title": article["title"],
            "source": article["source"],
            "url": article["url"],
            "varianten": varianten,
        }

        tid_str = str(theme_id)
        if tid_str not in result:
            result[tid_str] = []
        result[tid_str].append(entry)
        theme_counts[theme_id] += 1

    # 5. Mit bestehenden Einträgen zusammenführen (Archiv erhalten)
    MAX_ARCHIVE = 10  # max. Einträge pro Thema im JSON
    final = {}
    for tid_str in [str(i) for i in range(1, 8)]:
        new_entries = result.get(tid_str, [])
        old_entries = existing.get(tid_str, [])
        # Neue zuerst, dann Archiv (ohne Duplikate)
        seen_titles = {e["title"] for e in new_entries}
        old_unique = [e for e in old_entries if e["title"] not in seen_titles]
        combined = (new_entries + old_unique)[:MAX_ARCHIVE]
        if combined:
            final[tid_str] = combined

    # 6. Schreiben
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    # Zusammenfassung
    total = sum(len(v) for v in final.values())
    print(f"\n✅ {output_file} geschrieben")
    print(f"   {total} Artikel über {len(final)} Themen")
    for tid_str, entries in final.items():
        print(f"   Thema {tid_str}: {len(entries)} Artikel")


if __name__ == "__main__":
    main()
