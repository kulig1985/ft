# Freqtrade Használati Útmutató

> **Három aktív stratégia fut a rendszerben:**
>
> | Bot | Stratégia | Timeframe | Párok | Port | Config |
> |-----|-----------|-----------|-------|------|--------|
> | `freqtrade_bb` | BBRsiAdxStrategy | 1H | ETH, SOL, ARB, AVAX | 8080 | `strategies/bb_rsi_adx/config.json` |
> | `freqtrade_rb` | RangeBreakoutPullbackStrategy | 5m | ETH, SUI, DOGE, BTC | 8081 | `strategies/range_breakout/config.json` |
> | `freqtrade_st` | SuperTrendMacdRsiStrategy | 1H | ETH, SOL, ARB, AVAX, TIA, SUI, BTC, DOGE, LTC, XRP | 8082 | `strategies/supertrend_macd_rsi/config.json` |
>
> ⚠️ **Minden parancsot a `ft_userdata/` könyvtárból futtass!** (`cd ft/ft_userdata`)
> A config útvonalak **konténer-relatívak** (`user_data/...` = `/freqtrade/user_data/...` a konténerben).
> **NE használj abszolút host elérési utat** (`/Users/...`) a Docker parancsokban!
> Minden parancsot a `ft_userdata/` könyvtárból kell futtatni.
> Minden stratégiának **saját config, .env, adatbázis és log** fájljai vannak a `user_data/strategies/<nev>/` mappában.
> A historikus adatok (`user_data/data/`) **közösek** — elég egyszer letölteni.

## Tartalomjegyzék

