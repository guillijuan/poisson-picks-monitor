# check_value_bets.py
"""Corre en GitHub Actions (sin PC local). Compara la cuota de cierre de
Pinnacle (devigada, referencia "sharp") contra Bet365 para detectar value
bets, y avisa creando un Issue de GitHub cuando encuentra algo nuevo.

Enfoque validado en poisson_picks/docs/decisions/2026-08-03_nuevo_enfoque_closing_line_value.md
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

API_KEY = os.environ["ODDSPAPI_KEY"]
BASE_URL = "https://api.oddspapi.io"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"

MONEYLINE_MARKET_ID = "101"
SOFT_BOOKMAKER = "bet365"
EV_MIN = 0.05

TOURNAMENTS = {
    17: "England Premier League",
    242: "MLS (USA)",
    325: "Brasileiro Serie A",
    20: "Eliteserien (Noruega)",
    40: "Allsvenskan (Suecia)",
}

LOG_PATH = "value_bets_log.csv"
LOG_FIELDS = [
    "detected_at", "tournament", "fixture_id", "start_time", "side", "soft_odds",
    "pinnacle_fair_prob", "ev", "status", "actual_result", "profit",
]


def fetch_odds(bookmaker, tournament_ids, retries=3):
    ids = ",".join(str(t) for t in tournament_ids)
    for attempt in range(retries):
        r = requests.get(
            f"{BASE_URL}/v4/odds-by-tournaments",
            params={"bookmaker": bookmaker, "tournamentIds": ids, "apiKey": API_KEY},
            timeout=30,
        )
        if r.status_code == 429 and attempt < retries - 1:
            wait = 5 * (attempt + 1)
            print(f"  429 de OddsPapi, reintentando en {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


# Las claves de outcome del market "101" (1X2) son consistentes ENTRE casas
# de apuestas: "101"=home, "102"=draw, "103"=away. El campo bookmakerOutcomeId
# NO lo es -- Pinnacle lo etiqueta como texto ("home"/"draw"/"away"), pero
# Bet365 (y probablemente otras) usan ahi su ID interno numerico. Verificado
# a mano comparando las respuestas crudas de ambas casas para el mismo
# fixture: mismo orden 101/102/103, mismos favoritos.
OUTCOME_KEY_TO_SIDE = {"101": "home", "102": "draw", "103": "away"}


def extract_1x2(fixture, bookmaker):
    odds = fixture.get("bookmakerOdds", {}).get(bookmaker, {})
    if odds.get("suspended"):
        return None
    market = odds.get("markets", {}).get(MONEYLINE_MARKET_ID)
    if not market or not market.get("marketActive", True):
        return None
    prices = {}
    for outcome_key, outcome in market.get("outcomes", {}).items():
        side = OUTCOME_KEY_TO_SIDE.get(outcome_key)
        if not side:
            continue
        player = outcome.get("players", {}).get("0", {})
        price = player.get("price")
        if price:
            prices[side] = price
    if set(prices.keys()) != {"home", "draw", "away"}:
        return None
    return prices


def devig(prices):
    imp = {k: 1 / v for k, v in prices.items()}
    total = sum(imp.values())
    return {k: v / total for k, v in imp.items()}


def already_logged(fixture_id, side):
    if not os.path.exists(LOG_PATH):
        return False
    with open(LOG_PATH, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["fixture_id"] == fixture_id and row["side"] == side:
                return True
    return False


def log_value_bet(row):
    is_new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if is_new_file:
            writer.writeheader()
        writer.writerow(row)


def create_github_issue(title, body):
    if not (GITHUB_TOKEN and GITHUB_REPOSITORY):
        print("  (sin GITHUB_TOKEN/repo, no se crea Issue)")
        return
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body},
        timeout=20,
    )
    if r.status_code >= 300:
        print(f"  Error creando Issue: {r.status_code} {r.text[:300]}")
    else:
        print(f"  Issue creado: {r.json().get('html_url')}")


def main():
    if os.environ.get("TEST_ISSUE", "").lower() in ("true", "1"):
        print("TEST_ISSUE activado: creando Issue de prueba (simulando al bot) y saliendo.")
        create_github_issue(
            "Prueba de notificacion (creado por el bot)",
            "Issue de prueba disparado manualmente con test_issue=true, para confirmar que "
            "el correo SI llega cuando el actor es github-actions[bot] y no tu usuario. "
            "Se puede cerrar despues de confirmar.",
        )
        return

    tournament_ids = list(TOURNAMENTS.keys())

    try:
        pinnacle_data = fetch_odds("pinnacle", tournament_ids)
        time.sleep(3)
        soft_data = fetch_odds(SOFT_BOOKMAKER, tournament_ids)
    except requests.RequestException as e:
        print(f"Error consultando OddsPapi: {e}")
        sys.exit(1)

    soft_by_id = {fx["fixtureId"]: fx for fx in soft_data}
    print(f"Partidos con cuotas Pinnacle: {len(pinnacle_data)}")

    new_hits = []
    for fx in pinnacle_data:
        pin_prices = extract_1x2(fx, "pinnacle")
        if not pin_prices:
            continue
        soft_fx = soft_by_id.get(fx["fixtureId"])
        if not soft_fx:
            continue
        soft_prices = extract_1x2(soft_fx, SOFT_BOOKMAKER)
        if not soft_prices:
            continue

        fair = devig(pin_prices)
        tournament_name = TOURNAMENTS.get(fx.get("tournamentId"), "?")

        for side in ("home", "draw", "away"):
            ev = fair[side] * soft_prices[side] - 1
            if ev >= EV_MIN and not already_logged(fx["fixtureId"], side):
                row = {
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "tournament": tournament_name,
                    "fixture_id": fx["fixtureId"],
                    "start_time": fx["startTime"],
                    "side": side,
                    "soft_odds": soft_prices[side],
                    "pinnacle_fair_prob": round(fair[side], 4),
                    "ev": round(ev, 4),
                    "status": "pending",
                    "actual_result": "",
                    "profit": "",
                }
                log_value_bet(row)
                new_hits.append(row)
                print(f"  VALOR NUEVO | {tournament_name} | {side.upper()} @ {soft_prices[side]:.2f} | EV={ev:+.3f}")

    print(f"Nuevos value bets: {len(new_hits)}")

    if new_hits:
        lines = [
            f"- **{h['tournament']}** | {h['side'].upper()} @ {h['soft_odds']} "
            f"(EV {h['ev']:+.1%}, kickoff {h['start_time']})"
            for h in new_hits
        ]
        body = "\n".join(lines) + f"\n\nDetectado: {datetime.now(timezone.utc).isoformat()}"
        create_github_issue(f"{len(new_hits)} value bet(s) nuevo(s)", body)


if __name__ == "__main__":
    main()
