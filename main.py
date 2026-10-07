import glob
import os
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Folder with the CSV files: ../data/ (next to BackEnd and FrontEnd)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')


# =====================================================================
# Indicators (Step 4)
# =====================================================================
def add_indicators(group):
    group = group.sort_values('Date').reset_index(drop=True)  # sort by date oldest to newest
    # Moving Average
    group['MA_short'] = group['Close'].rolling(window=10).mean()  # average of last 10 closes
    group['MA_long'] = group['Close'].rolling(window=50).mean()   # average of last 50 closes
    # ATR (Average True Range)
    group['prev_close'] = group['Close'].shift(1)                 # get previous candle's close price
    group['tr1'] = group['High'] - group['Low']                   # candle size (high to low)
    group['tr2'] = (group['High'] - group['prev_close']).abs()    # gap up from previous close
    group['tr3'] = (group['Low'] - group['prev_close']).abs()     # gap down from previous close
    group['true_range'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)  # biggest of the three
    group['ATR'] = group['true_range'].rolling(window=14).mean()  # average True Range of 14 candles
    return group  # return the table with new columns added


# =====================================================================
# MA Crossover signal logic (Step 5)
# =====================================================================
def add_signals(group, sl_atr_mult=1.5, rr_ratio=2.0):
    group = group.sort_values('Date').reset_index(drop=True)  # sort by date oldest to newest

    # --- MA Crossover Signal ---
    valid = group['MA_short'].notna() & group['MA_long'].notna()  # both MA must have values
    above = group['MA_short'] > group['MA_long']                  # is MA_short above MA_long today?
    prev_above = above.shift(1, fill_value=False)                 # was MA_short above yesterday?
    prev_valid = valid.shift(1, fill_value=False)                 # were both MA valid yesterday?
    cross_ok = valid & prev_valid                                  # both today and yesterday valid

    # Signal: 1 = Buy, -1 = Sell, 0 = no trade
    group['Signal'] = 0
    group.loc[cross_ok & above & ~prev_above, 'Signal'] = 1   # MA_short crossed UP   -> Buy
    group.loc[cross_ok & ~above & prev_above, 'Signal'] = -1  # MA_short crossed DOWN -> Sell

    # --- Stop Loss and Take Profit using ATR ---
    sl_dist = group['ATR'] * sl_atr_mult          # stop loss distance = ATR x 1.5
    buy = group['Signal'] == 1                    # rows where signal is Buy
    sell = group['Signal'] == -1                  # rows where signal is Sell

    group['Entry'] = np.where(buy | sell, group['Close'], np.nan)  # entry price = close of signal candle
    group['SL'] = np.where(buy, group['Close'] - sl_dist,          # Buy  -> SL below entry
                  np.where(sell, group['Close'] + sl_dist,         # Sell -> SL above entry
                  np.nan))                                          # no signal -> no SL
    group['TP'] = np.where(buy, group['Close'] + sl_dist * rr_ratio,   # Buy  -> TP above entry
                  np.where(sell, group['Close'] - sl_dist * rr_ratio,  # Sell -> TP below entry
                  np.nan))                                              # no signal -> no TP
    return group  # return table with Signal, Entry, SL, TP columns added


# =====================================================================
# Backtest win or loss per trade (Step 6)
# =====================================================================
def backtest(group):
    group = group.reset_index(drop=True)             # clean 0,1,2 index
    trades = []                                       # store each trade here
    for i in group.index[group['Signal'] != 0]:      # loop signal rows only
        d = group.at[i, 'Signal']                     # 1 = buy, -1 = sell
        entry = group.at[i, 'Entry']                  # entry price
        sl = group.at[i, 'SL']                        # stop loss
        tp = group.at[i, 'TP']                        # take profit
        rr = abs(tp - entry) / abs(sl - entry)        # reward : risk
        for j in range(i + 1, len(group)):            # check future candles
            high = group.at[j, 'High']                # candle high
            low = group.at[j, 'Low']                  # candle low
            hit_sl = low <= sl if d == 1 else high >= sl   # SL touched?
            hit_tp = high >= tp if d == 1 else low <= tp   # TP touched?
            if hit_sl or hit_tp:                      # trade closed
                win = hit_tp and not hit_sl           # both same day = loss (safe)
                trades.append({
                    'Symbol': group.at[i, 'Symbol'],           # Forex trading pair
                    'Entry_Date': group.at[i, 'Date'],         # date the trade was opened
                    'Exit_Date': group.at[j, 'Date'],          # date the trade hit TP or SL
                    'Direction': 'Buy' if d == 1 else 'Sell',  # Buy or Sell
                    'Entry': entry,                            # entry price
                    'Exit': tp if win else sl,                 # exit at TP (win) or SL (loss)
                    'Result': 'Win' if win else 'Loss',        # hit TP = win, hit SL = loss
                    'R': rr if win else -1                     # win = +RR, loss = -1R
                })
                break                                 # stop, go to next trade
    return pd.DataFrame(trades)                       # table of trades


