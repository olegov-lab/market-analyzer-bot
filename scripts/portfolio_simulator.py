"""
Monte Carlo Portfolio Simulator with DCA — Production Version.

Fixes applied per audit by: Sigma-Architect, Rapid-Dev, Market-Brain,
Break-Hunter, finance_analyst, data_analyst (agents01.md).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ==============================================================================
# CONFIGURATION
# ==============================================================================


@dataclass
class Config:
    tickers: Tuple[str, ...] = ("NVDA", "PLTR", "TSLA", "MU")
    target_weights: Dict[str, float] = None  # set in __post_init__

    initial_capital: float = 150.0
    monthly_inflow: float = 150.0
    min_order: float = 20.0
    tx_cost_bps: float = 1.0

    num_simulations: int = 10_000
    horizon_months: int = 12
    days_per_month: int = 21
    seed: int = 42

    use_t_dist: bool = True
    t_df: float = 5.0
    use_shrinkage: bool = True
    bench_ticker: str = "SPY"

    def __post_init__(self) -> None:
        if self.target_weights is None:
            raw = {"NVDA": 50.0, "PLTR": 40.0, "TSLA": 30.0, "MU": 30.0}
            total = sum(raw.values())
            self.target_weights = {k: v / total for k, v in raw.items()}

    @property
    def total_days(self) -> int:
        return self.days_per_month * self.horizon_months

    @property
    def total_invested(self) -> float:
        return self.monthly_inflow * self.horizon_months


# ==============================================================================
# DATA LOADING & VALIDATION
# ==============================================================================


def load_prices(tickers: List[str], period: str = "5y") -> Tuple[pd.DataFrame, List[str]]:
    """Load adjusted close prices. Returns (DataFrame, list of available tickers)."""
    logger.info("Загрузка %d тикеров (%s)...", len(tickers), period)

    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
    except Exception as exc:
        raise RuntimeError(f"yfinance download failed: {exc}") from exc

    if raw is None or raw.empty:
        raise ValueError("yfinance returned empty DataFrame")

    prices = raw.get("Close", raw)
    if isinstance(prices, pd.Series):
        prices = prices.to_frame()

    available = [t for t in tickers if t in prices.columns]
    missing = set(tickers) - set(available)
    if missing:
        logger.warning("Тикеры не найдены в данных: %s", missing)
    if len(available) < 1:
        raise ValueError(f"No ticker data found for: {tickers}")

    prices = prices[available].dropna()
    if prices.empty:
        raise ValueError("All rows dropped after removing NaN")
    if len(prices) < 252:
        logger.warning("Всего %d торговых дней (< 1 года) — данных мало", len(prices))

    logger.info("Загружено: %d строк x %d активов", *prices.shape)
    return prices, available


# ==============================================================================
# STATISTICS
# ==============================================================================


def compute_stats(prices: pd.DataFrame, tickers: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Daily mean and covariance from returns."""
    returns = prices[tickers].pct_change().dropna()
    if len(returns) < 60:
        raise ValueError(f"Only {len(returns)} return observations")
    mu = returns.mean().values
    sigma = returns.cov().values
    if np.any(np.isnan(mu)) or np.any(np.isnan(sigma)):
        raise ValueError("NaN in mean or covariance")
    return mu, sigma


def safe_cholesky(cov: np.ndarray) -> np.ndarray:
    """Cholesky with nearest-PD fallback (Higham 1988)."""
    try:
        return np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        logger.warning("Cholesky упал — nearest-PD коррекция")
        w, v = np.linalg.eigh(cov)
        w = np.clip(w, 1e-10, None)
        cov_pd = v @ np.diag(w) @ v.T
        d = np.sqrt(np.diag(cov) / np.diag(cov_pd))
        cov_pd = cov_pd * np.outer(d, d)
        return np.linalg.cholesky(cov_pd)


