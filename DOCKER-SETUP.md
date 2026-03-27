# Freqtrade Docker Telepítési Útmutató

Ez a dokumentáció leírja, hogyan telepíthető és konfigurálható a Freqtrade kereskedő platform Docker segítségével - lokálisan (macOS) és VPS-en (Ubuntu) egyaránt.

## Mappastruktúra

Minden stratégiának saját almappája van a `user_data/strategies/` alatt, saját `.env`, `config.json`, logok és adatbázis. A historikus adatok (`user_data/data/`) közösek.

```
ft/
└── ft_userdata/
    ├── docker-compose.yml
    └── user_data/
        ├── data/                                 # Közös historikus adatok
        ├── strategies/
        │   ├── bb_rsi_adx/                       # BBRsiAdxStrategy
        │   │   ├── .env                          # Saját Telegram token, API kulcsok (NEM GITBE!)
        │   │   ├── .env.example
        │   │   ├── config.json                   # Saját konfig (NEM GITBE!)
        │   │   ├── config.json.orignal            # Backtest konfig
        │   │   ├── BBRsiAdxStrategy.py
        │   │   ├── BBRsiAdxStrategy.json
        │   │   ├── pair_configs.json
        │   │   ├── logs/
        │   │   └── tradesv3.sqlite               # Saját DB (generálódik)
        │   └── range_breakout/                   # RangeBreakoutPullbackStrategy
        │       ├── .env
        │       ├── .env.example
        │       ├── config.json
        │       ├── config.json.orignal
        │       ├── RangeBreakoutPullbackStrategy.py
        │       ├── RangeBreakoutPullbackStrategy.json
        │       ├── rb_pair_configs.json
        │       ├── logs/
        │       └── tradesv3.sqlite
        └── ...
```

Mindkét konténer a teljes `user_data/`-t mountolja, de saját config-ra és .env-re mutat. Így a `data/` mappa közös (elég egyszer letölteni), de a Telegram bot, adatbázis és logok stratégiánként elkülönülnek.

---

## Konfiguráció Felépítése

Stratégiánként két konfigurációs réteg:

| Fájl | Tartalom | Git-be kerül? |
|------|----------|---------------|
| `strategies/<nev>/config.json` | Kereskedési beállítások | **NEM** |
| `strategies/<nev>/.env` | Telegram token, Exchange kulcsok, FreqUI jelszó | **NEM** |
| `strategies/<nev>/.env.example` | `.env` sablon | **IGEN** |
| `strategies/<nev>/*.py` | Stratégia kód | **IGEN** |

**A `.env` fájl környezeti változói FELÜLÍRJÁK a `config.json` értékeit!**

Minden konténernek saját `.env` fájlja van, így **eltérő Telegram botokat** lehet használni stratégiánként.

---

## Lokális Fejlesztés (macOS)

### 1. Docker Desktop Telepítése

