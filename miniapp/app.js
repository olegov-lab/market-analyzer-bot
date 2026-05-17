const API_BASE = window.location.origin;
let Telegram = null;
let initData = '';
let userId = null;
let pollTimers = {};
let articles = [];
let lessons = [];
let chatMessages = [];
let chatSending = false;

try {
  Telegram = window.Telegram.WebApp;
  Telegram.ready();
  Telegram.expand();
  initData = Telegram.initData || '';
  if (Telegram.colorScheme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
  }
} catch (e) {
  try {
    const hash = window.location.hash;
    if (hash && hash.includes('tgWebAppData=')) {
      const params = new URLSearchParams(hash.slice(1));
      const rawData = params.get('tgWebAppData') || '';
      initData = decodeURIComponent(rawData);
      Telegram = { ready: function(){}, expand: function(){}, sendData: function(){}, setHeaderColor: function(){}, openTelegramLink: function(){}, openLink: function(){}, BackButton: { show: function(){}, hide: function(){}, onClick: function(){} }, HapticFeedback: { impactOccurred: function(){} } };
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    }
  } catch (_) {}
}

// Fallback: ensure Telegram is never null (prevents haptic/UI errors)
if (!Telegram) {
  Telegram = { ready: function(){}, expand: function(){}, sendData: function(){}, setHeaderColor: function(){}, openTelegramLink: function(){}, openLink: function(){}, BackButton: { show: function(){}, hide: function(){}, onClick: function(){} }, HapticFeedback: { impactOccurred: function(){} } };
  initData = '';
}

document.addEventListener('click', function(e) {
  var btn = e.target.closest('[data-action]');
  if (!btn) return;
  var action = btn.getAttribute('data-action');
  var tier = btn.getAttribute('data-tier');
  var paymentId = btn.getAttribute('data-payment-id');
  var uri = btn.getAttribute('data-uri');

  if (action === 'subscribe') subscribeTier(tier);
  else if (action === 'cryptoPay') createCryptoPayment(tier);
  else if (action === 'switchPayment') switchPaymentMethod(tier);
  else if (action === 'linkWallet') linkTonWallet();
  else if (action === 'unlinkWallet') unlinkTonWallet();
  else if (action === 'verifyPayment') verifyAndActivate(parseInt(paymentId));
  else if (action === 'copyAddress') copyToClipboard(btn.getAttribute('data-address'));
});

async function apiCall(path, options = {}, timeout = 15000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  const headers = { 'X-Telegram-Init-Data': initData, ...options.headers };
  try {
    const resp = await fetch(`${API_BASE}${path}`, { ...options, headers, signal: controller.signal });
    clearTimeout(timeoutId);
    if (!resp.ok) {
      const text = await resp.text();
      let errMsg = `HTTP ${resp.status}`;
      try {
        const errJson = JSON.parse(text);
        errMsg = errJson.detail || errMsg;
      } catch (_) {}
      if (resp.status === 401) {
        sessionExpired(errMsg);
        throw new Error(errMsg);
      }
      throw new Error(errMsg);
    }
    return resp.json();
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') throw new Error('Таймаут запроса');
    if (e.message.includes('401') || e.message.includes('Invalid init data')) {
      sessionExpired(e.message);
    }
    throw e;
  }
}

function sessionExpired(msg) {
  const content = document.getElementById('content');
  if (!content) return;
  content.innerHTML =
    '<div class="card" style="text-align:center;padding:30px;">' +
    '<div style="font-size:40px;">🔐</div>' +
    '<div style="margin-top:12px;font-size:14px;color:var(--text);">Сессия истекла</div>' +
    '<div style="margin-top:4px;font-size:11px;color:var(--hint);">' + escapeHtml(msg) + '</div>' +
    '<button onclick="window.location.reload()" class="upgrade-btn" style="margin-top:16px;">🔄 Перезагрузить</button>' +
    '</div>';
}

function render(html) {
  try {
    const content = document.getElementById('content');
    if (content) {
      content.classList.remove('fade-in');
      void content.offsetWidth;
      content.innerHTML = html;
      content.classList.add('fade-in');
    }
  } catch (e) {
    console.error('Render failed:', e);
    const content = document.getElementById('content');
    if (content) content.innerHTML = '<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">Ошибка отображения</div></div>';
  }
}

function renderSub(html) {
  const el = document.getElementById('sub-content');
  if (el) el.innerHTML = html;
}
function renderTabs(html) {
  const el = document.getElementById('sub-tabs-bar');
  if (el) el.innerHTML = html;
}

function tgBackButton(action) {
  if (!Telegram) return;
  if (action === 'show') Telegram.BackButton.show();
  else if (action === 'hide') Telegram.BackButton.hide();
  else if (action === 'onClick') Telegram.BackButton.onClick(arguments[1]);
}

function tgShowAlert(msg) {
  if (Telegram) Telegram.showAlert(msg);
  else alert(msg);
}

function showLoading() {
  render('<div class="loading"><div class="spinner"></div><p>⏳ Загрузка...</p></div>');
}

function showError(msg) {
  render('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + msg + '</div></div>');
}

function haptic(style) {
  try {
    if (Telegram && Telegram.HapticFeedback && Telegram.HapticFeedback.impactOccurred) {
      Telegram.HapticFeedback.impactOccurred(style || 'light');
    }
  } catch(e) {}
}

function setSentiment(direction) {
  const map = { BUY: 'bullish', SELL: 'bearish', HOLD: 'neutral' };
  const sentiment = map[direction] || 'neutral';
  document.documentElement.setAttribute('data-sentiment', sentiment);
  try {
    const colors = { bullish: '#00c853', bearish: '#ff1744', neutral: '#2481cc' };
    Telegram.setHeaderColor(colors[sentiment]);
  } catch(e) {}
}

function navigate(page, sub) {
  haptic('medium');
  sub = sub || '';
  const map = {
    'indicators': sub ? '#indicators/' + sub : '#indicators/price',
    'miniapp': sub ? '#miniapp/' + sub : '#miniapp/games',
    'news': sub ? '#news/' + sub : '#news/general',
    'upgrade': '#upgrade',
  };
  window.location.hash = map[page] || '#' + page;
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const page = btn.dataset.page;
    if (page === 'indicators') navigate('indicators', 'price');
    else if (page === 'miniapp') navigate('miniapp', 'games');
    else if (page === 'news') navigate('news', 'general');
    else if (page === 'chat') { window.location.hash = '#chat'; return; }
    else navigate(page);
  });
});

function setActiveNav(page) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector('.nav-btn[data-page="' + page + '"]');
  if (btn) btn.classList.add('active');
}

function parseHash() {
  let h = window.location.hash.slice(1);
  if (!h || h.startsWith('tgWebAppData=')) return { page: 'indicators', sub: 'chart', param: null, chartTf: null, chartInd: null };
  const parts = h.split('/');
  if (parts[0] === 'indicators' || parts[0] === '' || !['chat','miniapp','news','upgrade'].includes(parts[0])) {
    const sub = parts[1] || 'chart';
    const chartTf = (sub === 'chart' && parts[2]) ? parts[2] : null;
    const chartInd = (sub === 'chart' && parts[3]) ? parts[3] : null;
    return { page: 'indicators', sub: sub, param: parts[2] || null, chartTf: chartTf, chartInd: chartInd };
  }
  if (parts[0] === 'chat') return { page: 'chat', sub: null, param: null, chartTf: null, chartInd: null };
  if (parts[0] === 'miniapp') return { page: 'miniapp', sub: parts[1] || 'lessons', param: parts[2] || null, chartTf: null, chartInd: null };
  if (parts[0] === 'news') return { page: 'news', sub: parts[1] || 'general', param: null, chartTf: null, chartInd: null };
  if (parts[0] === 'upgrade') return { page: 'upgrade', sub: null, param: null, chartTf: null, chartInd: null };
  return { page: 'indicators', sub: 'chart', param: null, chartTf: null, chartInd: null };
}

function startPoll(name, fn, interval) {
  stopPoll(name);
  fn();
  pollTimers[name] = setInterval(fn, interval);
}

function stopPoll(name) {
  if (pollTimers[name]) {
    clearInterval(pollTimers[name]);
    delete pollTimers[name];
  }
}

function stopAllPolls() {
  Object.keys(pollTimers).forEach(stopPoll);
}

