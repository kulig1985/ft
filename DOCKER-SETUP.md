# Freqtrade Docker Telepítési Útmutató

Ez a dokumentáció leírja, hogyan telepíthető és konfigurálható a Freqtrade kereskedő platform Docker segítségével - lokálisan (macOS) és VPS-en (Ubuntu) egyaránt.

## Mappastruktúra

```
ft/
├── DOCKER-SETUP.md
├── CLAUDE.md
└── ft_userdata/
    ├── docker-compose.yml
    ├── .env                    # API kulcsok (NE COMMITOLD!)
    ├── .env.example
    └── user_data/
        ├── config.json         # Freqtrade konfiguráció
        ├── strategies/         # Kereskedési stratégiák (.py fájlok)
        ├── data/               # Historikus adatok
        ├── logs/               # Log fájlok
        ├── backtest_results/   # Backtest eredmények
        ├── plot/               # Plot kimenet
        └── notebooks/          # Jupyter notebook-ok
```

A stratégiák közvetlenül a `user_data/strategies/` mappába kerülnek - nincs szükség külön git repo-ra.

---

## Lokális Fejlesztés (macOS)

### 1. Docker Desktop Telepítése

Töltsd le és telepítsd a [Docker Desktop for Mac](https://docs.docker.com/docker-for-mac/install/)-et.

### 2. Projekt Klónozása és Első Indítás

```bash
git clone -b develop https://github.com/kulig1985/ft.git
cd ft/ft_userdata

# Image letöltése
docker compose pull

# Konfiguráció létrehozása (interaktív)
docker compose run --rm freqtrade new-config --config user_data/config.json
```

A konfiguráció létrehozásakor:
- Exchange: válaszd ki a kívántat (pl. binance)
- Dry-run: **Yes** (lokális fejlesztéshez)
- API szerver: **Yes** (FreqUI-hoz)

### 3. FreqUI Webserver Mód (Backtesting UI-val)

A `webserver` mód lehetővé teszi a backtesting futtatását közvetlenül a böngészőből:

```bash
docker compose run --rm -p 8080:8080 freqtrade webserver --config user_data/config.json
```

FreqUI elérhető: **http://localhost:8080**

A webserver módban elérhető:
- Backtesting futtatás és vizualizáció
- Adat letöltés
- Pairlist tesztelés
- Korábbi backtest eredmények betöltése

### 4. Backtesting Parancssorból

```bash
# Adat letöltése (először!)
docker compose run --rm freqtrade download-data \
  --pairs ETH/USDT BTC/USDT \
  --exchange binance \
  --days 30 \
  -t 5m 1h

# Backtesting futtatása
docker compose run --rm freqtrade backtesting \
  --config user_data/config.json \
  --strategy MyStrategy \
  --timerange 20240101-20240201 \
  -i 5m

# Több stratégia összehasonlítása
docker compose run --rm freqtrade backtesting \
  --strategy-list Strategy1 Strategy2 \
  --timerange 20240101-20240201

# Havi/éves bontás
docker compose run --rm freqtrade backtesting \
  --strategy MyStrategy \
  --breakdown month year
```

### 5. Plotting

```bash
# Profit plot
docker compose run --rm freqtrade plot-profit \
  --strategy MyStrategy

# Dataframe plot (indikátorokkal)
docker compose run --rm freqtrade plot-dataframe \
  --strategy MyStrategy \
  -p BTC/USDT \
  --timerange 20240101-20240115
```

A kimenet a `user_data/plot/` mappában lesz, böngészőben megnyitható HTML fájlként.

### 6. Hyperopt (Paraméter Optimalizálás)

```bash
docker compose run --rm freqtrade hyperopt \
  --config user_data/config.json \
  --strategy MyStrategy \
  --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell \
  -e 100
```

### 7. Jupyter Notebook

```bash
# Jupyter Lab indítása
docker compose -f docker-compose-jupyter.yml up
```

Elérhető: **http://127.0.0.1:8888/lab**

---

## VPS Telepítés (Ubuntu)

### Előfeltételek

- Ubuntu VPS (20.04+)
- Domain DNS beállítva: `freqtrade.kebodev.hu` -> VPS IP

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

### 3. Projekt Klónozása

```bash
git clone -b develop https://github.com/kulig1985/ft.git
cd ft/ft_userdata

# .env fájl létrehozása
cp .env.example .env
nano .env  # API kulcsok kitöltése
```

### 4. Konfiguráció

```bash
docker compose pull
docker compose run --rm freqtrade new-config --config user_data/config.json
```

A `config.json`-ban módosítsd az API szervert:

```json
{
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "verbosity": "error",
        "jwt_secret_key": "GENERALT_RANDOM_STRING",
        "CORS_origins": ["https://freqtrade.kebodev.hu"],
        "username": "admin",
        "password": "EROSJELSZO123!"
    }
}
```

Token generálás:
```bash
python3 -c "import secrets; print('jwt_secret_key:', secrets.token_hex(32))"
```

### 5. Caddy Konfiguráció

```bash
sudo nano /etc/caddy/Caddyfile
```

```caddyfile
freqtrade.kebodev.hu {
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl reload caddy
```

### 6. Freqtrade Indítása (Live/Dry-run)

A `docker-compose.yml`-ben állítsd be a stratégiát:

```yaml
command: >
  trade
  --logfile /freqtrade/user_data/logs/freqtrade.log
  --db-url sqlite:////freqtrade/user_data/tradesv3.sqlite
  --config /freqtrade/user_data/config.json
  --strategy MyStrategy
```

Indítás:
```bash
docker compose up -d
docker compose logs -f
```

FreqUI: **https://freqtrade.kebodev.hu**

---

## Hasznos Parancsok

```bash
# Konténer állapot
docker compose ps

# Logok
docker compose logs -f

# Leállítás
docker compose down

# Újraindítás
docker compose restart

# Frissítés
docker compose pull && docker compose up -d

# Stratégiák listázása
docker compose run --rm freqtrade list-strategies

# Konfiguráció ellenőrzése
docker compose run --rm freqtrade show-config --config user_data/config.json
```

---

## Pairlist Beállítása

A `config.json`-ban az `exchange` szekción belül állítsd be a kereskedési párokat:

```json
{
    "exchange": {
        "name": "binance",
        "key": "",
        "secret": "",
        "pair_whitelist": [
            "BTC/USDC",
            "ETH/USDC",
            "SOL/USDC",
            "ARB/USDC",
            "TIA/USDC",
            "ADA/USDC",
            "AVAX/USDC",
            "DOGE/USDC"
        ],
        "pair_blacklist": []
    },
    "pairlists": [
        {"method": "StaticPairList"}
    ]
}
```

A FreqUI "Download Data" felületén az **"Add all pairs from pairlist"** gomb ezeket a párokat fogja használni.

---

## Telegram Bot Beállítása

### 1. Bot Létrehozása

1. Nyisd meg a Telegram-ot és keresd meg a [@BotFather](https://telegram.me/BotFather)-t
2. Küldj üzenetet: `/newbot`
3. Add meg a bot nevét (pl. `Freqtrade Bot`)
4. Add meg a bot username-jét (pl. `my_freqtrade_bot`) - **kötelezően `bot`-ra kell végződnie!**
5. **Mentsd el a kapott API TOKEN-t** (pl. `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Chat ID Lekérése

1. Keresd meg a [@userinfobot](https://telegram.me/userinfobot)-ot
2. Küldj neki bármit
3. **Mentsd el az "Id" értéket** (pl. `123456789`)

### 3. Bot Aktiválása

**FONTOS:** Nyisd meg a saját botodat és nyomd meg a `/start` gombot! Enélkül nem fog működni.

### 4. Konfiguráció

Add hozzá a `config.json`-hoz:

```json
{
    "telegram": {
        "enabled": true,
        "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        "chat_id": "123456789",
        "notification_settings": {
            "status": "on",
            "warning": "on",
            "startup": "on",
            "entry": "on",
            "entry_fill": "on",
            "exit": "on",
            "exit_fill": "on"
        }
    }
}
```

**Vagy használd a `.env` fájlt** (biztonságosabb):

```bash
# .env fájlban
FREQTRADE__TELEGRAM__TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
FREQTRADE__TELEGRAM__CHAT_ID=123456789
```

### 5. Telegram Parancsok

| Parancs | Leírás |
|---------|--------|
| `/start` | Bot indítása |
| `/stop` | Bot leállítása |
| `/status` | Nyitott pozíciók listázása |
| `/profit` | Profit összesítés |
| `/balance` | Egyenleg |
| `/daily` | Napi profit (utolsó 7 nap) |
| `/forceexit <trade_id>` | Pozíció azonnali zárása |
| `/help` | Összes parancs listázása |

---

## Különbségek: Lokális vs VPS

| | Lokális (macOS) | VPS (Ubuntu) |
|---|-----------------|--------------|
| FreqUI URL | http://localhost:8080 | https://freqtrade.kebodev.hu |
| Caddy | Nem kell | Kell (HTTPS) |
| .env (API kulcsok) | Nem kell backtesthez | Kell live tradinghez |
| config.json `dry_run` | `true` | `false` (éles kereskedés) |
| Telegram | Opcionális | Ajánlott |
| Használat | Backtesting, fejlesztés, plotting | Live/dry-run trading |
