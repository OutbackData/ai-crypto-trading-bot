# =====================================================
# GOLD CLOUD – ADVANCED AI DAY TRADER (Production Ready)
# No more blinking • Beautiful rich UI • phi4:latest
# BTC / DOGE / XRP on Binance.US (direct USD)
# =====================================================

import ccxt
import pandas as pd
import numpy as np
import time
import ollama
from datetime import datetime
import socket
import getpass
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box, print as rprint

console = Console()

# ================== FORCE IPv4 ==================
def force_ipv4():
    original = socket.getaddrinfo
    def ipv4_only(*args, **kwargs):
        return [r for r in original(*args, **kwargs) if r[0] == socket.AF_INET]
    socket.getaddrinfo = ipv4_only
force_ipv4()

# ================== SETTINGS ==================
TIMEFRAME          = '1m'
LOOKBACK           = 300
LOOP_EVERY         = 30           # seconds between updates
MAX_TRADE_USD      = 9.0
MIN_USD_FOR_BUY    = 3.0

# ================== PAIR SELECTION ==================
rprint("\n[bold cyan]Choose pair to day-trade (direct USD):[/bold cyan]")
rprint("1 → [bold]BTC/USD[/]")
rprint("2 → [bold magenta]DOGE/USD[/]")
rprint("3 → [bold blue]XRP/USD[/]")
choice = input("\nEnter 1-3: ").strip()

if choice == '2':
    SYMBOL = 'DOGE/USD'
elif choice == '3':
    SYMBOL = 'XRP/USD'
else:
    SYMBOL = 'BTC/USD'

rprint(f"\n[bold green]Selected: {SYMBOL}[/]")

# ================== MODE ==================
MODE = input("\nMode (PAPER or REAL): ").strip().upper()
if MODE not in ['PAPER', 'REAL']:
    MODE = 'PAPER'

rprint("\n" + "═" * 100)
rprint(f"  [bold yellow]GOLD CLOUD ADVANCED AI DAY TRADER[/]  •  {SYMBOL}  •  [{MODE} MODE]")
rprint(f"  AI: phi4:latest  •  Beautiful UI  •  No blinking")
if MODE == 'REAL':
    rprint("  [bold red]REAL MONEY TRADING ACTIVE[/]")
rprint("═" * 100 + "\n")

# ================== EXCHANGE ==================
api_key = api_secret = ""
if MODE == 'REAL':
    api_key    = input("Binance.US API Key: ").strip()
    api_secret = getpass.getpass("Binance.US API Secret: ").strip()

exchange = ccxt.binanceus({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot', 'adjustForTimeDifference': True, 'recvWindow': 60000}
})

try:
    exchange.load_markets()
except:
    pass

# PAPER MODE
paper_usd = paper_coin = 0.0
if MODE == 'PAPER':
    start_input = input("Paper starting USD (default 100.0): ").strip()
    paper_usd = float(start_input) if start_input else 100.0
    rprint(f"[green]✅ PAPER MODE started with ${paper_usd:.2f} USD[/]")

# ================== TRACKING ==================
entry_price        = 0.0
total_realized_pnl = 0.0
win_count = loss_count = total_trades = 0
trade_history      = []
starting_equity    = 0.0

# ================== HELPERS ==================
def get_balances():
    if MODE == 'PAPER':
        return paper_usd, paper_coin
    try:
        bal = exchange.fetch_balance()
        usd = bal.get('USD', {}).get('free', 0.0)
        coin = SYMBOL.split('/')[0]
        coin_free = bal.get(coin, {}).get('free', 0.0)
        return usd, coin_free
    except:
        return 0.0, 0.0

def fetch_data():
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LOOKBACK + 20)
        return pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
    except:
        return None

def compute_indicators(df):
    if df is None or len(df) < 60:
        return None
    close = df['c']
    decimals = 6 if 'DOGE' in SYMBOL or 'XRP' in SYMBOL else 2

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs)).iloc[-1]

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_hist = (ema12 - ema26 - (ema12 - ema26).ewm(span=9, adjust=False).mean()).iloc[-1]

    # ATR
    tr = pd.concat([df['h']-df['l'], abs(df['h']-close.shift()), abs(df['l']-close.shift())], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]

    # Advanced
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    bb_mid = close.rolling(20).mean().iloc[-1]
    bb_std = close.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    vol_ratio = df['v'].iloc[-1] / df['v'].rolling(20).mean().iloc[-1] if df['v'].rolling(20).mean().iloc[-1] > 0 else 1.0
    last_change = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100) if len(close) >= 2 else 0.0

    return {
        'rsi14': round(rsi, 1),
        'macd_hist': round(macd_hist, 4),
        'atr': round(atr, decimals),
        'ema12': round(ema12.iloc[-1], decimals),
        'ema26': round(ema26.iloc[-1], decimals),
        'ema50': round(ema50, decimals),
        'bb_upper': round(bb_upper, decimals),
        'bb_lower': round(bb_lower, decimals),
        'vol_ratio': round(vol_ratio, 2),
        'last_change_pct': round(last_change, 2)
    }

