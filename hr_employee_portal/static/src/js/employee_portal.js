/** @odoo-module ignore **/
// Employee portal effects: 3D tilt, staff card flip, reveal on scroll, count-up
// numbers, file picker label, password show/hide and profile sections opened by
// link. Plain script, no dependency. Everything degrades to a static page
// without it, and motion is skipped when the visitor asked for reduced motion.
(function () {
    'use strict';

    var media = function (query) {
        return Boolean(window.matchMedia && window.matchMedia(query).matches);
    };
    var reduceMotion = media('(prefers-reduced-motion: reduce)');
    var finePointer = media('(hover: hover) and (pointer: fine)');
    var TILT_MAX = { '': 8, soft: 4, subtle: 3 };

    // Set as early as possible so revealed content does not flash before hiding.
    document.documentElement.classList.add('ep-js');

    // ---- Clicks (delegated, so they work before the page is fully loaded) ----
    document.addEventListener('click', function (ev) {
        if (!ev.target.closest) {
            return;
        }
        var toggle = ev.target.closest('.ep-pw-toggle');
        if (toggle) {
            var input = document.getElementById(toggle.getAttribute('aria-controls'));
            if (input) {
                var show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                toggle.setAttribute('aria-pressed', show ? 'true' : 'false');
                toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            }
            return;
        }
        var flip = ev.target.closest('[data-ep-flip]');
        var card = flip ? flip.closest('.ep-card3d') : ev.target.closest('.ep-card3d');
        if (card && (flip || !ev.target.closest('a, button'))) {
            flipCard(card);
        }
    });

    function flipCard(card) {
        var flipped = card.classList.toggle('is-flipped');
        var button = card.querySelector('[data-ep-flip]');
        if (button) {
            button.setAttribute('aria-pressed', flipped ? 'true' : 'false');
        }
        // Let the flip use its slow transition even while the pointer is on the card.
        card.classList.add('is-turning');
        window.setTimeout(function () {
            card.classList.remove('is-turning');
        }, 800);
    }

    // ---- New request menu: closes on a click outside it or on Escape ----
    document.addEventListener('click', function (ev) {
        document.querySelectorAll('details[data-ep-ask][open]').forEach(function (menu) {
            if (!menu.contains(ev.target)) {
                menu.open = false;
            }
        });
    });
    document.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Escape') {
            return;
        }
        document.querySelectorAll('details[data-ep-ask][open]').forEach(function (menu) {
            menu.open = false;
            menu.querySelector('summary').focus();
        });
    });

    // ---- Login badge: a gold scan line passes over it on Sign in ----
    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (form.matches && form.matches('[data-ep-login]') && !reduceMotion) {
            form.classList.add('is-scanning');
        }
    });

    // ---- Leave form: half day only for types taken in half days, and a
    // half day has no last day. Without script the server checks both. ----
    function syncLeaveForm(form) {
        var parts = form.querySelector('[data-ep-day-part]');
        if (!parts) {
            return;
        }
        var type = form.querySelector('input[name="leave_type_id"]:checked');
        var allowHalf = Boolean(type && type.hasAttribute('data-ep-half'));
        parts.hidden = !allowHalf;
        var part = form.querySelector('input[name="day_part"]:checked');
        if (!allowHalf && part && part.value !== 'full') {
            form.querySelector('input[name="day_part"][value="full"]').checked = true;
            part = null;
        }
        var halfDay = Boolean(allowHalf && part && part.value !== 'full');
        var dateTo = form.querySelector('[data-ep-date-to]');
        if (dateTo) {
            dateTo.hidden = halfDay;
            var input = dateTo.querySelector('input');
            input.required = !halfDay;
            input.disabled = halfDay;
        }
    }

    // ---- File picker: show the chosen file names ----
    document.addEventListener('change', function (ev) {
        var input = ev.target;
        if (input.form && (input.name === 'leave_type_id' || input.name === 'day_part')) {
            syncLeaveForm(input.form);
            return;
        }
        if (!input.classList || !input.classList.contains('ep-file')) {
            return;
        }
        var label = input.closest('.ep-form-field');
        label = label && label.querySelector('[data-ep-files]');
        if (!label) {
            return;
        }
        if (!label.dataset.epEmpty) {
            label.dataset.epEmpty = label.textContent;
        }
        var names = Array.prototype.map.call(input.files || [], function (file) {
            return file.name;
        });
        label.textContent = names.length ? names.join(', ') : label.dataset.epEmpty;
    });

    // ---- Tilt: elements with data-ep-tilt follow the pointer in 3D ----
    function setupTilt(root) {
        if (reduceMotion || !finePointer) {
            return;
        }
        root.querySelectorAll('[data-ep-tilt]').forEach(function (el) {
            var max = TILT_MAX[el.getAttribute('data-ep-tilt')] || TILT_MAX[''];
            var frame = 0;
            el.addEventListener('pointermove', function (ev) {
                var rect = el.getBoundingClientRect();
                var x = (ev.clientX - rect.left) / rect.width;
                var y = (ev.clientY - rect.top) / rect.height;
                window.cancelAnimationFrame(frame);
                frame = window.requestAnimationFrame(function () {
                    el.style.setProperty('--ry', ((x - 0.5) * 2 * max).toFixed(2) + 'deg');
                    el.style.setProperty('--rx', ((0.5 - y) * 2 * max).toFixed(2) + 'deg');
                    el.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
                    el.style.setProperty('--my', (y * 100).toFixed(1) + '%');
                });
                el.classList.add('is-tilting');
            });
            el.addEventListener('pointerleave', function () {
                window.cancelAnimationFrame(frame);
                el.classList.remove('is-tilting');
                ['--rx', '--ry', '--mx', '--my'].forEach(function (name) {
                    el.style.removeProperty(name);
                });
            });
        });
    }

    // ---- Count-up for plain numbers (data-ep-count) ----
    function countUp(el) {
        var target = parseFloat(el.textContent);
        if (isNaN(target) || el.dataset.epCounted) {
            return;
        }
        el.dataset.epCounted = '1';
        if (reduceMotion || target === 0) {
            return;
        }
        var final = el.textContent;
        var start = null;
        var duration = 1100;
        var step = function (now) {
            start = start || now;
            var progress = Math.min((now - start) / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = progress < 1 ? String(Math.round(target * eased)) : final;
            if (progress < 1) {
                window.requestAnimationFrame(step);
            }
        };
        el.textContent = '0';
        window.requestAnimationFrame(step);
    }

    // ---- Reveal on scroll (.ep-reveal), with a small stagger per batch ----
    function show(el) {
        el.classList.add('is-in');
        if (el.hasAttribute('data-ep-count')) {
            countUp(el);
        }
        el.querySelectorAll('[data-ep-count]').forEach(countUp);
    }

    function setupReveal(root) {
        var items = Array.prototype.slice.call(root.querySelectorAll('.ep-reveal'));
        if (reduceMotion || !('IntersectionObserver' in window)) {
            items.forEach(show);
            return;
        }
        // What is on screen at load appears right away, in page order.
        var height = window.innerHeight || document.documentElement.clientHeight;
        var later = items.filter(function (el, index) {
            var rect = el.getBoundingClientRect();
            if (rect.top < height && rect.bottom > 0) {
                el.style.setProperty('--d', String(Math.min(index, 8)));
                show(el);
                return false;
            }
            return true;
        });
        var answered = false;
        var observer = new IntersectionObserver(function (entries) {
            answered = true;
            var index = 0;
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) {
                    return;
                }
                entry.target.style.setProperty('--d', String(index++));
                show(entry.target);
                observer.unobserve(entry.target);
            });
        }, { rootMargin: '0px 0px -8% 0px', threshold: 0.01 });
        later.forEach(function (el) {
            observer.observe(el);
        });
        // Content must never stay hidden: if the observer does not answer, show everything.
        window.setTimeout(function () {
            if (!answered) {
                later.forEach(show);
            }
        }, 1500);
    }

    // ---- Profile sections: a link to #ep-sec-<topic> opens that section ----
    function openFromHash() {
        var id = (window.location.hash || '').slice(1);
        var section = id && document.getElementById(id);
        if (section && section.tagName === 'DETAILS') {
            section.open = true;
        }
    }
    window.addEventListener('hashchange', openFromHash);

    function init() {
        var root = document.querySelector('.ep-app, .ep-login');
        if (!root) {
            return;
        }
        root.querySelectorAll('form').forEach(syncLeaveForm);
        openFromHash();
        setupReveal(root);
        setupTilt(root);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