async function renderDashboard() {
  tgBackButton('hide');
  renderSub('<div class="skeleton skeleton-hero"></div><div class="skeleton skeleton-block"></div><div class="skeleton skeleton-block"></div>');
  try {
    const data = await apiCall('/miniapp/dashboard');
    const p = data.price;
    const ind = data.indicators;
    const pred = data.prediction_summary;
    const signal = pred ? pred.direction : 'HOLD';

    let signalClass = 'hold';
    if (signal === 'BUY') signalClass = 'buy';
    else if (signal === 'SELL') signalClass = 'sell';

    setSentiment(signal);

    try {
      const colors = { buy: '#00c853', sell: '#ff1744', hold: '#ff9800' };
      Telegram.setHeaderColor(colors[signalClass] || '#000');
    } catch(e) {}

    let signalEmoji = '⚪';
    if (signal === 'BUY') signalEmoji = '🟢';
    else if (signal === 'SELL') signalEmoji = '🔴';

    let signalText = 'HOLD';
    if (signal === 'BUY') signalText = 'BUY — oversold';
    else if (signal === 'SELL') signalText = 'SELL — overbought';

    let html = '<div class="hero ' + signalClass + '">';
    html += '<div class="hero-signal">' + signalEmoji + ' ' + signalText + '</div>';
    html += '<div class="hero-price">$' + (p ? Number(p).toLocaleString('en-US') : '—') + '</div>';
    if (ind && ind.rsi != null) {
      const rsiColor = ind.rsi > 70 ? '🔴' : ind.rsi < 30 ? '🟢' : '⚪';
      html += '<div class="hero-rsi">RSI(14) ' + rsiColor + ' ' + ind.rsi.toFixed(1) + '</div>';
    }
    if (data.fear_greed) {
      const fg = data.fear_greed;
      const fgEmoji = fg.value >= 50 ? '🟢' : '🔴';
      html += '<div class="hero-rsi">' + fgEmoji + ' Fear & Greed: ' + fg.value + '/100 — ' + fg.classification + '</div>';
    }
    html += '</div>';

    if (pred) {
      const confPct = Math.round(pred.confidence * 100);
      const confColor = confPct >= 70 ? 'high' : confPct >= 40 ? 'med' : 'low';
      html += '<div class="card"><div class="card-title">Уверенность прогноза</div><div class="conf-bar"><div class="conf-bar-fill ' + confColor + '" style="width:' + confPct + '%"></div></div><div class="row"><span class="label">' + confPct + '%</span><span class="value">' + (confPct >= 70 ? 'высокая' : confPct >= 40 ? 'средняя' : 'низкая') + '</span></div></div>';
    }

    if (data.consensus && !data.consensus.low_confidence) {
      const cp = data.consensus.bullish_pct;
      const sig = data.consensus.signal;
      const sigLabel = sig === 'strong_bullish' ? 'Сильно бычий' : sig === 'bullish' ? 'Бычий' : sig === 'strong_bearish' ? 'Сильно медвежий' : sig === 'bearish' ? 'Медвежий' : 'Нейтральный';
      html += '<div class="card"><div class="card-title">Консенсус индикаторов</div><div class="conf-bar"><div class="conf-bar-fill" style="width:' + cp + '%;background:linear-gradient(90deg,#00c853,' + (cp >= 50 ? '#ffc107' : '#ff1744') + ')"></div></div><div class="row"><span class="label">' + cp + '% за рост</span><span class="value">' + sigLabel + '</span></div></div>';
    }

    if (ind) {
      html += '<div class="card"><div class="card-title">Технические индикаторы</div>';
      if (ind.rsi != null) {
        const rsiFillColor = ind.rsi > 70 ? '#ff1744' : ind.rsi < 30 ? '#00c853' : '#ffc107';
        html += '<div class="row"><span class="label">RSI(14)</span><span class="value"><div class="conf-bar" style="width:80px;display:inline-block;vertical-align:middle;"><div class="conf-bar-fill" style="width:' + ind.rsi.toFixed(0) + '%;background:' + rsiFillColor + '"></div></div> ' + ind.rsi.toFixed(1) + '</span></div>';
      }
      if (ind.bb_lower != null) {
        html += '<div class="row"><span class="label">BB(20,2)</span><span class="value">' + fmtPrice(ind.bb_lower) + ' / ' + fmtPrice(ind.bb_middle) + ' / ' + fmtPrice(ind.bb_upper) + '</span></div>';
      }
      if (ind.macd != null) {
        const macdDir = ind.macd > ind.macd_signal ? ' бычье' : ' медвежье';
        html += '<div class="row"><span class="label">MACD</span><span class="value">' + ind.macd.toFixed(1) + macdDir + '</span></div>';
      }
      const maParts = [];
      if (ind.ma_50 != null) maParts.push('MA50 ' + fmtPrice(ind.ma_50));
      if (ind.ma_100 != null) maParts.push('MA100 ' + fmtPrice(ind.ma_100));
      if (ind.ma_200 != null) maParts.push('MA200 ' + fmtPrice(ind.ma_200));
      if (maParts.length) {
        html += '<div class="row"><span class="label">MA</span><span class="value">' + maParts.join(' | ') + '</span></div>';
      }
      html += '</div>';
    }

    if (data.volatility) {
      const v = data.volatility;
      const pct = Math.round(v.current * 100);
      const volColor = pct < 25 ? 'var(--green)' : pct < 50 ? 'var(--yellow)' : pct < 75 ? '#ff9800' : 'var(--red)';
      const volLabel = v.classification === 'low' ? 'Низкая' : v.classification === 'medium' ? 'Средняя' : v.classification === 'high' ? 'Высокая' : 'Экстремальная';
      html += '<div class="card"><div class="card-title">📊 Волатильность</div>';
      html += '<div class="vol-gauge"><div class="vol-gauge-fill" style="width:' + pct + '%;background:' + volColor + '"></div></div>';
      html += '<div class="row"><span class="label">Уровень</span><span class="value">' + volLabel + '</span></div>';
      html += '<div class="row"><span class="label">BB ширина</span><span class="value">' + v.bb_width_pct.toFixed(2) + '%</span></div>';
      html += '<div class="row"><span class="label">ATR</span><span class="value">' + v.atr_pct.toFixed(2) + '%</span></div>';
      html += '<div class="row"><span class="label">Перцентиль (30д)</span><span class="value">' + v.percentile.toFixed(0) + '%</span></div>';
      if (v.history && v.history.length) {
        const max = Math.max(...v.history, 0.01);
        html += '<div class="sparkline">';
        for (const h of v.history) {
          const hp = Math.max(2, (h / max) * 100);
          const hc = h < 0.25 ? 'var(--green)' : h < 0.5 ? 'var(--yellow)' : h < 0.75 ? '#ff9800' : 'var(--red)';
          html += '<div class="spark-bar" style="height:' + hp + '%;background:' + hc + '"></div>';
        }
        html += '</div>';
      }
      html += '</div>';
    }

    html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">♻️ Обновление каждые 30с</div>';

    apiCall('/miniapp/metcalfe').then(function(mc) {
      if (!mc || document.getElementById('metcalfe-card')) return;
      var sigEmoji = mc.signal === 'undervalued' ? '🟢' : mc.signal === 'overvalued' ? '🔴' : '🟡';
      var sigText = mc.signal === 'undervalued' ? 'Недооценён' : mc.signal === 'overvalued' ? 'Переоценён' : 'Справедливо';
      var mcHtml = '<div class="card" id="metcalfe-card"><div class="card-title">📐 Закон Меткалфа</div>';
      mcHtml += '<div style="font-size:16px;font-weight:700;">' + sigEmoji + ' ' + sigText + ' (' + (mc.deviation_pct > 0 ? '+' : '') + mc.deviation_pct + '%)</div>';
      mcHtml += '<div class="row"><span class="label">Справедливая цена</span><span class="value">$' + fmtPrice(mc.metcalfe_price) + '</span></div>';
      mcHtml += '<div class="row"><span class="label">Коридор</span><span class="value">$' + fmtPrice(mc.lower_band) + ' – $' + fmtPrice(mc.upper_band) + '</span></div>';
      mcHtml += '<div class="row"><span class="label">Активные адреса</span><span class="value">' + Number(mc.active_addresses).toLocaleString() + '</span></div>';
      mcHtml += '</div>';
      var footer = document.querySelector('#sub-content .card:last-child');
      if (footer) footer.insertAdjacentHTML('beforebegin', mcHtml);
    }).catch(function(){});

    renderSub(html);

    // Async AI summary — loads after dashboard renders, does not block UI
    apiCall('/miniapp/summary').then(function(summary) {
      if (!summary || !Object.values(summary).some(function(s) { return s; })) return;
      var subContent = document.getElementById('sub-content');
      if (!subContent) return;
      var labels = { trend: 'Тренд', momentum: 'Моментум', volatility: 'Волатильность', onchain: 'On-chain', sentiment: 'Сентимент' };
      var summaryHtml = '<div class="card" id="ai-summary-card"><div class="card-title">🧠 AI Сводка</div>';
      for (var key in summary) {
        if (summary[key]) {
          summaryHtml += '<div style="margin-bottom:10px;"><div style="font-size:11px;font-weight:600;color:var(--btn);margin-bottom:2px;">' + (labels[key] || key) + '</div><div style="font-size:12px;color:var(--text);line-height:1.55;">' + escapeHtml(summary[key]) + '</div></div>';
        }
      }
      summaryHtml += '</div>';
      // Insert after consensus card, or after hero block
      var cards = subContent.querySelectorAll('.card');
      var insertAfter = null;
      for (var i = 0; i < cards.length; i++) {
        var title = cards[i].querySelector('.card-title');
        if (title && title.textContent.indexOf('Консенсус') !== -1) {
          insertAfter = cards[i];
          break;
        }
      }
      if (!insertAfter) {
        var hero = subContent.querySelector('.hero');
        if (hero) insertAfter = hero;
      }
      if (insertAfter) {
        insertAfter.insertAdjacentHTML('afterend', summaryHtml);
      }
    }).catch(function(){});
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

async function renderPredict() {
  tgBackButton('hide');
  renderSub('<div class="card"><div class="spinner"></div></div>');
  try {
    const [pred, vol] = await Promise.all([
      apiCall('/miniapp/predict'),
      apiCall('/miniapp/volatility').catch(() => null),
    ]);
    let html = '';

    if (pred) {
      const p4h = pred.meta?.prediction_4h || {};
      const p1w = pred.meta?.prediction_1w;
      const plong = pred.meta?.prediction_long || {};

      const signal = pred.direction || 'HOLD';
      let signalClass = 'hold', signalEmoji = '⚪';
      if (signal === 'BUY') { signalClass = 'buy'; signalEmoji = '🟢'; }
      else if (signal === 'SELL') { signalClass = 'sell'; signalEmoji = '🔴'; }

      const confPct = Math.round((pred.confidence || 0) * 100);
      const confColor = confPct >= 70 ? 'high' : confPct >= 40 ? 'med' : 'low';
      const priceMin = pred.price_min || 0;
      const priceMax = pred.price_max || 0;

      html += '<div class="card"><div class="card-title">Сегодня</div><div class="signal ' + signalClass + '">' + signalEmoji + ' ' + signal + '</div><div style="margin-top:8px;font-weight:600;">$' + fmtPrice(priceMin) + ' – $' + fmtPrice(priceMax) + '</div><div class="conf-bar"><div class="conf-bar-fill ' + confColor + '" style="width:' + confPct + '%"></div></div><div class="row"><span class="label">Уверенность</span><span class="value">' + confPct + '%</span></div>';
      if (vol) {
        const vLabel = vol.classification === 'low' ? '🟢 Низкая' : vol.classification === 'medium' ? '🟡 Средняя' : vol.classification === 'high' ? '🟠 Высокая' : '🔴 Экстремальная';
        const vCls = vol.classification === 'low' ? 'green' : vol.classification === 'medium' ? 'yellow' : vol.classification === 'high' ? 'orange' : 'red';
        html += '<div class="row"><span class="label">📊 Волатильность</span><span class="value"><span class="vol-indicator ' + vCls + '">' + vLabel + '</span></span></div>';
      }
      html += '</div>';

      const zones = p4h.liquidity_zones || [];
      if (zones.length) {
        html += '<div class="card"><div class="card-title">Риски</div>';
        for (const z of zones) {
          const text = z.type === 'long'
            ? 'откат до $' + fmtPrice(z.price) + ' перед ростом'
            : 'пробой $' + fmtPrice(z.price) + ' → цепная реакция';
          html += '<div class="row"><span class="label">' + text + '</span></div>';
        }
        html += '</div>';
      }

      if (p1w && p1w.cycle_phase) {
        const phaseLabel = { ACCUMULATION: 'накопление', MARKUP: 'рост', DISTRIBUTION: 'распределение', MARKDOWN: 'снижение' };
        html += '<div class="card"><div class="card-title">Неделя</div>';
        html += '<div class="row"><span class="label">Фаза</span><span class="value">' + (phaseLabel[p1w.cycle_phase] || p1w.cycle_phase) + ' (score ' + (p1w.cycle_score||0).toFixed(2) + ')</span></div>';
        if (p1w.mvrv_z != null) html += '<div class="row"><span class="label">MVRV Z-Score</span><span class="value">' + p1w.mvrv_z.toFixed(2) + '</span></div>';
        if (p1w.sopr != null) html += '<div class="row"><span class="label">SOPR</span><span class="value">' + p1w.sopr.toFixed(2) + '</span></div>';
        html += '</div>';
      }

      if (plong.price_vs_200w_ma_text || plong.halving_days != null) {
        html += '<div class="card"><div class="card-title">Долгосрочно</div>';
        if (plong.price_vs_200w_ma_text) {
          html += '<div class="row"><span class="label">' + plong.price_vs_200w_ma_text + '</span></div>';
        }
        if (plong.halving_days != null) {
          html += '<div class="row"><span class="label">Халвинг через</span><span class="value">' + plong.halving_days + ' дн</span></div>';
        }
        html += '</div>';
      }

      html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">♻️ Прогноз — 1ч · On-chain — 6ч</div>';
    } else {
      html = '<div class="card"><div class="card-title">Прогноз</div>⏳ Собираем историю для прогноза (~48ч)</div>';
    }

    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

async function renderNews() {
  tgBackButton('hide');
  renderSub('<div class="card"><div class="spinner"></div></div>');
  try {
    const data = await apiCall('/miniapp/news');
    articles = data.articles || [];
    const bullCount = data.sentiment?.bullish || 0;
    const bearCount = data.sentiment?.bearish || 0;
    const neutralCount = data.sentiment?.neutral || 0;
    const mood = data.sentiment?.mood || 'neutral';

    const moodEmoji = mood === 'bullish' ? '🟢' : mood === 'bearish' ? '🔴' : '🟡';
    const moodText = mood === 'bullish' ? 'Бычье' : mood === 'bearish' ? 'Медвежье' : 'Нейтральное';

    const worry = articles.length ? bearCount / articles.length : 0;
    let worryLabel = '🟢 Низкий';
    if (worry >= 0.6) worryLabel = '🔴 Высокий';
    else if (worry >= 0.3) worryLabel = '🟡 Средний';

    let html = '<div class="card"><div class="card-title">Пульс рынка</div><div style="font-size:18px;font-weight:700;">' + moodEmoji + ' ' + moodText + '</div><div class="mood-row"><div class="mood-item bullish"><div class="count">' + bullCount + '</div><div class="mood-label">Бычьих</div></div><div class="mood-item bearish"><div class="count">' + bearCount + '</div><div class="mood-label">Медвежьих</div></div><div class="mood-item neutral"><div class="count">' + neutralCount + '</div><div class="mood-label">Нейтр.</div></div></div><div style="margin-top:8px;font-size:13px;">Тревога: ' + worryLabel + '</div></div>';

    const sentEmoji = { bullish: '🟢', bearish: '🔴', neutral: '🟡' };
    for (const a of articles) {
      const emoji = sentEmoji[a.sentiment] || '🟡';
      const src = a.source ? ' — ' + escapeHtml(a.source) : '';
      html += '<div class="news-item"><div class="news-title">' + emoji + ' ' + escapeHtml(a.title) + '</div><div class="news-meta"><a class="news-link" href="' + escapeHtml(a.url) + '" target="_blank">Читать' + src + '</a></div></div>';
    }

    html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">♻️ Новости — 5 мин</div>';
    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

async function renderLearnList() {
  tgBackButton('hide');
  renderSub('<div class="card"><div class="spinner"></div></div>');
  try {
    const data = await apiCall('/miniapp/lessons');
    lessons = data;
    const basic = data.filter(l => l.id <= 20);
    const advanced = data.filter(l => l.id > 20 && l.id <= 40);
    const pro = data.filter(l => l.id > 40);

    function sectionHtml(title, desc, items, open) {
      const id = title.replace(/\s/g,'');
      const arrow = open ? '▼' : '▶';
      return '<div class="accordion-card">' +
        '<div class="accordion-header" onclick="toggleAccordion(\'' + id + '\')">' +
          '<span>' + title + '</span>' +
          '<span style="font-size:12px;color:var(--hint);margin:0 8px;flex-shrink:0;">' + desc + '</span>' +
          '<span class="accordion-arrow">' + arrow + '</span>' +
        '</div>' +
        '<div class="accordion-body" id="acc-' + id + '"' + (open ? '' : ' style="display:none"') + '>' +
          items.map(l => '<a class="lesson-card" href="#miniapp/lessons/' + l.id + '">' + l.id + '. ' + escapeHtml(l.title) + '</a>').join('') +
        '</div></div>';
    }

    let html = '<div class="card" style="padding:0;"><div class="card-title" style="padding:14px 14px 0;">📖 Азбука крипты</div><p style="margin-bottom:0;padding:0 14px 6px;color:var(--hint);">60 уроков: от новичка до профи с формулами и графиками</p></div>';
    html += sectionHtml('📖 Для начинающих', '20 уроков', basic, false);
    html += sectionHtml('🧠 Для опытных', advanced.length + ' уроков с формулами', advanced, false);
    if (pro.length) {
      html += sectionHtml('🚀 Для профи', pro.length + ' уроков — аналитика + ML', pro, false);
    }
    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

async function renderLesson(id) {
  id = Number(id);
  renderSub('<div class="card"><div class="spinner"></div></div>');
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#miniapp/lessons'; });

  try {
    const [lesson, allLessons] = await Promise.all([
      apiCall('/miniapp/lessons/' + id),
      lessons.length ? Promise.resolve(lessons) : apiCall('/miniapp/lessons'),
    ]);
    if (!lessons.length) lessons = allLessons;
    let html = '<div class="card"><div class="card-title">Урок ' + lesson.id + '</div><div class="lesson-text">' + escapeHtml(lesson.text || '') + '</div><div class="lesson-nav">';

    if (id > 1) html += '<button onclick="window.location.hash=\'#miniapp/lessons/' + (id-1) + '\'">◀️ Назад</button>';
    else html += '<div></div>';
    if (id < lessons.length) html += '<button onclick="window.location.hash=\'#miniapp/lessons/' + (id+1) + '\'">▶️ Вперёд</button>';
    else html += '<div></div>';
    html += '</div></div>';

    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

async function renderChat() {
  tgBackButton('hide');
  stopAllPolls();
  renderTabs('');

  let html = '<div class="chat-overlay"><div class="chat-overlay-header"><span>🧠 AI Аналитика</span><button class="chat-close-btn" id="chat-close-btn" onclick="window.location.hash=\'#indicators/chart\'">✕</button></div><div class="chat-container"><div class="chat-messages" id="chat-messages">';

  if (chatMessages.length === 0) {
    const quickQs = [
      ['📉','Почему BTC падает?'],
      ['🔮','Прогноз на сегодня'],
      ['📊','Что такое MVRV?'],
      ['💰','Стоит ли покупать BTC?'],
      ['🛡️','Уровни поддержки и сопротивления'],
      ['📈','Что говорят индикаторы?'],
      ['⛏️','Как халвинг влияет на цену?'],
      ['🥇','Сравни BTC с золотом'],
    ];
    html += '<div class="chat-welcome"><h3>🧠 AI Аналитика</h3><p>Спросите Market-Brain о Bitcoin. Получайте анализ с учётом текущих рыночных данных.</p><div class="chat-quick-grid">' +
      quickQs.map(([icon, q]) => '<button class="chat-quick-btn" onclick="sendMessage(\'' + q.replace(/'/g,"\\'") + '\')"><span class="chat-quick-icon">' + icon + '</span><span>' + q + '</span></button>').join('') +
    '</div></div>';
  } else {
    for (const m of chatMessages) {
      const cls = m.role === 'user' ? 'user' : m.role === 'thinking' ? 'thinking' : m.role === 'error' ? 'error' : 'bot';
      html += '<div class="chat-msg ' + cls + '">' + escapeHtml(m.text) + '</div>';
    }
  }

  html += '</div>';
  html += '<div class="chat-input-bar">';
  html += '<input type="text" class="chat-input" id="chat-input" placeholder="Задайте вопрос о Bitcoin..."' + (chatSending ? ' disabled' : '') + '>';
  html += '<button class="chat-send-btn" id="chat-send-btn"' + (chatSending ? ' disabled' : '') + '>➤</button>';
  html += '</div></div></div>';

  render(html);

  const messagesEl = document.getElementById('chat-messages');
  if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;

  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send-btn');
  if (!input || !sendBtn) return;

  const doSend = () => {
    const text = input.value.trim();
    if (!text || chatSending) return;
    input.value = '';
    sendMessage(text);
  };

  sendBtn.addEventListener('click', doSend);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSend();
  });

  if (!chatSending) input.focus();
}

async function sendMessage(text) {
  if (chatMessages.length >= 100) chatMessages.splice(0, 20);
  chatMessages.push({ role: 'user', text });
  chatMessages.push({ role: 'thinking', text: '⏳ думаю...' });
  chatSending = true;
  renderChat();

  try {
    const data = await apiCall('/miniapp/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text }),
    });

    const taskId = data.task_id;
    if (!taskId) {
      chatMessages.pop();
      chatMessages.push({ role: 'error', text: 'Не удалось создать задачу' });
      chatSending = false;
      renderChat();
      return;
    }

    let done = false;
    while (!done) {
      await new Promise(r => setTimeout(r, 1500));
      const status = await apiCall('/miniapp/ask/' + taskId);
      switch (status.status) {
        case 'done':
          chatMessages.pop();
          chatMessages.push({ role: 'bot', text: status.result || 'Пустой ответ' });
          done = true;
          break;
        case 'error':
          chatMessages.pop();
          chatMessages.push({ role: 'error', text: '❌ ' + (status.result || 'AI недоступен') });
          done = true;
          break;
        case 'pending':
        case 'running':
          break;
        default:
          chatMessages.pop();
          chatMessages.push({ role: 'error', text: '❌ Неизвестный статус: ' + status.status });
          done = true;
      }
    }
  } catch (e) {
    chatMessages.pop();
    chatMessages.push({ role: 'error', text: '❌ ' + e.message });
  }

  chatSending = false;
  renderChat();
}

const ALERT_TYPES = [
  { id: 'rsi', icon: '📊', name: 'RSI', desc: 'Перекупленность / перепроданность', tooltip: 'RSI ниже 30 = перепроданность (сигнал к покупке), выше 70 = перекупленность (сигнал к продаже). Анализируем на 15-минутных свечах.' },
  { id: 'ma_cross', icon: '📈', name: 'MA Cross', desc: 'Сигнал смены тренда', tooltip: 'Пересечение MA50 и MA200. «Золотой крест» (MA50 выше MA200) = бычий сигнал. «Смертельный крест» (MA50 ниже MA200) = медвежий сигнал.' },
  { id: 'volume_spike', icon: '🔥', name: 'Volume Spike', desc: 'Аномальный объём', tooltip: 'Всплеск объёма в 2+ раза выше среднего за 24ч. Указывает на повышенный интерес к активу, часто предшествует сильным движениям цены.' },
];

async function renderAlerts() {
  tgBackButton('hide');
  renderSub('<div class="card"><div class="spinner"></div></div>');
  try {
    const subs = await apiCall('/miniapp/subscriptions');
    const activeTypes = new Set();
    for (const s of subs) for (const at of s.alert_types) activeTypes.add(at);

    let html = '';

    // ─── Active subscriptions ───
    html += '<div class="card"><div class="card-title">🔔 Мои подписки</div>';
    if (!subs.length) {
      html += '<div class="empty-state">Нет активных подписок</div>';
    } else {
      for (const sub of subs) {
        for (const at of sub.alert_types) {
          const info = ALERT_TYPES.find(a => a.id === at) || { icon: '🔔', name: at, desc: '' };
          html += `
            <div class="alert-card">
              <span class="alert-card-icon">${info.icon}</span>
              <div class="alert-card-info">
                <div class="alert-card-name">${info.name}</div>
                <div class="alert-card-desc">${info.desc}</div>
              </div>
              <button class="btn-unsub" data-sub-id="${sub.id}" data-type="${at}" title="Отписаться">✕</button>
            </div>`;
        }
      }
    }
    html += '</div>';

    // ─── Add subscription ───
    html += '<div class="card"><div class="card-title">➕ Добавить подписку</div>';
    for (const a of ALERT_TYPES) {
      const isActive = activeTypes.has(a.id);
      html += `
        <div class="sub-card${isActive ? ' active' : ''}" data-alert-type="${a.id}">
          <span class="sub-card-icon">${a.icon}</span>
          <div class="sub-card-info">
            <div class="sub-card-name">${a.name}</div>
            <div class="sub-card-desc">${a.desc}</div>
          </div>
          <div class="sub-card-action">${isActive ? '✓' : '+'}</div>
          <div class="sub-card-tooltip">${a.tooltip}</div>
        </div>`;
    }
    html += '</div>';

    renderSub(html);

    // ─── Unsubscribe ───
    document.querySelectorAll('.btn-unsub').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        haptic('light');
        const subId = btn.dataset.subId;
        const alertType = btn.dataset.type;
        try {
          await apiCall('/miniapp/subscriptions/' + subId + '/' + alertType, { method: 'DELETE' });
          tgShowAlert('Подписка отменена');
          renderAlerts();
        } catch (e) {
          tgShowAlert('Ошибка: ' + e.message);
        }
      });
    });

    // ─── Subscribe + tooltip ───
    document.querySelectorAll('.sub-card:not(.active)').forEach(card => {
      card.addEventListener('click', async () => {
        const alertType = card.dataset.alertType;
        try {
          await apiCall('/miniapp/subscriptions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alert_type: alertType }),
          });
          tgShowAlert('✓ Подписка на ' + (ALERT_TYPES.find(a => a.id === alertType) || {}).name + ' оформлена');
          renderAlerts();
        } catch (e) {
          tgShowAlert('Ошибка: ' + e.message);
        }
      });
    });

    // ─── Tooltip on tap ───
    document.querySelectorAll('.sub-card').forEach(card => {
      card.addEventListener('contextmenu', (e) => { e.preventDefault(); });
      let tooltipTimer = null;
      card.addEventListener('touchstart', () => {
        tooltipTimer = setTimeout(() => {
          const tip = card.querySelector('.sub-card-tooltip');
          if (tip) tip.classList.add('visible');
        }, 400);
      });
      card.addEventListener('touchend', () => {
        clearTimeout(tooltipTimer);
        const tip = card.querySelector('.sub-card-tooltip');
        if (tip) tip.classList.remove('visible');
      });
      card.addEventListener('touchmove', () => {
        clearTimeout(tooltipTimer);
        const tip = card.querySelector('.sub-card-tooltip');
        if (tip) tip.classList.remove('visible');
      });
    });
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Chart ──────────────────────────────────────────────────────────
let chartInstance = null;
let chartResizeObserver = null;
let lastCandles = null;
let chartType = 'candlestick';
let chartTimeframe = '4h';
let chartOverlay = null;
let chartDataCache = {};

function destroyChart() {
  if (chartResizeObserver) {
    chartResizeObserver.disconnect();
    chartResizeObserver = null;
  }
  if (chartInstance) {
    chartInstance.remove();
    chartInstance = null;
  }
  lastCandles = null;
}

async function renderChart(overrideTf, overrideInd) {
  if (overrideTf && ['1h','4h','1d','1w'].includes(overrideTf)) {
    chartTimeframe = overrideTf;
    chartType = 'candlestick';
  }
  chartOverlay = overrideInd || null;
  tgBackButton('hide');
  renderSub(`
    <div class="chart-header">
      <div class="chart-header-main">
        <div class="chart-price" id="chart-price">—</div>
        <div class="chart-change" id="chart-change">—</div>
      </div>
      <div class="chart-pair">BTC/USD</div>
    </div>
    <div class="chart-controls">
      <div class="chart-timeframes">
        <button class="chart-btn" data-tf="1h">1H</button>
        <button class="chart-btn active" data-tf="4h">4H</button>
        <button class="chart-btn" data-tf="1d">1D</button>
        <button class="chart-btn" data-tf="1w">1W</button>
      </div>
      <div class="chart-types">
        <button class="chart-btn active" data-ct="candlestick">Свечи</button>
        <button class="chart-btn" data-ct="line">Линия</button>
        <button class="chart-btn" data-ct="area">Область</button>
        <button class="chart-btn" data-ct="metcalfe">📐</button>
      </div>
    </div>
    <div class="chart-container" id="chart-container">
      <div class="loading" style="padding:20px;"><div class="spinner"></div></div>
    </div>
    <div class="chart-info-bar" id="chart-info-bar"></div>
  `);

  document.querySelectorAll('[data-tf]').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('rigid');
      document.querySelectorAll('[data-tf]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      chartTimeframe = btn.dataset.tf;
      loadChartData();
    });
  });

  document.querySelectorAll('[data-ct]').forEach(btn => {
    btn.addEventListener('click', () => {
      haptic('medium');
      var ct = btn.dataset.ct;
      if (ct === 'metcalfe') {
        btn.classList.toggle('active');
        if (btn.classList.contains('active') && lastCandles) {
          _addChartOverlay(lastCandles, 'METCALFE');
        } else {
          if (window._metcalfeSeries) {
            window._metcalfeSeries.forEach(function(s) { try { chartInstance.removeSeries(s); } catch(e) {} });
            window._metcalfeSeries = [];
          }
        }
        return;
      }
      document.querySelectorAll('[data-ct]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      chartType = btn.dataset.ct;
      if (lastCandles) initChart(lastCandles);
    });
  });

  await loadChartData();
}

async function loadChartData() {
  const container = document.getElementById('chart-container');
  if (!container) return;

  if (!chartInstance) {
    container.innerHTML = '<div class="loading" style="padding:20px;"><div class="spinner"></div></div>';
  }

  try {
    const limit = chartTimeframe === '1h' ? 200 : chartTimeframe === '4h' ? 160 : 100;
    const cacheKey = `chart:${chartTimeframe}:${limit}`;
    let candles;
    const cached = chartDataCache[cacheKey];
    if (cached && (Date.now() - cached._ts < 60000)) {
      candles = cached.data;
    } else {
      const data = await apiCall(`/miniapp/chart?timeframe=${chartTimeframe}&limit=${limit}`);
      candles = data.candles;
      if (candles && candles.length) chartDataCache[cacheKey] = { data: candles, _ts: Date.now() };
    }
    if (!candles || !candles.length) {
      container.innerHTML = '<div class="card" style="text-align:center;padding:20px;color:var(--hint);">Нет данных</div>';
      return;
    }
    initChart(candles);
  } catch (e) {
    container.innerHTML = `<div class="card" style="text-align:center;padding:20px;color:var(--red);">❌ ${escapeHtml(e.message)}</div>`;
  }
}

function initChart(candles) {
  destroyChart();
  lastCandles = candles;

  const container = document.getElementById('chart-container');
  if (!container) return;

  container.innerHTML = '';

  const textColor = getComputedStyle(container).getPropertyValue('--text').trim() || '#d1d1d1';
  const chartHeight = Math.min(Math.max(Math.round(window.innerHeight * 0.55), 280), 500);
  chartInstance = LightweightCharts.createChart(container, {
    layout: {
      background: { type: 'solid', color: 'transparent' },
      textColor: textColor,
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,0.04)' },
      horzLines: { color: 'rgba(255,255,255,0.04)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {
        width: 1,
        color: 'rgba(36,129,204,0.25)',
        style: LightweightCharts.LineStyle.Dashed,
        labelBackgroundColor: 'rgba(36,129,204,0.7)',
      },
      horzLine: {
        width: 1,
        color: 'rgba(36,129,204,0.25)',
        style: LightweightCharts.LineStyle.Dashed,
        labelBackgroundColor: 'rgba(36,129,204,0.7)',
      },
    },
    rightPriceScale: {
      borderColor: 'rgba(255,255,255,0.08)',
    },
    timeScale: {
      borderColor: 'rgba(255,255,255,0.08)',
      timeVisible: true,
      secondsVisible: false,
    },
    width: container.clientWidth,
    height: chartHeight,
    handleScroll: true,
    handleScale: true,
  });

  let series, seriesData;
  switch (chartType) {
    case 'line':
      series = chartInstance.addLineSeries({
        color: '#2481cc',
        lineWidth: 2,
      });
      seriesData = candles.map(c => ({ time: c.time, value: c.close }));
      break;
    case 'area':
      series = chartInstance.addAreaSeries({
        topColor: 'rgba(36,129,204,0.4)',
        bottomColor: 'rgba(36,129,204,0.01)',
        lineColor: '#2481cc',
        lineWidth: 2,
      });
      seriesData = candles.map(c => ({ time: c.time, value: c.close }));
      break;
    default:
      series = chartInstance.addCandlestickSeries({
        upColor: '#00c853',
        downColor: '#ff1744',
        borderUpColor: '#00c853',
        borderDownColor: '#ff1744',
        wickUpColor: '#00c853',
        wickDownColor: '#ff1744',
      });
      seriesData = candles;
      break;
  }
  series.setData(seriesData);
  chartInstance.timeScale().fitContent();

  const priceEl = document.getElementById('chart-price');
  const changeEl = document.getElementById('chart-change');
  if (priceEl && changeEl && candles.length) {
    const last = candles[candles.length - 1];
    const first = candles[0];
    priceEl.textContent = fmtPrice(last.close);
    const changeVal = last.close - first.close;
    const changePct = (changeVal / first.close) * 100;
    const sign = changeVal >= 0 ? '+' : '';
    changeEl.textContent = `${sign}${changePct.toFixed(2)}%`;
    changeEl.className = 'chart-change ' + (changeVal >= 0 ? 'up' : 'down');
  }

  const volumeSeries = chartInstance.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  });
  chartInstance.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
  });
  volumeSeries.setData(
    candles.map(c => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(0,200,83,0.4)' : 'rgba(255,23,68,0.4)',
    }))
  );

  const lastCandle = lastCandles[lastCandles.length - 1];
  if (chartType === 'line' || chartType === 'area') {
    updateInfoBar({ value: lastCandle.close });
  } else {
    updateInfoBar(lastCandle);
  }

  chartInstance.subscribeCrosshairMove(param => {
    if (param.point && param.seriesData && param.seriesData.size) {
      const data = param.seriesData.get(series);
      if (data) updateInfoBar(data);
    } else if (lastCandles && lastCandles.length) {
      const last = lastCandles[lastCandles.length - 1];
      if (chartType === 'line' || chartType === 'area') {
        updateInfoBar({ value: last.close });
      } else {
        updateInfoBar(last);
      }
    }
  });

  chartInstance.timeScale().fitContent();

  if (chartOverlay && candles.length) {
    setTimeout(function() {
      try { _addChartOverlay(candles, chartOverlay); } catch(e) {}
    }, 200);
  }

  const handleResize = () => {
    if (chartInstance && container.clientWidth > 0) {
      chartInstance.applyOptions({
        width: container.clientWidth,
        height: Math.min(Math.max(Math.round(window.innerHeight * 0.55), 280), 500),
      });
    }
  };
  chartResizeObserver = new ResizeObserver(handleResize);
  chartResizeObserver.observe(container);
  window.addEventListener('resize', handleResize);
}