def shrink_covariance(returns: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf shrinkage for covariance matrix."""
    n, p = returns.shape
    S = np.cov(returns, rowvar=False)
    # Target: constant-correlation
    std = np.sqrt(np.diag(S))
    C = S / np.outer(std, std)
    rho = (C.sum() - p) / (p * (p - 1))
    T = np.outer(std, std) * ((1 - rho) * np.eye(p) + rho)
    # Shrinkage intensity
    X = returns - returns.mean(axis=0)
    pi_mat = (X.T @ X) / n
    diff = S - T
    delta2 = (diff**2).sum()
    pi_hat = sum((x.reshape(-1, 1) @ x.reshape(1, -1) - S) ** 2 for x in X).sum() / (n * n)
    gamma = ((pi_mat - S) ** 2).sum() / n
    rho_hat = pi_hat
    kappa = (pi_hat - rho_hat) / gamma if gamma > 1e-15 else 0.0
    shrinkage = max(0.0, min(1.0, kappa / n))
    return (1 - shrinkage) * S + shrinkage * T


# ==============================================================================
# RETURN GENERATION
# ==============================================================================


def gen_returns_normal(
    n_days: int, n_assets: int, mu: np.ndarray, L: np.ndarray, rng: np.random.RandomState
) -> np.ndarray:
    return rng.randn(n_days, n_assets) @ L.T + mu


def gen_returns_mvt(
    n_days: int, n_assets: int, mu: np.ndarray, L: np.ndarray,
    df: float, rng: np.random.RandomState,
) -> np.ndarray:
    """Multivariate-t via normal / sqrt(chi2/df). Preserves covariance structure."""
    z = rng.randn(n_days, n_assets) @ L.T
    chi = rng.chisquare(df, size=(n_days, 1)) / df
    return z / np.sqrt(chi) + mu


# ==============================================================================
# DCA ALLOCATION (FIXED)
# ==============================================================================


def dca_allocate(
    current: np.ndarray,
    inflow: float,
    target_w: np.ndarray,
    min_order: float,
    cost_bps: float,
) -> np.ndarray:
    """Allocate monthly inflow with min-order constraint. No sells, exact budget."""
    budget = inflow * (1.0 - cost_bps / 10_000)
    ideal = target_w * (current.sum() + budget)
    raw = np.clip(ideal - current, 0, None)
    buys = np.zeros_like(raw)

    if raw.sum() < 1e-10:
        # Portfolio is overweight vs target on all assets – proportional DCA
        return target_w * budget

    remaining = budget
    active = raw > 0

    for _ in range(3):  # max 3 iterations for convergence
        if not active.any() or remaining < 1e-10:
            break
        # Proportional split of remaining budget
        prop = raw.copy()
        prop[~active] = 0.0
        prop_sum = prop.sum()
        alloc = prop / prop_sum * remaining if prop_sum > 0 else np.zeros_like(prop)
        buys += alloc
        remaining = budget - buys.sum()
        active = (raw > buys) & (remaining >= min_order)

    # Distribute remainder
    if remaining > 0 and buys.sum() > 1e-10:
        buys += buys / buys.sum() * remaining

    # Enforce min_order on non-zero positions
    small = (buys > 0) & (buys < min_order)
    if small.any():
        deficit = (min_order - buys[small]).sum()
        # Scale down non-small allocations to cover deficit
        not_small = ~small & (buys > min_order)
        if not_small.any() and deficit > 0:
            scale = max(0.0, (buys[not_small].sum() - deficit) / buys[not_small].sum())
            buys[not_small] *= scale
        buys[small] = min_order
        # Renormalize
        if buys.sum() > 1e-10:
            buys = buys / buys.sum() * budget

    buys = np.clip(buys, 0, None)
    return buys


# ==============================================================================
# MONTE CARLO ENGINE
# ==============================================================================


def run_simulation(
    cfg: Config,
    mu: np.ndarray,
    L: np.ndarray,
    n_assets: int,
    tickers: List[str],
) -> np.ndarray:
    """Run Monte Carlo. Returns array of final portfolio values."""
    rng = np.random.RandomState(cfg.seed)
    w = np.array([cfg.target_weights[t] for t in tickers])
    start = np.array([cfg.target_weights[t] * cfg.initial_capital for t in tickers])
    gen = gen_returns_mvt if cfg.use_t_dist else gen_returns_normal
    gen_kw = {"df": cfg.t_df} if cfg.use_t_dist else {}

    finals = np.zeros(cfg.num_simulations)

    for sim in range(cfg.num_simulations):
        if cfg.use_t_dist:
            rets = gen_returns_mvt(cfg.total_days, n_assets, mu, L, cfg.t_df, rng)
        else:
            rets = gen_returns_normal(cfg.total_days, n_assets, mu, L, rng)

        vals = start.copy()

        for day in range(cfg.total_days):
            r = rets[day]
            vals *= np.exp(np.clip(r, -5.0, 5.0))  # log-return: price > 0 guaranteed

            # DCA contribution: 12 times — at end of each 21-day block
            if (day + 1) % cfg.days_per_month == 0:
                buys = dca_allocate(vals, cfg.monthly_inflow, w, cfg.min_order, cfg.tx_cost_bps)
                vals += buys

            # NaN guard
            vals = np.nan_to_num(vals, nan=0.0, posinf=1e10, neginf=0.0)

        finals[sim] = vals.sum()

    # Remove failed simulations
    valid = np.isfinite(finals)
    if not valid.all():
        logger.warning("Отброшено NaN/inf симуляций: %d", (~valid).sum())
        finals = finals[valid]

    if len(finals) == 0:
        raise ValueError("All simulations produced NaN")

    return finals


# ==============================================================================
# BENCHMARK
# ==============================================================================


def run_benchmark(
    cfg: Config, bench_rets: np.ndarray
) -> np.ndarray:
    """Simulate DCA into SPY benchmark."""
    rng = np.random.RandomState(cfg.seed)
    mu_b, std_b = bench_rets.mean(), bench_rets.std(ddof=1)
    finals = np.zeros(cfg.num_simulations)

    for sim in range(cfg.num_simulations):
        val = 0.0
        for _ in range(cfg.horizon_months):
            for _ in range(cfg.days_per_month):
                val *= np.exp(np.clip(rng.normal(mu_b, std_b), -5.0, 5.0))
            val += cfg.monthly_inflow
        finals[sim] = val

    return finals


# ==============================================================================
# RISK METRICS
# ==============================================================================


@dataclass
class RiskReport:
    p10: float; p50: float; p90: float
    mean: float; std: float
    sharpe: float; sortino: float
    var95: float; cvar95: float
    profit_factor: float

    @classmethod
    def compute(cls, vals: np.ndarray, invested: float, rf: float = 0.04) -> "RiskReport":
        pnl = vals - invested
        rets = pnl / invested
        p10, p50, p90 = np.percentile(vals, [10, 50, 90])

        ex = rets.mean() - rf
        sharpe = ex / rets.std(ddof=1) if rets.std(ddof=1) > 0 else 0.0

        neg = rets[rets < 0]
        down = neg.std(ddof=1) if len(neg) > 0 else 0.0
        sortino = rets.mean() / down if down > 0 else 0.0

        var95 = invested - np.percentile(vals, 5)
        tail = vals[vals <= np.percentile(vals, 5)]
        cvar95 = invested - tail.mean() if len(tail) > 0 else 0.0

        g = pnl[pnl > 0]; l = pnl[pnl < 0]
        pf = g.sum() / abs(l.sum()) if len(l) > 0 and l.sum() != 0 else (np.inf if len(g) > 0 else 0.0)

        return cls(p10, p50, p90, vals.mean(), vals.std(ddof=1),
                   sharpe, sortino, var95, cvar95, pf)


# ==============================================================================
# VISUALIZATION
# ==============================================================================


def plot_report(
    vals: np.ndarray, bench: Optional[np.ndarray],
    rp: RiskReport, bench_rp: Optional[RiskReport], cfg: Config,
    save_path: str = "portfolio_simulation.png",
) -> None:
    """4-panel visualization."""
    available = plt.style.available
    style = next((s for s in ("seaborn-v0_8-whitegrid", "ggplot", "default") if s in available), "default")
    plt.style.use(style)

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))

    # (A) Histogram
    ax = axes[0, 0]
    ax.hist(vals, bins=60, color="crimson", edgecolor="black", alpha=0.7, density=True)
    ax.axvline(rp.p10, color="red", ls=":", lw=2, label=f"P10: ${rp.p10:,.0f}")
    ax.axvline(rp.p50, color="gold", ls="--", lw=2, label=f"P50: ${rp.p50:,.0f}")
    ax.axvline(rp.p90, color="green", ls=":", lw=2, label=f"P90: ${rp.p90:,.0f}")
    ax.axvline(cfg.total_invested, color="blue", ls="-", lw=1, alpha=0.4, label=f"Invested: ${cfg.total_invested:,.0f}")
    ax.set_title("Portfolio Value Distribution")
    ax.set_xlabel("USD"); ax.set_ylabel("Density")
    ax.legend(fontsize=7)

    # (B) Violin plot: portfolio vs benchmark
    ax = axes[0, 1]
    p_ret = (vals - cfg.total_invested) / cfg.total_invested * 100
    data, labels = [p_ret], ["AI Portfolio"]
    if bench is not None:
        b_ret = (bench - cfg.total_invested) / cfg.total_invested * 100
        data.append(b_ret); labels.append(cfg.bench_ticker)
    ax.violinplot(data, showmeans=True, showmedians=True)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Return (%)")
    ax.set_title("Return Distribution Comparison")
    ax.axhline(0, color="black", lw=0.5)

    # (C) Risk table
    ax = axes[1, 0]; ax.axis("off")
    lines = [
        "RISK-REWARD REPORT",
        "=" * 42,
        f"P10 (pessimistic):    ${rp.p10:>10,.0f}",
        f"P50 (median):         ${rp.p50:>10,.0f}",
        f"P90 (optimistic):     ${rp.p90:>10,.0f}",
        f"Mean:                 ${rp.mean:>10,.0f}",
        f"Std Dev:              ${rp.std:>10,.0f}",
        f"Sharpe Ratio:         {rp.sharpe:>10.2f}",
        f"Sortino Ratio:        {rp.sortino:>10.2f}",
        f"VaR(95%):             ${rp.var95:>10,.0f}",
        f"CVaR(95%):            ${rp.cvar95:>10,.0f}",
        f"Profit Factor:        {rp.profit_factor:>10.2f}",
        "=" * 42,
        f"Total Invested:       ${cfg.total_invested:>10,.0f}",
        f"Net Median Profit:    ${rp.p50 - cfg.total_invested:>10,.0f}",
    ]
    if bench_rp is not None:
        lines += [
            "",
            f"{cfg.bench_ticker} BENCHMARK:",
            f"  P50: ${bench_rp.p50:,.0f}  Sharpe: {bench_rp.sharpe:.2f}  VaR: ${bench_rp.var95:,.0f}",
        ]
    ax.text(0.05, 0.95, "\n".join(lines), transform=ax.transAxes,
            fontsize=9, verticalalignment="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    # (D) CDF
    ax = axes[1, 1]
    s = np.sort(vals); c = np.linspace(0, 1, len(s))
    ax.plot(s, c, color="crimson", lw=2, label="Portfolio")
    if bench is not None:
        sb = np.sort(bench); cb = np.linspace(0, 1, len(sb))
        ax.plot(sb, cb, color="blue", lw=2, ls="--", label=cfg.bench_ticker)
    for y, color, lbl in [(0.1, "red", None), (0.5, "gold", None), (0.9, "green", None)]:
        ax.axhline(y, color=color, ls=":", alpha=0.3)
    ax.axvline(cfg.total_invested, color="gray", ls="-", alpha=0.3)
    ax.set_title("Cumulative Distribution Function")
    ax.set_xlabel("USD"); ax.set_ylabel("CDF")
    ax.legend(fontsize=7)

    plt.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    logger.info("График сохранён в %s", save_path)
    plt.close(fig)


# ==============================================================================
# MAIN
# ==============================================================================


def main() -> Tuple[np.ndarray, RiskReport]:
    cfg = Config()

    logger.info("=" * 60)
    logger.info("Монте-Карло симулятор портфеля v2.0")
    logger.info("=" * 60)

    # 1. Load data
    logger.info("[1/5] Загрузка рыночных данных...")
    prices, tickers = load_prices(list(cfg.tickers))
    bench_prices, _ = load_prices([cfg.bench_ticker])

    # Filter config to available tickers, renormalize weights
    old_weights = cfg.target_weights
    cfg.target_weights = {t: old_weights[t] for t in tickers}
    w_sum = sum(cfg.target_weights.values())
    cfg.target_weights = {k: v / w_sum for k, v in cfg.target_weights.items()}

    n_assets = len(tickers)
    logger.info("Активы: %s", tickers)
    logger.info("Веса: %s", {k: f"{v:.1%}" for k, v in cfg.target_weights.items()})

    # 2. Statistics
    logger.info("[2/5] Расчёт статистик...")
    mu, sigma = compute_stats(prices, tickers)
    rets_arr = prices[tickers].pct_change().dropna().values
    if cfg.use_shrinkage:
        sigma = shrink_covariance(rets_arr)
        logger.info("Шринкедж Ledoit-Wolf применён")
    L = safe_cholesky(sigma)
    ann_vol = np.sqrt(np.diag(sigma) * 252)
    logger.info("Год.вола (ср): %.1f%%  |  Днев.доход (ср): %.6f", ann_vol.mean() * 100, mu.mean())

    # 2.5. Hybrid audit (G/L ratio, win rate)
    returns_df = prices[tickers].pct_change().dropna()
    w_arr = np.array([cfg.target_weights[t] for t in tickers])
    pf_daily = returns_df.dot(w_arr)
    gains = pf_daily[pf_daily > 0]
    losses = pf_daily[pf_daily < 0]
    gl = gains.mean() / abs(losses).mean() if len(losses) > 0 else float('nan')
    win_rate = len(gains) / len(pf_daily) * 100 if len(pf_daily) > 0 else 0
    print(f"\n{'='*66}")
    print("  ГИБРИДНЫЙ АУДИТ ПОРТФЕЛЯ (5 лет ковариация / 3 г. доходность)")
    print(f"{'='*66}")
    print(f"  G/L коэффициент:    {gl:>8.4f}")
    print(f"  Win-rate (дней):    {win_rate:>7.1f}%")
    print(f"  Дней наблюдений:    {len(pf_daily):>8}")
    print(f"  Горизонт прогноза:  12 месяцев")
    print(f"{'='*66}")

    # 3. Monte Carlo
    logger.info("[3/5] Запуск %d симуляций...", cfg.num_simulations)
    finals = run_simulation(cfg, mu, L, n_assets, tickers)

    # 4. Benchmark
    logger.info("[4/5] Симуляция бенчмарка %s...", cfg.bench_ticker)
    try:
        bench_col = cfg.bench_ticker if cfg.bench_ticker in bench_prices.columns else bench_prices.columns[0]
        bench_rets = bench_prices[bench_col].pct_change().dropna().values
        bench_vals = run_benchmark(cfg, bench_rets)
    except Exception:
        logger.warning("Бенчмарк упал", exc_info=True)

    # 5. Report
    logger.info("[5/5] Расчёт метрик и построение графиков...")
    rp = RiskReport.compute(finals, cfg.total_invested)
    bench_rp = RiskReport.compute(bench_vals, cfg.total_invested) if bench_vals is not None else None

    # --- Текущий смарт-ордер ---
    print(f"\n{'='*66}")
    print("  ТЕКУЩИЙ СМАРТ-ОРДЕР НА ${:.0f}".format(cfg.monthly_inflow))
    print(f"{'='*66}")
    latest = prices[tickers].iloc[-1]
    for t in tickers:
        alloc = cfg.target_weights[t] * cfg.monthly_inflow
        shares = alloc / latest[t]
        print(f"  {t:<6} ${alloc:>7.2f}   (~{shares:.4f} акций  @ ${latest[t]:.2f})")
    print(f"{'='*66}")

    # --- Итоговый прогноз ---
    print(f"\n{'='*66}")
    print("  ВЕРОЯТНОСТНЫЙ ПРОГНОЗ ЧЕРЕЗ 12 МЕСЯЦЕВ")
    print(f"{'='*66}")
    print(f"  Портфель:     {', '.join(tickers)}")
    print(f"  Модель:       {'MVT (df=' + str(cfg.t_df) + ')' if cfg.use_t_dist else 'Гауссовская'}")
    print(f"  Симуляций:    {cfg.num_simulations:,}")
    print(f"  Пополнений:   {cfg.horizon_months} x ${cfg.monthly_inflow:.0f} = ${cfg.total_invested:,.0f}")
    print(f"{'  -' + '-'*64}")
    print(f"  [ОПТИМИСТ] P90:  ${rp.p90:>10,.0f}   (доход: {rp.p90 - cfg.total_invested:>+,.0f})")
    print(f"  [МЕДИАНА]  P50:  ${rp.p50:>10,.0f}   (доход: {rp.p50 - cfg.total_invested:>+,.0f})")
    print(f"  [ПЕССИМИСТ] P10: ${rp.p10:>10,.0f}   (доход: {rp.p10 - cfg.total_invested:>+,.0f})")
    print(f"{'  -' + '-'*64}")
    print(f"  Коэф. Шарпа:  {rp.sharpe:>7.2f}")
    print(f"  Коэф. Сортино:{rp.sortino:>7.2f}")
    print(f"  VaR (95%):    ${rp.var95:>7,.0f}")
    print(f"  CVaR (95%):   ${rp.cvar95:>7,.0f}")
    print(f"  Profit Factor:{rp.profit_factor:>7.2f}")
    print(f"  Чистая медианная прибыль: ${rp.p50 - cfg.total_invested:>+,.0f}")
    if bench_rp is not None:
        outperf = rp.p50 - bench_rp.p50
        print(f"{'  -' + '-'*64}")
        print(f"  {cfg.bench_ticker} — P50: ${bench_rp.p50:,.0f} | Шарп: {bench_rp.sharpe:.2f}")
        print(f"  Превосходство над {cfg.bench_ticker}: ${outperf:+,.0f}")
    print(f"{'='*66}\n")

    plot_report(finals, bench_vals, rp, bench_rp, cfg)
    return finals, rp


if __name__ == "__main__":
    main()
