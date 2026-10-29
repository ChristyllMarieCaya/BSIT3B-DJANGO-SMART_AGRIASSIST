(function () {
  const root = document.documentElement;
  const allowedThemes = ['light', 'dark', 'system'];
  const authenticated = root.dataset.themeAuthenticated === 'true';
  const accountTheme = root.dataset.themePreference || 'light';
  const savedTheme = document.cookie
    .split('; ')
    .find(cookie => cookie.startsWith('smart_app_theme='));
  const browserTheme = savedTheme
    ? decodeURIComponent(savedTheme.split('=').slice(1).join('='))
    : window.localStorage.getItem('smart_app_theme');
  const systemTheme = window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;
  let preference = authenticated
    ? accountTheme
    : allowedThemes.includes(browserTheme) ? browserTheme : accountTheme;

  function resolveTheme(theme) {
    if (theme === 'light' || theme === 'dark') {
      return theme;
    }

    return systemTheme && systemTheme.matches ? 'dark' : 'light';
  }

  function applyTheme(theme, persist) {
    if (!allowedThemes.includes(theme)) {
      return;
    }

    preference = theme;
    root.setAttribute('data-user-theme-pref', theme);
    root.setAttribute('data-bs-theme', resolveTheme(theme));
    if (persist) {
      window.localStorage.setItem('smart_app_theme', theme);
      document.cookie = 'smart_app_theme=' + encodeURIComponent(theme) + '; Path=/; Max-Age=31536000; SameSite=Lax';
    }
  }

  applyTheme(preference, authenticated);
  window.applySmartTheme = function (theme, persist) {
    applyTheme(theme, persist !== false);
  };

  if (systemTheme) {
    const updateSystemTheme = function () {
      if (preference === 'system') {
        root.setAttribute('data-bs-theme', resolveTheme(preference));
      }
    };

    if (systemTheme.addEventListener) {
      systemTheme.addEventListener('change', updateSystemTheme);
    } else {
      systemTheme.addListener(updateSystemTheme);
    }
  }
})();