def execute_trade(action, price):
    global entry_price, total_realized_pnl, win_count, loss_count, total_trades, paper_usd, paper_coin

    usd, coin = get_balances()

    if action == "BUY" and usd >= MIN_USD_FOR_BUY:
        usd_to_use = min(usd * 0.95, MAX_TRADE_USD)
        amount_str = exchange.amount_to_precision(SYMBOL, usd_to_use / price)
        amount = float(amount_str)

        if amount < exchange.markets[SYMBOL]['limits']['amount']['min']:
            console.print("[yellow]Order too small – skipped[/]")
            return

        if MODE == 'REAL':
            exchange.create_market_buy_order(SYMBOL, amount_str)
            console.print(f"[bold green]REAL BUY {amount:.8f} {SYMBOL.split('/')[0]}[/]")
        else:
            paper_usd -= amount * price
            paper_coin += amount
            console.print(f"[bold green][PAPER] BUY {amount:.8f} {SYMBOL.split('/')[0]}[/]")

        entry_price = price
        trade_history.append(f"[green]BUY @ ${price:.6f}[/]")
        return "BUY"

    elif action == "SELL" and coin > 1e-8:
        amount_str = exchange.amount_to_precision(SYMBOL, coin)
        amount = float(amount_str)

        if MODE == 'REAL':
            exchange.create_market_sell_order(SYMBOL, amount_str)
            console.print(f"[bold red]REAL SELL {amount:.8f} {SYMBOL.split('/')[0]}[/]")
        else:
            paper_usd += amount * price
            paper_coin = 0.0
            console.print(f"[bold red][PAPER] SELL {amount:.8f} {SYMBOL.split('/')[0]}[/]")

        if entry_price > 0:
            pnl = (price - entry_price) * coin
            total_realized_pnl += pnl
            total_trades += 1
            if pnl > 0:
                win_count += 1
                trade_history.append(f"[green]SELL +${pnl:.4f}[/]")
            else:
                loss_count += 1
                trade_history.append(f"[red]SELL ${pnl:.4f}[/]")
        entry_price = 0.0
        return "SELL"

    return "HOLD"

# ================== DASHBOARD ==================
def make_dashboard(price, usd, coin, unreal_pnl, equity, ind, action, reasoning):
    global starting_equity
    if starting_equity == 0 and equity > 0:
        starting_equity = equity

    ret = ((equity - starting_equity) / starting_equity * 100) if starting_equity > 0 else 0
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

    layout = Panel(
        f"[bold yellow]{SYMBOL} ADVANCED AI TRADER[/]   •   {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}   •   {MODE} mode",
        style="bold cyan", box=box.ROUNDED
    )

    # Price Panel
    price_panel = Panel(
        Text.assemble(
            (f"${price:,.6f}" if price < 10 else f"${price:,.2f}", "bold magenta underline"),
            f"\nPosition: {coin:,.8f} (${coin*price:,.2f})",
            f"\nUSD Free: ${usd:,.2f}",
            f"\nEquity: ${equity:,.2f}   ",
            (f"Return: {ret:+.2f}%", "green" if ret >= 0 else "red")
        ),
        title="Price & Position", border_style="blue", box=box.DOUBLE
    )

    # Indicators
    ind_table = Table(box=box.MINIMAL, expand=True)
    ind_table.add_column("Indicator", style="bold")
    ind_table.add_column("Value", justify="right")
    ind_table.add_row("RSI(14)", str(ind['rsi14']))
    ind_table.add_row("MACD Hist", str(ind['macd_hist']))
    ind_table.add_row("ATR", f"${ind['atr']}")
    ind_table.add_row("EMA12/26/50", f"{ind['ema12']} / {ind['ema26']} / {ind['ema50']}")
    ind_table.add_row("BB Upper/Lower", f"{ind['bb_upper']} / {ind['bb_lower']}")
    ind_table.add_row("Volume Ratio", f"{ind['vol_ratio']}×")
    ind_table.add_row("Last Candle", f"{ind['last_change_pct']:+.2f}%")
    ind_panel = Panel(ind_table, title="Technical Indicators", border_style="dim cyan")

    # Session + AI
    session_text = Text.assemble(
        f"Realized PnL: ${total_realized_pnl:+.2f}\n",
        f"Win Rate: {win_rate:.1f}% ({total_trades} trades)\n",
        f"Unrealized: ${unreal_pnl:+.4f}  ",
        ("AI → " + action, "bold green" if action == "BUY" else "bold red" if action == "SELL" else "bold white"),
        f"\nReason: {reasoning[:110]}{'...' if len(reasoning)>110 else ''}"
    )
    ai_panel = Panel(session_text, title="Session & AI Decision", border_style="yellow")

    # Recent Trades
    trades_panel = Panel(
        "\n".join(trade_history[-6:]) or "[dim]No trades yet[/]",
        title="Recent Trades", border_style="magenta"
    )

    # Final layout
    console.print(layout)
    console.print(price_panel)
    console.print(ind_panel)
    console.print(ai_panel)
    console.print(trades_panel)

