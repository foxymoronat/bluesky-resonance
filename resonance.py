r"""
Resonance - baut zwei personalisierte Bluesky-Listen aus deinen Interaktionen.

  ECHO Resonance     = Accounts, die du oft GELIKED hast        (ab ECHO_SCHWELLE)
  AMPLIFY Resonance  = Accounts, die du oft REPOSTET/ZITIERT hast (ab AMPLIFY_SCHWELLE)

Drei Modi (das Wort hinten anhaengen):
  .\.venv\Scripts\python.exe resonance.py            -> nur BERICHT (schreibt nichts)
  .\.venv\Scripts\python.exe resonance.py dry-run    -> TROCKENLAUF: zeigt was es taete
  .\.venv\Scripts\python.exe resonance.py write      -> ECHT: Listen anlegen/aktualisieren

Wiederholtes Ausfuehren mit 'write' AKTUALISIERT die bestehenden Listen
(fuegt neue Accounts hinzu, entfernt nicht mehr passende) - es entstehen
keine Duplikate.
"""

import re
import sys
import getpass
from collections import Counter
from datetime import datetime, timezone, timedelta

from atproto import Client, models


# --- Konfiguration ---------------------------------------------------------
HANDLE = "georghanisch.org"   # dein Bluesky-Handle (ohne @)

ECHO_SCHWELLE = 10           # nur fuer die INFO-Tabellen (report/zeit): Roh-Likes
AMPLIFY_SCHWELLE = 3         # nur fuer die INFO-Tabellen (report/zeit): Roh-Reposts

TOP_N = 40                   # Berichts-Tabelle: so viele Accounts zeigen

# Gewichte fuer die zeitgewichtete Auswahl (auch fuer dry-run/write):
W_NEU = 1.0      # Aktion < 1 Jahr her
W_MITTEL = 0.5   # Aktion 1 - 2 Jahre her
W_ALT = 0.25     # Aktion > 2 Jahre her

# Score-Schwellen, ab denen ein Account in die jeweilige Liste kommt (dry-run/write):
ECHO_SCORE_MIN = 6       # gewichteter Score fuer "Echo Resonance"
AMPLIFY_SCORE_MIN = 1.5  # gewichteter Score fuer "Amplify Resonance"

def _de_zahl(z):
    """Zahl deutsch darstellen: 6 -> '6', 1.5 -> '1,5'."""
    return str(z).replace(".", ",")

ECHO_NAME = "Echo Resonance"
ECHO_BESCHREIBUNG = (
    "Accounts, deren Beiträge ich oft like – zeitgewichtet: Likes aus dem letzten "
    "Jahr zählen voll, 1–2 Jahre alte halb, ältere ein Viertel. Aufgenommen ab Score "
    f"{_de_zahl(ECHO_SCORE_MIN)}. Regelmäßig aktualisiert mit meinem Python-Skript Resonance."
)
AMPLIFY_NAME = "Amplify Resonance"
AMPLIFY_BESCHREIBUNG = (
    "Accounts, die ich oft reposte oder zitiere – zeitgewichtet: das letzte Jahr zählt "
    "voll, 1–2 Jahre halb, älteres ein Viertel. Aufgenommen ab Score "
    f"{_de_zahl(AMPLIFY_SCORE_MIN)}. Regelmäßig aktualisiert mit meinem Python-Skript Resonance."
)


# === Hilfsfunktionen =======================================================

def jetzt_iso():
    """Aktuelle Zeit im von Bluesky erwarteten Format (z.B. 2026-06-21T19:30:00Z)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def alle_records(client, repo, collection):
    """Liefert nacheinander ALLE Records einer Sammlung (seitenweise je 100)."""
    cursor = None
    while True:
        antwort = client.com.atproto.repo.list_records({
            "repo": repo, "collection": collection, "limit": 100, "cursor": cursor,
        })
        for record in antwort.records:
            yield record
        cursor = antwort.cursor
        if not cursor:
            break


def autor_did_aus_uri(uri):
    """Autor-DID aus einer Beitrags-Adresse holen.
    at://did:plc:ABC/app.bsky.feed.post/xyz -> 'did:plc:ABC'. Sonst None."""
    teile = uri.split("/")
    if len(teile) >= 4 and teile[3] == "app.bsky.feed.post":
        return teile[2]
    return None


