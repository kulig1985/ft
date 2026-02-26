# Freqtrade Docker Telepítési Útmutató

Ez a dokumentáció leírja, hogyan telepíthető és konfigurálható a Freqtrade kereskedő platform Ubuntu VPS-en Docker segítségével, a `freqtrade.kebodev.hu` domain alatt.

## Előfeltételek

- Ubuntu VPS (20.04+ ajánlott)
- Docker és Docker Compose telepítve
- Caddy webszerver telepítve
- Domain DNS beállítva: `freqtrade.kebodev.hu` -> VPS IP

## 1. Docker és Docker Compose Telepítése

```bash
# Docker telepítése
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Felhasználó hozzáadása a docker csoporthoz
sudo usermod -aG docker $USER
newgrp docker

# Docker Compose plugin ellenőrzése
docker compose version
```

## 2. Mappastruktúra

A projekt a következő mappastruktúrát használja:

```
freq_trade/
├── ft_userdata/
│   ├── docker-compose.yml
│   └── user_data/
│       ├── config.json          # Freqtrade konfiguráció
│       ├── strategies/          # Kereskedési stratégiák (git repo-ból)
│       ├── data/                # Historikus adatok
│       ├── logs/                # Log fájlok
│       └── notebooks/           # Jupyter notebook-ok
```

## 3. Docker Compose Konfiguráció

Hozd létre a `ft_userdata/docker-compose.yml` fájlt:

```yaml
---
services:
  freqtrade:
    image: freqtradeorg/freqtrade:stable
    restart: unless-stopped
    container_name: freqtrade
    volumes:
      - "./user_data:/freqtrade/user_data"
    ports:
      - "127.0.0.1:8080:8080"
    command: >
      trade
      --logfile /freqtrade/user_data/logs/freqtrade.log
      --db-url sqlite:////freqtrade/user_data/tradesv3.sqlite
      --config /freqtrade/user_data/config.json
      --strategy YourStrategyName
```

## 4. Freqtrade Konfiguráció Létrehozása

### 4.1 Interaktív konfiguráció generálás

```bash
cd ft_userdata

# Freqtrade image letöltése
docker compose pull

# User directory struktúra létrehozása
docker compose run --rm freqtrade create-userdir --userdir user_data

# Konfiguráció létrehozása (interaktív)
docker compose run --rm freqtrade new-config --config user_data/config.json
```

### 4.2 API szerver beállítások

A `user_data/config.json` fájlban konfiguráld az API szervert a FreqUI eléréséhez:

```json
{
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "verbosity": "error",
        "enable_openapi": false,
        "jwt_secret_key": "GENERALT_RANDOM_STRING_32_KARAKTER_VAGY_TOBB",
        "CORS_origins": ["https://freqtrade.kebodev.hu"],
        "username": "admin",
        "password": "EROSJELSZO123!",
        "ws_token": "GENERALT_WS_TOKEN"
    }
}
```

**JWT és WS token generálása:**

```bash
python3 -c "import secrets; print('jwt_secret_key:', secrets.token_hex(32)); print('ws_token:', secrets.token_urlsafe(25))"
```

## 5. Caddy Reverse Proxy Konfiguráció

Szerkeszd a `/etc/caddy/Caddyfile` fájlt és add hozzá:

```caddyfile
freqtrade.kebodev.hu {
    reverse_proxy localhost:8080
}
```

Caddy újraindítása:

```bash
sudo systemctl reload caddy
```

A Caddy automatikusan kezeli a HTTPS tanúsítványokat Let's Encrypt-tel.

## 6. Stratégia Beállítása Git Repo-ból

A stratégiák a `user_data/strategies/` mappában találhatók. Git repo klónozása:

```bash
cd ft_userdata/user_data/strategies
git clone https://github.com/your-repo/your-strategies.git .
# vagy
git pull origin main  # frissítéshez
```

A `docker-compose.yml` fájlban módosítsd a stratégia nevét:

```yaml
command: >
  trade
  --strategy YourStrategyName
  ...
```

## 7. Freqtrade Indítása

```bash
cd ft_userdata

# Indítás háttérben
docker compose up -d

# Logok követése
docker compose logs -f

# Állapot ellenőrzése
docker compose ps
```

## 8. FreqUI Elérése

A FreqUI elérhető: `https://freqtrade.kebodev.hu`

Bejelentkezés a `config.json`-ban megadott `username` és `password` párossal.

## Hasznos Parancsok

### Konténer Kezelés

```bash
# Leállítás
docker compose down

# Újraindítás
docker compose restart

# Frissítés új verzióra
docker compose pull
docker compose up -d
```

### Backtesting

```bash
docker compose run --rm freqtrade backtesting \
  --config user_data/config.json \
  --strategy YourStrategyName \
  --timerange 20230101-20231231 \
  -i 5m
```

### Adat Letöltés

```bash
docker compose run --rm freqtrade download-data \
  --pairs ETH/USDT BTC/USDT \
  --exchange binance \
  --days 30 \
  -t 5m 1h 1d
```

### Stratégiák Listázása

```bash
docker compose run --rm freqtrade list-strategies
```

### Konfiguráció Ellenőrzése

```bash
docker compose run --rm freqtrade show-config --config user_data/config.json
```

## Környezeti Változók

Érzékeny adatok (API kulcsok) kezelhetők környezeti változókkal a `docker-compose.yml`-ben:

```yaml
services:
  freqtrade:
    environment:
      - FREQTRADE__EXCHANGE__KEY=${EXCHANGE_KEY}
      - FREQTRADE__EXCHANGE__SECRET=${EXCHANGE_SECRET}
      - FREQTRADE__TELEGRAM__TOKEN=${TELEGRAM_TOKEN}
      - FREQTRADE__TELEGRAM__CHAT_ID=${TELEGRAM_CHAT_ID}
```

Hozz létre egy `.env` fájlt (NE COMMITOLD GIT-BE!):

```bash
EXCHANGE_KEY=your_api_key
EXCHANGE_SECRET=your_api_secret
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Biztonsági Megjegyzések

- A Caddy HTTPS-t biztosít, így a FreqUI kapcsolat titkosított
- Erős jelszó használata kötelező az API szerverhez
- Az API szerver csak localhost-on hallgat (127.0.0.1:8080), a Caddy kezeli a külső forgalmat
- Exchange API kulcsokat és egyéb titkos adatokat környezeti változókban tárold
- A `.env` fájlt soha ne commitold verziókezelőbe