1. [Alapok - Hogyan működik a rendszer?](#1-alapok---hogyan-működik-a-rendszer)
2. [Adat letöltés](#2-adat-letöltés)
3. [Backtesting - BBRsiAdxStrategy](#3-backtesting---bbrsiadxstrategy)
4. [Hyperopt - BBRsiAdxStrategy](#4-hyperopt---bbrsiadxstrategy)
5. [Teljes workflow: Hyperopt-tól a live tradingig](#5-teljes-workflow-hyperopt-tól-a-live-tradingig)
6. [Live/Dry-run trading - Éles kereskedés](#6-livedry-run-trading---éles-kereskedés)
7. [FreqUI webfelület](#7-frequi-webfelület)
8. [Gyakori kérdések](#8-gyakori-kérdések)
9. [RangeBreakoutPullbackStrategy - Adat, Backtest, Hyperopt](#9-rangebreakoutpullbackstrategy---adat-backtest-hyperopt)
10. [SuperTrendMacdRsiStrategy - Adat, Backtest, Hyperopt](#10-supertrendmacdrsistrategy---adat-backtest-hyperopt)
11. [Három bot kezelése - VPS beállítás](#11-három-bot-kezelése---vps-beállítás)

---

## 1. Alapok - Hogyan működik a rendszer?

### Minden parancsot a `ft_userdata/` könyvtárból futtass!

```bash
cd ft/ft_userdata
```

### A Docker kétféle módban tud futni

| Mód | Parancs | Mire való |
|-----|---------|-----------|
| **Trading** (live/dry-run) | `docker compose up -d` | Valós idejű kereskedés. Háttérben fut, 0-24. |
| **Egyszeri parancsok** | `docker compose run --rm freqtrade_bb ...` | Backtesting, hyperopt, adat letöltés. Lefut és leáll. |

> ⚠️ **`--strategy-path` kötelező** minden strategy-t érintő parancsnál! A freqtrade nem keres almappákban automatikusan.

A `docker compose up -d` a `docker-compose.yml`-ben lévő `command:` sort hajtja végre (a `trade` parancs).
A `docker compose run --rm <service> ...` egy **ideiglenes** konténert indít, majd törli magát (`--rm`).

**Ezek egymástól függetlenek.** Futtathatsz backtestet miközben a trading bot is fut.

### A mappastruktúra lényege

```
ft_userdata/
├── docker-compose.yml
└── user_data/
    ├── data/                          ← KÖZÖS historikus adatok (mind a 3 stratégiához)
    └── strategies/
        ├── bb_rsi_adx/
        │   ├── .env                   ← BBRsiAdx Telegram token, API kulcsok
        │   ├── config.json            ← BBRsiAdx konfig
        │   ├── config.json.orignal    ← BBRsiAdx backtest konfig (üres exchange kulcsok)
        │   ├── pair_configs.json      ← Páronkénti optimalizált paraméterek
        │   └── BBRsiAdxStrategy.py
        ├── range_breakout/
        │   ├── .env
        │   ├── config.json
        │   ├── config.json.orignal
        │   ├── rb_pair_configs.json
        │   └── RangeBreakoutPullbackStrategy.py
        └── supertrend_macd_rsi/
            ├── .env
            ├── config.json
            ├── config.json.orignal
            ├── st_pair_configs.json   ← Páronkénti optimalizált paraméterek
            └── SuperTrendMacdRsiStrategy.py
```

### Páronkénti paraméterek (pair_configs.json)

Minden stratégia **minden párhoz külön paramétereket** használ. Ezek a stratégia almappájában lévő `*_pair_configs.json` fájlban vannak.

**Hogyan működik:**
- Betöltéskor a stratégia beolvassa a fájlt
- Ha egy pár **benne van** → azokat a paramétereket használja
- Ha **nincs benne** → a kódban lévő default értékeket (hyperopt default) alkalmazza

---

## 2. Adat letöltés

Az adatok **közösek** (`user_data/data/`), így elég egyszer letölteni bármelyik service-szel. Letöltés után minden stratégia eléri ugyanazt az adatot.

### Összes adat letöltése (mindhárom stratégiához)

```bash
# 1H és 4H adatok (BBRsiAdxStrategy és SuperTrendMacdRsiStrategy)
docker compose run --rm freqtrade_bb download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal

# 5m adatok (RangeBreakoutPullbackStrategy)
docker compose run --rm freqtrade_rb download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/strategies/range_breakout/config.json.orignal

# SuperTrendMacdRsi párok (ha eltérnek a bb_rsi_adx-től)
docker compose run --rm freqtrade_st download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal
```

### Csak egy pár adatának letöltése

```bash
# BBRsiAdx / SuperTrendMacdRsi párhoz (1H)
docker compose run --rm freqtrade_bb download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --pairs ETH/USDC:USDC

# RangeBreakout párhoz (5m)
docker compose run --rm freqtrade_rb download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --pairs ETH/USDC:USDC
```

### Több specifikus pár letöltése

```bash
docker compose run --rm freqtrade_bb download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --pairs ETH/USDC:USDC SOL/USDC:USDC BTC/USDC:USDC
```

### Fontos paraméterek

| Paraméter | Leírás | Példa |
|-----------|--------|-------|
| `--timeframes` | Milyen időkereteket töltsön | `1h`, `5m`, `1h 5m` |
| `--timerange` | Milyen időszaktól | `20250101-` (2025.01.01-től máig) |
| `--config` | Config fájl (exchange, párok) | `user_data/strategies/bb_rsi_adx/config.json.orignal` |
| `--pairs` | Specifikus párok (felülírja config-ot) | `ETH/USDC:USDC SOL/USDC:USDC` |

### Adat frissítés

Ugyanaz a parancs újra futtatva **hozzáfűzi** az új adatokat a meglévőkhöz.

### Timerange formátumok

```
--timerange 20250101-          # 2025.01.01-től máig
--timerange -20260101          # Az elejétől 2026.01.01-ig
--timerange 20250101-20260101  # 2025.01.01-től 2026.01.01-ig
```

### Adatok helye

`user_data/data/binance/futures/` — Fájlnév: `PAIR-TIMEFRAME-TYPE.feather`

---

## 3. Backtesting - BBRsiAdxStrategy

### A stratégia rövid leírása

1H BB + 4H RSI + 1H/4H ADX alapú trendkövető stratégia. ATR-alapú stop loss. 20x leverage, 20 USDC stake/trade.

### A 6 paraméter

| Paraméter | Leírás | Tartomány |
|-----------|--------|-----------|
| `bb_period` | Bollinger szalag periódus | 15–20 |
| `bb_std` | Bollinger szalag szórás | 1.5–2.0 |
| `rsi_threshold` | 4H RSI küszöb | 50–55 |
| `adx_threshold_1h` | 1H ADX küszöb | 20–25 |
| `adx_threshold_4h` | 4H ADX küszöb | 25–30 |
| `atr_multiplier` | ATR szorzó stoploss-hoz | 3.0–5.0 |

### Backtesting az összes párral

```bash
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h
```

### Backtesting egyetlen párral

```bash
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  -p ETH/USDC:USDC
```

### Havi/éves bontás

```bash
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  --breakdown month year
```

### Backtesting parancs paraméterei

| Paraméter | Leírás |
|-----------|--------|
| `-i` / `--timeframe` | Fő timeframe (`1h`) |
| `--timerange` | Tesztelési időszak |
| `-p` / `--pairs` | Melyik pár(ok)ra teszteljen |
| `--breakdown` | Időszakos bontás (`month year`) |
| `--timeframe-detail 5m` | Gyertyán belüli szimuláció (pontosabb, de lassabb) |

---

## 4. Hyperopt - BBRsiAdxStrategy

### Hogyan működik a hyperopt a pair_configs.json-nal?

1. A hyperopt próbálgat különböző értékeket
2. Ha a pár **benne van** a `pair_configs.json`-ban, a stratégia **onnan veszi a fix értékeket** — a hyperopt NEM tud felülírni
3. Ezért **hyperopt előtt ki kell venni a párt** a `pair_configs.json`-ból (prefixeld `_`-lel)

### Hyperopt futtatása egy párra

```bash
# 1. pair_configs.json-ban: "SOL/USDC:USDC" → "_SOL/USDC:USDC"

# 2. Hyperopt futtatása
docker compose run --rm freqtrade_bb hyperopt \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 500 \
  --timerange 20250701-20260201 \
  --analyze-per-epoch \
  -p SOL/USDC:USDC

# 3. Eredményt bemásolni a pair_configs.json-ba, kulcs visszaállítása
# 4. Backtest validáció
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20250701-20260201 \
  -i 1h -p SOL/USDC:USDC
```

> **Miért kell `--analyze-per-epoch`?** A `bb_period`, `bb_std` paraméterek az indikátor-számítást érintik. Nélküle a hyperopt mindig az első epoch indikátorait használja — az optimalizáció értelmetlen.

### Hyperopt eredmény bemásolása a pair_configs.json-ba

```json
"SOL/USDC:USDC": {
    "bb_period": 18,
    "bb_std": 1.8,
    "rsi_threshold": 52,
    "adx_threshold_1h": 22,
    "adx_threshold_4h": 27,
    "atr_multiplier": 4.2
}
```

**Fájl helye:** `user_data/strategies/bb_rsi_adx/pair_configs.json`

### Loss function-ök

| Loss function | Mit optimalizál |
|---------------|----------------|
| `SharpeHyperOptLossDaily` | Napi Sharpe-ráta — **általános célra ajánlott** |
| `SortinoHyperOptLossDaily` | Napi Sortino-ráta |
| `MaxDrawDownHyperOptLoss` | Max drawdown minimalizálás |
| `CalmarHyperOptLoss` | Hozam/drawdown arány |

---

## 5. Teljes workflow: Hyperopt-tól a live tradingig

### 5.1 Adat letöltés

```bash
docker compose run --rm freqtrade_bb download-data \
  --timeframes 1h \
  --timerange 20250701- \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal
```

### 5.2 Hyperopt futtatása páronként

Ismételd minden párra (ETH, SOL, ARB, AVAX):

**a)** `pair_configs.json`-ban: `"ETH/USDC:USDC"` → `"_ETH/USDC:USDC"`

**b)** Hyperopt:
```bash
docker compose run --rm freqtrade_bb hyperopt \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy --epochs 500 \
  --timerange 20250701-20260201 \
  --analyze-per-epoch \
  -p ETH/USDC:USDC
```

**c)** Eredményt bemásolni a `pair_configs.json`-ba, kulcs visszaállítása.

**d)** Következő pár.

### 5.3 Validálás: Backtest az összes párral

```bash
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h
```

### 5.4 Out-of-sample teszt (overfitting ellenőrzés)

```bash
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20260201-20260327 \
  -i 1h
```

### 5.5 Bot indítása

```bash
docker compose up -d freqtrade_bb
```

---

## 6. Live/Dry-run trading - Éles kereskedés

### Trading indítása

```bash
# Összes bot indítása
docker compose up -d

# Csak egy bot
docker compose up -d freqtrade_bb
docker compose up -d freqtrade_rb
docker compose up -d freqtrade_st

# Állapot ellenőrzése
docker compose ps

# Logok (valós idejű)
docker compose logs -f freqtrade_bb

# Leállítás
docker compose down

# Egy bot újraindítása (pl. pair_configs módosítás után)
docker compose restart freqtrade_bb
```

### Dry-run vs. Live mód

A `config.json`-ban a `"dry_run"` beállítás:

| Beállítás | Mit jelent |
|-----------|-----------|
| `"dry_run": true` | Szimulált kereskedés — nem küld rendeléseket |
| `"dry_run": false` | Éles kereskedés valódi pénzzel — API kulcsok kellenek! |

### Mikor kell újraindítani a botot?

| Mit változtattál? | Parancs |
|-------------------|---------|
| `pair_configs.json` | `docker compose restart freqtrade_bb` |
| `config.json` | `docker compose restart freqtrade_bb` |
| `BBRsiAdxStrategy.py` | `docker compose restart freqtrade_bb` |

A `pair_configs.json` **induláskor töltődik be egyszer** — módosítás után mindig újra kell indítani.

### FreqUI Trade felület

| Bot | Lokális | VPS |
|-----|---------|-----|
| freqtrade_bb | http://localhost:8080 | https://freqtrade.kebodev.hu |
| freqtrade_rb | http://localhost:8081 | https://freqtrade-rb.kebodev.hu |
| freqtrade_st | http://localhost:8082 | https://freqtrade-st.kebodev.hu |

Bejelentkezéshez a stratégia `.env` fájljában lévő `FREQTRADE__API_SERVER__USERNAME` és `PASSWORD`.

---

## 7. FreqUI webfelület

### A két üzemmód

**Trade mód** (`docker compose up -d freqtrade_bb`):
- Bot kereskedik a háttérben
- FreqUI: Trade fül (pozíciók, zárt tradek, kézi belépés/zárás)
- Backtesting fül **nem** jelenik meg

**Webserver mód** (backtesting UI-hoz):
```bash
docker compose run --rm -p 8080:8080 freqtrade_bb webserver \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal
```
- Bot **nem** kereskedik
- FreqUI: Backtesting fül (futtatás, eredmények, adatletöltés böngészőből)

### Korábbi backtest eredmények megtekintése

Mentés helye: `user_data/strategies/bb_rsi_adx/backtest_results/`

Betölthetők a FreqUI-ban a "Load" gombbal, trade módban is.

---

## 8. Gyakori kérdések

### Hogyan adok hozzá új párt (BBRsiAdx-hez)?

1. `config.json` → `pair_whitelist` → add hozzá: `"LINK/USDC:USDC"`
2. `pair_configs.json`-ba add hozzá default értékekkel:
   ```json
   "LINK/USDC:USDC": {
     "bb_period": 20, "bb_std": 2.0, "rsi_threshold": 55,
     "adx_threshold_1h": 20, "adx_threshold_4h": 25, "atr_multiplier": 4.5
   }
   ```
3. Töltsd le az adatot:
   ```bash
   docker compose run --rm freqtrade_bb download-data \
     --timeframes 1h \
     --timerange 20250101- \
     --config user_data/strategies/bb_rsi_adx/config.json.orignal \
     --pairs LINK/USDC:USDC
   ```
4. Hyperopt futtatása az új párra (lásd 4. fejezet)
5. Indítsd újra: `docker compose restart freqtrade_bb`

### Mi az a stake_amount?

A `config.json`-ban a `"stake_amount": 20` = 20 USDC fedezet/trade. 20x leverage-dzsel = 400 USDC névértékű pozíció.

### Miért kapcsolódik a Binance-hoz backtest közben?

A trading limitek, ár precizitás és díjak lekéréséhez — publikus API, nem kereskedik.

### A BBRsiAdxStrategy.json fájl kell?

Nem kötelező. A hyperopt automatikusan generálja. A `pair_configs.json` az elsődleges (páronkénti értékek), a generált JSON csak globális paramétert tartalmaz.

---

## 9. RangeBreakoutPullbackStrategy - Adat, Backtest, Hyperopt

### A stratégia rövid leírása

5m intraday rendszer. NY idő szerinti nap első 4 órájából range meghatározás, kitörés + visszazárás belépési jelzés.
- **LONG**: alsó kitörés + visszazárás a range_low-ra
- **SHORT**: felső kitörés + visszazárás a range_high-ra
- SL: kitörési szélső érték + buffer | TP: R-alapú | 20x leverage, 5 USDC/trade

**Config**: `user_data/strategies/range_breakout/config.json`
**Párok**: ETH, SUI, DOGE, BTC (USDC:USDC futures)

### 9.1 Adat letöltés

```bash
# Összes pár (5m)
docker compose run --rm freqtrade_rb download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/strategies/range_breakout/config.json.orignal

# Csak egy pár
docker compose run --rm freqtrade_rb download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --pairs ETH/USDC:USDC
```

### 9.2 Backtesting

```bash
# Egy pár
docker compose run --rm freqtrade_rb backtesting \
  --strategy-path user_data/strategies/range_breakout \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --timerange 20260101-20260320 \
  -i 5m \
  -p ETH/USDC:USDC

# Összes pár
docker compose run --rm freqtrade_rb backtesting \
  --strategy-path user_data/strategies/range_breakout \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --timerange 20260101-20260320 \
  -i 5m

# Havi bontással
docker compose run --rm freqtrade_rb backtesting \
  --strategy-path user_data/strategies/range_breakout \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --timerange 20260101-20260320 \
  -i 5m --breakdown month
```

### 9.3 Hyperopt

**Fontos: `--analyze-per-epoch` KÖTELEZŐ!** A paraméterek az indikátor-számítást érintik.

```bash
# 1. rb_pair_configs.json-ban: "ETH/USDC:USDC" → "_ETH/USDC:USDC"

# 2. Hyperopt
docker compose run --rm freqtrade_rb hyperopt \
  --strategy-path user_data/strategies/range_breakout \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/strategies/range_breakout/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy --epochs 300 \
  --timerange 20260101-20260301 \
  --analyze-per-epoch \
  -j 1 \
  -p ETH/USDC:USDC

# 3. Eredmény bemásolása rb_pair_configs.json-ba, kulcs visszaállítása
# 4. Backtest validáció
docker compose run --rm freqtrade_rb backtesting \
  --strategy-path user_data/strategies/range_breakout \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/strategies/range_breakout/config.json.orignal \
  -p ETH/USDC:USDC --timerange 20260101-20260301 -i 5m
```

> `-j 1` javasolt az 5m + analyze-per-epoch kombóhoz a memória miatt.

**rb_pair_configs.json helye:** `user_data/strategies/range_breakout/rb_pair_configs.json`

---

## 10. SuperTrendMacdRsiStrategy - Adat, Backtest, Hyperopt

### A stratégia rövid leírása

1H trendkövető stratégia. SuperTrend + MACD + RSI alapú belépés, swing-alapú SL, R-alapú TP.
- **LONG**: close > SuperTrend (uptrend) AND RSI > threshold AND MACD > Signal
- **SHORT**: close < SuperTrend (downtrend) AND RSI < (100-threshold) AND MACD < Signal
- SL: legutóbbi swing low/high (`swing_lookback` gyertyán belül)
- TP: entry ± R × risk_reward_ratio
- Leverage: 20x, stake: 10 USDC/trade (páronként állítható `stake_amount_usd`-del)

**Config**: `user_data/strategies/supertrend_macd_rsi/config.json`
**Párok**: ETH, SOL, ARB, AVAX, TIA, SUI, BTC, DOGE, LTC, XRP (USDC:USDC futures)

### A 7 paraméter

| Paraméter | Leírás | Tartomány | Default |
|-----------|--------|-----------|---------|
| `supertrend_atr_period` | ATR periódus a SuperTrendhez | 7–21 | 10 |
| `supertrend_multiplier` | ATR szorzó a SuperTrendhez | 1.5–4.0 | 3.0 |
| `rsi_threshold` | RSI küszöb (long > x, short < 100-x) | 45–60 | 50 |
| `swing_lookback` | Hány gyertyát néz vissza swing ponthoz | 5–20 | 10 |
| `risk_reward_ratio` | Take profit/stop loss arány | 1.0–3.0 | 1.5 |
| `max_candle_size_pct` | Max gyertya body méret % (0 = kikapcsolt) | 0.0–5.0 | 0.0 |
| `stake_amount_usd` | Trade méret USD-ben | 5–200 | 10.0 |

> **`stake_amount_usd`**: Páronként állítható az `st_pair_configs.json`-ban. Nem hyperopt paraméter (`optimize=False`) — kézzel kell beállítani.

### 10.1 Adat letöltés

```bash
# Összes pár (1H)
docker compose run --rm freqtrade_st download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal

# Csak egy pár
docker compose run --rm freqtrade_st download-data \
  --timeframes 1h \
  --timerange 20250101- \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --pairs ETH/USDC:USDC
```

### 10.2 Backtesting

```bash
# Egy pár
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20250101-20260327 \
  -i 1h \
  -p ETH/USDC:USDC

# Összes pár
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20250101-20260327 \
  -i 1h

# Havi bontással
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20250101-20260327 \
  -i 1h --breakdown month

# Részletesebb szimuláció (gyertyán belül)
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20250101-20260327 \
  -i 1h --timeframe-detail 5m
```

### 10.3 Hyperopt

**Fontos: `--analyze-per-epoch` KÖTELEZŐ!** A SuperTrend ATR periódus és szorzó az indikátor-számítást érinti.

> ⚠️ **Mindig `freqtrade_st` service-t használj** a SuperTrendMacdRsiStrategy parancsokhoz!
> `freqtrade_bb`-vel is megtalálja a stratégiát (közös user_data), de a config és .env a BB stratégiáé lesz.

```bash
# 1. st_pair_configs.json-ban: "ETH/USDC:USDC" → "_ETH/USDC:USDC"

# 2. Hyperopt futtatása
docker compose run --rm freqtrade_st hyperopt \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 500 \
  --timerange 20250101-20260201 \
  --analyze-per-epoch \
  -p ETH/USDC:USDC

# 3. Eredmény bemásolása st_pair_configs.json-ba, kulcs visszaállítása
# 4. Backtest validáció
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20250101-20260201 \
  -i 1h -p ETH/USDC:USDC
```

### 10.4 Eredmény bemásolása st_pair_configs.json-ba

```json
"ETH/USDC:USDC": {
    "supertrend_atr_period": 12,
    "supertrend_multiplier": 2.8,
    "rsi_threshold": 52,
    "swing_lookback": 8,
    "risk_reward_ratio": 2.0,
    "max_candle_size_pct": 0.0,
    "stake_amount_usd": 10.0
}
```

**Fájl helye:** `user_data/strategies/supertrend_macd_rsi/st_pair_configs.json`

### 10.5 Trade méret módosítása páronként

A `stake_amount_usd` páronként eltérő lehet az `st_pair_configs.json`-ban:

```json
{
  "BTC/USDC:USDC": {
    "stake_amount_usd": 20.0,
    ...
  },
  "DOGE/USDC:USDC": {
    "stake_amount_usd": 5.0,
    ...
  }
}
```

Módosítás után újra kell indítani: `docker compose restart freqtrade_st`

### 10.6 Logok értelmezése

```
# Induláskor:
SuperTrendMacdRsi | st_pair_configs.json betöltve, 10 pár konfigurálva
SuperTrendMacdRsi | ETH/USDC:USDC | atr_period=10, multiplier=3.0, swing_lookback=10

# Minden gyertyán:
[ETH/USDC:USDC] 2026-03-27 15:00:00+00:00 | close=1950.1200  ST=1920.3400(UP)  RSI=54.2  MACD=2.1234/SIG=1.9876  SwLow=1890.0000  SwHigh=1980.0000
[ETH/USDC:USDC] LONG  blokkolt: MACD 2.1234 <= SIG 2.2000
[ETH/USDC:USDC] SHORT blokkolt: ST uptrend (dir=1) | RSI 54.2 >= 50

# Belépéskor:
SuperTrendMacdRsi | ETH/USDC:USDC | LONG filled @ 1950.12 | SL=1890.00 | TP=2040.18 | R=60.120000 | RR=1.5

# TP elérésekor:
SuperTrendMacdRsi | ETH/USDC:USDC | LONG TP hit @ 2041.00 (target=2040.18)
```

---

## 11. Három bot kezelése - VPS beállítás

### Caddy konfiguráció (VPS-en)

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

freqtrade-st.kebodev.hu {
    reverse_proxy localhost:8082
}
```

```bash
sudo systemctl reload caddy
```

**DNS**: Mindhárom domainhez adj `A` rekordot (ugyanaz a VPS IP).

### Mindhárom bot egyszerre

```bash
# Összes bot indítása
docker compose up -d

# Logok (valós idejű, összes)
docker compose logs -f

# Egy bot logja
docker compose logs -f freqtrade_st

# Állapot
docker compose ps

# Összes leállítása
docker compose down
```

### FreqUI bot selector beállítása

1. Nyisd meg: **https://freqtrade.kebodev.hu**
2. Jobb felső sarokba → **"Switch Bot"** gomb
3. **"Add Bot"** → `https://freqtrade-rb.kebodev.hu` (rb bot)
4. **"Add Bot"** → `https://freqtrade-st.kebodev.hu` (st bot)

Ezután egy ablakból mindhárom bot kezelhető.

### Mikor kell újraindítani?

| Mit változtattál? | Bot | Parancs |
|-------------------|-----|---------|
| `bb_rsi_adx/pair_configs.json` | freqtrade_bb | `docker compose restart freqtrade_bb` |
| `bb_rsi_adx/config.json` | freqtrade_bb | `docker compose restart freqtrade_bb` |
| `BBRsiAdxStrategy.py` | freqtrade_bb | `docker compose restart freqtrade_bb` |
| `range_breakout/rb_pair_configs.json` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `range_breakout/config.json` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `RangeBreakoutPullbackStrategy.py` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `supertrend_macd_rsi/st_pair_configs.json` | freqtrade_st | `docker compose restart freqtrade_st` |
| `supertrend_macd_rsi/config.json` | freqtrade_st | `docker compose restart freqtrade_st` |
| `SuperTrendMacdRsiStrategy.py` | freqtrade_st | `docker compose restart freqtrade_st` |

### Backtest futtatása miközben botok futnak

```bash
# BBRsiAdx backtest (fut a freqtrade_bb bot mellett)
docker compose run --rm freqtrade_bb backtesting \
  --strategy-path user_data/strategies/bb_rsi_adx \
  --strategy BBRsiAdxStrategy \
  --config user_data/strategies/bb_rsi_adx/config.json.orignal \
  --timerange 20260101-20260327 -i 1h

# ST backtest (fut a freqtrade_st bot mellett)
docker compose run --rm freqtrade_st backtesting \
  --strategy-path user_data/strategies/supertrend_macd_rsi \
  --strategy SuperTrendMacdRsiStrategy \
  --config user_data/strategies/supertrend_macd_rsi/config.json.orignal \
  --timerange 20260101-20260327 -i 1h
```

A `docker compose run --rm` ideiglenes konténereket indít — **nem zavarják a futó botokat**.

### Összefoglaló táblázat

| | BBRsiAdxStrategy | RangeBreakoutPullbackStrategy | SuperTrendMacdRsiStrategy |
|--|--|--|--|
| **Service** | `freqtrade_bb` | `freqtrade_rb` | `freqtrade_st` |
| **Config** | `bb_rsi_adx/config.json` | `range_breakout/config.json` | `supertrend_macd_rsi/config.json` |
| **Pair configs** | `bb_rsi_adx/pair_configs.json` | `range_breakout/rb_pair_configs.json` | `supertrend_macd_rsi/st_pair_configs.json` |
| **Timeframe** | 1H | 5m | 1H |
| **Stake** | 20 USDC | 5 USDC | 10 USDC (páronként állítható) |
| **Max trades** | 5 | 10 | 5 |
| **Port (lokális)** | 8080 | 8081 | 8082 |
| **VPS URL** | freqtrade.kebodev.hu | freqtrade-rb.kebodev.hu | freqtrade-st.kebodev.hu |
| **Log** | `bb_rsi_adx/logs/freqtrade.log` | `range_breakout/logs/freqtrade.log` | `supertrend_macd_rsi/logs/freqtrade.log` |