def parse_zeit(s):
    """Wandelt einen Bluesky-Zeitstempel in ein datetime um (Python-3.10-tauglich)."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    # Bruchteilssekunden auf 6 Stellen normalisieren, sonst stolpert 3.10
    m = re.match(r"(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", s)
    if m:
        basis, frac, rest = m.groups()
        frac = (frac + "000000")[:7] if frac else ""
        s = basis + frac + rest
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def handles_holen(client, dids):
    """DIDs -> Handles (fuer die Anzeige), in Paketen zu 25."""
    ergebnis = {}
    dids = list(dids)
    for i in range(0, len(dids), 25):
        for p in client.app.bsky.actor.get_profiles({"actors": dids[i:i + 25]}).profiles:
            ergebnis[p.did] = p.handle
    return ergebnis


# === Zaehlen ===============================================================

def zaehle_echo(client, eigene_did):
    print("Lese Likes ...")
    echo = Counter()
    for record in alle_records(client, HANDLE, "app.bsky.feed.like"):
        did = autor_did_aus_uri(record.value.subject.uri)
        if did and did != eigene_did:
            echo[did] += 1
    print(f"  {sum(echo.values())} Likes auf {len(echo)} Accounts.")
    return echo


def zaehle_amplify(client, eigene_did):
    print("Lese Reposts ...")
    amplify = Counter()
    for record in alle_records(client, HANDLE, "app.bsky.feed.repost"):
        did = autor_did_aus_uri(record.value.subject.uri)
        if did and did != eigene_did:
            amplify[did] += 1

    print("Lese eigene Posts (fuer Zitate) ...")
    for record in alle_records(client, HANDLE, "app.bsky.feed.post"):
        embed = getattr(record.value, "embed", None)
        if embed is None:
            continue
        py_type = getattr(embed, "py_type", None)
        zitierte_uri = None
        if py_type == "app.bsky.embed.record":
            zitierte_uri = getattr(embed.record, "uri", None)
        elif py_type == "app.bsky.embed.recordWithMedia":
            inner = getattr(embed.record, "record", None)
            zitierte_uri = getattr(inner, "uri", None)
        if zitierte_uri:
            did = autor_did_aus_uri(zitierte_uri)
            if did and did != eigene_did:
                amplify[did] += 1
    print(f"  AMPLIFY gesamt: {sum(amplify.values())} auf {len(amplify)} Accounts.")
    return amplify


# === Zeitfenster-Analyse (Echo UND Amplify) ================================

def _echo_stream(client, eigene_did):
    """Liefert (autor_did, zeitstempel) fuer jedes Like."""
    for record in alle_records(client, HANDLE, "app.bsky.feed.like"):
        did = autor_did_aus_uri(record.value.subject.uri)
        if did and did != eigene_did:
            yield did, parse_zeit(getattr(record.value, "created_at", None))


def _amplify_stream(client, eigene_did):
    """Liefert (autor_did, zeitstempel) fuer jeden Repost und jedes Zitat."""
    for record in alle_records(client, HANDLE, "app.bsky.feed.repost"):
        did = autor_did_aus_uri(record.value.subject.uri)
        if did and did != eigene_did:
            yield did, parse_zeit(getattr(record.value, "created_at", None))
    for record in alle_records(client, HANDLE, "app.bsky.feed.post"):
        embed = getattr(record.value, "embed", None)
        if embed is None:
            continue
        py_type = getattr(embed, "py_type", None)
        zitierte_uri = None
        if py_type == "app.bsky.embed.record":
            zitierte_uri = getattr(embed.record, "uri", None)
        elif py_type == "app.bsky.embed.recordWithMedia":
            inner = getattr(embed.record, "record", None)
            zitierte_uri = getattr(inner, "uri", None)
        if zitierte_uri:
            did = autor_did_aus_uri(zitierte_uri)
            if did and did != eigene_did:
                # Zeit des Zitats = Datum deines zitierenden Posts
                yield did, parse_zeit(getattr(record.value, "created_at", None))


def _buckets_aus(stream, grenze_1j, grenze_2j):
    """Verteilt einen Strom von (did, ts) auf Zeitfenster-Zaehler."""
    letztes_jahr, ein_bis_zwei, gesamt = Counter(), Counter(), Counter()
    ohne_datum = 0
    aeltester = None
    for did, ts in stream:
        gesamt[did] += 1
        if ts is None:
            ohne_datum += 1
            continue
        if aeltester is None or ts < aeltester:
            aeltester = ts
        if ts >= grenze_1j:
            letztes_jahr[did] += 1
        elif ts >= grenze_2j:
            ein_bis_zwei[did] += 1
    return letztes_jahr, ein_bis_zwei, gesamt, ohne_datum, aeltester


def _zeit_tabelle(titel, letztes_jahr, ein_bis_zwei, gesamt, ohne_datum, aeltester,
                  schwellen, jetzige):
    letzte_2j = Counter()
    for d in set(letztes_jahr) | set(ein_bis_zwei):
        letzte_2j[d] = letztes_jahr[d] + ein_bis_zwei[d]

    def n_ab(z, s):
        return sum(1 for v in z.values() if v >= s)

    print("\n" + "=" * 66)
    print(titel)
    print("=" * 66)
    print(f"  insgesamt {sum(gesamt.values())} Aktionen auf {len(gesamt)} Accounts "
          f"| letztes Jahr: {sum(letztes_jahr.values())} | 1-2 J.: {sum(ein_bis_zwei.values())}")
    if aeltester:
        print(f"  aelteste Aktion: {aeltester.date()}")
    if ohne_datum:
        print(f"  (ohne lesbares Datum: {ohne_datum})")
    print(f"\n{'Schwelle':>9} | {'letztes Jahr':>13} | {'1-2 Jahre':>10} | "
          f"{'letzte 2 J.':>11} | {'gesamt':>7}")
    print("-" * 66)
    for s in schwellen:
        marke = "  <- aktuell" if s == jetzige else ""
        print(f"{s:>9} | {n_ab(letztes_jahr, s):>13} | {n_ab(ein_bis_zwei, s):>10} | "
              f"{n_ab(letzte_2j, s):>11} | {n_ab(gesamt, s):>7}{marke}")


def gewichtete_werte(stream, g1, g2):
    """Pro Account: Anzahl je Zeitfenster (u/m/o) und gewichteter Score."""
    u, m, o = Counter(), Counter(), Counter()   # unter 1J / 1-2J / ueber 2J
    ohne_datum = 0
    for did, ts in stream:
        if ts is None:
            ohne_datum += 1
            o[did] += 1            # ohne Datum: als "alt" werten (geringstes Gewicht)
            continue
        if ts >= g1:
            u[did] += 1
        elif ts >= g2:
            m[did] += 1
        else:
            o[did] += 1
    score = {}
    for did in set(u) | set(m) | set(o):
        score[did] = W_NEU * u[did] + W_MITTEL * m[did] + W_ALT * o[did]
    return u, m, o, score, ohne_datum


def gewicht_tabelle(client, titel, u, m, o, score, schwellen):
    def n_ab(s):
        return sum(1 for v in score.values() if v >= s)

    print("\n" + "=" * 70)
    print(titel)
    print("=" * 70)
    print(f"  {len(score)} Accounts insgesamt | Formel: "
          f"{W_NEU}*neu + {W_MITTEL}*mittel + {W_ALT}*alt")

    print(f"\n  Score-Schwelle | Accounts")
    print("  " + "-" * 26)
    for s in schwellen:
        print(f"  {s:>13} | {n_ab(s)}")

    # Top-Accounts mit Aufschluesselung, um die Rangfolge zu beurteilen
    top = sorted(score.items(), key=lambda kv: kv[1], reverse=True)[:25]
    handles = handles_holen(client, [d for d, _ in top])
    print(f"\n  Top 25 nach Score   (neu/mittel/alt -> Score)")
    print("  " + "-" * 56)
    for did, sc in top:
        print(f"  {sc:>6.2f}   ({u[did]:>3}/{m[did]:>3}/{o[did]:>3})   @{handles.get(did, did)}")


def gewicht_analyse(client, eigene_did):
    jetzt = datetime.now(timezone.utc)
    g1 = jetzt - timedelta(days=365)
    g2 = jetzt - timedelta(days=730)

    print("Lese Likes mit Zeitstempel ...")
    u, m, o, score, _ = gewichtete_werte(_echo_stream(client, eigene_did), g1, g2)
    gewicht_tabelle(client, "ECHO (Likes) - gewichteter Score",
                    u, m, o, score, (2.5, 5, 7.5, 10, 15, 20))

    print("\nLese Reposts + eigene Posts (fuer Zitate) ...")
    u, m, o, score, _ = gewichtete_werte(_amplify_stream(client, eigene_did), g1, g2)
    gewicht_tabelle(client, "AMPLIFY (Reposts + Zitate) - gewichteter Score",
                    u, m, o, score, (1, 1.5, 2, 3, 5, 10))


def zeit_analyse(client, eigene_did):
    jetzt = datetime.now(timezone.utc)
    g1 = jetzt - timedelta(days=365)   # Grenze: 1 Jahr her
    g2 = jetzt - timedelta(days=730)   # Grenze: 2 Jahre her

    print("Lese Likes mit Zeitstempel ...")
    lj, ez, ge, od, ae = _buckets_aus(_echo_stream(client, eigene_did), g1, g2)
    _zeit_tabelle("ECHO (Likes) - Accounts je Zeitfenster",
                  lj, ez, ge, od, ae, (3, 5, 10, 15, 20), ECHO_SCHWELLE)

    print("\nLese Reposts + eigene Posts (fuer Zitate) mit Zeitstempel ...")
    lj, ez, ge, od, ae = _buckets_aus(_amplify_stream(client, eigene_did), g1, g2)
    _zeit_tabelle("AMPLIFY (Reposts + Zitate) - Accounts je Zeitfenster",
                  lj, ez, ge, od, ae, (1, 2, 3, 5, 10), AMPLIFY_SCHWELLE)

    print("\n" + "-" * 66)
    print("Lesehilfe: 'letztes Jahr' = so gross waere der Feed, wenn NUR das letzte")
    print("Jahr zaehlt. 'gesamt' = deine jetzigen Listen. Spalte '<- aktuell' = deine")
    print("derzeit gewaehlte Schwelle.")


# === Listen lesen/anlegen/synchronisieren ==================================

def finde_liste(client, eigene_did, name):
    """Sucht eine bestehende Liste mit diesem Namen. Gibt den Record oder None."""
    for record in alle_records(client, eigene_did, "app.bsky.graph.list"):
        if record.value.name == name:
            return record
    return None


def aktualisiere_beschreibung(client, eigene_did, gefunden, name, beschreibung):
    """Schreibt Name/Beschreibung einer bestehenden Liste neu (createdAt bleibt erhalten)."""
    client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=eigene_did,
            collection=models.ids.AppBskyGraphList,
            rkey=gefunden.uri.split("/")[-1],
            record=models.AppBskyGraphList.Record(
                purpose="app.bsky.graph.defs#curatelist",
                name=name,
                description=beschreibung,
                created_at=getattr(gefunden.value, "created_at", jetzt_iso()),
            ),
        )
    )


def erstelle_liste(client, eigene_did, name, beschreibung):
    res = client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=eigene_did,
            collection=models.ids.AppBskyGraphList,
            record=models.AppBskyGraphList.Record(
                purpose="app.bsky.graph.defs#curatelist",
                name=name,
                description=beschreibung,
                created_at=jetzt_iso(),
            ),
        )
    )
    return res.uri


def aktuelle_mitglieder(client, eigene_did, list_uri):
    """Liefert {DID: listitem_uri} aller aktuell in der Liste eingetragenen Accounts."""
    ergebnis = {}
    for record in alle_records(client, eigene_did, "app.bsky.graph.listitem"):
        if record.value.list == list_uri:
            ergebnis[record.value.subject] = record.uri
    return ergebnis


def sync_liste(client, eigene_did, list_uri, ziel_dids):
    """Bringt die Liste auf den Soll-Stand: fehlende hinzu, ueberzaehlige raus."""
    aktuell = aktuelle_mitglieder(client, eigene_did, list_uri)
    ziel = set(ziel_dids)
    hinzu = list(ziel - set(aktuell.keys()))
    entfernen = list(set(aktuell.keys()) - ziel)

    for i in range(0, len(hinzu), 100):
        writes = [
            models.ComAtprotoRepoApplyWrites.Create(
                collection=models.ids.AppBskyGraphListitem,
                value=models.AppBskyGraphListitem.Record(
                    subject=did, list=list_uri, created_at=jetzt_iso()
                ),
            )
            for did in hinzu[i:i + 100]
        ]
        client.com.atproto.repo.apply_writes(
            models.ComAtprotoRepoApplyWrites.Data(repo=eigene_did, writes=writes)
        )

    for i in range(0, len(entfernen), 100):
        writes = [
            models.ComAtprotoRepoApplyWrites.Delete(
                collection=models.ids.AppBskyGraphListitem,
                rkey=aktuell[did].split("/")[-1],
            )
            for did in entfernen[i:i + 100]
        ]
        client.com.atproto.repo.apply_writes(
            models.ComAtprotoRepoApplyWrites.Data(repo=eigene_did, writes=writes)
        )

    return len(hinzu), len(entfernen)


# === Ausgabe (Berichtsmodus) ==============================================

def bericht(client, echo, amplify):
    anzuzeigen = {d for d, _ in echo.most_common(TOP_N)} | {d for d, _ in amplify.most_common(TOP_N)}
    handles = handles_holen(client, anzuzeigen)

    def tabelle(titel, zaehler):
        print("\n" + "=" * 60 + f"\n{titel}\n" + "=" * 60)
        for platz, (did, anzahl) in enumerate(zaehler.most_common(TOP_N), start=1):
            print(f"{platz:>4}.  {anzahl:>4}x  @{handles.get(did, did)}")
        if len(zaehler) > TOP_N:
            print(f"      ... und {len(zaehler) - TOP_N} weitere")

    def schwellen(titel, zaehler, werte):
        print("\n" + "-" * 60 + f"\n{titel}\n" + "-" * 60)
        for s in werte:
            print(f"  ab {s:>3}:  {sum(1 for v in zaehler.values() if v >= s)} Accounts")

    tabelle("ECHO  -  am haeufigsten GELIKED (Top 40)", echo)
    schwellen("ECHO: Accounts pro Schwellenwert", echo, (1, 2, 3, 5, 10, 20))
    tabelle("AMPLIFY  -  am haeufigsten REPOSTET/ZITIERT (Top 40)", amplify)
    schwellen("AMPLIFY: Accounts pro Schwellenwert", amplify, (1, 2, 3, 5, 10))


# === Hauptprogramm =========================================================

ERLAUBTE_MODI = ("report", "dry-run", "write", "zeit", "gewichtet")


def run(handle, app_password, modus):
    """Verbindet sich mit Bluesky und fuehrt den gewuenschten Modus aus.
    Wird von der Kommandozeile (main) UND vom Colab-Notebook genutzt."""
    global HANDLE
    HANDLE = handle   # alle Funktionen lesen das Handle aus dieser globalen Variable

    if modus not in ERLAUBTE_MODI:
        print("Unbekannter Modus. Erlaubt:", " | ".join(ERLAUBTE_MODI))
        return

    client = Client()
    try:
        client.login(handle, app_password)
    except Exception as fehler:
        print("\nLOGIN FEHLGESCHLAGEN. Pruefe App-Passwort (19 Zeichen, mit Bindestrichen).")
        print("Technische Meldung:", fehler)
        return
    eigene_did = client.me.did
    print(f"Verbunden als {handle}.  Modus: {modus.upper()}\n")

    if modus == "zeit":
        zeit_analyse(client, eigene_did)
        return

    if modus == "gewichtet":
        gewicht_analyse(client, eigene_did)
        return

    if modus == "report":
        echo = zaehle_echo(client, eigene_did)
        amplify = zaehle_amplify(client, eigene_did)
        bericht(client, echo, amplify)
        return

    # --- dry-run / write: ZEITGEWICHTETE Auswahl --------------------------
    jetzt = datetime.now(timezone.utc)
    g1 = jetzt - timedelta(days=365)
    g2 = jetzt - timedelta(days=730)

    print("Berechne gewichtete Scores aus Likes ...")
    _, _, _, echo_score, _ = gewichtete_werte(_echo_stream(client, eigene_did), g1, g2)
    print("Berechne gewichtete Scores aus Reposts + Zitaten ...")
    _, _, _, amplify_score, _ = gewichtete_werte(_amplify_stream(client, eigene_did), g1, g2)

    echo_ziel = [d for d, sc in echo_score.items() if sc >= ECHO_SCORE_MIN]
    amplify_ziel = [d for d, sc in amplify_score.items() if sc >= AMPLIFY_SCORE_MIN]

    aufgaben = [
        (ECHO_NAME, ECHO_BESCHREIBUNG, echo_ziel, ECHO_SCORE_MIN),
        (AMPLIFY_NAME, AMPLIFY_BESCHREIBUNG, amplify_ziel, AMPLIFY_SCORE_MIN),
    ]

    print("\n" + "#" * 60)
    for name, beschreibung, ziel, schwelle in aufgaben:
        print(f"\n>>> {name}  (Score >= {schwelle}, {len(ziel)} Soll-Accounts)")
        gefunden = finde_liste(client, eigene_did, name)

        if modus == "dry-run":
            if gefunden is None:
                print(f"    WUERDE die Liste NEU anlegen und {len(ziel)} Accounts eintragen.")
                # ein paar Beispiele zeigen, damit es greifbar ist
                beispiele = handles_holen(client, ziel[:12])
                for did in ziel[:12]:
                    print(f"      + @{beispiele.get(did, did)}")
                if len(ziel) > 12:
                    print(f"      ... und {len(ziel) - 12} weitere")
            else:
                aktuell = aktuelle_mitglieder(client, eigene_did, gefunden.uri)
                hinzu = len(set(ziel) - set(aktuell))
                raus = len(set(aktuell) - set(ziel))
                print(f"    Liste existiert. WUERDE Beschreibung aktualisieren,")
                print(f"    {hinzu} Accounts hinzufuegen, {raus} entfernen.")
            print("    (Trockenlauf - es wurde NICHTS geschrieben.)")
        else:  # write
            if gefunden is None:
                uri = erstelle_liste(client, eigene_did, name, beschreibung)
                print(f"    Liste neu angelegt.")
            else:
                uri = gefunden.uri
                aktualisiere_beschreibung(client, eigene_did, gefunden, name, beschreibung)
                print(f"    Liste gefunden, Beschreibung aktualisiert.")
            hinzu, raus = sync_liste(client, eigene_did, uri, ziel)
            print(f"    Fertig: {hinzu} hinzugefuegt, {raus} entfernt.")
            print(f"    -> In Bluesky unter 'Listen' oeffnen und 'Pin to Home' tippen.")

    print("\n" + "#" * 60)
    if modus == "dry-run":
        print("Sieht gut aus? Dann nochmal mit  write  statt  dry-run  starten.")


def main():
    """Einstieg fuer die Kommandozeile: Modus aus dem Aufruf, Passwort abfragen."""
    modus = sys.argv[1].lower() if len(sys.argv) > 1 else "report"
    if modus not in ERLAUBTE_MODI:
        print("Unbekannter Modus. Erlaubt: (nichts) | zeit | gewichtet | dry-run | write")
        return
    app_password = getpass.getpass(f"App-Passwort fuer {HANDLE} (unsichtbar): ").strip()
    print(f"  (Eingabe erhalten: {len(app_password)} Zeichen - sollten 19 sein)")
    run(HANDLE, app_password, modus)


if __name__ == "__main__":
    main()
