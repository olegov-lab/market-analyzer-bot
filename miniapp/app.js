const API_BASE = window.location.origin;
let Telegram = null;
let initData = '';
let userId = null;
let pollTimers = {};
let articles = [];
let lessons = [];

try {
  Telegram = window.Telegram.WebApp;
  Telegram.ready();
  Telegram.expand();
  initData = Telegram.initData || '';
} catch (e) {
  try {
    const hash = window.location.hash;
    if (hash && hash.includes('tgWebAppData=')) {
      const params = new URLSearchParams(hash.slice(1));
      const rawData = params.get('tgWebAppData') || '';
      initData = decodeURIComponent(rawData);
      Telegram = { ready: function(){}, expand: function(){}, BackButton: { show: function(){}, hide: function(){}, onClick: function(){} } };
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    }
  } catch (_) {}
}

async function apiCall(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000);
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
      throw new Error(errMsg);
    }
    return resp.json();
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') throw new Error('Таймаут запроса');
    throw e;
  }
}

function render(html) {
  try {
    const content = document.getElementById('content');
    if (content) content.innerHTML = html;
  } catch (e) {
    console.error('Render failed:', e);
    const content = document.getElementById('content');
    if (content) content.innerHTML = '<div class="card" style="text-align:center;padding:30px;"><div style="font-size:40px;">❌</div><div style="margin-top:12px;color:var(--text);">Ошибка отображения</div></div>';
  }
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

function navigate(page) {
  if (page.startsWith('lesson_')) {
    window.location.hash = '#learn/' + page.split('_')[1];
    return;
  }
  window.location.hash = page === 'price' ? '' : '#' + page;
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

function setActiveNav(page) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector('.nav-btn[data-page="' + page + '"]');
  if (btn) btn.classList.add('active');
}

function getHashPage() {
  const hash = window.location.hash.slice(1);
  if (!hash || hash.startsWith('tgWebAppData=')) return 'price';
  if (hash.startsWith('learn/')) return 'learn';
  return hash;
}

function getHashParam() {
  const hash = window.location.hash.slice(1);
  if (hash.startsWith('learn/')) return parseInt(hash.split('/')[1], 10);
  return null;
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
  setActiveNav('price');
  tgBackButton('hide');
  showLoading();
  try {
    const data = await apiCall('/miniapp/dashboard');
    const p = data.price;
    const ind = data.indicators;
    const pred = data.prediction_summary;
    const signal = pred ? pred.direction : 'HOLD';

    let signalClass = 'hold';
    if (signal === 'BUY') signalClass = 'buy';
    else if (signal === 'SELL') signalClass = 'sell';

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
    html += '</div>';

    if (pred) {
      const confPct = Math.round(pred.confidence * 100);
      const confColor = confPct >= 70 ? 'high' : confPct >= 40 ? 'med' : 'low';
      html += '<div class="card"><div class="card-title">Уверенность прогноза</div><div class="conf-bar"><div class="conf-bar-fill ' + confColor + '" style="width:' + confPct + '%"></div></div><div class="row"><span class="label">' + confPct + '%</span><span class="value">' + (confPct >= 70 ? 'высокая' : confPct >= 40 ? 'средняя' : 'низкая') + '</span></div></div>';
    }

    if (ind) {
      html += '<div class="card"><div class="card-title">Технические индикаторы</div>';
      if (ind.rsi != null) {
        const rsiColor = ind.rsi > 70 ? 'down' : ind.rsi < 30 ? 'up' : '';
        const barLen = 10;
        const filled = Math.max(0, Math.min(barLen, Math.round(ind.rsi / 100 * barLen)));
        const bar = '█'.repeat(filled) + '░'.repeat(barLen - filled);
        html += '<div class="row"><span class="label">RSI(14)</span><span class="value ' + rsiColor + '">' + bar + ' ' + ind.rsi.toFixed(1) + '</span></div>';
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

    html += '<div class="card" style="font-size:11px;color:var(--hint);text-align:center;">♻️ Обновление каждые 30с</div>';
    render(html);
  } catch (e) {
    showError('Не удалось загрузить данные: ' + e.message);
  }
}

async function renderPredict() {
  setActiveNav('predict');
  tgBackButton('hide');
  showLoading();
  try {
    const pred = await apiCall('/miniapp/predict');
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

      html += '<div class="card"><div class="card-title">Сегодня</div><div class="signal ' + signalClass + '">' + signalEmoji + ' ' + signal + '</div><div style="margin-top:8px;font-weight:600;">$' + fmtPrice(priceMin) + ' – $' + fmtPrice(priceMax) + '</div><div class="conf-bar"><div class="conf-bar-fill ' + confColor + '" style="width:' + confPct + '%"></div></div><div class="row"><span class="label">Уверенность</span><span class="value">' + confPct + '%</span></div></div>';

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

    render(html);
  } catch (e) {
    showError('Не удалось загрузить прогноз: ' + e.message);
  }
}

async function renderNews() {
  setActiveNav('news');
  tgBackButton('hide');
  showLoading();
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
    render(html);
  } catch (e) {
    showError('Не удалось загрузить новости: ' + e.message);
  }
}

async function renderLearnList() {
  setActiveNav('learn');
  tgBackButton('hide');
  showLoading();
  try {
    const data = await apiCall('/miniapp/lessons');
    lessons = data;
    let html = '<div class="card"><div class="card-title">Азбука крипты</div><p style="margin-bottom:12px;color:var(--hint);">10 коротких уроков для начинающих</p>';
    for (const l of lessons) {
      html += '<a class="lesson-card" href="#learn/' + l.id + '">' + l.id + '. ' + escapeHtml(l.title) + '</a>';
    }
    html += '</div>';
    render(html);
  } catch (e) {
    showError('Не удалось загрузить уроки: ' + e.message);
  }
}

async function renderLesson(id) {
  showLoading();
  tgBackButton('show');
  tgBackButton('onClick', () => { window.location.hash = '#learn'; });

  try {
    const lesson = await apiCall('/miniapp/lessons/' + id);
    let html = '<div class="card"><div class="card-title">Урок ' + lesson.id + '</div><div class="lesson-text">' + escapeHtml(lesson.text || '') + '</div><div class="lesson-nav">';

    if (id > 1) html += '<button onclick="window.location.hash=\'#learn/' + (id-1) + '\'">◀️ Назад</button>';
    else html += '<div></div>';
    if (id < lessons.length) html += '<button onclick="window.location.hash=\'#learn/' + (id+1) + '\'">▶️ Вперёд</button>';
    else html += '<div></div>';
    html += '</div></div>';

    render(html);
  } catch (e) {
    showError('Не удалось загрузить урок: ' + e.message);
  }
}

async function renderAlerts() {
  setActiveNav('alerts');
  tgBackButton('hide');
  showLoading();
  try {
    const subs = await apiCall('/miniapp/subscriptions');
    let html = '<div class="card"><div class="card-title">Мои подписки</div>';

    if (!subs.length) {
      html += '<p style="color:var(--hint);">Нет активных подписок</p>';
    } else {
      for (const sub of subs) {
        for (const at of sub.alert_types) {
          html += '<div class="alert-item"><span class="alert-type">' + escapeHtml(at) + '</span><button class="btn-unsub" data-sub-id="' + sub.id + '" data-type="' + escapeHtml(at) + '">Отписаться</button></div>';
        }
      }
    }
    html += '</div>';

    html += '<div class="card"><div class="card-title">Добавить подписку</div>';
    for (const item of [['rsi', 'RSI — перекупленность/перепроданность'], ['ma_cross', 'MA Cross — пересечение MA50 и MA200'], ['volume_spike', 'Volume Spike — аномальный объём']]) {
      html += '<button class="sub-btn" data-alert-type="' + item[0] + '">+ ' + escapeHtml(item[1]) + '</button>';
    }
    html += '</div>';

    render(html);

    document.querySelectorAll('.btn-unsub').forEach(btn => {
      btn.addEventListener('click', async () => {
        const subId = btn.dataset.subId;
        const alertType = btn.dataset.type;
        try {
          await apiCall('/miniapp/subscriptions/' + subId + '/' + alertType, { method: 'DELETE' });
          tgShowAlert('Подписка удалена');
          renderAlerts();
        } catch (e) {
          tgShowAlert('Ошибка: ' + e.message);
        }
      });
    });

    document.querySelectorAll('.sub-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const alertType = btn.dataset.alertType;
        try {
          await apiCall('/miniapp/subscriptions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alert_type: alertType }),
          });
          tgShowAlert('Подписка на ' + alertType + ' оформлена');
          renderAlerts();
        } catch (e) {
          tgShowAlert('Ошибка: ' + e.message);
        }
      });
    });
  } catch (e) {
    showError('Не удалось загрузить подписки: ' + e.message);
  }
}

function routePage() {
  const page = getHashPage();
  const param = getHashParam();
  stopAllPolls();

  if (!initData) {
    render('<div class="card" style="text-align:center;padding:40px;"><div style="font-size:40px;margin-bottom:16px;">📊</div><div style="font-weight:600;font-size:18px;">BTC Monitor</div><div style="margin-top:8px;color:var(--hint);">Открой это приложение через Telegram Bot<br>👇<br>📊 BTC Dashboard</div></div>');
    return;
  }

  switch (page) {
    case 'price':
      startPoll('dashboard', renderDashboard, 30000);
      break;
    case 'predict':
      startPoll('predict', renderPredict, 60000);
      break;
    case 'news':
      startPoll('news', renderNews, 120000);
      break;
    case 'learn':
      if (param) renderLesson(param);
      else renderLearnList();
      break;
    case 'alerts':
      renderAlerts();
      break;
    default:
      startPoll('dashboard', renderDashboard, 30000);
  }
}

window.addEventListener('hashchange', routePage);

function fmtPrice(v) {
  if (v == null) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

routePage();
