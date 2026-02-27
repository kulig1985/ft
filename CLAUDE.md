# CLAUDE.md

Ez a fájl útmutatást ad a Claude Code (claude.ai/code) számára a repository-val való munkához.

## Projekt áttekintés

Freqtrade kereskedési platform Docker-alapú konfigurációja. Két használati mód:
- **Lokális (macOS)**: Backtesting, plotting, stratégia fejlesztés
- **VPS (Ubuntu)**: Live/dry-run trading (`freqtrade.kebodev.hu`)

## Munkakönyvtár struktúra

```
ft/
├── ft_userdata/
│   ├── docker-compose.yml      # Freqtrade konténer definíció
│   ├── .env                    # Érzékeny adatok (NEM COMMITOLNI!)
│   ├── .env.example            # Környezeti változók sablon
│   └── user_data/
│       ├── config.json         # Freqtrade konfiguráció
│       ├── strategies/         # Kereskedési stratégiák Python fájljai
│       ├── data/               # Historikus árfolyam adatok
│       ├── logs/               # Log fájlok
│       └── notebooks/          # Jupyter notebook-ok elemzéshez
```

## Gyakori parancsok

Minden parancsot a `ft_userdata/` könyvtárból futtass!

### Konténer kezelés
```bash
docker compose up -d              # Indítás háttérben
docker compose down               # Leállítás
docker compose restart            # Újraindítás
docker compose logs -f            # Logok követése
docker compose ps                 # Állapot ellenőrzése
docker compose pull && docker compose up -d  # Frissítés
```

### FreqUI Webserver mód (Backtesting UI-val)
```bash
docker compose run --rm -p 8080:8080 freqtrade webserver --config user_data/config.json.orignal
```
Elérhető: http://localhost:8080 - backtesting, plotting, adat letöltés böngészőből.

### Backtesting (parancssor)
```bash
docker compose run --rm freqtrade backtesting \
  --config user_data/config.json.orignal \
  --strategy StrategiaNeved \
  --timerange 20230101-20231231 \
  -i 5m
```

### Adat letöltés
```bash
docker compose run --rm freqtrade download-data \
  --pairs ETH/USDT BTC/USDT \
  --exchange binance \
  --days 30 \
  -t 5m 1h 1d
```

### Stratégiák listázása
```bash
docker compose run --rm freqtrade list-strategies
```

### Konfiguráció ellenőrzése
```bash
docker compose run --rm freqtrade show-config --config user_data/config.json.orignal
```

### Új konfiguráció generálása
```bash
docker compose run --rm freqtrade new-config --config user_data/config.json.orignal
```

### Plotting
```bash
docker compose run --rm freqtrade plot-dataframe \
  --strategy StrategiaNeved \
  -p BTC/USDT \
  --timerange 20240101-20240115
```
Kimenet: `user_data/plot/` (HTML fájl)

## Konfiguráció

- **Stratégia módosítás**: `docker-compose.yml` fájlban a `--strategy` paraméter
- **Exchange API kulcsok**: `.env` fájlban (lásd `.env.example` sablont)
- **API szerver (FreqUI)**: `user_data/config.json` - `api_server` szekció

## Architektúra

- Freqtrade hivatalos Docker image: `freqtradeorg/freqtrade:stable`
- GPU támogatás (FreqAI): `freqtradeorg/freqtrade:stable_freqaitorch` image
- API szerver: localhost:8080-on fut, Caddy reverse proxy biztosítja a HTTPS-t
- Adatbázis: SQLite (`user_data/tradesv3.sqlite`)