# =====================================================================
# Metrics (Step 7)
# =====================================================================
def get_metrics(t):
    wins = t[t['Result'] == 'Win']            # winning trades
    losses = t[t['Result'] == 'Loss']         # losing trades
    gross_win = wins['R'].sum()               # total R won
    gross_loss = abs(losses['R'].sum())       # total R lost
    return pd.Series({
        'Trades': len(t),                                          # Total trades
        'Win_Rate_%': round(len(wins) / len(t) * 100, 1),          # Win percentage
        'Total_R': round(t['R'].sum(), 1),                         # Total R gained or lost
        # won / lost: above 1 means profitable
        'Profit_Factor': round(gross_win / gross_loss, 2) if gross_loss > 0 else np.nan,
        'Expectancy_R': round(t['R'].mean(), 2)                    # Average R per trade
    })


# =====================================================================
# Account growth (Step 8)
# =====================================================================
def account_growth(trades, account_size=1000, risk_pct=1.0):
    t = trades.sort_values('Exit_Date').reset_index(drop=True)  # order trades by when they closed
    balance = account_size                                      # starting money
    pnls, balances = [], []
    for r in t['R']:                                            # loop each trade's R
        risk_amount = balance * risk_pct / 100                  # risk per trade
        pnl = r * risk_amount                                   # R to dollars
        balance += pnl                                          # update balance
        pnls.append(pnl)
        balances.append(balance)
    t['PnL_$'] = pnls                                           # profit/loss per trade
    t['Balance'] = balances                                     # balance after each trade
    return t


# =====================================================================
# Strategies (Step 9)
# =====================================================================
def cross_signal(fast, slow):                          # crossover logic (MA + EMA)
    valid = fast.notna() & slow.notna()                # both lines have values
    above = fast > slow                                # fast above slow?
    prev_above = above.shift(1, fill_value=False)      # yesterday
    prev_valid = valid.shift(1, fill_value=False)
    ok = valid & prev_valid
    sig = pd.Series(0, index=fast.index)               # default 0 = no trade
    sig[ok & above & ~prev_above] = 1                  # cross up = BUY
    sig[ok & ~above & prev_above] = -1                 # cross down = SELL
    return sig


def first_only(sig):                                   # keep only first day of a signal run
    return sig.where(sig != sig.shift(1), 0)           # repeated days -> 0


def add_sl_tp(group, sl_atr_mult=1.5, rr_ratio=2.0):   # same SL/TP logic as Step 5
    sl_dist = group['ATR'] * sl_atr_mult               # stop loss distance = ATR x 1.5
    buy, sell = group['Signal'] == 1, group['Signal'] == -1
    group['Entry'] = np.where(buy | sell, group['Close'], np.nan)       # entry price = close
    group['SL'] = np.where(buy, group['Close'] - sl_dist,               # Buy  -> SL below
                  np.where(sell, group['Close'] + sl_dist, np.nan))     # Sell -> SL above
    group['TP'] = np.where(buy, group['Close'] + sl_dist * rr_ratio,    # Buy  -> TP above
                  np.where(sell, group['Close'] - sl_dist * rr_ratio, np.nan))  # Sell -> TP below
    return group


# 1. MA Crossover - simple average cross
def strat_ma(g, fast=10, slow=50):
    return cross_signal(g['Close'].rolling(fast).mean(),
                        g['Close'].rolling(slow).mean())


# 2. EMA Crossover - same idea, but recent prices weigh more (reacts faster)
def strat_ema(g, fast=12, slow=26):
    return cross_signal(g['Close'].ewm(span=fast, adjust=False).mean(),
                        g['Close'].ewm(span=slow, adjust=False).mean())


# 3. Support & Resistance - bounce off recent low/high
def strat_sr(g, lookback=20):
    support = g['Low'].rolling(lookback).min().shift(1)       # lowest low (past 20)
    resistance = g['High'].rolling(lookback).max().shift(1)   # highest high (past 20)
    zone = g['ATR'] * 0.5                                     # "near" = within 0.5 ATR
    buy = (g['Low'] <= support + zone) & (g['Close'] > support)          # touch support, close above
    sell = (g['High'] >= resistance - zone) & (g['Close'] < resistance)  # touch resistance, close below
    sig = pd.Series(np.where(buy & ~sell, 1, np.where(sell & ~buy, -1, 0)), index=g.index)
    return first_only(sig)


