# Freqtrade Használati Útmutató

> **Két aktív stratégia fut a rendszerben:**
> - **BBRsiAdxStrategy** – 1H Bollinger+RSI+ADX futures stratégia (`config.json`)
> - **RangeBreakoutPullbackStrategy** – 5m NY range kitörés+visszazárás stratégia (`config_rb.json`)
>
> Az 1-8. szekció az **BBRsiAdxStrategy**-re vonatkozik.
> A 9-10. szekció a **RangeBreakoutPullbackStrategy**-t és a **két bot együttes kezelését** ismerteti.

## Tartalomjegyzék

1. [Alapok - Hogyan működik a rendszer?](#1-alapok---hogyan-működik-a-rendszer)
2. [Adat letöltés (BBRsiAdx)](#2-adat-letöltés)
3. [Backtesting - BBRsiAdxStrategy](#3-backtesting---stratégia-tesztelése-múltbeli-adatokon)
4. [Hyperopt - BBRsiAdxStrategy](#4-hyperopt---páronkénti-paraméter-optimalizáció)
5. [Teljes workflow: Hyperopt-tól a live tradingig](#5-teljes-workflow-hyperopt-tól-a-live-tradingig)
6. [Live/Dry-run trading - Éles kereskedés](#6-livedry-run-trading---éles-kereskedés)
7. [FreqUI webfelület](#7-frequi-webfelület)
8. [Gyakori kérdések](#8-gyakori-kérdések)
9. [RangeBreakoutPullbackStrategy - Adat, Backtest, Hyperopt](#9-rangebreakoutpullbackstrategy---adat-backtest-hyperopt)
10. [Két bot egy FreqUI-n - VPS beállítás](#10-két-bot-egy-frequi-n---vps-beállítás)

---

## 1. Alapok - Hogyan működik a rendszer?

### Minden parancsot a `ft_userdata/` könyvtárból futtass!

```bash
cd ft_userdata
```

### A Docker kétféle módban tud futni

A Freqtrade Docker konténer kétféle dolgot tud csinálni. **Fontos megérteni a különbséget:**

| Mód | Parancs | Mire való |
|-----|---------|-----------|
| **Trading** (live/dry-run) | `docker compose up -d` | Valós idejű kereskedés a Binance-en. Háttérben fut, 0-24. |
| **Egyszeri parancsok** | `docker compose run --rm freqtrade ...` | Backtesting, hyperopt, adat letöltés, webserver. Lefut és leáll. |

- A `docker compose up -d` a `docker-compose.yml`-ben lévő `command:` sort hajtja végre (ami a `trade` parancs)
- A `docker compose run --rm freqtrade ...` egy **ideiglenes** konténert indít a megadott paranccsal, majd törli magát (`--rm`)

**Ezek egymástól függetlenek.** Futtathatsz backtestet miközben a trading bot is fut.

### Mi a stratégia?

A `BBRsiAdxStrategy` egy kereskedési stratégia, ami 6 darab számszerű paraméterrel dolgozik. Ezek a paraméterek határozzák meg, hogy mikor nyisson és zárjon pozíciót.

### Páronkénti paraméterek (`pair_configs.json`)

A stratégia **minden párhoz külön paramétereket** használ. Miért? Mert ami a BTC-nek jó beállítás, az nem biztos hogy a DOGE-nak is jó.

Az összes pár paramétere egyetlen fájlban van tárolva:
**`user_data/strategies/pair_configs.json`**

Ez így néz ki:

```json
{
  "BTC/USDC:USDC": {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_threshold": 55,
    "adx_threshold_1h": 20,
    "adx_threshold_4h": 25,
    "atr_multiplier": 4.5
  },
  "ETH/USDC:USDC": {
    "bb_period": 18,
    "bb_std": 1.8,
    "rsi_threshold": 52,
    "adx_threshold_1h": 22,
    "adx_threshold_4h": 27,
    "atr_multiplier": 4.2
  }
}
```

**Hogyan működik:**
- Amikor a stratégia elindul (backtest, hyperopt, vagy live), **betölti** ezt a fájlt
- Amikor egy adott párra (pl. BTC/USDC:USDC) számol indikátorokat, **megnézi, hogy az a pár benne van-e a fájlban**
- Ha **benne van** → azokat a paramétereket használja
- Ha **nincs benne** → a kódban lévő default értékeket használja (ez a hyperopt futtatáskor fontos, lásd később)

### A 6 paraméter magyarázata

| Paraméter | Mi ez? | Mire hatással van? |
|-----------|--------|-------------------|
| `bb_period` | Bollinger szalag periódusa | Hány gyertyából számolja a szalagot (15-20) |
| `bb_std` | Bollinger szalag szórása | Milyen széles a szalag (1.5-2.0) |
| `rsi_threshold` | RSI küszöbérték | 4H RSI felett/alatt nyit pozíciót (50-55) |
| `adx_threshold_1h` | 1 órás ADX küszöb | Minimum trendérősség 1H-n (20-25) |
| `adx_threshold_4h` | 4 órás ADX küszöb | Minimum trendérősség 4H-n (25-30) |
| `atr_multiplier` | ATR szorzó a stoploss-hoz | Mekkora stoploss távolság (3.0-5.0) |

---

## 2. Adat letöltés

Mielőtt backtestet vagy hyperoptot futtatsz, **le kell tölteni a historikus adatokat** a Binance-ról.

### Összes pár adatának letöltése

```bash
docker compose run --rm freqtrade download-data \
  --timeframes 1h 4h \
  --timerange 20250701- \
  --config user_data/config.json.orignal
```

Ez letölti a `config.json`-ben lévő **összes pár** (BTC, ETH, SOL, ARB, TIA, ADA, AVAX, DOGE) adatát a megadott időszakra.

A `config.json`-ben beállított `trading_mode: futures` miatt automatikusan letölti:
- **OHLCV gyertya adat** (futures) - az ár adatok
- **Funding rate** - a funding fee számításhoz
- **Mark price** - a mark ár a liquidation számításhoz

### Csak egy pár adatának letöltése

Ha csak egy konkrét párhoz kell adat (pl. a hyperopthoz):

```bash
docker compose run --rm freqtrade download-data \
  --timeframes 1h 4h \
  --timerange 20250701- \
  --config user_data/config.json.orignal \
  --pairs BTC/USDC:USDC
```

### Több specifikus pár letöltése

```bash
docker compose run --rm freqtrade download-data \
  --timeframes 1h 4h \
  --timerange 20250701- \
  --config user_data/config.json.orignal \
  --pairs BTC/USDC:USDC ETH/USDC:USDC SOL/USDC:USDC
```

### Fontos paraméterek

| Paraméter | Leírás | Példa |
|-----------|--------|-------|
| `--timeframes` | Milyen időkereteket töltsön | `1h 4h 5m 1d` |
| `--timerange` | Milyen időszaktól | `20250701-` (2025.07.01-től máig) |
| `--timerange` | Zárt időszak | `20250701-20260101` |
| `--config` | Config fájl (exchange, párok) | `user_data/config.json` |
| `--pairs` | Specifikus párok (felülírja config-ot) | `BTC/USDC:USDC ETH/USDC:USDC` |
| `--exchange` | Exchange (ha nincs config) | `binance` |

### Adat frissítés

Ugyanaz a parancs újra futtatva **hozzáfűzi** az új adatokat a meglévőkhöz (nem törli a régit).

### Adat ellenőrzés

Az adatok itt tárolódnak: `user_data/data/binance/futures/`

Fájlnév formátum: `PAIR-TIMEFRAME-TYPE.feather`
- Példa: `BTC_USDC_USDC-1h-futures.feather`
- Típusok: `futures` (OHLCV), `funding_rate`, `mark`

### Timerange formátumok

```
--timerange 20250701-          # 2025.07.01-től máig
--timerange -20260101          # Az elejétől 2026.01.01-ig
--timerange 20250701-20260101  # 2025.07.01-től 2026.01.01-ig
```

---

## 3. Backtesting - Stratégia tesztelése múltbeli adatokon

A backtesting azt jelenti, hogy a stratégiát lefuttatjuk **múltbeli adatokon**, mintha valódi kereskedés folyna. Így megnézhetjük, hogyan teljesített volna a stratégia.

### Backtesting az összes párral

Ez az alapértelmezett mód. A `config.json`-ben lévő **mind a 8 pár** tesztelődik egyszerre:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h
```

Ilyenkor **minden pár a saját paramétereit használja** a `pair_configs.json`-ból. A BTC a BTC beállításaival fut, az ETH az ETH beállításaival, stb.

### Backtesting egyetlen párral

Ha csak **egy konkrét párt** akarsz tesztelni, add hozzá a `-p` (vagy `--pairs`) kapcsolót:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  -p BTC/USDC:USDC
```

Ez **csak a BTC-t** teszteli, a `pair_configs.json`-ból a BTC paramétereit használva.

### Backtesting néhány kiválasztott párral

Több párt is megadhatsz egyszerre, szóközzel elválasztva:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  -p BTC/USDC:USDC ETH/USDC:USDC SOL/USDC:USDC
```

### Honnan tudom, hogy tényleg a pair_configs.json értékeit használja?

A logban megjelenik minden párra, hogy milyen paramétereket használ:

```
BBRsiAdx | pair_configs.json betöltve, 8 pár konfigurálva
BBRsiAdx | BTC/USDC:USDC | bb_period=18, bb_std=1.8, atr_multiplier=4.2
BBRsiAdx | ETH/USDC:USDC | bb_period=17, bb_std=1.9, atr_multiplier=3.8
BBRsiAdx | SOL/USDC:USDC | bb_period=20, bb_std=2.0, atr_multiplier=4.5
```

Ha nem optimalizáltál még egy párt, az a default értékekkel fog futni (bb_period=20, bb_std=2.0, stb.).

### Backtesting parancs paraméterei

| Paraméter | Leírás | Példa |
|-----------|--------|-------|
| `--strategy` | Stratégia osztály neve | `BBRsiAdxStrategy` |
| `-i` / `--timeframe` | Fő timeframe | `1h` |
| `--timerange` | Tesztelési időszak | `20250701-20260201` |
| `--config` | Config fájl | `user_data/config.json` |
| `-p` / `--pairs` | Melyik pár(ok)ra teszteljen | `BTC/USDC:USDC` |
| `--dry-run-wallet` | Kezdő egyenleg | `1000` |
| `--fee` | Egyedi fee érték (ratio) | `0.001` (= 0.1%) |
| `--timeframe-detail` | Részletesebb szimuláció | `5m` (gyertyán belüli mozgás) |
| `--breakdown` | Időszakos bontás | `month year` |
| `--strategy-list` | Több stratégia összehasonlítása | `Strategy1 Strategy2` |

### Havi/éves bontás

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  --breakdown month year
```

### Részletesebb backtesting (gyertyán belüli szimuláció)

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h \
  --timeframe-detail 5m
```

> Ehhez 5m adat is kell! Több memóriát és időt igényel, de pontosabb eredményt ad.

### Eredmények értelmezése

A backtest kimenet táblázatai:

1. **BACKTESTING REPORT** - Összes trade páronként (Win/Loss/Draw)
2. **LEFT OPEN TRADES** - A tesztidőszak végén nyitott pozíciók
3. **ENTER TAG STATS** - Belépési tag-ek szerinti bontás
4. **EXIT REASON STATS** - Kilépési okok szerinti bontás (roi, stoploss, exit_signal)
5. **SUMMARY METRICS** - Összefoglaló metrikák

Fontos metrikák:
- **Total profit %**: Teljes profit a kezdőtőkéhez képest
- **Sharpe**: Kockázattal korrigált hozam (>1 jó, >2 nagyon jó)
- **Sortino**: Mint a Sharpe, de csak a lefelé volatilitást bünteti
- **Max drawdown**: Legnagyobb csúcstól-völgyig esés
- **Profit factor**: Nyerő tradek összege / vesztes tradek összege (>1.5 jó)
- **SQN**: System Quality Number (>2 jó, >3 kiváló)
- **Win%**: Nyerő tradek aránya

### Binance kapcsolat backtestingkor

A backtester **mindig kapcsolódik** a Binance-hez, még ha van is lokális adat. Ez azért van, mert le kell kérnie:
- Trading limitek (minimum trade méret)
- Ár precizitás (hány tizedes)
- Fee-k (kereskedési díjak)

Ez publikus API hívás, **nem igényel API kulcsot** és nem kereskedik.

---

## 4. Hyperopt - Páronkénti paraméter optimalizáció

### Mi a Hyperopt?

A hyperopt automatikusan **megkeresi a legjobb paraméter-kombinációt** egy adott párhoz. Többszáz backtestet futtat különböző paraméterekkel, és kiválasztja a legjobbat.

### Miért páronként?

Minden kriptovaluta másképp viselkedik. A BTC lassan, nagy trendekben mozog, a DOGE hirtelen kiugrik és visszaesik. Ezért **minden párhoz külön-külön futtatjuk** a hyperoptot, és mindegyik megkapja a saját optimális beállításait.

### Hogyan működik a hyperopt a pair_configs.json-nal?

Fontos megérteni:

1. A hyperopt **próbálgat** különböző paraméter értékeket (pl. bb_period 15-20 között)
2. Ha a pár benne van a `pair_configs.json`-ban, a stratégia **onnan veszi a fix értékeket**, nem a hyperopt próbálgatásából
3. Ezért a hyperopt **csak akkor tud optimalizálni egy párt, ha az NINCS benne** a `pair_configs.json`-ban

Tehát: **hyperopt előtt ki kell venni a párt a `pair_configs.json`-ból**, utána vissza kell tenni az eredménnyel.

### Hyperopt futtatása egy párra - lépésről lépésre

#### 1. lépés: Pár kivétele a `pair_configs.json`-ból

Nyisd meg a `user_data/strategies/pair_configs.json` fájlt, és **írd át a kulcs nevét** úgy, hogy a stratégia ne találja meg. A legegyszerűbb: tegyél egy `_` jelet a pár neve elé.

Példa - ha a SOL-t akarod optimalizálni, írd át a kulcsát:

**Előtte:**
```json
{
  "BTC/USDC:USDC": { ... },
  "SOL/USDC:USDC": { ... },
  "ETH/USDC:USDC": { ... }
}
```

**Utána (a SOL ki van véve):**
```json
{
  "BTC/USDC:USDC": { ... },
  "_SOL/USDC:USDC": { ... },
  "ETH/USDC:USDC": { ... }
}
```

A `_SOL/USDC:USDC` kulcsot a stratégia nem fogja megtalálni, ezért a hyperopt próbálgatott értékeit fogja használni.

#### 2. lépés: Hyperopt futtatása

```bash
docker compose run --rm freqtrade hyperopt \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 500 \
  --timerange 20250701-20260201 \
  --analyze-per-epoch \
  -p SOL/USDC:USDC
```

```bash
docker compose run --rm freqtrade hyperopt \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 500 \
  --timerange 20250701-20260201 \
  --analyze-per-epoch \
  -j 2 \
  -p SOL/USDC:USDC
```

**A parancs minden egyes részének magyarázata:**

| Rész | Mit jelent |
|------|-----------|
| `docker compose run --rm freqtrade` | Ideiglenes Docker konténert indít a Freqtrade-del. A `--rm` törli a konténert a futás végén. |
| `hyperopt` | A Freqtrade hyperopt módját indítja (paraméter optimalizáció). |
| `--strategy BBRsiAdxStrategy` | Melyik stratégiát optimalizálja. |
| `--config user_data/config.json` | A config fájl elérési útja (exchange beállítások, API kulcsok, stb.). |
| `--hyperopt-loss SharpeHyperOptLossDaily` | A célfüggvény: mit próbáljon maximalizálni. A Sharpe-ráta a hozam/kockázat arányt méri. |
| `--spaces buy` | Melyik paramétercsoportot optimalizálja. Mind a 6 paraméterünk a `buy` space-ben van. |
| `--epochs 500` | Hány különböző paraméter-kombinációt próbáljon ki. 500-1000 ajánlott. |
| `--timerange 20250701-20260201` | Melyik időszak adatain optimalizáljon. |
| `--analyze-per-epoch` | **KÖTELEZŐ!** Lásd lent a magyarázatot. |
| `-p SOL/USDC:USDC` | **Melyik párra** optimalizáljon. Mindig CSAK EGY párt adj meg! |

> **Miért kell az `--analyze-per-epoch`?**
> A `bb_period` és `bb_std` paraméterek az indikátor-számításban (Bollinger szalag) vannak használva.
> Alapesetben a Freqtrade **egyszer** kiszámolja az indikátorokat és cache-eli az eredményt.
> Ez azt jelenti, hogy hiába próbálgat a hyperopt különböző `bb_period` értékeket (pl. 15, 17, 20),
> mindig az elsőnek kiszámolt Bollinger szalagot használná → az optimalizáció értelmetlen lenne.
> Az `--analyze-per-epoch` flag megmondja a Freqtrade-nek, hogy **minden epoch-ban számoljon újra**
> mindent az aktuális paraméterekkel. Lassabb, de nélküle a hyperopt nem működik helyesen.

#### 3. lépés: Várj, amíg lefut

Egy pár, 500 epoch, `--analyze-per-epoch` flag-gel általában **10-30 percet** vesz igénybe (géptől függően). A terminálban látni fogod a haladást:

```
Epochs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  120/500  24%
```

#### 4. lépés: Eredmény kiolvasása

A hyperopt végén megjelenik a legjobb eredmény:

```
Best result:

    44/500:    135 trades. Avg profit 0.57%. Total profit 77.38 USDC.

    # Buy hyperspace params:
    buy_params = {
        'bb_period': 18,
        'bb_std': 1.8,
        'rsi_threshold': 52,
        'adx_threshold_1h': 22,
        'adx_threshold_4h': 27,
        'atr_multiplier': 4.2,
    }
```

Ez az a 6 érték, amit a hyperopt a legjobbnak talált a SOL párra.

#### 5. lépés: Eredmény bemásolása a `pair_configs.json`-ba

Nyisd meg a `user_data/strategies/pair_configs.json` fájlt, és:

1. **Írd vissza a helyes kulcsnevet** (`_SOL/USDC:USDC` → `SOL/USDC:USDC`)
2. **Írd be az új értékeket** a hyperopt kimenetéből

**Előtte:**
```json
"_SOL/USDC:USDC": {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_threshold": 55,
    "adx_threshold_1h": 20,
    "adx_threshold_4h": 25,
    "atr_multiplier": 4.5
}
```

**Utána (optimalizált értékekkel):**
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

#### 6. lépés: Ellenőrzés backtesttel

Futtass egy backtestet az adott párra, hogy meggyőződj róla, az új paraméterek jól működnek:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260201 \
  -i 1h \
  -p SOL/USDC:USDC
```

A logban ellenőrizd, hogy a `pair_configs.json`-ból vette-e az értékeket:
```
BBRsiAdx | SOL/USDC:USDC | bb_period=18, bb_std=1.8, atr_multiplier=4.2
```

#### 7. lépés: Ismétlés a többi párra

Ugyanezt a folyamatot (1-6. lépés) ismételd meg minden párra:
- BTC/USDC:USDC
- ETH/USDC:USDC
- SOL/USDC:USDC
- ARB/USDC:USDC
- TIA/USDC:USDC
- ADA/USDC:USDC
- AVAX/USDC:USDC
- DOGE/USDC:USDC

Mindig csak **egy párt** végy ki a `pair_configs.json`-ból, futtasd a hyperoptot, írd be az eredményt, majd lépj a következőre.

### Hyperopt parancs összes paramétere

| Paraméter | Leírás | Példa / Default |
|-----------|--------|-----------------|
| `--strategy` | Stratégia neve | `BBRsiAdxStrategy` |
| `--hyperopt-loss` | Célfüggvény (mit optimalizáljon) | `SharpeHyperOptLossDaily` |
| `--spaces` | Melyik paramétercsoportot | `buy` |
| `-e` / `--epochs` | Iterációk száma | `500` (ajánlott: 500-1000) |
| `--timerange` | Optimalizálási időszak | `20250701-20260201` |
| `-p` / `--pairs` | Melyik párra futtasson | `SOL/USDC:USDC` |
| `--analyze-per-epoch` | Indikátor újraszámítás epochonként | **KÖTELEZŐ** |
| `-j` / `--job-workers` | CPU magok száma | `-1` (mind), `-2` (mind-1), `1` (szekvenciális) |
| `--early-stop` | Leállás javulás nélkül N epoch után | `150` (0 = kikapcsolva) |
| `--min-trades` | Minimum trade szám elfogadáshoz | `1` (default) |
| `--random-state` | Fix random seed (reprodukálhatóság) | `42` |
| `--print-all` | Minden epoch eredménye | (flag) |
| `--print-json` | JSON formátumú kimenet | (flag) |
| `--disable-param-export` | Ne mentse a JSON fájlt | (flag) |

### Loss function-ök (célfüggvények)

A `--hyperopt-loss` értéke határozza meg, hogy **mit próbáljon maximalizálni** a hyperopt:

| Loss function | Mit optimalizál | Mikor használd |
|---------------|----------------|----------------|
| `SharpeHyperOptLossDaily` | Napi Sharpe-ráta | **Általános célra, jó kiindulás** |
| `SortinoHyperOptLossDaily` | Napi Sortino-ráta | Ha a lefelé kockázat a fontos |
| `MaxDrawDownHyperOptLoss` | Max drawdown minimalizálás | Konzervatív, alacsony kockázat |
| `CalmarHyperOptLoss` | Calmar-ráta (hozam/drawdown) | Hozam-kockázat arány |
| `ProfitDrawDownHyperOptLoss` | Max profit & min drawdown | Agresszívebb, de figyelmes |
| `OnlyProfitHyperOptLoss` | Csak profit | Agresszív, overfitting veszély |

### Korábbi hyperopt eredmények megtekintése

```bash
# Összes eredmény listázása
docker compose run --rm freqtrade hyperopt-list \
  --config user_data/config.json.orignal

# Legjobb eredmény részletei
docker compose run --rm freqtrade hyperopt-show \
  --config user_data/config.json.orignal \
  --best
```

---

## 5. Teljes workflow: Hyperopt-tól a live tradingig

Ez a fejezet végigvezet a **teljes folyamaton**, az elejétől a végéig.

### 5.1 Előkészítés: Adat letöltés

```bash
docker compose run --rm freqtrade download-data \
  --timeframes 1h 4h \
  --timerange 20250701- \
  --config user_data/config.json.orignal
```

### 5.2 Hyperopt futtatása minden párra (egyenként)

Ismételd ezt mind a 8 párra (BTC, ETH, SOL, ARB, TIA, ADA, AVAX, DOGE):

**a)** Nyisd meg a `pair_configs.json`-t és írd át a pár kulcsát `_` prefixszel (pl. `"SOL/USDC:USDC"` → `"_SOL/USDC:USDC"`)

**b)** Futtasd a hyperoptot (cseréld ki a pár nevét):
```bash
docker compose run --rm freqtrade hyperopt \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 500 \
  --timerange 20250701-20260201 \
  --analyze-per-epoch \
  -p SOL/USDC:USDC
```

**c)** Az eredményből másold ki a 6 paramétert és írd be a `pair_configs.json`-ba (és állítsd vissza a kulcsnevet `_SOL` → `SOL`)

**d)** Lépj a következő párra

### 5.3 Validálás: Backtest az összes párral együtt

Miután **minden pár** megkapta a saját optimalizált paramétereit, futtass egy backtestet az összes párral:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20250701-20260227 \
  -i 1h
```

Ellenőrizd a logban, hogy minden pár a saját paramétereit használja:
```
BBRsiAdx | pair_configs.json betöltve, 8 pár konfigurálva
BBRsiAdx | BTC/USDC:USDC | bb_period=18, bb_std=1.8, atr_multiplier=4.2
BBRsiAdx | ETH/USDC:USDC | bb_period=17, bb_std=1.9, atr_multiplier=3.8
BBRsiAdx | SOL/USDC:USDC | bb_period=19, bb_std=1.7, atr_multiplier=4.0
...
```

### 5.4 Out-of-sample teszt (overfitting ellenőrzés)

A hyperoptot a `20250701-20260201` időszakon futtattad. Most teszteld egy **másik időszakon** is, amin **nem** futott optimalizáció:

```bash
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json.orignal \
  --timerange 20260201-20260227 \
  -i 1h
```

Ha itt is hasonlóan jól teljesít → a stratégia valószínűleg nem overfittel (nem tanulta be túlságosan a múltat).
Ha itt sokkal rosszabbul teljesít → overfitting, érdemes kevesebb epoch-kal vagy más loss function-nel újrapróbálni.

### 5.5 Live/Dry-run trading indítása

Ha elégedett vagy az eredménnyel, indítsd el a trading botot:

```bash
docker compose up -d
```

Ez a parancs:
1. Elindítja a Freqtrade konténert a háttérben
2. A `docker-compose.yml`-ben lévő `trade` parancsot hajtja végre
3. A bot 0-24 fut, figyeli a piacot, és automatikusan kereskedik

Részletek a következő fejezetben.

---

## 6. Live/Dry-run trading - Éles kereskedés

### A lényeg 3 mondatban

1. A `docker compose up -d` parancs indítja el a trading botot **ÉS** a FreqUI webes felületet
2. A FreqUI-ban a **Trade fülön** látod a nyitott pozíciókat, kézzel zárhatsz, stb.
3. A `docker compose run --rm freqtrade webserver` egy **teljesen más dolog** - az csak backtesting felületet ad, NEM kereskedik

### Hogyan indul el a trading?

A `docker-compose.yml` fájlban ez a parancs van beállítva:

```yaml
command: >
  trade
  --logfile /freqtrade/user_data/logs/freqtrade.log
  --db-url sqlite:////freqtrade/user_data/tradesv3.sqlite
  --config /freqtrade/user_data/config.json
  --strategy BBRsiAdxStrategy
```

Amikor kiadod a `docker compose up -d` parancsot, ez történik:

1. Docker elindítja a Freqtrade konténert **a háttérben**
2. A konténer végrehajtja a fenti `trade` parancsot
3. A Freqtrade betölti a `config.json`-t (exchange beállítások, párlista, Telegram, stb.)
4. Betölti a `BBRsiAdxStrategy`-t
5. A stratégia **automatikusan betölti a `pair_configs.json`-t**
6. **Elindítja az API szervert** a 8080-as porton (mert a config-ban `api_server.enabled: true`)
7. Elkezd kereskedni: figyeli a piacot, és ha jelet lát, nyit/zár pozíciót
8. **Minden pár a `pair_configs.json`-ban lévő saját paramétereit használja** - pont ugyanazokat, amiket a backtestben és hyperoptban beállítottál

**Nem kell semmit külön beállítani.** Ami a `pair_configs.json`-ban van, azt használja élesben is.

### FreqUI Trade felület (böngészőből)

Amíg a bot fut (`docker compose up -d`), a FreqUI elérhető a böngészőben:

**http://localhost:8080**

Bejelentkezéshez a `.env` fájlban beállított felhasználónév és jelszó kell (`FREQTRADE__API_SERVER__USERNAME` és `FREQTRADE__API_SERVER__PASSWORD`).

A **Trade fülön** (ami csak trade módban jelenik meg!) ezeket látod/csinálhatod:

| Funkció | Leírás |
|---------|--------|
| **Nyitott pozíciók** | Melyik párban van nyitott long/short, mióta, mennyi a profit |
| **Zárt tradek** | Korábbi tradek listája eredménnyel |
| **Kézi pozíció zárás** | Bármelyik nyitott pozíciót kézzel bezárhatod |
| **Kézi pozíció nyitás** | Force entry: kézzel nyithatsz long/short pozíciót bármelyik párban |
| **Bot start/stop** | A botot leállíthatod/elindíthatod a felületről |
| **Grafikon** | Gyertyák, indikátorok, belépési/kilépési pontok vizualizálása |
| **Teljesítmény** | Összesített profit, drawdown, nyerési arány |

> **A kézi pozíció nyitás** (force entry) a `config.json`-ben a `"force_entry_enable": true` beállítással van engedélyezve (már be van állítva).

### Dry-run vs. Live mód

A `config.json`-ben a `"dry_run"` beállítás határozza meg, hogy valódi pénzzel kereskedik-e:

| Beállítás | Mit jelent | Mikor használd |
|-----------|-----------|----------------|
| `"dry_run": true` | **Szimulált kereskedés.** A bot úgy tesz, mintha kereskedne, de NEM küld rendeléseket a Binance-re. Nem mozog valódi pénz. A FreqUI-ban is látod a szimulált pozíciókat. | Tesztelésre, amíg nem vagy biztos a stratégiában. |
| `"dry_run": false` | **Éles kereskedés valódi pénzzel.** A bot ténylegesen vásárol és elad a Binance-en. | Ha kész vagy élesen kereskedni. Ehhez API kulcsok kellenek a `.env`-ben! |

Jelenleg a configban `"dry_run": true` van beállítva, tehát a bot **szimulált módban** fog futni. A FreqUI-ban is szimulált pozíciókat fogsz látni, de minden úgy fog kinézni, mintha éles lenne.

### Trading indítása és kezelése

```bash
# 1. Trading bot indítása háttérben (FreqUI is elindul!)
docker compose up -d

# 2. Nyisd meg a böngészőben: http://localhost:8080
#    Jelentkezz be a .env-ben beállított felhasználónévvel/jelszóval

# 3. Ellenőrizd, hogy fut-e a konténer
docker compose ps

# 4. Nézd meg a logokat terminálban (valós idejű követés)
docker compose logs -f

# 5. Utolsó 100 sor log
docker compose logs --tail 100

# 6. Trading bot leállítása (FreqUI is leáll!)
docker compose down

# 7. Újraindítás (pl. pair_configs.json módosítás után)
docker compose restart
```

### Mikor kell újraindítani a botot?

| Mit változtattál? | Kell újraindítás? | Parancs |
|-------------------|-------------------|---------|
| `pair_configs.json` (paraméterek) | **Igen** | `docker compose restart` |
| `config.json` (config) | **Igen** | `docker compose restart` |
| `BBRsiAdxStrategy.py` (stratégia kód) | **Igen** | `docker compose restart` |
| Semmi, csak nézni akarod a logot | Nem | `docker compose logs -f` |
| Semmi, csak a FreqUI-t nézed | Nem | Böngésző: http://localhost:8080 |

A `pair_configs.json` **induláskor töltődik be egyszer**. Ha módosítod a fájlt (pl. beírod egy pár új hyperopt eredményét), a bot **nem veszi észre automatikusan** - újra kell indítani.

### Logok értelmezése

A logban keresheted a `BBRsiAdx |` előtagú sorokat, amik a stratégia üzenetei:

```
# Induláskor - paraméterek betöltése:
BBRsiAdx | pair_configs.json betöltve, 8 pár konfigurálva
BBRsiAdx | BTC/USDC:USDC | bb_period=18, bb_std=1.8, atr_multiplier=4.2

# Amikor pozíciót nyit:
BBRsiAdx | SOL/USDC:USDC | LONG entry filled @ 145.23, SL set to 138.450000

# Freqtrade saját üzenetei:
freqtrade.worker - INFO - Bot heartbeat. PID=1, version=2024.xx
```

### Telegram értesítések

Ha a `config.json`-ben a Telegram be van kapcsolva (`"enabled": true`), a bot Telegram üzeneteket küld:
- Pozíció nyitáskor
- Pozíció záráskor (profit/loss-szal)
- Hiba esetén

---

## 7. FreqUI webfelület

### A FreqUI a Freqtrade beépített webes felülete

A FreqUI **nem egy külön program** - a Freqtrade szerves része. Mindig a Freqtrade konténerrel együtt fut, és a Freqtrade üzemmódjától függ, hogy mit mutat.

### A két üzemmód és a FreqUI kapcsolata

A Freqtrade kétféle üzemmódban tud futni. Mindkettőben elérhető a FreqUI a **http://localhost:8080** címen, de **más-más funkciókat** mutat:

**1. Trade mód** (`docker compose up -d`):
- A bot **kereskedik** a háttérben (figyeli a piacot, nyit/zár pozíciókat)
- A FreqUI-ban megjelenik a **Trade fül**:
  - Nyitott pozíciók listája (pár, irány, profit, mióta nyitva)
  - Zárt tradek története
  - Kézi pozíció zárás (bármelyik nyitott pozíciót bezárhatod)
  - Kézi pozíció nyitás (force entry - ha akarod, kézzel nyithatsz)
  - Bot start/stop gomb
  - Gyertyás grafikon indikátorokkal, belépési/kilépési pontokkal
  - Teljesítmény összesítés (profit, drawdown)
- A **Backtesting fül NEM jelenik meg** ebben a módban

**2. Webserver mód** (`docker compose run --rm -p 8080:8080 freqtrade webserver --config user_data/config.json`):
- A bot **NEM kereskedik** - nem figyeli a piacot, nem nyit pozíciókat
- A FreqUI-ban megjelenik a **Backtesting fül**:
  - Stratégia kiválasztása, timerange beállítás, backtest futtatás böngészőből
  - Korábbi backtest eredmények betöltése ("Load" gomb)
  - Adat letöltés
  - Plotting
- A **Trade fül NEM jelenik meg** ebben a módban

### Miért nem lehet mindkettő egyszerre?

Ez a Freqtrade architektúrája: a `trade` és `webserver` üzemmódok kölcsönösen kizárják egymást. Egy Freqtrade példány vagy kereskedik, vagy backtestel - nem csinálja mindkettőt egyszerre.

Továbbá mindkettő a **8080-as portot** használja, tehát fizikailag sem futhatnak párhuzamosan (port ütközés).

### Ajánlott munkafolyamat a gyakorlatban

**Fejlesztés/tesztelés fázis** (hyperopt, backtesting):
1. A trading bot NEM fut
2. Hyperoptot és backtestet a **terminálból** futtatod (lásd 3. és 4. fejezet)
3. Ha a böngészős backtesting felületre van szükséged:
   ```bash
   docker compose run --rm -p 8080:8080 freqtrade webserver --config user_data/config.json.orignal
   ```
4. Leállítás: `Ctrl+C`

**Éles/dry-run kereskedés fázis**:
1. Trading bot indítása:
   ```bash
   docker compose up -d
   ```
2. Böngészőben megnyitod: **http://localhost:8080**
3. Bejelentkezel a `.env`-ben beállított felhasználónévvel/jelszóval
4. A **Trade fülön** figyeled a pozíciókat, szükség esetén kézzel zársz
5. Ha backtestet akarsz futtatni, azt **terminálból** teszed (nem kell leállítani a botot):
   ```bash
   docker compose run --rm freqtrade backtesting \
     --strategy BBRsiAdxStrategy \
     --config user_data/config.json.orignal \
     --timerange 20250701-20260227 \
     -i 1h
   ```
   Ez egy ideiglenes konténerben fut, nem zavarja a trading botot.

### Korábbi backtest eredmények

A terminálból futtatott backtest eredmények automatikusan mentődnek ide:
`user_data/backtest_results/backtest-result-<dátum>.json`

Ezek a fájlok a FreqUI-ban is megtekinthetők (akár trade módban is, a grafikon részen).

---

## 8. Gyakori kérdések

### Mi a különbség a `docker compose up -d` és a `docker compose run --rm` között?

| Parancs | Mit csinál | Mikor használd |
|---------|-----------|----------------|
| `docker compose up -d` | Elindítja a `docker-compose.yml`-ben definiált `trade` parancsot. Háttérben fut, nem áll le. | **Live/dry-run trading** |
| `docker compose run --rm freqtrade ...` | Elindít egy ideiglenes konténert a megadott paranccsal. Lefut, kiírja az eredményt, leáll és törlődik. | **Backtest, hyperopt, adat letöltés, webserver** |

### Miért kapcsolódik a Binance-hoz backtest közben?

A Freqtrade backtesternek szüksége van az exchange-re a trading limitek (minimum trade méret, ár precizitás, díjak) lekéréséhez. Ez normális viselkedés, publikus API-t használ, nem kereskedik.

### A FreqUI-ban újra kell futtatni a backtestet?

**Nem!** A terminálból futtatott eredmények betölthetők a FreqUI-ban a "Load" gombbal.

### Mi az a funding_rate és mark price?

Futures kereskedésnél:
- **Funding rate**: A long/short pozíciók közötti díj, amit 8 óránként fizetnek/kapnak
- **Mark price**: A referencia ár, ami alapján a liquidation-t számolják

### Hogyan frissítsem az adatokat?

Ugyanazt a download-data parancsot futtatva az új adatokat hozzáfűzi a meglévőkhöz:

```bash
docker compose run --rm freqtrade download-data \
  --timeframes 1h 4h \
  --timerange 20250701- \
  --config user_data/config.json.orignal
```

### Mi van ha kifogy a memória hyperopt közben?

- Csökkentsd a párhuzamos processzeket: `-j 2` vagy `-j 1`
- Rövidítsd a timerange-et
- Ne használj `--timeframe-detail`-t hyperoptkor

### Mennyi epoch kell?

500-1000 epoch általában elegendő. Ha "The objective has been evaluated at this point before" üzenetet látsz gyakran, a keresési tér kimerült. Használj `--early-stop 150` értéket, ami leállítja a hyperoptot, ha 150 epoch-on át nem talál jobb eredményt.

### Hogyan adok hozzá új párt?

1. Add hozzá a `config.json` → `pair_whitelist` listához (pl. `"LINK/USDC:USDC"`)
2. Add hozzá a `pair_configs.json`-hoz default értékekkel:
   ```json
   "LINK/USDC:USDC": {
     "bb_period": 20, "bb_std": 2.0,
     "rsi_threshold": 55, "adx_threshold_1h": 20, "adx_threshold_4h": 25,
     "atr_multiplier": 4.5
   }
   ```
3. Töltsd le az adatot:
   ```bash
   docker compose run --rm freqtrade download-data \
     --timeframes 1h 4h \
     --timerange 20250701- \
     --config user_data/config.json.orignal \
     --pairs LINK/USDC:USDC
   ```
4. Futtasd a hyperoptot az új párra (lásd 4. fejezet)
5. Írd be az optimalizált értékeket a `pair_configs.json`-ba
6. Indítsd újra a botot: `docker compose restart`

### Mi történik, ha egy pár nincs benne a pair_configs.json-ban?

A stratégia a **kódban lévő default értékeket** fogja használni (bb_period=20, bb_std=2.0, rsi_threshold=55, adx_threshold_1h=20, adx_threshold_4h=25, atr_multiplier=4.5). Működni fog, de nem lesz optimalizált arra a párra.

### A BBRsiAdxStrategy.json fájl kell még?

A hyperopt automatikusan generál egy `BBRsiAdxStrategy.json` fájlt is a `strategies/` mappába. **Ez nem kell, figyelmen kívül hagyhatod vagy törölheted.** A mi rendszerünkben a `pair_configs.json` az elsődleges, mert az páronként külön értékeket tud tárolni, míg a `BBRsiAdxStrategy.json` csak egyetlen globális paraméterkészletet tartalmaz.

### A stake_amount USDC-ben van?

**Igen.** A `config.json`-ben a `"stake_amount": 20` azt jelenti, hogy minden trade **20 USDC fedezetet** (margin-t) használ. A 20x leverage-dzsel ez 400 USDC névértékű pozíciót jelent (20 × 20 = 400). A backtest kimenetben:
- `stake_amount` = a te pénzed ami kockázatban van (USDC)
- `amount` = hány darab coint veszel (pl. 19.44 AVAX)
- `cost` (az order-ben) = a pozíció teljes névértéke (stake × leverage)

---

## 9. RangeBreakoutPullbackStrategy - Adat, Backtest, Hyperopt

### A stratégia rövid leírása

A `RangeBreakoutPullbackStrategy` egy intraday rendszer. Minden kereskedési napon meghatároz egy **napi range-et** a referencia időzóna (alapértelmezett: New York) szerinti nap első 4 órájából (00:00-04:00 NY idő). Ha az ár kitör ebből a range-ből, majd visszazár, az belépési jelzést ad.

**Logika:**
- **Napi range**: NY 00:00-04:00 között az 5 perces gyertyák max HIGH-ja és min LOW-ja
- **Felső kitörés** (close > range_high) → SHORT setup indul
- **Visszazárás** (close <= range_high) → **SHORT belépő**
- **Alsó kitörés** (close < range_low) → LONG setup indul
- **Visszazárás** (close >= range_low) → **LONG belépő**
- **Stop loss**: a kitörési szakasz szélső értékénél (+ stop_buffer_pct)
- **Take profit**: R-alapú (entry ± R × risk_reward_ratio)
- **Leverage**: 20x, **stake**: 5 USDC/trade

**Config**: `user_data/config_rb.json` | **Párok**: ETH, SOL, ARB, AVAX, SUI, TIA, STX, CFX, HBAR, OP (mind USDC:USDC futures)

---

### 9.1 Adat letöltés

A stratégia **5m gyertyákat** használ. Ezt külön kell letölteni a `config_rb.json`-ban lévő párokra.

**Az összes pár letöltése:**
```bash
docker compose run --rm freqtrade download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/config_rb.json
```

**Csak egy pár letöltése:**
```bash
docker compose run --rm freqtrade download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/config_rb.json \
  --pairs ETH/USDC:USDC
```

**Több specifikus pár:**
```bash
docker compose run --rm freqtrade download-data \
  --timeframes 5m \
  --timerange 20260101- \
  --config user_data/config_rb.json \
  --pairs ETH/USDC:USDC SOL/USDC:USDC ARB/USDC:USDC
```

> **Megjegyzés:** A `config_rb.json`-ban az exchange `key` és `secret` üres. Az adatletöltés publikus API-t használ, nem kell API kulcs. A Telegram és API server credentialeket a `.env` fájlban kell beállítani (lásd 9.5 szekció).

---

### 9.2 Backtesting

**Stratégia ellenőrzése (megjelenik-e a listában?):**
```bash
docker compose run --rm freqtrade list-strategies --config user_data/config_rb.json
```

**Backtest egyetlen párral:**
```bash
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260101-20260320 \
  -i 5m \
  -p ETH/USDC:USDC
```

**Backtest az összes párral (config_rb.json whitelist alapján):**
```bash
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260101-20260320 \
  -i 5m
```

**Backtest több kiválasztott párral:**
```bash
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260101-20260320 \
  -i 5m \
  -p ETH/USDC:USDC SOL/USDC:USDC AVAX/USDC:USDC
```

**Havi bontással:**
```bash
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260101-20260320 \
  -i 5m \
  --breakdown month
```

**Mit kell keresni a logban?**

```
RangeBreakoutPullback | rb_pair_configs.json betöltve, 10 pár konfigurálva
RangeBreakout | ETH/USDC:USDC | tz=America/New_York, rr=2.0, max_bars=24
RangeBreakout | ETH/USDC:USDC | 2026-01-15 (America/New_York) | Range kész: H=3240.5000 L=3198.2000 (1.32%)
RangeBreakout | ETH/USDC:USDC | SHORT SIGNAL | entry~=3235.1 SL=3255.2 TP=3195.0
```

---

### 9.3 Hyperopt - Páronkénti optimalizáció

#### Hogyan működik a hyperopt itt?

Ugyanaz a minta mint a BBRsiAdxStrategy-nál (`rb_pair_configs.json`). A lényeg:

- Ha a pár **benne van** a `rb_pair_configs.json`-ban → a stratégia azokat a fix értékeket használja, a hyperopt NEM tudja felülírni
- Ha a pár **nincs benne** (vagy `_` prefixszel van) → a hyperopt próbálgatja az értékeket

**Fontos: `--analyze-per-epoch` KÖTELEZŐ!**
A 9 paraméter közül szinte mind a `populate_indicators()`-t érinti (range méret szűrők, kitörési távolság, setup lejárat, SL buffer, RR ráta, időzóna). Nélküle a hyperopt mindig az alapértékekkel számolt indikátorokat kapja → az optimalizáció értelmetlen.

#### Lépésről lépésre (példa: ETH/USDC:USDC)

**1. Lépés: Pár kivétele az `rb_pair_configs.json`-ból**

Nyisd meg a `user_data/strategies/rb_pair_configs.json` fájlt, és írj `_` jelet az ETH kulcsa elé:

```json
{
  "_ETH/USDC:USDC": { ... },   ← a hyperopt nem találja, a próbált értékeket használja
  "SOL/USDC:USDC": { ... },    ← ezek nem futnak (-p flag miatt)
  ...
}
```

**2. Lépés: Hyperopt futtatása**

```bash
docker compose run --rm freqtrade hyperopt \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy \
  --epochs 300 \
  --timerange 20260101-20260301 \
  --analyze-per-epoch \
  -j 1 \
  -p ETH/USDC:USDC
```

| Paraméter | Miért |
|-----------|-------|
| `--spaces buy` | Mind a 9 paraméter `space="buy"` |
| `--analyze-per-epoch` | **KÖTELEZŐ** - paraméterek az indikátor-számítást érintik |
| `-j 1` | 5m adat + analyze-per-epoch memóriaigényes; 1-2 worker ajánlott |
| `-p ETH/USDC:USDC` | Csak erre a párra optimalizál |
| `--epochs 300` | 300-500 ajánlott; több epoch = jobb eredmény de lassabb |

> **Miért `-j 1` és nem több?** Az 5m timeframe sokkal több gyertyát jelent mint az 1H (x12). Az `--analyze-per-epoch` minden epochban újraszámolja az összes gyertya indikátorát. Ha `-j 4` munkással futtatod, 4× annyi memória kell. Kezdj `-j 1`-gyel, ha belefér a memóriába, növeld.

**3. Lépés: Eredmény kiolvasása**

A hyperopt végén megjelenik:
```
Best result:
    # Buy hyperspace params:
    buy_params = {
        'allow_long': True,
        'allow_short': True,
        'max_range_size_pct': 4.5,
        'max_setup_bars': 18,
        'min_breakout_distance_pct': 0.05,
        'min_range_size_pct': 0.4,
        'range_timezone': 'America/New_York',
        'risk_reward_ratio': 2.5,
        'stop_buffer_pct': 0.08,
    }
```

**4. Lépés: Eredmény bemásolása az `rb_pair_configs.json`-ba**

Írd vissza az ETH kulcsát (`_ETH` → `ETH`) és töltsd ki az értékeket:
```json
"ETH/USDC:USDC": {
    "risk_reward_ratio": 2.5,
    "min_breakout_distance_pct": 0.05,
    "min_range_size_pct": 0.4,
    "max_range_size_pct": 4.5,
    "max_setup_bars": 18,
    "stop_buffer_pct": 0.08,
    "allow_long": true,
    "allow_short": true,
    "range_timezone": "America/New_York"
}
```

**5. Lépés: Validálás backtesttel**
```bash
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  -p ETH/USDC:USDC \
  --timerange 20260101-20260301 \
  -i 5m
```

Ellenőrizd a logban: `RangeBreakout | ETH/USDC:USDC | tz=America/New_York, rr=2.5, max_bars=18`

**6. Lépés: Ismétlés** a többi 9 párra egyenként.

---

### 9.4 Teljes workflow összefoglalás (RB stratégia)

```bash
# 1. Adat letöltés (mind a 10 pár, 5m)
docker compose run --rm freqtrade download-data \
  --timeframes 5m --timerange 20260101- --config user_data/config_rb.json

# 2. Páronkénti hyperopt (ismételd 10x, páronként):
#    a) rb_pair_configs.json-ban: "_ETH/USDC:USDC" (prefix)
#    b) Hyperopt futtatás:
docker compose run --rm freqtrade hyperopt \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --hyperopt-loss SharpeHyperOptLossDaily \
  --spaces buy --epochs 300 --analyze-per-epoch -j 1 \
  -p ETH/USDC:USDC
#    c) Eredmény bemásolása rb_pair_configs.json-ba (kulcs visszaállítása)
#    d) Backtest validáció az adott párral

# 3. Out-of-sample validáció az összes párral
docker compose run --rm freqtrade backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260301-20260320 -i 5m

# 4. Bot indítása
docker compose up -d freqtrade_rb
```

---

### 9.5 Config és .env beállítás

A `config_rb.json`-ban az API kulcsok és Telegram token üres (`""`). Ezeket a `.env` fájl tölti fel.

Nyisd meg az `ft_userdata/.env` fájlt és add hozzá:
```bash
# RangeBreakoutPullback bot Telegram token
# Ha ugyanazt a Telegram botot használod mint a BBRsiAdx-nek, másold onnan.
# Ha külön botot akarsz, hozz létre egyet a @BotFather-nél.
FREQTRADE__TELEGRAM__TOKEN=ide_a_telegram_token
FREQTRADE__TELEGRAM__CHAT_ID=ide_a_chat_id

# API server jelszó a FreqUI-hoz (freqtrade-rb.kebodev.hu)
FREQTRADE__API_SERVER__USERNAME=admin
FREQTRADE__API_SERVER__PASSWORD=eros_jelszo_ide
```

> **Fontos**: Ha mindkét bot ugyanazt a Telegram tokent használja, mindkét bot ugyanabba a chatba küld üzeneteket. Ez általában jó dolog - mindent egy helyen látsz. Ha teljesen külön akarod kezelni őket Telegramon, hozz létre egy második botot a @BotFather-nél.

> **Telegram strategy_msg**: A range értesítések (`self.dp.send_msg()`) csak akkor mennek ki Telegramon, ha a `config_rb.json`-ban a `"strategy_msg": "on"` be van állítva (alapból már így van). Ellenőrizd a Telegram beállításokat is: a botnak küldj `/start` parancsot hogy fogadja az üzeneteket.

---

## 10. Két bot egy FreqUI-n - VPS beállítás

### A helyzet

- `freqtrade` bot fut: `localhost:8080` → publikusan elérhető: `https://freqtrade.kebodev.hu`
- `freqtrade_rb` bot fut: `localhost:8081` → **nincs publikusan kitéve**

A FreqUI multi-bot funkciója lehetővé teszi, hogy **egy böngészőablakból mindkét botot kezeld**. Ehhez azonban a böngészőnek (a te laptopodnak) el kell érnie mindkét bot API-ját HTTPS-en.

### Megoldás: Második Caddy entry a VPS-en

A VPS-en a Caddyfile-hoz adj hozzá egy új site blockot:

```
freqtrade.kebodev.hu {
    reverse_proxy localhost:8080
}

freqtrade-rb.kebodev.hu {
    reverse_proxy localhost:8081
}
```

**DNS beállítás**: A domain provider-nél adj hozzá egy `A` rekordot:
- `freqtrade-rb.kebodev.hu` → a VPS IP-je (ugyanaz mint `freqtrade.kebodev.hu`)

Caddy automatikusan kér SSL tanúsítványt az új domainhez is.

**Caddy újraindítás:**
```bash
sudo systemctl reload caddy
# vagy
sudo caddy reload --config /etc/caddy/Caddyfile
```

### FreqUI bot selector beállítása

1. Nyisd meg: **https://freqtrade.kebodev.hu**
2. Jobb felső sarokba → **"Switch Bot"** gomb (vagy fogaskerék ikon)
3. **"Add Bot"** → URL megadása: `https://freqtrade-rb.kebodev.hu`
4. Felhasználónév/jelszó megadása (`.env`-ből)

Ezután a FreqUI-ban **váltogathatsz a két bot között** egyetlen kattintással, és mindkettő nyitott pozícióit, logját, teljesítményét látod.

### Mindkét bot indítása és leállítása

```bash
# Mindkét bot indítása
cd ft_userdata
docker compose up -d

# Csak BBRsiAdx indítása
docker compose up -d freqtrade

# Csak RangeBreakout indítása
docker compose up -d freqtrade_rb

# Mindkét bot leállítása
docker compose down

# Mindkét bot logja (valós idejű)
docker compose logs -f

# Csak RangeBreakout logja
docker compose logs -f freqtrade_rb

# Utolsó 100 sor a RangeBreakout botból
docker compose logs --tail 100 freqtrade_rb
```

### Mikor kell újraindítani?

| Mit változtattál? | Bot | Parancs |
|-------------------|-----|---------|
| `rb_pair_configs.json` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `config_rb.json` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `RangeBreakoutPullbackStrategy.py` | freqtrade_rb | `docker compose restart freqtrade_rb` |
| `pair_configs.json` | freqtrade | `docker compose restart freqtrade` |
| `config.json` | freqtrade | `docker compose restart freqtrade` |
| `BBRsiAdxStrategy.py` | freqtrade | `docker compose restart freqtrade` |

### Backtest futtatása miközben mindkét bot fut

A `docker compose run --rm freqtrade ...` és `docker compose run --rm freqtrade_rb ...` ideiglenes konténereket indít. Ezek **nem zavarják a futó botokat**.

```bash
# BBRsiAdx backtest (fut a freqtrade bot mellett)
docker compose run --rm freqtrade backtesting \
  --strategy BBRsiAdxStrategy \
  --config user_data/config.json \
  --timerange 20260101-20260320 -i 1h

# RangeBreakout backtest (fut a freqtrade_rb bot mellett)
docker compose run --rm freqtrade_rb backtesting \
  --strategy RangeBreakoutPullbackStrategy \
  --config user_data/config_rb.json \
  --timerange 20260101-20260320 -i 5m
```

### Összefoglaló: melyik config melyik bothoz

| | BBRsiAdxStrategy | RangeBreakoutPullbackStrategy |
|--|--|--|
| **Config** | `user_data/config.json` | `user_data/config_rb.json` |
| **Párok** | ETH, SOL, ARB, AVAX | ETH, SOL, ARB, AVAX, SUI, TIA, STX, CFX, HBAR, OP |
| **Pair configs** | `strategies/pair_configs.json` | `strategies/rb_pair_configs.json` |
| **Timeframe** | 1H | 5m |
| **Stake** | 20 USDC | 5 USDC |
| **Max trades** | 5 | 10 |
| **Port (lokális)** | 8080 | 8081 |
| **VPS URL** | freqtrade.kebodev.hu | freqtrade-rb.kebodev.hu |
| **DB** | tradesv3.sqlite | tradesv3-rb.sqlite |
| **Log** | logs/freqtrade.log | logs/freqtrade_rb.log |