function _addChartOverlay(candles, indicator) {
  var closes = candles.map(function(c) { return c.close; });
  var times = candles.map(function(c) { return c.time; });
  var len = closes.length;

  if (indicator === 'MA50') {
    var ma = _calcMA(closes, 50);
    _addLineSeries(times, ma, '#ff9800', 1);
  } else if (indicator === 'MA200') {
    var ma = _calcMA(closes, 200);
    _addLineSeries(times, ma, '#e040fb', 1);
  } else if (indicator === 'BB') {
    var ma20 = _calcMA(closes, 20);
    var sd = _calcSD(closes, 20, ma20);
    var upper = ma20.map(function(v, i) { return sd[i] != null ? v + 2 * sd[i] : null; });
    var lower = ma20.map(function(v, i) { return sd[i] != null ? v - 2 * sd[i] : null; });
    _addLineSeries(times, upper, 'rgba(255,255,255,0.2)', 1);
    _addLineSeries(times, ma20, 'rgba(255,255,255,0.5)', 1);
    _addLineSeries(times, lower, 'rgba(255,255,255,0.2)', 1);
  } else if (indicator === 'RSI') {
    var rsi = _calcRSI(closes, 14);
    _addSubChart(times, rsi, 'RSI(14)', 0, 100, 30, 70);
  } else if (indicator === 'VOL') {
    _addSubChart(times, candles.map(function(c) { return c.volume; }), 'Volume', 0, null, null, null);
  } else if (indicator === 'METCALFE') {
    apiCall('/miniapp/metcalfe').then(function(data) {
      if (!data || !data.history || !data.history.length) return;
      var mtTimes = data.history.map(function(d) { return d.time; });
      if (window._metcalfeSeries) {
        window._metcalfeSeries.forEach(function(s) { try { chartInstance.removeSeries(s); } catch(e) {} });
      }
      window._metcalfeSeries = [];
      window._metcalfeSeries.push(_addLineSeries(mtTimes, data.history.map(function(d) { return d.upper; }), 'rgba(255,23,68,0.35)', 1));
      window._metcalfeSeries.push(_addLineSeries(mtTimes, data.history.map(function(d) { return d.metcalfe_price; }), 'rgba(255,193,7,0.7)', 2));
      window._metcalfeSeries.push(_addLineSeries(mtTimes, data.history.map(function(d) { return d.lower; }), 'rgba(0,200,83,0.35)', 1));
    }).catch(function(){});
  }
  chartOverlay = null;
}