# ================== MAIN LOOP (NO BLINKING) ==================
rprint(f"\n[bold green]Bot is running... Ctrl+C to stop[/]\n")

while True:
    try:
        console.clear()                     # Single clean clear → no flicker

        usd, coin = get_balances()
        df = fetch_data()
        if df is None:
            time.sleep(LOOP_EVERY)
            continue

        ind = compute_indicators(df)
        if ind is None:
            time.sleep(LOOP_EVERY)
            continue

        # Live price
        try:
            ticker = exchange.fetch_ticker(SYMBOL)
            price = ticker['last']
        except:
            price = df['c'].iloc[-1]

        unreal_pnl = (price - entry_price) * coin if entry_price > 0 and coin > 0 else 0.0
        equity = usd + coin * price

        # ================== AI CALL ==================
        prompt = f"""You are an elite conservative 1m scalper for {SYMBOL}.
LONG ONLY. Extremely selective. Target >75% win rate. $3-9 trades max.

REALTIME DATA (use exactly):
Price: ${price}
RSI(14): {ind['rsi14']}
MACD Hist: {ind['macd_hist']}
ATR: ${ind['atr']}
EMA12/26/50: ${ind['ema12']}/${ind['ema26']}/${ind['ema50']}
BB: ${ind['bb_upper']} / ${ind['bb_lower']}
Vol Ratio: {ind['vol_ratio']}x
Last candle: {ind['last_change_pct']:+.2f}%

Position: {coin:.8f} (${coin*price:.2f}) | Entry: ${entry_price if entry_price>0 else 'NONE'}
Unrealized: ${unreal_pnl:+.4f}
Session: ${total_realized_pnl:+.2f} | Win Rate: {(win_count/total_trades*100 if total_trades else 0):.1f}%

Step-by-step: trend, momentum, volume, risk. Only strong setups.

Output exactly:
REASONING: [2-4 short sentences]
ACTION: BUY / SELL / HOLD"""

        try:
            resp = ollama.chat(model='phi4:latest', messages=[{'role':'user','content':prompt}])
            text = resp['message']['content'].strip()
        except Exception as e:
            text = "ACTION: HOLD\nREASONING: Ollama not responding"

        action = "HOLD"
        reasoning = "No reasoning"
        for line in text.splitlines():
            if "REASONING:" in line:
                reasoning = line.split(":", 1)[1].strip()
            elif "ACTION:" in line:
                act = line.split(":", 1)[1].strip().upper()
                if "BUY" in act: action = "BUY"
                elif "SELL" in act: action = "SELL"

        console.print(f"[dim]AI Decision: {action} | {reasoning[:100]}...[/]")

        execute_trade(action, price)

        # Final refresh after trade
        usd, coin = get_balances()
        equity = usd + coin * price
        unreal_pnl = (price - entry_price) * coin if entry_price > 0 and coin > 0 else 0.0

        make_dashboard(price, usd, coin, unreal_pnl, equity, ind, action, reasoning)

        console.print(f"\n[dim]Next update in {LOOP_EVERY} seconds... (Ctrl+C to quit)[/]")

        time.sleep(LOOP_EVERY)

    except KeyboardInterrupt:
        console.clear()
        rprint("[bold red]Bot stopped by user.[/]")
        usd, coin = get_balances()
        try:
            last_price = exchange.fetch_ticker(SYMBOL)['last']
            rprint(f"Final Equity: [bold green]${usd + coin*last_price:,.2f}[/]")
        except:
            rprint(f"Final USD: [bold cyan]${usd:,.2f}[/]")
        break

    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        time.sleep(10)
