(function () {
    var OVERLAY_ID = 'render-wake-loader';
    var LAST_AWAKE_KEY = 'kolumbus_render_last_awake_at';
    var SLEEP_WINDOW_MS = 15 * 60 * 1000;
    var LIKELY_SLEEPING_DELAY_MS = 350;
    var MIN_VISIBLE_MS = 650;

    var pendingReasons = new Set();
    var showTimer = null;
    var hideTimer = null;
    var visibleSince = 0;
    var overlay = null;

    function now() {
        return Date.now();
    }

    function noteAwake() {
        try {
            localStorage.setItem(LAST_AWAKE_KEY, String(now()));
        } catch (e) {
            // LocalStorage may be unavailable in private browsing modes.
        }
    }

    function getLastAwakeAt() {
        try {
            var value = Number(localStorage.getItem(LAST_AWAKE_KEY));
            return Number.isFinite(value) ? value : 0;
        } catch (e) {
            return 0;
        }
    }

    function likelySleeping() {
        var lastAwakeAt = getLastAwakeAt();
        return Boolean(lastAwakeAt && now() - lastAwakeAt > SLEEP_WINDOW_MS);
    }

    function ensureOverlay() {
        if (overlay) return overlay;

        overlay = document.getElementById(OVERLAY_ID);
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = OVERLAY_ID;
            overlay.className = 'render-wake-loader';
            overlay.setAttribute('role', 'status');
            overlay.setAttribute('aria-live', 'polite');
            overlay.setAttribute('aria-hidden', 'true');
            overlay.innerHTML = [
                '<div class="render-wake-loader__panel">',
                '<div class="render-wake-loader__compass" aria-hidden="true"></div>',
                '<p class="render-wake-loader__title">Palvelin her&auml;&auml;</p>',
                '<p class="render-wake-loader__text">Peli k&auml;ytt&auml;&auml; MySQL-tietokantaa. Renderin ilmainen palvelin nukkuu 15 minuutin hiljaisuuden j&auml;lkeen, joten cold start voi kest&auml;&auml; noin minuutin. P&auml;&auml;set kohta pelaamaan.</p>',
                '</div>'
            ].join('');
            document.body.appendChild(overlay);
        }

        return overlay;
    }

    function showOverlay() {
        clearTimeout(showTimer);
        showTimer = null;
        clearTimeout(hideTimer);
        hideTimer = null;

        var el = ensureOverlay();
        visibleSince = now();
        el.setAttribute('aria-hidden', 'false');
        el.classList.add('is-visible');
    }

    function hideOverlay() {
        clearTimeout(showTimer);
        showTimer = null;

        if (!overlay) {
            visibleSince = 0;
            return;
        }

        var el = overlay;
        el.classList.remove('is-visible');
        el.setAttribute('aria-hidden', 'true');
        visibleSince = 0;
    }

    function start(reason, options) {
        if (!(options && options.force) && !likelySleeping()) {
            return null;
        }

        var key = reason || 'request';
        var delay = options && typeof options.delay === 'number'
            ? options.delay
            : LIKELY_SLEEPING_DELAY_MS;

        pendingReasons.add(key);
        clearTimeout(hideTimer);
        hideTimer = null;

        if (overlay && overlay.classList.contains('is-visible')) return key;
        if (!showTimer) {
            showTimer = setTimeout(showOverlay, delay);
        }
        return key;
    }

    function stop(reason) {
        if (!reason) return;

        var key = reason || 'request';
        pendingReasons.delete(key);
        if (pendingReasons.size > 0) return;

        clearTimeout(showTimer);
        showTimer = null;

        if (!overlay || !overlay.classList.contains('is-visible')) return;

        var elapsed = visibleSince ? now() - visibleSince : MIN_VISIBLE_MS;
        var remaining = Math.max(0, MIN_VISIBLE_MS - elapsed);
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hideOverlay, remaining);
    }

    function isSameOriginUrl(input) {
        try {
            var rawUrl = typeof input === 'string'
                ? input
                : (input && input.url ? input.url : String(input || ''));
            var url = new URL(rawUrl, window.location.href);
            return url.origin === window.location.origin;
        } catch (e) {
            return false;
        }
    }

    function isPlainNavigationClick(event, anchor) {
        if (!anchor || !anchor.href) return false;
        if (event.defaultPrevented || event.button !== 0) return false;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
        if (anchor.target && anchor.target !== '_self') return false;

        var url = new URL(anchor.href, window.location.href);
        if (url.origin !== window.location.origin) return false;
        if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) {
            return false;
        }

        return true;
    }

    function installFetchWrapper() {
        if (!window.fetch || window.fetch.__renderWakeLoaderWrapped) return;

        var originalFetch = window.fetch.bind(window);
        function wrappedFetch(input, init) {
            if (!isSameOriginUrl(input)) {
                return originalFetch(input, init);
            }

            var reason = start('fetch:' + Math.random().toString(36).slice(2));
            return originalFetch(input, init)
                .then(function (response) {
                    noteAwake();
                    return response;
                })
                .catch(function (error) {
                    throw error;
                })
                .finally(function () {
                    stop(reason);
                });
        }

        wrappedFetch.__renderWakeLoaderWrapped = true;
        window.fetch = wrappedFetch;
    }

    function installNavigationListeners() {
        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (!(form instanceof HTMLFormElement)) return;
            if (event.defaultPrevented || form.target && form.target !== '_self') return;

            var action = form.getAttribute('action') || window.location.href;
            if (!isSameOriginUrl(action)) return;
            start('form-navigation');
        });

        document.addEventListener('click', function (event) {
            var anchor = event.target.closest ? event.target.closest('a[href]') : null;
            if (!isPlainNavigationClick(event, anchor)) return;
            start('link-navigation');
        });

        window.addEventListener('pageshow', function () {
            pendingReasons.clear();
            hideOverlay();
            noteAwake();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            noteAwake();
            installFetchWrapper();
            installNavigationListeners();
        });
    } else {
        noteAwake();
        installFetchWrapper();
        installNavigationListeners();
    }

    window.RenderWakeLoader = {
        start: start,
        stop: stop,
        noteAwake: noteAwake
    };
}());