Töltsd le és telepítsd a [Docker Desktop for Mac](https://docs.docker.com/docker-for-mac/install/)-et.

### 2. Projekt Klónozása és .env Beállítása

```bash
git clone -b develop https://github.com/kulig1985/ft.git
cd ft/ft_userdata

# .env fájlok létrehozása stratégiánként
cp user_data/strategies/bb_rsi_adx/.env.example user_data/strategies/bb_rsi_adx/.env
cp user_data/strategies/range_breakout/.env.example user_data/strategies/range_breakout/.env

# Szerkesztés - töltsd ki a valós értékeket!
nano user_data/strategies/bb_rsi_adx/.env
nano user_data/strategies/range_breakout/.env
```

### 3. Image Letöltése

```bash
docker compose pull
```

### 4. FreqUI Webserver Mód (Backtesting UI-val)

```bash
# BBRsiAdx stratégiához:
docker compose run --rm -p 8080:8080 freqtrade_bb webserver \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal

# RangeBreakout stratégiához:
docker compose run --rm -p 8080:8080 freqtrade_rb webserver \
  --config user_data/strategies/range_breakout/config.json.orignal
```

FreqUI elérhető: **http://localhost:8080**

### 5. Backtesting Parancssorból

```bash
# Adat letöltése (közös data/ mappába kerül)
docker compose run --rm freqtrade_bb download-data \
  --pairs ETH/USDT BTC/USDT \
  --exchange binance \
  --days 30 \
  -t 5m 1h

# Backtesting - BBRsiAdx
docker compose run --rm freqtrade_bb backtesting \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --strategy BBRsiAdxStrategy \
  --timerange 20240101-20240201 \
  -i 1h

# Backtesting - RangeBreakout
docker compose run --rm freqtrade_rb backtesting \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --strategy RangeBreakoutPullbackStrategy \
  --timerange 20240101-20240201 \
  -i 5m
```

### 6. Hyperopt (Paraméter Optimalizálás)

```bash
docker compose run --rm freqtrade_bb hyperopt \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --strategy BBRsiAdxStrategy \
  --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell \
  -e 100
```

---

## VPS Telepítés (Ubuntu)

### Előfeltételek

- Ubuntu VPS (20.04+)
- Domain DNS beállítva: `freqtrade.kebodev.hu` és `freqtrade-rb.kebodev.hu` -> VPS IP

### 1. Docker Telepítése

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Caddy Telepítése (Reverse Proxy + HTTPS)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### 3. Projekt Klónozása és .env Beállítása

```bash
git clone -b develop https://github.com/kulig1985/ft.git
cd ft/ft_userdata

# .env fájlok létrehozása (mindegyik stratégiához saját Telegram token!)
cp user_data/strategies/bb_rsi_adx/.env.example user_data/strategies/bb_rsi_adx/.env
cp user_data/strategies/range_breakout/.env.example user_data/strategies/range_breakout/.env

nano user_data/strategies/bb_rsi_adx/.env
nano user_data/strategies/range_breakout/.env
```

### 4. Caddy Konfiguráció

```bash
sudo nano /etc/caddy/Caddyfile
```

```caddyfile
freqtrade.kebodev.hu {
    reverse_proxy localhost:8080
}

freqtrade-rb.kebodev.hu {
    reverse_proxy localhost:8081
}
```

```bash
sudo systemctl reload caddy
```

### 5. Freqtrade Indítása

```bash
docker compose pull
docker compose up -d

# Logok
docker compose logs -f
docker compose logs -f freqtrade_bb
docker compose logs -f freqtrade_rb
```

**FreqUI elérés:**
- BBRsiAdx: **https://freqtrade.kebodev.hu**
- RangeBreakout: **https://freqtrade-rb.kebodev.hu**

---

## Új Stratégia Hozzáadása

```bash
cd ft/ft_userdata

# 1. Mappa létrehozása
mkdir -p user_data/strategies/uj_strategia/logs

# 2. Stratégia fájl elhelyezése
cp /path/to/UjStrategia.py user_data/strategies/uj_strategia/

# 3. .env és config létrehozása (meglévőből másolva, módosítva)
cp user_data/strategies/bb_rsi_adx/.env.example user_data/strategies/uj_strategia/.env.example
cp user_data/strategies/uj_strategia/.env.example user_data/strategies/uj_strategia/.env
cp user_data/strategies/bb_rsi_adx/config.json user_data/strategies/uj_strategia/config.json
nano user_data/strategies/uj_strategia/.env
nano user_data/strategies/uj_strategia/config.json
```

A `docker-compose.yml`-be add hozzá:

```yaml
  freqtrade_uj:
    image: freqtradeorg/freqtrade:stable
    restart: unless-stopped
    container_name: freqtrade_uj
    volumes:
      - "./user_data:/freqtrade/user_data"
    ports:
      - "127.0.0.1:8082:8080"
    env_file:
      - ./user_data/strategies/uj_strategia/.env
    command: >
      trade
      --logfile /freqtrade/user_data/strategies/uj_strategia/logs/freqtrade.log
      --db-url sqlite:////freqtrade/user_data/strategies/uj_strategia/tradesv3.sqlite
      --config /freqtrade/user_data/strategies/uj_strategia/config.json
      --strategy UjStrategia
```

---

## Hasznos Parancsok

```bash
# Konténer állapot
docker compose ps

# Összes log
docker compose logs -f

# Egy stratégia logja
docker compose logs -f freqtrade_bb

# Leállítás
docker compose down

# Csak egy stratégia újraindítása
docker compose restart freqtrade_bb

# Frissítés
docker compose pull && docker compose up -d

# Stratégiák listázása
docker compose run --rm freqtrade_bb list-strategies

# Konfiguráció ellenőrzése
docker compose run --rm freqtrade_bb show-config \
  --config user_data/strategies/bb_rsi_adx/config.json
```

---

## Telegram Bot Beállítása

Stratégiánként **külön Telegram bot** szükséges (eltérő tokenek).

### Bot Létrehozása

1. [@BotFather](https://telegram.me/BotFather) → `/newbot` → mentsd a tokent
2. [@userinfobot](https://telegram.me/userinfobot) → mentsd a chat ID-t
3. Nyisd meg a botot és nyomd meg a `/start` gombot

### Konfiguráció

Minden stratégia `.env` fájljába a saját tokent írd:

```bash
# user_data/strategies/bb_rsi_adx/.env
FREQTRADE__TELEGRAM__TOKEN=111111:AAA_bb_bot_token
FREQTRADE__TELEGRAM__CHAT_ID=588528102

# user_data/strategies/range_breakout/.env
FREQTRADE__TELEGRAM__TOKEN=222222:BBB_rb_bot_token
FREQTRADE__TELEGRAM__CHAT_ID=588528102
```

---

## Különbségek: Lokális vs VPS

| | Lokális (macOS) | VPS (Ubuntu) |
|---|-----------------|--------------|
| FreqUI URL | http://localhost:8080 / :8081 | https://freqtrade.kebodev.hu / freqtrade-rb.kebodev.hu |
| Caddy | Nem kell | Kell (HTTPS) |
| .env (API kulcsok) | Nem kell backtesthez | Kell live tradinghez |
| config.json `dry_run` | `true` | `false` (éles kereskedés) |
| Telegram | Opcionális | Ajánlott (stratégiánként külön bot) |
| Használat | Backtesting, fejlesztés | Live/dry-run trading |