# 4. Breakout - close breaks past the recent high/low
def strat_breakout(g, lookback=20):
    high_n = g['High'].rolling(lookback).max().shift(1)       # past 20-day high
    low_n = g['Low'].rolling(lookback).min().shift(1)         # past 20-day low
    sig = pd.Series(np.where(g['Close'] > high_n, 1,          # break up = BUY
                    np.where(g['Close'] < low_n, -1, 0)),     # break down = SELL
                    index=g.index)
    return first_only(sig)


# 5. Fibonacci Retracement - buy the pullback in trend at 61.8%
def strat_fib(g, lookback=50, level=0.618):
    swing_high = g['High'].rolling(lookback).max().shift(1)   # recent swing high
    swing_low = g['Low'].rolling(lookback).min().shift(1)     # recent swing low
    rng = swing_high - swing_low                              # swing size
    uptrend = g['Close'] > g['Close'].rolling(lookback).mean()  # trend filter
    buy_lvl = swing_high - rng * level                        # 61.8% pullback (uptrend)
    sell_lvl = swing_low + rng * level                        # 61.8% pullback (downtrend)
    buy = uptrend & (g['Low'] <= buy_lvl) & (g['Close'] > buy_lvl)       # touch + close above
    sell = ~uptrend & (g['High'] >= sell_lvl) & (g['Close'] < sell_lvl)  # touch + close below
    sig = pd.Series(np.where(buy, 1, np.where(sell, -1, 0)), index=g.index)
    return first_only(sig)


STRATEGIES = {                                   # name -> function (dashboard dropdown)
    'MA Crossover': strat_ma,
    'EMA Crossover': strat_ema,
    'Support & Resistance': strat_sr,
    'Breakout': strat_breakout,
    'Fibonacci': strat_fib
}


def add_strategy(group, strategy, sl_atr_mult=1.5, rr_ratio=2.0):
    group = group.sort_values('Date').reset_index(drop=True)
    group['Signal'] = STRATEGIES[strategy](group).values      # pick strategy -> signals
    return add_sl_tp(group, sl_atr_mult, rr_ratio)            # add Entry/SL/TP


def run_strategy(df, strategy, sl_atr_mult=1.5, rr_ratio=2.0):
    signals = df.groupby('Symbol', group_keys=False)[df.columns].apply(
        lambda g: add_strategy(g, strategy, sl_atr_mult, rr_ratio))           # signals per symbol
    trades = pd.concat([backtest(g) for _, g in signals.groupby('Symbol')],
                       ignore_index=True)                                    # backtest per symbol
    trades['Strategy'] = strategy                                            # label strategy
    return trades


# =====================================================================
# Helper: calculate ATR (for Weekly data)
# =====================================================================
def add_atr(df, n=14):
    df = df.copy()
    prev_close = df['Close'].shift(1)                     # previous candle's close
    tr = pd.concat([df['High'] - df['Low'],               # candle range
                    (df['High'] - prev_close).abs(),      # gap up
                    (df['Low'] - prev_close).abs()],      # gap down
                   axis=1).max(axis=1)                    # True Range
    df['ATR'] = tr.rolling(n).mean()                      # average over 14 candles
    return df


# =====================================================================
# Load data on startup
# =====================================================================
def load_timeframe(tag):
    frames = []
    for f in sorted(glob.glob(os.path.join(DATA_DIR, f'*_{tag}.csv'))):
        df = pd.read_csv(f)
        df['Symbol'] = os.path.basename(f).replace(f'_{tag}.csv', '')  # symbol from file name
        frames.append(df[['Date', 'Open', 'High', 'Low', 'Close', 'Symbol']])
    if not frames:
        raise RuntimeError(f'No *_{tag}.csv files found in {os.path.abspath(DATA_DIR)}')
    combined = pd.concat(frames, ignore_index=True)
    combined['Date'] = pd.to_datetime(combined['Date'])
    return combined.sort_values(['Symbol', 'Date']).reset_index(drop=True)


daily_df = load_timeframe('daily')
daily_df = daily_df.groupby('Symbol', group_keys=False)[daily_df.columns].apply(add_indicators)
daily_df = daily_df.drop(columns=['prev_close', 'tr1', 'tr2', 'tr3', 'true_range']).reset_index(drop=True)

weekly_df = load_timeframe('weekly')

DATA = {'Daily': daily_df, 'Weekly': weekly_df}

for k, v in DATA.items():
    print(f"{k}: {len(v)} rows | {v['Date'].min().date()} -> {v['Date'].max().date()}")


