# CLAUDE.md

Ez a fájl útmutatást ad a Claude Code (claude.ai/code) számára a repository-val való munkához.

## Projekt áttekintés

Ez egy Freqtrade kereskedési platform Docker-alapú konfigurációja. A projekt célja: kriptovaluta kereskedési bot futtatása Ubuntu VPS-en Caddy reverse proxy mögött (`freqtrade.kebodev.hu`).

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

### Backtesting
```bash
docker compose run --rm freqtrade backtesting \
  --config user_data/config.json \
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
docker compose run --rm freqtrade show-config --config user_data/config.json
```

### Új konfiguráció generálása
```bash
docker compose run --rm freqtrade new-config --config user_data/config.json
```

## Konfiguráció

- **Stratégia módosítás**: `docker-compose.yml` fájlban a `--strategy` paraméter
- **Exchange API kulcsok**: `.env` fájlban (lásd `.env.example` sablont)
- **API szerver (FreqUI)**: `user_data/config.json` - `api_server` szekció

## Architektúra

- Freqtrade hivatalos Docker image: `freqtradeorg/freqtrade:stable`
- GPU támogatás (FreqAI): `freqtradeorg/freqtrade:stable_freqaitorch` image
- API szerver: localhost:8080-on fut, Caddy reverse proxy biztosítja a HTTPS-t
- Adatbázis: SQLite (`user_data/tradesv3.sqlite`)
