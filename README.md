# poisson-picks-monitor

Detector de value bets: compara la cuota de cierre de Pinnacle (devigada,
referencia "sharp") contra Bet365, vía [OddsPapi](https://oddspapi.io).
Corre en GitHub Actions, 3 veces al día (9:00, 15:00, 21:00 UTC) — no
depende de que ninguna PC este encendida.

Enfoque validado con backtest historico en el proyecto principal
(`poisson_picks/docs/decisions/2026-08-03_nuevo_enfoque_closing_line_value.md`).

## Setup

1. En este repo, ve a **Settings -> Secrets and variables -> Actions** y
   agrega un secret llamado `ODDSPAPI_KEY` con tu API key de OddsPapi.
2. Listo — el workflow ya esta configurado para correr solo.

## Que hace

- Consulta 5 ligas en temporada (Premier League, MLS, Brasileirao,
  Eliteserien, Allsvenskan) contra Pinnacle y Bet365.
- Si encuentra un value bet con EV >= 5% que no habia visto antes, lo
  guarda en `value_bets_log.csv` (se commitea automaticamente) y crea un
  **Issue** en este repo -- eso te llega como notificacion de GitHub
  (email / app movil si tienes la app instalada y las notificaciones
  activas).
- Solo detecta. No coloca ninguna apuesta.

## Correr manualmente

Pestaña **Actions** -> "Check value bets" -> **Run workflow**.
