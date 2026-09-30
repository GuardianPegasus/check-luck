/* Личный кабинет: статус чека обновляется без перезагрузки страницы.
   Раз в POLL_MS спрашиваем /api/receipts/ и подменяем бейдж/текст,
   если статус модератора изменился. Перезагрузка страницы не нужна. */
(function () {
  "use strict";

  var body = document.querySelector("[data-receipts-body]");
  if (!body || !window.Luck) return;

  var POLL_MS = 20000;
  var BADGE_TEMPLATES = {
    pending: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 6v4.2l2.6 1.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    approved: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    winner: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.6l2.2 4.5 5 .7-3.6 3.5.9 4.9-4.5-2.4-4.5 2.4.9-4.9L2.8 7.8l5-.7z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    rejected: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7.4 7.4l5.2 5.2M12.6 7.4l-5.2 5.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  };

  var lastSignature = signature();

  function signature() {
    return Array.prototype.map
      .call(body.querySelectorAll("[data-status-for]"), function (el) {
        return el.id + ":" + el.className;
      })
      .join("|");
  }

  function render(data) {
    (data.results || []).forEach(function (receipt) {
      var row = body.querySelector('[data-receipt-id="' + receipt.id + '"]');
      if (!row) return;

      var badge = row.querySelector('[data-status-for="' + receipt.id + '"]');
      if (badge && !badge.classList.contains("badge--" + receipt.status_css)) {
        badge.className = "badge badge--" + receipt.status_css;
        badge.innerHTML = (BADGE_TEMPLATES[receipt.status_css] || "") + " " + receipt.status_display;
      }

      var info = row.querySelector('[data-info-for="' + receipt.id + '"]');
      if (info && info.textContent.trim() !== receipt.info) {
        info.textContent = receipt.info;
      }

      var created = row.querySelector('[data-created-for="' + receipt.id + '"]');
      if (created && created.textContent.trim() !== receipt.created_at) {
        created.textContent = receipt.created_at;
      }
    });

    var current = signature();
    if (current !== lastSignature) {
      lastSignature = current;
      announce("Статус чека обновился");
    }
  }

  function announce(text) {
    var box = document.querySelector(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      document.body.appendChild(box);
    }
    var toast = document.createElement("div");
    toast.className = "toast toast--info";
    toast.textContent = text;
    box.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 4000);
  }

  function poll() {
    window.Luck.getJSON("/api/receipts/")
      .then(render)
      .catch(function () { /* сеть недоступна — просто ждём следующего тика */ });
  }

  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
})();