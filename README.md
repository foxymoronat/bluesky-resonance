# Resonance — Bluesky-Feeds aus deinen eigenen Interaktionen

*Build two personal Bluesky feeds from the accounts you actually interact with.*

Du folgst auf Bluesky sehr vielen Leuten, aber dein „Following" ist überfüllt?
**Resonance** baut dir zwei ruhigere Feeds — nur mit Accounts, mit denen du
**wirklich** interagierst:

- **Echo** — Accounts, deren Beiträge du oft **likest**.
- **Amplify** — Accounts, die du oft **repostest oder zitierst**.

Technisch entstehen daraus zwei **Bluesky-Listen**, die du als Feed-Reiter
anpinnen kannst. Kein Server, kein Firehose — das Skript liest nur deine eigenen
Likes/Reposts und trägt die passenden Accounts in zwei Listen ein.

## So funktioniert die Auswahl (zeitgewichtet)

Jede Interaktion zählt, ältere aber weniger — so verschwinden Accounts, mit denen
du früher viel, heute nichts mehr zu tun hast:

> **Score = 1,0 × (letztes Jahr) + 0,5 × (1–2 Jahre) + 0,25 × (älter)**

Ein Account kommt in den Feed, wenn sein Score eine Schwelle überschreitet.
Schwellen und Gewichte stehen oben im Skript und sind frei einstellbar.

## Nutzung

### Variante A — im Browser, ohne Installation (empfohlen für Einsteiger:innen)

[![In Colab öffnen](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/foxymoronat/bluesky-resonance/blob/main/resonance.ipynb)

Auf den Knopf klicken → mit Google anmelden → Handle und App-Passwort eintippen →
„Alle ausführen". Läuft auf Googles Servern, nichts wird bei dir installiert.

### Variante B — lokal als Python-Skript

```bash
pip install atproto
# Handle oben im Skript eintragen, dann:
python resonance.py            # Bericht (schreibt nichts)
python resonance.py dry-run    # zeigt, was geschrieben würde
python resonance.py write      # legt die Listen an / aktualisiert sie
```

Zum Auffrischen einfach `write` erneut laufen lassen — die Listen werden
abgeglichen, es entstehen keine Duplikate.

## App-Passwort & Sicherheit

- Du brauchst ein **App-Passwort** (Bluesky → *Settings → Privacy and Security →
  App Passwords*). Das ist **nicht** dein echtes Passwort und jederzeit widerrufbar.
- Das Passwort wird **nur zur Laufzeit abgefragt** und **nirgends gespeichert**.
- Das Skript liest **ausschließlich dein eigenes Repo** und schreibt nur deine
  zwei Listen. Der Code ist offen — du kannst (oder jemand, der sich auskennt) genau
  nachlesen, was passiert.

## Roadmap

- [x] **Stufe 1** — persönliches Skript (Listen erzeugen & pflegen)
- [ ] **Stufe 2** — Colab-Notebook + dieses Repo für alle (FOSS)
- [ ] **Stufe 3** *(optional)* — echter Feed-Generator mit Firehose für Live-Updates

## Lizenz

MIT — siehe [LICENSE](LICENSE).

## Autor

Georg Hanisch · [foxymoron.at](https://foxymoron.at)
