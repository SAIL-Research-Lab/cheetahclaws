/* Login / register / logout flow for the chat UI. */

Object.assign(ChatApp.prototype, {

  _showLogin() {
    document.getElementById('login-overlay').style.display = 'flex';
  },

  _hideLogin() {
    document.getElementById('login-overlay').style.display = 'none';
  },

  async bootstrap() {
    // Decide whether to show login or register on first load.
    try {
      const r = await fetch('/api/auth/bootstrap', {credentials:'same-origin'});
      const d = await r.json();
      if (d.no_auth) {
        this._authed = true;
        this._hideLogin();
        await this.whoami();
        this.loadSessions();
        return;
      }
      this._authMode = d.has_users ? 'login' : 'register';
      // Closed registration (default once an admin exists): hide the
      // "create an account" toggle — the server would refuse it anyway.
      if (d.has_users && d.open_registration === false) {
        const t = document.getElementById('auth-toggle-link');
        if (t) t.style.display = 'none';
      }
      this._renderAuthMode();
      const who = await this.whoami();
      if (who) {
        this._hideLogin();
        this.loadSessions();
      } else {
        this._showLogin();
      }
    } catch(e) {
      const who = await this.whoami();
      if (who) { this._hideLogin(); this.loadSessions(); }
      else { this._showLogin(); }
    }
  },

  _renderAuthMode() {
    const isReg = this._authMode === 'register';
    document.getElementById('auth-mode-label').textContent =
      isReg ? 'Create your first account' : 'Sign in to continue';
    document.getElementById('auth-submit-btn').textContent =
      isReg ? 'Create account' : 'Sign in';
    document.getElementById('auth-toggle-link').textContent = isReg
      ? 'Have an account? Sign in'
      : 'First time? Create an account';
  },

  toggleAuthMode(e) {
    e.preventDefault();
    this._authMode = this._authMode === 'register' ? 'login' : 'register';
    this._renderAuthMode();
    document.getElementById('login-err').textContent = '';
  },

  async doAuth(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-pwd').value;
    const errEl = document.getElementById('login-err');
    errEl.textContent = '';
    if (!username || !password) {
      errEl.textContent = 'Username and password required';
      return;
    }
    const url = this._authMode === 'register'
      ? '/api/auth/register' : '/api/auth/login';
    try {
      const r = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({username, password}),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { errEl.textContent = d.error || 'Auth failed'; return; }
      this._authed = true;
      this._user = d.user || null;
      this._hideLogin();
      document.getElementById('login-pwd').value = '';
      this._renderUserFoot();
      this.loadSessions();
    } catch(err) { errEl.textContent = 'Connection error'; }
  },

  async whoami() {
    try {
      const r = await fetch('/api/auth/whoami', {credentials:'same-origin'});
      if (!r.ok) return null;
      const d = await r.json();
      this._user = d.user;
      this._authed = true;
      this._renderUserFoot();
      return d.user;
    } catch(e) { return null; }
  },

  _renderUserFoot() {
    const el = document.getElementById('sidebar-user');
    if (!el) return;
    el.textContent = this._user ? this._user.username : '—';
  },

  async logout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST', credentials: 'same-origin',
      });
    } catch(e) {}
    this._authed = false;
    this._user = null;
    this._disconnectWS();
    this.sessionId = null;
    location.reload();
  },

  async _fetchAuth(url, opts) {
    const r = await fetch(url, {credentials:'same-origin', ...opts});
    if (r.status === 401) {
      this._showLogin();
      throw new Error('auth required');
    }
    return r;
  },
});