function _calcMA(data, period) {
  var result = new Array(data.length).fill(null);
  for (var i = period - 1; i < data.length; i++) {
    var sum = 0;
    for (var j = 0; j < period; j++) sum += data[i - j];
    result[i] = sum / period;
  }
  return result;
}

function _calcSD(data, period, ma) {
  var result = new Array(data.length).fill(null);
  for (var i = period - 1; i < data.length; i++) {
    var sumSq = 0;
    for (var j = 0; j < period; j++) sumSq += Math.pow(data[i - j] - ma[i], 2);
    result[i] = Math.sqrt(sumSq / period);
  }
  return result;
}

function _calcRSI(prices, period) {
  var gains = [], losses = [], rsi = new Array(prices.length).fill(null);
  for (var i = 1; i < prices.length; i++) {
    var diff = prices[i] - prices[i - 1];
    gains.push(diff > 0 ? diff : 0);
    losses.push(diff < 0 ? -diff : 0);
  }
  var avgGain = 0, avgLoss = 0;
  for (var i = 0; i < period; i++) {
    avgGain += gains[i] || 0;
    avgLoss += losses[i] || 0;
  }
  avgGain /= period;
  avgLoss /= period;
  rsi[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (var i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    rsi[i + 1] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return rsi;
}

function _addLineSeries(times, values, color, width) {
  var data = [];
  for (var i = 0; i < times.length; i++) {
    if (values[i] != null) data.push({ time: times[i], value: values[i] });
  }
  var series = chartInstance.addLineSeries({ color: color, lineWidth: width, priceLineVisible: false });
  series.setData(data);
  return series;
}

function _addSubChart(times, values, label, min, max, lowLine, highLine) {
  var pane = chartInstance.addPane({ height: 120 });
  var data = [];
  for (var i = 0; i < times.length; i++) {
    if (values[i] != null) data.push({ time: times[i], value: values[i] });
  }
  chartInstance.addLineSeries({ color: '#2481cc', lineWidth: 2, pane: pane, priceLineVisible: false }).setData(data);
  if (min != null || max != null) {
    chartInstance.priceScale(pane).applyOptions({ autoScale: false });
    if (lowLine != null) {
      chartInstance.addLineSeries({ color: '#00c853', lineWidth: 1, pane: pane, priceLineVisible: false }).setData(times.map(function(t) { return { time: t, value: lowLine }; }));
    }
    if (highLine != null) {
      chartInstance.addLineSeries({ color: '#ff1744', lineWidth: 1, pane: pane, priceLineVisible: false }).setData(times.map(function(t) { return { time: t, value: highLine }; }));
    }
  }
}

function updateInfoBar(data) {
  const bar = document.getElementById('chart-info-bar');
  if (!bar || !data) return;
  if (chartType === 'line' || chartType === 'area') {
    const val = data.value;
    bar.innerHTML = `
      <div class="chart-info-item"><span class="chart-info-label">Price</span><span class="chart-info-value">${fmtChartPrice(val)}</span></div>`;
  } else {
    bar.innerHTML = `
      <div class="chart-info-item"><span class="chart-info-label">O</span><span class="chart-info-value">${fmtChartPrice(data.open)}</span></div>
      <div class="chart-info-item"><span class="chart-info-label">H</span><span class="chart-info-value">${fmtChartPrice(data.high)}</span></div>
      <div class="chart-info-item"><span class="chart-info-label">L</span><span class="chart-info-value">${fmtChartPrice(data.low)}</span></div>
      <div class="chart-info-item"><span class="chart-info-label">C</span><span class="chart-info-value">${fmtChartPrice(data.close)}</span></div>
      <div class="chart-info-item"><span class="chart-info-label">Vol</span><span class="chart-info-value">${fmtChartVolume(data.volume)}</span></div>`;
  }
}

function fmtChartPrice(v) {
  if (v == null) return '—';
  if (v >= 1000) return Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  if (v >= 1) return Number(v).toFixed(2);
  return Number(v).toFixed(6);
}

function fmtChartVolume(v) {
  if (v == null) return '—';
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return v.toFixed(0);
}

// ─── Indicators Page ────────────────────────────────────────────────
function renderIndicatorsPage(sub, chartTf, chartInd) {
  tgBackButton('hide');
  render('<div id="sub-content"></div>');
  renderTabs(`
    <button class="sub-tab${sub === 'chart' ? ' active' : ''}" data-icon="📊" data-label="График" onclick="navigate('indicators','chart')"></button>
    <button class="sub-tab${sub === 'price' ? ' active' : ''}" data-icon="💰" data-label="Цена" onclick="navigate('indicators','price')"></button>
    <button class="sub-tab${sub === 'predict' ? ' active' : ''}" data-icon="🔮" data-label="Прогноз" onclick="navigate('indicators','predict')"></button>
    <button class="sub-tab${sub === 'alerts' ? ' active' : ''}" data-icon="🔔" data-label="Подписки" onclick="navigate('indicators','alerts')"></button>
  `);
  if (sub === 'chart') renderChart(chartTf, chartInd);
  else if (sub === 'predict') startPoll('indicators_predict', renderPredict, 60000);
  else if (sub === 'alerts') renderAlerts();
  else startPoll('indicators_price', renderDashboard, 30000);
}

// ─── Mini App Page ──────────────────────────────────────────────────
function renderMiniAppPage(sub, param) {
  tgBackButton('hide');
  render('<div id="sub-content"></div>');
  renderTabs(`
    <button class="sub-tab${sub === 'lessons' ? ' active' : ''}" data-icon="📖" data-label="Обучение" onclick="navigate('miniapp','lessons')"></button>
    <button class="sub-tab${sub === 'games' ? ' active' : ''}" data-icon="🎮" data-label="Игры" onclick="navigate('miniapp','games')"></button>
    <button class="sub-tab${sub === 'arena' ? ' active' : ''}" data-icon="🏆" data-label="Арена" onclick="navigate('miniapp','arena')"></button>
  `);
  if (sub === 'games') {
    if (param === 'trading') renderTradingGame();
    else if (param === 'guess') renderGuessGame();
    else if (param === 'roulette') renderRouletteGame();
    else if (param === 'mining') renderMiningGame();
    else renderGameLobby();
  }
  else if (sub === 'arena') renderArena();
  else if (sub === 'lessons' && param) renderLesson(param);
  else renderLearnList();
}

// ─── News Page ──────────────────────────────────────────────────────
function renderNewsPage(sub) {
  tgBackButton('hide');
  render('<div id="sub-content"></div>');
  renderTabs(`
    <button class="sub-tab${sub === 'general' ? ' active' : ''}" data-icon="📰" data-label="Общие" onclick="navigate('news','general')"></button>
    <button class="sub-tab${sub === 'timothy' ? ' active' : ''}" data-icon="🐦" data-label="Timothy" onclick="navigate('news','timothy')"></button>
  `);
  if (sub === 'timothy') {
    renderTimothyNews();
  } else {
    startPoll('news', renderNews, 120000);
  }
}

async function renderTimothyNews() {
  renderSub('<div class="card"><div class="spinner"></div><p style="color:var(--hint);">Загрузка анализа Timothy Peterson...</p></div>');
  try {
    const data = await apiCall('/miniapp/news/timothy', {}, 120000);
    const text = data.text || 'Нет данных.';
    renderSub('<div class="card"><div class="card-title">🐦 Timothy Peterson</div><div style="white-space:pre-wrap;line-height:1.7;">' + escapeHtml(text) + '</div><div style="margin-top:12px;font-size:11px;color:var(--hint);">♻️ Кеш: 1 час</div></div>');
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Games Page ─────────────────────────────────────────────────────
const GAMES = [
  { slug: 'trading', icon: '🎯', title: 'Торговый симулятор', desc: 'Виртуальная торговля BTC. Стартовый баланс $10,000. Покупайте и продавайте по реальной цене.', btn: '▶ Играть' },
  { slug: 'roulette', icon: '🎰', title: 'Биткоин-рулетка', desc: 'Ставь ⭐ и крути! Множители до x5. Рискни и умножь.', btn: '🎰 Крутить' },
  { slug: 'guess', icon: '🔮', title: 'Угадай цену BTC', desc: 'Предскажи цену закрытия BTC на сегодня. Совпадёшь — получишь ⭐!', btn: '🔮 Играть' },
  { slug: 'mining', icon: '⛏️', title: 'Майнинг-ферма', desc: 'Тапай каждый час, добывай сатоши, копи на ⭐. Streak до x2!', btn: '⛏️ Копать' },
];

function renderGameLobby() {
  tgBackButton('hide');
  stopAllPolls();
  let html = '';
  for (const g of GAMES) {
    html += '<div class="game-lobby-card" onclick="window.location.hash=\'#miniapp/games/' + g.slug + '\'">';
    html += '<div class="game-lobby-icon">' + g.icon + '</div>';
    html += '<div class="game-lobby-body">';
    html += '<div class="game-lobby-title">' + g.title + '</div>';
    html += '<div class="game-lobby-desc">' + g.desc + '</div>';
    html += '<div class="game-lobby-btn">' + g.btn + '</div>';
    html += '</div></div>';
  }
  html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">Больше игр скоро появятся 🚀</div>';
  renderSub(html);
}

async function renderTradingGame() {
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#miniapp/games'; });
  stopAllPolls();
  renderSub('<div class="skeleton skeleton-hero"></div><div class="skeleton skeleton-block"></div>');
  try {
    const data = await apiCall('/miniapp/game/state');
    const pnlClass = data.total_pnl >= 0 ? 'up' : 'down';
    const pnlSign = data.total_pnl >= 0 ? '+' : '';

    let html = '<div class="game-hero"><div class="game-hero-value">$' + fmtPrice(data.total_value) + '</div><div class="game-hero-sub">Стоимость портфеля</div>';
    html += '<div class="game-metrics">';
    html += '<div class="game-metric"><span class="label">Кеш</span><span class="value">$' + fmtPrice(data.balance) + '</span></div>';
    html += '<div class="game-metric"><span class="label">P&amp;L</span><span class="value ' + pnlClass + '">' + pnlSign + '$' + fmtPrice(data.total_pnl) + '</span></div>';
    html += '<div class="game-metric"><span class="label">Сделок</span><span class="value">' + data.total_trades + '</span></div>';
    html += '<div class="game-metric"><span class="label">Win Rate</span><span class="value">' + data.win_rate + '%</span></div>';
    html += '</div></div>';

    html += '<div class="card"><div class="card-title">BTC/USD</div>';
    html += '<div class="game-price">$' + (data.btc_price ? data.btc_price.toLocaleString('en-US') : '—') + '</div>';

    if (data.positions && data.positions.length > 0) {
      const pos = data.positions[0];
      const posPnlClass = pos.pnl >= 0 ? 'up' : 'down';
      html += '<div class="game-position"><span class="label">Позиция: ' + pos.side + ' ' + pos.quantity + ' BTC @ $' + fmtPrice(pos.entry_price) + '</span>';
      html += '<span class="value ' + posPnlClass + '">' + (pos.pnl >= 0 ? '+' : '') + '$' + fmtPrice(pos.pnl) + ' (' + pos.pnl_pct + '%)</span></div>';
      html += '<button class="game-btn sell" id="btn-sell">Продать BTC</button>';
    } else {
      html += '<div style="display:flex;gap:8px;margin-top:12px;">';
      html += '<input type="number" id="buy-amount" class="game-input" placeholder="Сумма в USD" min="10" max="' + Math.floor(data.balance) + '" value="100">';
      html += '<button class="game-btn buy" id="btn-buy">Купить BTC</button>';
      html += '</div>';
    }
    html += '</div>';

    if (data.recent_trades && data.recent_trades.length > 0) {
      html += '<div class="card"><div class="card-title">История сделок</div>';
      for (const t of data.recent_trades) {
        const tClass = t.pnl >= 0 ? 'up' : 'down';
        html += '<div class="game-trade"><span>' + t.side + ' ' + t.quantity + ' BTC</span><span class="value ' + tClass + '">' + (t.pnl >= 0 ? '+' : '') + '$' + fmtPrice(t.pnl) + '</span></div>';
      }
      html += '</div>';
    }

    html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">♻️ Комиссия 0.1% &middot; Мин. сделка $10</div>';
    renderSub(html);

    const btnBuy = document.getElementById('btn-buy');
    if (btnBuy) {
      btnBuy.addEventListener('click', async () => {
        haptic('heavy');
        const amt = parseFloat(document.getElementById('buy-amount').value);
        if (!amt || amt < 10) { tgShowAlert('Минимальная сумма: $10'); return; }
        btnBuy.disabled = true; btnBuy.textContent = '...';
        try {
          const res = await apiCall('/miniapp/game/buy', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({usdt_amount: amt}) });
          tgShowAlert('Куплено ' + res.quantity + ' BTC за $' + fmtPrice(res.notional));
          renderTradingGame();
        } catch (e) { tgShowAlert(e.message); btnBuy.disabled = false; btnBuy.textContent = 'Купить BTC'; }
      });
    }

    const btnSell = document.getElementById('btn-sell');
    if (btnSell) {
      btnSell.addEventListener('click', async () => {
        haptic('heavy');
        btnSell.disabled = true; btnSell.textContent = '...';
        try {
          const res = await apiCall('/miniapp/game/sell', { method: 'POST' });
          haptic(res.is_win ? 'success' : 'warning');
          const emoji = res.is_win ? '🎉' : '📉';
          tgShowAlert(emoji + ' ' + (res.pnl >= 0 ? '+' : '') + '$' + fmtPrice(res.pnl) + ' (' + res.pnl_pct + '%)');
          renderTradingGame();
        } catch (e) { tgShowAlert(e.message); btnSell.disabled = false; btnSell.textContent = 'Продать BTC'; }
      });
    }
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Guess Game ─────────────────────────────────────────────────────
async function renderGuessGame() {
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#miniapp/games'; });
  stopAllPolls();
  renderSub('<div class="skeleton skeleton-block"></div>');
  try {
    const state = await apiCall('/miniapp/game/guess/state');
    const price = state.btc_price;
    let html = '<div class="game-hero"><div class="game-hero-value">🔮 Угадай цену</div><div class="game-hero-sub">BTC/USD: $' + (price ? price.toLocaleString('en-US') : '—') + '</div></div>';

    html += '<div class="card" style="text-align:center;"><div style="font-size:14px;color:var(--hint);">Твои звёзды</div><div style="font-size:32px;font-weight:700;">' + state.stars + ' ⭐</div></div>';

    html += '<div class="card" style="font-size:12px;line-height:1.8;"><div class="card-title">📋 Правила</div>▪ Каждый день ты можешь 1 раз предсказать цену BTC<br>▪ Цена фиксируется в 00:00 UTC<br>▪ Если твой прогноз отличается от реальной цены менее чем на 0.5% — ты выиграл!<br>▪ Приз: <b>+1 ⭐</b> за каждую победу<br>▪ Максимум 1 попытка в день</div>';

    if (price) {
      var curGuess = state.today_guess ? state.today_guess.guess_price.toLocaleString('en-US') : '';
      var label = state.today_guess ? 'Изменить прогноз' : 'Ваш прогноз на сегодня';
      html += '<div class="card"><div class="card-title">' + label + '</div>';
      html += '<div style="display:flex;gap:8px;margin-top:12px;">';
      html += '<input type="number" id="guess-input" class="game-input" placeholder="Цена BTC в $" min="1" step="100" value="' + curGuess.replace(/,/g,'') + '">';
      html += '<button class="game-btn buy" id="btn-guess">🔮 Отправить</button>';
      html += '</div></div>';
    } else {
      html += '<div class="card" style="text-align:center;padding:20px;color:var(--hint);">⏳ Цена BTC загружается...</div>';
    }

    if (state.history && state.history.length > 0) {
      html += '<div class="card"><div class="card-title">📜 История</div>';
      for (const h of state.history) {
        const cls = h.won ? 'up' : 'down';
        const icon = h.won ? '✅' : '❌';
        html += '<div class="game-trade"><span>' + icon + ' $' + h.guess_price.toLocaleString('en-US') + '</span><span class="value ' + cls + '">' + (h.won ? '+' + h.stars_won + '⭐' : (h.deviation_pct != null ? h.deviation_pct.toFixed(1) + '%' : '⏳')) + '</span></div>';
      }
      html += '</div>';
    }
    renderSub(html);

    const btnGuess = document.getElementById('btn-guess');
    if (btnGuess) {
      btnGuess.addEventListener('click', async () => {
        haptic('heavy');
        const val = parseFloat(document.getElementById('guess-input').value);
        if (!val || val <= 0) { tgShowAlert('Введите корректную цену'); return; }
        btnGuess.disabled = true; btnGuess.textContent = '...';
        try {
          await apiCall('/miniapp/game/guess', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({guess_price: val}) });
          tgShowAlert('✅ Прогноз принят! Результат завтра в 00:05 UTC');
          renderGuessGame();
        } catch (e) { tgShowAlert(e.message); btnGuess.disabled = false; btnGuess.textContent = '🔮 Отправить'; }
      });
    }
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Roulette Game ──────────────────────────────────────────────────
async function renderRouletteGame() {
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#miniapp/games'; });
  stopAllPolls();
  renderSub('<div class="skeleton skeleton-block"></div>');
  try {
    const state = await apiCall('/miniapp/game/roulette/state');
    let html = '<div class="game-hero"><div class="game-hero-value">🎰 Биткоин-рулетка</div><div class="game-hero-sub">⭐ Баланс: ' + state.stars + '</div></div>';

    html += '<div class="card"><div class="card-title">📋 Правила</div>';
    html += '<div style="font-size:12px;line-height:1.8;">▪ Выбери ставку 1–10 ⭐ нажатием на звезду<br>▪ ⚡ Кулдаун 3 секунды между спинами<br>▪ Множители: x0 (40%), x1.5 (30%), x2 (20%), x3 (9%), x5 (1%)</div></div>';

    html += '<div class="card"><div class="card-title">🎰 Сделать ставку</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-top:8px;" id="star-bets">';
    for (let i = 1; i <= 10; i++) {
      html += '<div class="star-btn" data-bet="' + i + '" style="width:44px;height:44px;border-radius:50%;background:var(--bg-card);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:18px;cursor:pointer;transition:all 0.1s;">' + i + '⭐</div>';
    }
    html += '</div><div id="spin-result" style="text-align:center;margin-top:12px;min-height:24px;font-size:14px;"></div></div>';

    if (state.history && state.history.length > 0) {
      html += '<div class="card"><div class="card-title">📜 История (последние 10)</div>';
      for (const h of state.history) {
        const icon = h.net > 0 ? '🟢' : '🔴';
        html += '<div class="game-trade"><span>' + icon + ' ⭐' + h.bet + ' ×' + h.multiplier + '</span><span class="value ' + (h.net > 0 ? 'up' : 'down') + '">' + h.win + '⭐ <span style="font-size:11px;color:var(--hint);">' + (h.net > 0 ? '+' : '') + h.net + '⭐</span></span></div>';
      }
      html += '</div>';
    }

    renderSub(html);

    document.querySelectorAll('.star-btn').forEach(function(el) {
      el.addEventListener('click', async function() {
        if (el._loading) return;
        el._loading = true;
        el.style.transform = 'scale(1.2)';
        haptic('heavy');
        const bet = parseInt(el.dataset.bet);
        const resultDiv = document.getElementById('spin-result');
        resultDiv.textContent = '⏳ Крутим...';
        try {
          const res = await apiCall('/miniapp/game/roulette', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({bet: bet}) });
          const r = res.result;
          if (r.won) {
            resultDiv.innerHTML = r.emoji + ' ×' + r.multiplier + '! ⭐' + r.bet + '×' + r.multiplier + '=<b>' + r.win + '⭐</b> <span style="font-size:12px;color:var(--hint);">(+' + r.net + '⭐)</span>';
            haptic('success');
          } else {
            resultDiv.innerHTML = '😢 ⭐' + r.bet + '×0=0⭐ <span style="font-size:12px;color:var(--hint);">-'+r.bet+'⭐</span>';
            haptic('warning');
          }
          setTimeout(function() { renderRouletteGame(); }, 1500);
        } catch (e) {
          resultDiv.textContent = '❌ ' + e.message;
          el._loading = false;
          el.style.transform = '';
        }
      });
    });
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Mining Game ────────────────────────────────────────────────────
async function renderMiningGame() {
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#miniapp/games'; });
  stopAllPolls();
  renderSub('<div class="skeleton skeleton-block"></div>');
  try {
    const state = await apiCall('/miniapp/game/mining/state');
    const canMine = state.can_mine;
    let html = '<div class="game-hero"><div class="game-hero-value">⛏️ Майнинг-ферма</div><div class="game-hero-sub">' + state.total_sats + ' сатоши · ' + state.stars + ' ⭐</div></div>';

    html += '<div class="card"><div class="card-title">Добыча</div>';
    html += '<div class="game-metrics">';
    html += '<div class="game-metric"><span class="label">Сатоши</span><span class="value">' + state.total_sats + '</span></div>';
    html += '<div class="game-metric"><span class="label">Streak</span><span class="value">' + state.streak + '</span></div>';
    html += '<div class="game-metric"><span class="label">Множитель</span><span class="value">×' + state.streak_mult + '</span></div>';
    html += '<div class="game-metric"><span class="label">Рефералы</span><span class="value">×' + state.ref_mult + '</span></div>';
    html += '</div>';

    if (canMine) {
      html += '<button class="game-btn buy" id="btn-mine" style="width:100%;">⛏️ Копать!</button>';
    } else {
      html += '<div style="text-align:center;padding:16px;color:var(--orange);font-size:18px;font-variant-numeric:tabular-nums;" id="mine-cooldown">⏳ ' + formatTime(state.cooldown_sec) + '</div>';
    }
    html += '</div>';

    html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">⚡ 1 клик/30 мин · Streak +5% (макс ×2) · Рефералы +10% каждый · 1000 сатоши = 1 ⭐</div>';
    renderSub(html);

    if (!canMine && state.cooldown_sec > 0) {
      const startTs = Date.now();
      const startSec = state.cooldown_sec;
      const cdTimer = setInterval(function() {
        const el = document.getElementById('mine-cooldown');
        if (!el) { clearInterval(cdTimer); return; }
        const elapsed = Math.floor((Date.now() - startTs) / 1000);
        const left = Math.max(0, startSec - elapsed);
        if (left <= 0) { clearInterval(cdTimer); renderMiningGame(); return; }
        el.textContent = '⏳ ' + formatTime(left);
      }, 1000);
    }

    const btnMine = document.getElementById('btn-mine');
    if (btnMine) {
      btnMine.addEventListener('click', async () => {
        haptic('heavy');
        btnMine.disabled = true; btnMine.textContent = '⏳';
        try {
          const res = await apiCall('/miniapp/game/mining/click', { method: 'POST' });
          tgShowAlert('⛏️ +' + res.earned + ' сатоши! Streak: ' + res.streak + ' (×' + res.streak_mult + ')');
          haptic('success');
          renderMiningGame();
        } catch (e) { tgShowAlert(e.message); btnMine.disabled = false; btnMine.textContent = '⛏️ Копать!'; }
      });
    }
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// ─── Arena Page ────────────────────────────────────────────────────
async function renderArena() {
  stopAllPolls();
  renderSub('<div class="skeleton skeleton-block"></div><div class="skeleton skeleton-block"></div>');
  try {
    var league = await apiCall('/miniapp/game/league');
    var tourney = await apiCall('/miniapp/game/tournament');
    var pnl = await apiCall('/miniapp/game/pnl-card');
    var refs = await apiCall('/miniapp/referral/stats');

    var html = '';

    // League card
    html += '<div class="arena-section"><div class="arena-section-title">🏆 ' + league.league_name + ' Лига</div>';
    html += '<div class="league-banner" style="background:linear-gradient(135deg,' + league.league_color + '22,' + league.league_color + '08);border-color:' + league.league_color + '">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
    html += '<div><div style="font-size:24px;font-weight:700;">' + league.league_name + '</div>';
    html += '<div style="font-size:12px;color:var(--hint);">P&L: ' + (league.total_pnl >= 0 ? '+' : '') + '$' + fmtPrice(league.total_pnl) + ' | Win Rate: ' + pnl.win_rate + '%</div></div>';
    html += '<div style="font-size:40px;">' + (league.league === 'platinum' ? '👑' : league.league === 'gold' ? '🥇' : league.league === 'silver' ? '🥈' : '🥉') + '</div>';
    html += '</div>';
    if (league.next_league) {
      html += '<div class="league-progress"><div class="league-progress-fill" style="width:' + league.progress_pct + '%;background:' + league.league_color + '"></div></div>';
      html += '<div style="font-size:11px;color:var(--hint);margin-top:4px;">' + league.progress_pct.toFixed(0) + '% до ' + league.next_league_name + ' (нужно $' + fmtPrice(league.next_threshold) + ')</div>';
    }
    html += '</div></div>';

    // Tournament card
    html += '<div class="arena-section"><div class="arena-section-title">⚔️ Турнир</div>';
    if (tourney.active) {
      var endsAt = new Date(tourney.ends_at);
      var now = new Date();
      var remaining = Math.max(0, Math.floor((endsAt - now) / 1000));
      var days = Math.floor(remaining / 86400);
      var hours = Math.floor((remaining % 86400) / 3600);
      var timeStr = days + 'д ' + hours + 'ч';
      html += '<div class="tournament-card">';
      html += '<div style="font-size:16px;font-weight:700;">' + tourney.name + '</div>';
      html += '<div style="font-size:12px;color:var(--hint);margin:4px 0;">⏳ ' + timeStr + ' до конца | 🏆 ' + tourney.prize_pool_stars + ' ⭐ | 👥 ' + tourney.participants + ' участников</div>';
      if (tourney.joined) {
        html += '<div style="font-size:13px;color:var(--green);margin:6px 0;">✅ Вы участвуете' + (tourney.user_rank ? ' · Позиция: #' + tourney.user_rank : '') + '</div>';
      } else {
        html += '<button class="upgrade-btn" data-action="joinTournament" data-id="' + tourney.id + '">⚔️ Вступить</button>';
      }
      if (tourney.leaderboard && tourney.leaderboard.length) {
        html += '<div style="margin-top:8px;">';
        for (var i = 0; i < Math.min(5, tourney.leaderboard.length); i++) {
          var lb = tourney.leaderboard[i];
          var medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : (i + 1);
          html += '<div class="referral-row"><span>' + medal + ' ' + (lb.username || 'User ' + lb.user_id) + '</span><span style="color:' + (lb.pnl_delta >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (lb.pnl_delta >= 0 ? '+' : '') + '$' + fmtPrice(lb.pnl_delta) + '</span></div>';
        }
        html += '</div>';
      }
      html += '</div>';
    } else if (tourney.upcoming) {
      html += '<div class="tournament-card">';
      html += '<div style="font-size:16px;font-weight:700;">' + tourney.upcoming.name + '</div>';
      html += '<div style="font-size:12px;color:var(--hint);margin:4px 0;">📅 Старт: ' + new Date(tourney.upcoming.starts_at).toLocaleDateString() + ' | 🏆 ' + tourney.upcoming.prize_pool_stars + ' ⭐</div>';
      html += '</div>';
    } else {
      html += '<div class="card" style="text-align:center;color:var(--hint);">Нет активных турниров</div>';
    }
    html += '</div>';

    // PnL card
    html += '<div class="arena-section"><div class="arena-section-title">📤 P&L Карточка</div>';
    html += '<div class="card">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
    html += '<div><div style="font-weight:700;">$' + fmtPrice(pnl.balance) + '</div><div style="font-size:11px;color:var(--hint);">Баланс</div></div>';
    html += '<div><div style="font-weight:700;color:' + (pnl.total_pnl >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (pnl.total_pnl >= 0 ? '+' : '') + '$' + fmtPrice(pnl.total_pnl) + '</div><div style="font-size:11px;color:var(--hint);">P&L</div></div>';
    html += '<div><div style="font-weight:700;">' + pnl.win_rate + '%</div><div style="font-size:11px;color:var(--hint);">Win Rate</div></div>';
    html += '</div>';
    html += '<button class="upgrade-btn" style="width:100%;margin-top:10px;" data-action="sharePnl">📤 Поделиться в чат</button>';
    html += '</div></div>';

    // Referrals
    html += '<div class="arena-section"><div class="arena-section-title">👥 Рефералы</div>';
    html += '<div class="card">';
    html += '<div style="display:flex;justify-content:space-between;margin-bottom:8px;">';
    html += '<span>Приглашено: <b>' + refs.count + '</b></span><span>Бонусов: <b>+$' + refs.total_bonus.toFixed(0) + '</b></span>';
    html += '</div>';
    html += '<div class="payment-address" data-action="copyText" data-copy="' + refs.ref_link + '" style="font-size:10px;text-align:center;cursor:pointer;">' + refs.ref_link + ' <span style="color:var(--btn);">(копировать)</span></div>';
    for (var j = 0; j < Math.min(5, refs.referrals.length); j++) {
      var ref = refs.referrals[j];
      html += '<div class="referral-row"><span>👤 ' + (ref.username || 'User ' + ref.referred_id) + '</span><span style="color:var(--green);">+$' + ref.bonus_usd + ' ' + (ref.bonus_credited ? '✅' : '⏳') + '</span></div>';
    }
    html += '</div></div>';

    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

// Add delegated handlers for arena actions
(function() {
  var origHandler = document._arenaHandler;
  if (!origHandler) {
    document._arenaHandler = true;
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('[data-action]');
      if (!btn) return;
      var action = btn.getAttribute('data-action');
      if (action === 'joinTournament') {
        var tid = parseInt(btn.getAttribute('data-id'));
        joinTournament(tid);
      } else if (action === 'sharePnl') {
        sharePnlCard();
      } else if (action === 'copyText') {
        copyToClipboard(btn.getAttribute('data-copy') || '');
      }
    });
  }
})();

async function joinTournament(tournamentId) {
  haptic('heavy');
  try {
    await apiCall('/miniapp/game/tournament/' + tournamentId + '/join', { method: 'POST' });
    tgShowAlert('✅ Вы вступили в турнир!');
    renderArena();
  } catch(e) { tgShowAlert('Ошибка: ' + e.message); }
}

function sharePnlCard() {
  haptic('medium');
  apiCall('/miniapp/game/pnl-card').then(function(d) {
    var text = '🏆 BTC Monitor · ' + d.league.league_name + ' Лига\n';
    text += '💰 Баланс: $' + fmtPrice(d.balance) + '\n';
    text += '📈 P&L: ' + (d.total_pnl >= 0 ? '+' : '') + '$' + fmtPrice(d.total_pnl) + '\n';
    text += '🎯 Win Rate: ' + d.win_rate + '%\n';
    text += '⭐ Звёзд: ' + d.stars + '\n';
    text += '🎮 Торгуй вместе со мной: ' + window.location.origin + '/miniapp';
    try {
      Telegram.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(text));
    } catch(_) {
      copyToClipboard(text);
      tgShowAlert('Текст скопирован. Отправь в любой чат!');
    }
  }).catch(function(e) { tgShowAlert('Ошибка: ' + e.message); });
}

// ─── Upgrade / PRO Page ────────────────────────────────────────────
var paymentMethod = 'stars';
var paymentInterval = null;

async function renderUpgradePage() {
  stopAllPolls();
  renderTabs('');
  if (paymentInterval) { clearInterval(paymentInterval); paymentInterval = null; }
  renderSub('<div class="skeleton skeleton-hero"></div><div class="skeleton skeleton-block"></div>');
  try {
    var data = await apiCall('/miniapp/subscription/status');
    var tier = data.tier || 'free';
    var isPro = tier === 'pro';
    var isProPlus = tier === 'pro_plus';

    var html = '<div class="upgrade-hero">';
    html += '<div class="upgrade-tier-badge ' + tier + '">' + tier.toUpperCase() + '</div>';
    html += '<div class="upgrade-hero-title">Ваша подписка</div>';
    if (data.trial_until) html += '<div class="upgrade-expiry">🕐 Триал до: ' + data.trial_until + '</div>';
    if (data.pro_until) html += '<div class="upgrade-expiry">💎 PRO до: ' + data.pro_until + '</div>';
    if (data.pro_plus_until) html += '<div class="upgrade-expiry">👑 PRO+ до: ' + data.pro_plus_until + '</div>';
    html += '</div>';

    html += '<div class="payment-method-selector">';
    html += '<button class="payment-method' + (paymentMethod === 'stars' ? ' active' : '') + '" data-method="stars" data-action="switchPayment" data-tier="stars">💎 Stars</button>';
    html += '<button class="payment-method' + (paymentMethod === 'ton' ? ' active' : '') + '" data-method="ton" data-action="switchPayment" data-tier="ton">💠 TON</button>';
    html += '</div>';

    if (paymentMethod === 'ton') {
      var walletData = { linked: false };
      try { walletData = await apiCall('/crypto/wallet/status'); } catch(_) {}
      if (walletData.linked) {
        var shortAddr = walletData.wallet_address.substring(0, 8) + '...' + walletData.wallet_address.slice(-6);
        html += '<div class="wallet-chip"><span style="width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;"></span> ' + shortAddr + '</div>';
        html += '<button class="upgrade-btn" data-action="unlinkWallet">🔌 Отключить</button>';
        window._tonWallet = walletData.wallet_address;
      } else {
        html += '<div class="connect-wallet-wrap"><input class="wallet-input" id="ton-wallet-input" placeholder="Вставьте адрес TON кошелька..."><button class="upgrade-btn" data-action="linkWallet">🔌 Подключить</button></div>';
        html += '<div style="font-size:10px;color:var(--hint);margin-top:4px;">Адрес начинается с UQ...</div>';
      }
    }

    html += '<div class="upgrade-cards">';

    html += '<div class="upgrade-card' + (tier === 'free' ? ' current' : '') + '">';
    html += '<div class="upgrade-card-header">FREE</div>';
    html += '<div class="upgrade-card-price">0</div>';
    html += '<ul class="upgrade-features">';
    html += '<li>📊 Дашборд и график</li><li>📰 Новости с тональностью</li><li>📖 Уроки</li><li>🤖 3 AI вопроса/день</li><li>📈 3 сделки/день</li>';
    html += '</ul>';
    if (tier === 'free') html += '<div class="upgrade-current-badge">Текущий</div>';
    html += '</div>';

    html += '<div class="upgrade-card' + (isPro ? ' current' : '') + '">';
    html += '<div class="upgrade-card-header pro">PRO</div>';
    html += '<div class="upgrade-card-price">' + (paymentMethod === 'ton' ? '0.5 TON' : '50 ⭐') + '<span style="font-size:11px;font-weight:400;">/мес</span></div>';
    html += '<ul class="upgrade-features">';
    html += '<li>✅ Всё из FREE</li><li>🤖 AI без лимитов</li><li>📈 Сделки без лимитов</li><li>🔔 PRO-алерты</li><li>🏆 Полный лидерборд</li>';
    html += '</ul>';
    if (isPro) html += '<div class="upgrade-current-badge">Активна</div>';
    else if (!isProPlus) {
      if (paymentMethod === 'ton') {
        html += '<button class="upgrade-btn" data-action="cryptoPay" data-tier="pro">Купить за 0.5 TON</button>';
      } else {
        html += '<button class="upgrade-btn" data-action="subscribe" data-tier="pro">Подписаться за 50 ⭐</button>';
      }
    }
    html += '</div>';

    html += '<div class="upgrade-card' + (isProPlus ? ' current' : '') + '">';
    html += '<div class="upgrade-card-header pro-plus">PRO+</div>';
    html += '<div class="upgrade-card-price">' + (paymentMethod === 'ton' ? '1 TON' : '100 ⭐') + '<span style="font-size:11px;font-weight:400;">/мес</span></div>';
    html += '<ul class="upgrade-features">';
    html += '<li>✅ Всё из PRO</li><li>🎤 Голосовой ввод</li><li>⚡ Проактивные алерты</li><li>🎯 Confidence Score ML</li><li>📊 Персональный дашборд</li>';
    html += '</ul>';
    if (isProPlus) html += '<div class="upgrade-current-badge">Активна</div>';
    else {
      if (paymentMethod === 'ton') {
        html += '<button class="upgrade-btn plus" data-action="cryptoPay" data-tier="pro_plus">Купить за 1 TON</button>';
      } else {
        html += '<button class="upgrade-btn plus" data-action="subscribe" data-tier="pro_plus">Подписаться за 100 ⭐</button>';
      }
    }
    html += '</div>';

    html += '</div>';
    if (paymentMethod === 'stars') {
      html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;margin-top:8px;">💡 После оплаты звёздами подписка активируется автоматически</div>';
    } else {
      html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;margin-top:8px;">💠 Оплата напрямую с TON кошелька. Транзакция проверяется автоматически.</div>';
    }

    renderSub(html);
  } catch (e) {
    renderSub('<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">' + escapeHtml(e.message) + '</div></div>');
  }
}

function switchPaymentMethod(method) {
  paymentMethod = method;
  if (paymentInterval) { clearInterval(paymentInterval); paymentInterval = null; }
  renderUpgradePage();
}

async function linkTonWallet() {
  var input = document.getElementById('ton-wallet-input');
  var addr = (input && input.value || '').trim();
  if (!addr) { tgShowAlert('Введите адрес кошелька'); return; }
  if (!addr.startsWith('UQ') && !addr.startsWith('EQ')) { tgShowAlert('Адрес должен начинаться с UQ или EQ'); return; }
  try {
    await apiCall('/crypto/wallet/link', { method: 'POST', body: JSON.stringify({ wallet_address: addr }), headers: { 'Content-Type': 'application/json' } });
    window._tonWallet = addr;
    renderUpgradePage();
  } catch(e) { tgShowAlert('Ошибка: ' + e.message); }
}

async function unlinkTonWallet() {
  haptic('heavy');
  try {
    await apiCall('/crypto/wallet/unlink', { method: 'POST' });
    window._tonWallet = null;
    renderUpgradePage();
  } catch(e) { tgShowAlert('Ошибка: ' + e.message); }
}

var _paymentInProgress = false;

async function createCryptoPayment(tier) {
  haptic('heavy');
  if (_paymentInProgress) { tgShowAlert('Платёж уже создаётся...'); return; }
  var wallet = window._tonWallet || '';
  if (!wallet) { tgShowAlert('Сначала подключите TON кошелёк'); return; }
  _paymentInProgress = true;
  var btn = document.querySelector('.upgrade-btn[data-action="cryptoPay"][data-tier="' + tier + '"]');
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; btn.textContent = '⏳ Создание...'; }
  try {
    var pay = await apiCall('/crypto/payment/create', {
      method: 'POST',
      body: JSON.stringify({ tier: tier, wallet_address: wallet }),
      headers: { 'Content-Type': 'application/json' }
    });
    window._currentPaymentId = pay.payment_id;
    var html = '<div class="card" id="crypto-pay-card"><div class="card-title">💠 Оплата ' + pay.amount_ton + ' TON</div>';
    html += '<div style="margin:8px 0;font-size:11px;color:var(--hint);">Отправьте точно <b>' + pay.amount_ton + ' TON</b> на адрес:</div>';
    html += '<div class="payment-address" data-action="copyAddress" data-address="' + pay.recipient_wallet + '" style="cursor:pointer;">' + pay.recipient_wallet + ' <span style="color:var(--btn);font-size:10px;">(копировать)</span></div>';
    html += '<div style="font-size:11px;color:var(--hint);">Комментарий: <b>' + pay.comment + '</b></div>';
    html += '<div style="margin-top:12px;font-size:11px;color:var(--hint);text-align:center;">Открой любой TON-кошелёк, отправь <b>' + pay.amount_ton + ' TON</b> на адрес выше с комментарием</div>';
    html += '<button class="upgrade-btn" style="margin-top:8px;background:var(--green);" data-action="verifyPayment" data-payment-id="' + pay.payment_id + '">✅ Я оплатил</button>';
    html += '<div style="margin-top:8px;font-size:11px;color:var(--hint);text-align:center;" id="pay-status">Ожидание платежа...</div>';
    html += '</div>';

    var cards = document.querySelector('.upgrade-cards');
    if (cards) cards.insertAdjacentHTML('afterend', html);

    paymentInterval = setInterval(function() {
      apiCall('/crypto/payment/' + pay.payment_id).then(function(s) {
        if (s.status === 'paid') {
          clearInterval(paymentInterval);
          var el = document.getElementById('pay-status');
          if (el) el.innerHTML = '✅ Оплата получена! Обновляем...';
          setTimeout(function() { renderUpgradePage(); }, 1500);
        }
      }).catch(function(){});
    }, 5000);
  } catch(e) { tgShowAlert('Ошибка: ' + e.message); }
  _paymentInProgress = false;
  if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = tier === 'pro_plus' ? 'Купить за 1 TON' : 'Купить за 0.5 TON'; }
}

async function verifyAndActivate(paymentId) {
  try {
    var result = await apiCall('/crypto/payment/' + paymentId + '/verify', {
      method: 'POST',
      body: JSON.stringify({}),
      headers: { 'Content-Type': 'application/json' }
    });
    if (result.status === 'paid') {
      tgShowAlert('✅ Оплата подтверждена! PRO активирован.');
      if (paymentInterval) { clearInterval(paymentInterval); paymentInterval = null; }
      renderUpgradePage();
    } else {
      tgShowAlert('⏳ Платёж пока не найден. Попробуйте через минуту.');
    }
  } catch(e) { tgShowAlert('Ошибка: ' + e.message); }
}

function copyToClipboard(text) {
  haptic('medium');
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(function() {
      tgShowAlert('Адрес скопирован!');
    }).catch(function(){});
  } else {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    tgShowAlert('Адрес скопирован!');
  }
}

function subscribeTier(tier) {
  haptic('heavy');
  apiCall('/miniapp/subscribe', {
    method: 'POST',
    body: JSON.stringify({ tier: tier }),
    headers: { 'Content-Type': 'application/json' },
  }).then(function(resp) {
    if (resp.status === 'sent') {
      tgShowAlert('💎 Счёт отправлен в чат с ботом. Оплатите Telegram Stars для активации.');
    }
  }).catch(function(e) {
    tgShowAlert('Ошибка: ' + e.message);
  });
}

function routePage() {
  const { page, sub, param, chartTf, chartInd } = parseHash();
  stopAllPolls();
  destroyChart();

  if (!initData) {
    render('<div class="card" style="text-align:center;padding:40px;"><div style="font-size:40px;margin-bottom:16px;">📊</div><div style="font-weight:600;font-size:18px;">BTC Monitor</div><div style="margin-top:8px;color:var(--hint);">Открой это приложение через Telegram Bot<br>👇<br>📊 BTC Dashboard</div></div>');
    return;
  }

  switch (page) {
    case 'indicators':
      setActiveNav('indicators');
      renderIndicatorsPage(sub, chartTf, chartInd);
      break;
    case 'chat':
      renderChat();
      break;
    case 'miniapp':
      setActiveNav('miniapp');
      renderMiniAppPage(sub, param);
      break;
    case 'news':
      setActiveNav('news');
      renderNewsPage(sub);
      break;
    case 'upgrade':
      setActiveNav('upgrade');
      renderUpgradePage();
      break;
    default:
      setActiveNav('indicators');
      renderIndicatorsPage('price');
  }
}

window.addEventListener('hashchange', routePage);

function toggleAccordion(id) {
  const body = document.getElementById('acc-' + id);
  if (!body) return;
  const arrow = body.previousElementSibling.querySelector('.accordion-arrow');
  if (body.style.display === 'none') {
    body.style.display = '';
    if (arrow) arrow.textContent = '▼';
  } else {
    body.style.display = 'none';
    if (arrow) arrow.textContent = '▶';
  }
}

function fmtPrice(v) {
  if (v == null) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatTime(sec) {
  var m = Math.floor(sec / 60);
  var s = sec % 60;
  return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

routePage();
