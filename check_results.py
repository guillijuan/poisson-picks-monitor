# check_results.py
"""Paper trading: resuelve los value bets 'pending' en value_bets_log.csv
buscando el resultado final del partido (GET /v4/scores) y calculando la
ganancia/perdida hipotetica (1 unidad de stake, sin apostar plata real).

Corre 1 vez al dia, varias horas despues de los kickoffs para dar tiempo a
que los partidos terminen.
"""

import csv
import os
import time
from datetime import datetime, timedelta, timezone

import requests

API_KEY = os.environ["ODDSPAPI_KEY"]
BASE_URL = "https://api.oddspapi.io"

LOG_PATH = "value_bets_log.csv"
MIN_HOURS_SINCE_KICKOFF = 3  # margen para que el partido termine


def fetch_score(fixture_id):
    r = requests.get(
        f"{BASE_URL}/v4/scores",
        params={"fixtureId": fixture_id, "apiKey": API_KEY},
        timeout=20,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def determine_result(home_goals, away_goals):
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def main():
    if not os.path.exists(LOG_PATH):
        print("Sin log todavia, nada que resolver.")
        return

    with open(LOG_PATH, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("Log vacio.")
        return

    now = datetime.now(timezone.utc)
    resolved_count = 0
    score_cache = {}

    for row in rows:
        if row.get("status") != "pending":
            continue

        try:
            start = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
        except ValueError:
            continue

        if now < start + timedelta(hours=MIN_HOURS_SINCE_KICKOFF):
            continue  # el partido probablemente no ha terminado

        fixture_id = row["fixture_id"]
        if fixture_id not in score_cache:
            try:
                score_cache[fixture_id] = fetch_score(fixture_id)
            except requests.RequestException as e:
                print(f"  Error consultando score de {fixture_id}: {e}")
                score_cache[fixture_id] = None
            time.sleep(1.1)  # cooldown documentado del endpoint

        data = score_cache[fixture_id]
        if not data or not data.get("scores"):
            continue  # todavia sin resultado disponible

        # La respuesta real de /v4/scores usa claves con nombre ("fulltime",
        # "result", "p1"...), NO numericas como "0"/"1" (eso era de otro
        # endpoint). Verificado a mano: "fulltime" = marcador final.
        ft = data["scores"].get("periods", {}).get("fulltime")
        if not ft:
            continue

        home_goals = ft["participant1Score"]
        away_goals = ft["participant2Score"]
        actual = determine_result(home_goals, away_goals)

        win = row["side"] == actual
        odds = float(row["soft_odds"])
        profit = (odds - 1) if win else -1.0

        row["status"] = "resuelto"
        row["actual_result"] = f"{actual} ({home_goals}-{away_goals})"
        row["profit"] = round(profit, 3)
        resolved_count += 1
        print(f"  Resuelto: {row['tournament']} | {row['side']} | real={actual} | profit={profit:+.2f}")

    if resolved_count:
        with open(LOG_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n{resolved_count} value bet(s) resueltos y guardados.")
    else:
        print("\nNada que resolver todavia.")

    # Resumen acumulado de paper trading
    resolved = [r for r in rows if r.get("status") == "resuelto" and r.get("profit") not in (None, "")]
    if resolved:
        total_profit = sum(float(r["profit"]) for r in resolved)
        wins = sum(1 for r in resolved if float(r["profit"]) > 0)
        print(f"\n=== PAPER TRADING ACUMULADO ===")
        print(f"Apuestas resueltas: {len(resolved)} | Win rate: {wins/len(resolved):.1%} | "
              f"Profit total: {total_profit:+.2f}u | ROI: {100*total_profit/len(resolved):+.1f}%")


if __name__ == "__main__":
    main()
