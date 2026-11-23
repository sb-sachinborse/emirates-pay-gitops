(() => {
  'use strict';

  const I18N = {
    en: {
      tagline: 'Digital wallet in UAE dirhams', cur: 'AED', signOut: 'Sign out',
      signInTitle: 'Sign in with UAE Pass (demo)',
      demoNote: 'Demo sign-in only. There is no real UAE Pass connection and no real money.',
      name: 'Name', email: 'Email', signIn: 'Sign in',
      balance: 'Available balance', wallet: 'Wallet number',
      addFunds: 'Add funds (demo)', amount: 'Amount (AED)', add: 'Add funds',
      send: 'Send money', toWallet: 'Recipient wallet number', note: 'Note (optional)', sendBtn: 'Send',
      fee: 'Fee', vatShort: 'VAT', vat: 'VAT 5% on fee', total: 'Total deducted',
      activity: 'Activity', empty: 'No activity yet. Add funds to get started.',
      in: 'Received', out: 'Sent', topup: 'Funds added', from: 'From', to: 'To',
      version: 'Version', build: 'build', faultBanner: 'Fault injection is on. Some requests will fail on purpose.',
      sent: 'Transfer sent.', added: 'Funds added.', replayed: 'This transfer was already processed. You were not charged twice.',
      err_insufficient_funds: 'Your balance does not cover the amount plus fee and VAT.',
      err_wallet_not_found: 'No wallet exists with that number.',
      err_same_wallet: 'You cannot send money to your own wallet.',
      err_invalid_amount: 'Enter an amount greater than zero with at most 2 decimal places.',
      err_limit_exceeded: 'That amount is above the allowed limit.',
      err_invalid_input: 'Check the details you entered and try again.',
      err_unauthorized: 'Your session ended. Sign in again.',
      err_idempotency_conflict: 'This request was already used with different details. Reload and try again.',
      err_network: 'Cannot reach the server. Check your connection and try again.',
      err_server: 'The server hit an error. Try again in a moment.'
    },
    ar: {
      tagline: 'محفظة رقمية بالدرهم الإماراتي', cur: 'د.إ', signOut: 'تسجيل الخروج',
      signInTitle: 'الدخول عبر UAE Pass (تجريبي)',
      demoNote: 'دخول تجريبي فقط. لا يوجد اتصال فعلي بـ UAE Pass ولا أموال حقيقية.',
      name: 'الاسم', email: 'البريد الإلكتروني', signIn: 'تسجيل الدخول',
      balance: 'الرصيد المتاح', wallet: 'رقم المحفظة',
      addFunds: 'إضافة رصيد (تجريبي)', amount: 'المبلغ (درهم)', add: 'إضافة رصيد',
      send: 'تحويل أموال', toWallet: 'رقم محفظة المستلم', note: 'ملاحظة (اختياري)', sendBtn: 'تحويل',
      fee: 'الرسوم', vatShort: 'الضريبة', vat: 'ضريبة القيمة المضافة 5٪ على الرسوم', total: 'إجمالي المبلغ المخصوم',
      activity: 'النشاط', empty: 'لا توجد عمليات بعد. أضف رصيدًا لتبدأ.',
      in: 'وارد', out: 'صادر', topup: 'إضافة رصيد', from: 'من', to: 'إلى',
      version: 'الإصدار', build: 'البناء', faultBanner: 'حقن الأعطال مفعّل. ستفشل بعض الطلبات عمدًا.',
      sent: 'تم التحويل.', added: 'تمت إضافة الرصيد.', replayed: 'تمت معالجة هذا التحويل سابقًا. لم يتم الخصم مرتين.',
      err_insufficient_funds: 'رصيدك لا يغطي المبلغ مع الرسوم وضريبة القيمة المضافة.',
      err_wallet_not_found: 'لا توجد محفظة بهذا الرقم.',
      err_same_wallet: 'لا يمكنك التحويل إلى محفظتك نفسها.',
      err_invalid_amount: 'أدخل مبلغًا أكبر من صفر بحد أقصى خانتين عشريتين.',
      err_limit_exceeded: 'المبلغ أعلى من الحد المسموح.',
      err_invalid_input: 'تحقق من البيانات المدخلة وأعد المحاولة.',
      err_unauthorized: 'انتهت الجلسة. سجّل الدخول مرة أخرى.',
      err_idempotency_conflict: 'استُخدم هذا الطلب سابقًا ببيانات مختلفة. أعد تحميل الصفحة وحاول مجددًا.',
      err_network: 'تعذر الاتصال بالخادم. تحقق من الاتصال وأعد المحاولة.',
      err_server: 'حدث خطأ في الخادم. أعد المحاولة بعد قليل.'
    }
  };

  const $ = (id) => document.getElementById(id);
  const store = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) {} },
    del: (k) => { try { sessionStorage.removeItem(k); } catch (_) {} }
  };

  const state = {
    lang: store.get('ep_lang') || ((navigator.language || '').startsWith('ar') ? 'ar' : 'en'),
    token: store.get('ep_token'),
    me: null, txns: [], version: null,
    idem: { send: null }
  };

  const t = (k) => (I18N[state.lang] && I18N[state.lang][k]) || I18N.en[k] || k;
  const locale = () => (state.lang === 'ar' ? 'ar-AE-u-nu-latn-ca-gregory' : 'en-AE');
  const num = (s) => new Intl.NumberFormat(locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(s));
  const money = (s) => (state.lang === 'ar' ? `${num(s)} ${t('cur')}` : `${t('cur')} ${num(s)}`);
  const when = (iso) => new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Dubai' }).format(new Date(iso));
  const groupWallet = (w) => (w ? `${w.slice(0, 2)} ${w.slice(2, 6)} ${w.slice(6)}` : '');

  // ---------- status ----------
  let statusTimer;
  function say(message, kind) {
    const el = $('status');
    el.textContent = message;
    el.className = 'status ' + (kind || '');
    clearTimeout(statusTimer);
    if (message) statusTimer = setTimeout(() => say(''), 7000);
  }
  const errText = (e) => t('err_' + e.code) !== 'err_' + e.code ? t('err_' + e.code) : t('err_server');

  // ---------- API ----------
  async function api(path, opts = {}) {
    const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    if (opts.body) headers['Content-Type'] = 'application/json';
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    let res;
    try {
      res = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
    } catch (_) {
      throw { code: 'network' };
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
    if (!res.ok) {
      const err = { code: (data && data.error && data.error.code) || 'server', status: res.status };
      if (res.status === 401) signOut(true);
      throw err;
    }
    return data;
  }

  // ---------- rendering ----------
  function applyLang() {
    document.documentElement.lang = state.lang;
    document.documentElement.dir = state.lang === 'ar' ? 'rtl' : 'ltr';
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $('lang-toggle').textContent = state.lang === 'ar' ? 'English' : 'عربي';
    $('lang-toggle').setAttribute('aria-label', state.lang === 'ar' ? 'Switch to English' : 'التبديل إلى العربية');
    renderVersion();
    renderMe();
    renderTxns();
    updateQuote();
  }

  function renderVersion() {
    const v = state.version;
    const el = $('version');
    el.textContent = '';
    if (v) {
      [[t('version'), v.version], [t('build'), v.git_sha], [null, v.env]].forEach(([label, value], i) => {
        if (i) el.append(' | ');
        if (label) el.append(label + ' ');
        const b = document.createElement('bdi');
        b.textContent = value;
        el.append(b);
      });
    }
    $('fault-banner').hidden = !(v && v.fault_injection);
  }

  function renderMe() {
    const signedIn = !!state.me;
    $('auth').hidden = signedIn;
    $('dash').hidden = !signedIn;
    $('signout').hidden = !signedIn;
    if (!signedIn) return;
    $('balance').textContent = money(state.me.wallet.balance);
    $('wallet-no').textContent = groupWallet(state.me.wallet.wallet_no);
    $('user-name').textContent = state.me.user.name;
  }

  function renderTxns() {
    const list = $('txns');
    list.textContent = '';
    $('empty').hidden = state.txns.length > 0;
    for (const x of state.txns) {
      const li = document.createElement('li');
      li.className = 'txn';
      const title = document.createElement('span');
      title.className = 'txn-title';
      title.textContent = t(x.direction);
      const meta = document.createElement('span');
      meta.className = 'txn-meta';
      // Each part is bidi-isolated so Arabic text, wallet numbers and dates never interleave.
      const isolate = (text, dir) => {
        const b = document.createElement('bdi');
        if (dir) b.dir = dir;
        b.textContent = text;
        return b;
      };
      const parts = [];
      if (x.counterparty) {
        const span = document.createElement('span');
        span.append(t(x.direction === 'out' ? 'to' : 'from') + ' ', isolate(groupWallet(x.counterparty), 'ltr'));
        parts.push(span);
      }
      if (x.note) parts.push(isolate(x.note, 'auto'));
      parts.push(isolate(when(x.created_at)));
      parts.forEach((node, i) => { if (i) meta.append(' | '); meta.append(node); });
      const amt = document.createElement('span');
      amt.className = 'txn-amt ' + (x.direction === 'out' ? 'out' : 'in');
      amt.dir = 'ltr';
      const sign = x.direction === 'out' ? '-' : '+';
      amt.textContent = sign + money(x.direction === 'out' ? x.total : x.amount);
      if (x.direction === 'out') {
        const f = document.createElement('span');
        f.className = 'txn-fee';
        f.textContent = `${t('fee')} ${money(x.fee)} + ${t('vatShort')} ${money(x.vat)}`;
        amt.appendChild(f);
      }
      li.append(title, meta, amt);
      list.appendChild(li);
    }
  }

  // ---------- fee preview ----------
  let quoteTimer;
  function updateQuote() {
    clearTimeout(quoteTimer);
    const raw = $('send-amount').value.trim();
    if (!raw) { $('quote').hidden = true; return; }
    quoteTimer = setTimeout(async () => {
      try {
        const q = await fetch('/api/quote?amount=' + encodeURIComponent(raw));
        if (!q.ok) { $('quote').hidden = true; return; }
        const d = await q.json();
        $('q-fee').textContent = money(d.fee);
        $('q-vat').textContent = money(d.vat);
        $('q-total').textContent = money(d.total);
        $('quote').hidden = false;
      } catch (_) { $('quote').hidden = true; }
    }, 250);
  }

  // ---------- actions ----------
  async function refresh() {
    const [me, tx] = await Promise.all([api('/api/me'), api('/api/transactions')]);
    state.me = me;
    state.txns = tx.transactions;
    renderMe();
    renderTxns();
  }

  function signOut(silent) {
    state.token = null; state.me = null; state.txns = [];
    store.del('ep_token');
    renderMe();
    renderTxns();
    if (silent === true) say(t('err_unauthorized'), 'err');
  }

  async function withBusy(form, fn) {
    const btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    try { await fn(); } finally { btn.disabled = false; }
  }

  $('login-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    withBusy(ev.target, async () => {
      try {
        const d = await api('/api/auth/uaepass-mock', {
          method: 'POST', body: { name: $('login-name').value, email: $('login-email').value }
        });
        state.token = d.token;
        store.set('ep_token', d.token);
        say('');
        await refresh();
      } catch (e) { say(errText(e), 'err'); }
    });
  });

  $('topup-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    withBusy(ev.target, async () => {
      try {
        await api('/api/wallet/topup', { method: 'POST', body: { amount: $('topup-amount').value } });
        $('topup-amount').value = '';
        say(t('added'), 'ok');
        await refresh();
      } catch (e) { say(errText(e), 'err'); }
    });
  });

  // The Idempotency-Key is reused when the network fails mid-request, so a retry can never charge twice.
  $('send-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    withBusy(ev.target, async () => {
      state.idem.send = state.idem.send || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
      try {
        const d = await api('/api/transfer', {
          method: 'POST',
          headers: { 'Idempotency-Key': state.idem.send },
          body: { to_wallet: $('send-to').value, amount: $('send-amount').value, note: $('send-note').value }
        });
        state.idem.send = null;
        ev.target.reset();
        $('quote').hidden = true;
        say(d.replayed ? t('replayed') : t('sent'), 'ok');
        await refresh();
      } catch (e) {
        if (e.code !== 'network') state.idem.send = null;
        say(errText(e), 'err');
      }
    });
  });

  ['send-to', 'send-amount', 'send-note'].forEach((id) =>
    $(id).addEventListener('input', () => { state.idem.send = null; if (id === 'send-amount') updateQuote(); }));

  $('lang-toggle').addEventListener('click', () => {
    state.lang = state.lang === 'ar' ? 'en' : 'ar';
    store.set('ep_lang', state.lang);
    say('');
    applyLang();
  });
  $('signout').addEventListener('click', () => signOut());

  // ---------- boot ----------
  (async function init() {
    applyLang();
    try { state.version = await (await fetch('/api/version')).json(); renderVersion(); } catch (_) {}
    if (state.token) { try { await refresh(); } catch (_) { /* signOut already handled 401 */ } }
  })();
})();
