# CLAUDE.md

Ez a fájl útmutatást ad a Claude Code (claude.ai/code) számára a repository-val való munkához.

## Projekt áttekintés

Freqtrade kereskedési platform Docker-alapú konfigurációja. Két használati mód:
- **Lokális (macOS)**: Backtesting, plotting, stratégia fejlesztés
- **VPS (Ubuntu)**: Live/dry-run trading (`freqtrade.kebodev.hu`, `freqtrade-rb.kebodev.hu`)

## Munkakönyvtár struktúra

Minden stratégiának saját almappája van `user_data/strategies/` alatt, saját `.env`, `config.json`, logok és DB-vel. A historikus adatok (`data/`) közösek.

```
ft/
└── ft_userdata/
    ├── docker-compose.yml
    └── user_data/
        ├── data/                               # Közös historikus adatok
        └── strategies/
            ├── bb_rsi_adx/                     # BBRsiAdxStrategy
            │   ├── .env                        # Saját Telegram token (NEM GITBE!)
            │   ├── config.json                 # Saját konfig (NEM GITBE!)
            │   ├── BBRsiAdxStrategy.py
            │   └── logs/
            └── range_breakout/                 # RangeBreakoutPullbackStrategy
                ├── .env
                ├── config.json
                ├── RangeBreakoutPullbackStrategy.py
                └── logs/
```

## Gyakori parancsok

Minden parancsot a `ft_userdata/` könyvtárból futtass!

### Konténer kezelés
```bash
docker compose up -d                    # Összes indítás
docker compose up -d freqtrade_bb       # Csak egy stratégia
docker compose down                     # Leállítás
docker compose restart freqtrade_rb     # Egy stratégia újraindítása
docker compose logs -f freqtrade_bb     # Egy stratégia logja
docker compose ps                       # Állapot
docker compose pull && docker compose up -d  # Frissítés
```

### FreqUI Webserver mód (Backtesting UI-val)
```bash
docker compose run --rm -p 8080:8080 freqtrade_bb webserver \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal
```

### Backtesting (parancssor)
```bash
docker compose run --rm freqtrade_bb backtesting \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --strategy BBRsiAdxStrategy \
  --timerange 20230101-20231231 \
  -i 1h
```

### Adat letöltés (közös data/ mappába)
```bash
docker compose run --rm freqtrade_bb download-data \
  --pairs ETH/USDT BTC/USDT \
  --exchange binance \
  --days 30 \
  -t 5m 1h 1d
```

## Konfiguráció

- **Stratégia konfig**: `user_data/strategies/<nev>/config.json` (NEM megy gitbe)
- **Érzékeny adatok**: `user_data/strategies/<nev>/.env` (NEM megy gitbe)
- **Docker service-ek**: `docker-compose.yml` - konténerenként saját .env és config
- `.env` felülírja a `config.json` értékeket

## Architektúra

- Freqtrade Docker image: `freqtradeorg/freqtrade:stable`
- Stratégiánként külön konténer, külön port, külön Telegram bot, külön DB
- BBRsiAdx: localhost:8080 / freqtrade.kebodev.hu
- RangeBreakout: localhost:8081 / freqtrade-rb.kebodev.hu
- Caddy reverse proxy biztosítja a HTTPS-t (VPS-en)