# =====================================================================
# API
# =====================================================================
app = FastAPI(title='ForexBacktest API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


class BacktestInput(BaseModel):
    timeframe: str = 'Daily'
    symbol: str = 'EURUSD'
    strategy: str = 'MA Crossover'
    account_size: float = 1000
    risk_pct: float = 1.0
    rr_ratio: float = 2.0
    sl_atr_mult: float = 1.5
    start: str = '2000-01-03'
    end: str = '2025-07-08'
    trade_option: str = 'Both'


def clean(x, digits=2):
    """Round a number for JSON; NaN / inf become null."""
    if x is None or pd.isna(x) or np.isinf(x):
        return None
    return round(float(x), digits)


@app.get('/')
def root():
    return {'status': 'ok'}


@app.get('/symbols')
def get_symbols():
    return sorted(daily_df['Symbol'].unique().tolist())


@app.get('/strategies')
def get_strategies():
    return list(STRATEGIES.keys())


@app.post('/backtest')
def run_backtest(inp: BacktestInput):
    if inp.timeframe not in DATA:
        raise HTTPException(400, f"Unknown timeframe '{inp.timeframe}'. Use Daily or Weekly.")
    if inp.strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy '{inp.strategy}'.")
    if inp.trade_option not in ('Both', 'Buy', 'Sell'):
        raise HTTPException(400, 'trade_option must be Both, Buy or Sell.')
    if inp.account_size <= 0 or inp.risk_pct <= 0 or inp.rr_ratio <= 0 or inp.sl_atr_mult <= 0:
        raise HTTPException(400, 'Account size, risk %, RR ratio and SL ATR multiplier must be above 0.')

    df = DATA[inp.timeframe]                                       # Daily or Weekly
    if inp.symbol not in set(df['Symbol']):
        raise HTTPException(400, f"Unknown symbol '{inp.symbol}'.")

    try:
        start = date.fromisoformat(inp.start)
        end = date.fromisoformat(inp.end)
    except ValueError:
        raise HTTPException(400, 'Dates must be in YYYY-MM-DD format.')

    # keep dates inside the data range
    data_start = df['Date'].min().date()
    data_end = df['Date'].max().date()
    note = None
    if start < data_start or end > data_end:
        note = f'{inp.timeframe} data only covers {data_start} to {data_end}. Dates were adjusted.'
    start = max(start, data_start)
    end = min(end, data_end)
    if start > end:
        raise HTTPException(400, 'Start date is after end date.')

    data = df[df['Symbol'] == inp.symbol]                          # one symbol only
    if 'ATR' not in data.columns:                                  # Weekly has no ATR yet
        data = add_atr(data)
    data = add_strategy(data, inp.strategy, inp.sl_atr_mult, inp.rr_ratio)  # signals + SL/TP
    with np.errstate(divide='ignore', invalid='ignore'):
        trades = backtest(data)                                    # win/loss per trade
    if trades.empty:
        raise HTTPException(404, 'No trades found for this symbol and strategy.')

    trades = trades[(trades['Entry_Date'] >= pd.Timestamp(start)) &
                    (trades['Entry_Date'] <= pd.Timestamp(end))]   # date range filter
    if inp.trade_option != 'Both':
        trades = trades[trades['Direction'] == inp.trade_option]   # Buy only / Sell only
    if trades.empty:
        raise HTTPException(404, 'No trades in this date range. Try a wider range or another setting.')

    m = get_metrics(trades)
    g = account_growth(trades, inp.account_size, inp.risk_pct)
    avg_win = g.loc[g['PnL_$'] > 0, 'PnL_$'].mean()
    avg_loss = g.loc[g['PnL_$'] < 0, 'PnL_$'].mean()
    daily = g.groupby('Exit_Date')['PnL_$'].sum().reset_index()

    return {
        'trades': int(m['Trades']),
        'win_rate': clean(m['Win_Rate_%'], 1),
        'profit_factor': clean(m['Profit_Factor']),
        'total_r': clean(m['Total_R'], 1),
        'expectancy': clean(m['Expectancy_R']),
        'avg_win': clean(avg_win),
        'avg_loss': clean(avg_loss),
        'final_balance': clean(g['Balance'].iloc[-1]),
        'equity_curve': [
            {'Exit_Date': d.strftime('%Y-%m-%d'), 'Balance': clean(b)}
            for d, b in zip(g['Exit_Date'], g['Balance'])
        ],
        'daily_pnl': [
            {'Exit_Date': d.strftime('%Y-%m-%d'), 'PnL_$': clean(p)}
            for d, p in zip(daily['Exit_Date'], daily['PnL_$'])
        ],
        'note': note,
    }
