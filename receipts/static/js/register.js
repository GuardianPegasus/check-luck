/* Форма регистрации чека.
   1) Клиентская проверка обязательных полей и форматов до отправки.
   2) Отправка через fetch, ответ показывается на странице (без перезагрузки).
   3) Разбор строки из QR-кода и автозаполнение формы.
   Серверская валидация остаётся основной — здесь только UX. */
(function () {
  "use strict";

  var form = document.querySelector("[data-register-form]");
  if (!form) return;

  var submitBtn = form.querySelector("[data-submit]");
  var successBox = document.querySelector("[data-success]");
  var alertBox = document.getElementById("form-alert");

  var RULES = {
    fiscal_number: { label: "ФН", test: function (v) { return /^\d{12}$/.test(v); },
                     message: "ФН должен состоять ровно из 12 цифр" },
    document_number: { label: "Номер чека (ФД)", test: function (v) { return /^\d{1,10}$/.test(v); },
                     message: "Номер чека — от 1 до 10 цифр" },
    fiscal_signature: { label: "ФП", test: function (v) { return /^[0-9A-Fa-f]{1,64}$/.test(v); },
                        message: "ФП — до 64 символов, латинские буквы и цифры (0-9, A-F)" },
  };

  var MIN_AMOUNT = parseFloat(form.dataset.minAmount || "1000");
  var START_DATE = form.dataset.startDate || "";
  var END_DATE = form.dataset.endDate || "";

  /* --- Показ/скрытие ошибок у поля ------------------------------------- */
  function fieldWrap(input) {
    return input.closest(".field");
  }

  function showError(name, message) {
    var input = form.querySelector('[name="' + name + '"]');
    if (!input) return;
    var wrap = fieldWrap(input);
    if (wrap) wrap.classList.add("field--invalid");

    var holder = form.querySelector('[data-error-for="' + name + '"]');
    if (!holder) {
      holder = document.createElement("p");
      holder.className = "field__error";
      holder.setAttribute("data-error-for", name);
      if (wrap) wrap.appendChild(holder);
    }
    holder.textContent = message;
    holder.hidden = false;
  }

  function clearError(name) {
    var input = form.querySelector('[name="' + name + '"]');
    if (!input) return;
    var wrap = fieldWrap(input);
    if (wrap) wrap.classList.remove("field--invalid");
    var holder = form.querySelector('[data-error-for="' + name + '"]');
    if (holder && holder.tagName === "P" && !holder.dataset.serverError) {
      holder.textContent = "";
      holder.hidden = true;
    }
  }

  function clearAllErrors() {
    form.querySelectorAll(".field--invalid").forEach(function (el) {
      el.classList.remove("field--invalid");
    });
    form.querySelectorAll("[data-error-for]").forEach(function (el) {
      el.hidden = true;
      el.textContent = "";
      el.dataset.serverError = "";
    });
    if (alertBox) { alertBox.hidden = true; alertBox.textContent = ""; }
  }

  /* --- Валидация ------------------------------------------------------- */
  function valueOf(name) {
    var input = form.querySelector('[name="' + name + '"]');
    return input ? input.value.trim() : "";
  }

  function parseAmount(value) {
    var normalized = value.replace(/\s|\u00a0/g, "").replace(",", ".");
    var num = parseFloat(normalized);
    return isNaN(num) ? null : num;
  }

  function validate() {
    var errors = {};

    Object.keys(RULES).forEach(function (name) {
      var value = valueOf(name).toUpperCase();
      if (!value) {
        errors[name] = "Укажите " + RULES[name].label;
      } else if (!RULES[name].test(value)) {
        errors[name] = RULES[name].message;
      }
    });

    var dateValue = valueOf("purchase_date");
    if (!dateValue) {
      errors.purchase_date = "Укажите дату покупки";
    } else if (START_DATE && END_DATE && (dateValue < START_DATE || dateValue > END_DATE)) {
      errors.purchase_date = "Дата покупки должна попадать в период акции: " +
        fmtDate(START_DATE) + " — " + fmtDate(END_DATE);
    }

    var amountRaw = valueOf("amount");
    if (!amountRaw) {
      errors.amount = "Укажите сумму чека";
    } else {
      var amount = parseAmount(amountRaw);
      if (amount === null) {
        errors.amount = "Сумма должна быть числом, например 1200.50";
      } else if (amount <= 0) {
        errors.amount = "Сумма должна быть больше нуля";
      } else if (amount < MIN_AMOUNT) {
        errors.amount = "Минимальная сумма чека по условиям акции — " + fmtMoney(MIN_AMOUNT);
      }
    }

    var photo = form.querySelector('[name="photo"]');
    if (photo && photo.files && photo.files.length) {
      var file = photo.files[0];
      var allowed = (form.dataset.photoTypes || "").split(",").filter(Boolean);
      var ext = (file.name.split(".").pop() || "").toLowerCase();
      if (allowed.length && allowed.indexOf(ext) === -1) {
        errors.photo = "Поддерживаются только файлы: " + allowed.join(", ");
      } else if (form.dataset.photoMaxMb && file.size > parseInt(form.dataset.photoMaxMb, 10) * 1024 * 1024) {
        errors.photo = "Файл слишком большой: максимум " + form.dataset.photoMaxMb + " МБ";
      }
    }

    return errors;
  }

  function fmtDate(iso) {
    var parts = (iso || "").split("-");
    return parts.length === 3 ? parts[2] + "." + parts[1] + "." + parts[0] : iso;
  }

  /* Деньги тем же форматом, что и сервер: 1 000,00 ₽ */
  function fmtMoney(value) {
    try {
      return new Intl.NumberFormat("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value) + " ₽";
    } catch (e) {
      return value.toFixed(2).replace(".", ",") + " ₽";
    }
  }

  /* --- Подсветка ошибок ------------------------------------------------- */
  function renderErrors(errors, globalErrors) {
    // Сервер может ответить ошибкой уже после показа экрана успеха
    // (например, пользователь отправил тот же чек ещё раз) — возвращаем форму.
    form.hidden = false;
    if (successBox) successBox.hidden = true;
    clearAllErrors();
    var first = null;

    Object.keys(errors).forEach(function (name) {
      var list = [].concat(errors[name]);
      showError(name, list[0]);
      if (!first) first = form.querySelector('[name="' + name + '"]');
    });

    if (globalErrors && globalErrors.length) {
      var box = form.querySelector('[data-error-for="__all__"]');
      if (box) {
        box.textContent = globalErrors.join(" ");
        box.hidden = false;
      }
      if (alertBox && !first) {
        alertBox.textContent = globalErrors.join(" ");
        alertBox.hidden = false;
      }
    }

    if (first) {
      first.focus({ preventScroll: true });
      first.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  /* --- Валидация «на лету» --------------------------------------------- */
  form.querySelectorAll("input, textarea, select").forEach(function (input) {
    input.addEventListener("blur", function () {
      var name = input.name;
      if (!RULES[name] && name !== "amount" && name !== "purchase_date") return;
      var errors = validate();
      if (errors[name]) showError(name, errors[name]);
      else clearError(name);
    });
    input.addEventListener("input", function () {
      if (fieldWrap(input) && fieldWrap(input).classList.contains("field--invalid")) {
        clearError(input.name);
      }
    });
  });

  /* --- Отправка через fetch -------------------------------------------- */
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearAllErrors();

    var errors = validate();
    if (Object.keys(errors).length) {
      renderErrors(errors, []);
      return;
    }

    submitBtn.classList.add("is-loading");
    submitBtn.disabled = true;

    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "Fetch",
        "X-CSRFToken": (window.Luck && window.Luck.csrfToken()) || "",
        Accept: "application/json",
      },
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
      })
      .then(function (result) {
        submitBtn.classList.remove("is-loading");
        submitBtn.disabled = false;

        if (result.ok) {
          showSuccess(result.data);
          return;
        }

        var payload = result.data || {};
        var errors = {};
        var globals = [];
        Object.keys(payload.errors || {}).forEach(function (key) {
          if (key === "__all__") {
            globals = [].concat(payload.errors[key]);
          } else {
            errors[key] = [].concat(payload.errors[key]);
          }
        });
        if (payload.detail && !globals.length) globals.push(payload.detail);
        if (!Object.keys(errors).length && !globals.length) {
          globals.push("Не удалось отправить форму. Проверьте поля и попробуйте ещё раз.");
        }
        renderErrors(errors, globals);
      })
      .catch(function () {
        submitBtn.classList.remove("is-loading");
        submitBtn.disabled = false;
        renderErrors({}, ["Сеть недоступна. Проверьте соединение и попробуйте ещё раз."]);
      });
  });

  /* --- Экран успеха ----------------------------------------------------- */
  function showSuccess(data) {
    form.hidden = true;
    if (successBox) {
      var title = successBox.querySelector("[data-success-title]");
      var text = successBox.querySelector("[data-success-text]");
      var link = successBox.querySelector("[data-success-link]");
      if (title) title.textContent = data.is_resubmission ? "Чек отправлен повторно" : (data.message || "Ваш чек загружен");
      if (text) text.textContent = data.detail || "";
      if (link && data.redirect) link.setAttribute("href", data.redirect);
      successBox.hidden = false;
      successBox.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  /* --- Вставка строки из QR-кода --------------------------------------- */
  var qrInput = document.querySelector("[data-qr-input]");
  var qrBtn = document.querySelector("[data-qr-apply]");
  var qrMsg = document.querySelector("[data-qr-msg]");

  if (qrInput && qrBtn) {
    qrBtn.addEventListener("click", function () {
      var raw = qrInput.value.trim();
      if (!raw) {
        setQrMsg("Вставьте строку из QR-кода чека.", "error");
        return;
      }
      qrBtn.disabled = true;
      fetch(form.dataset.qrUrl || "/receipts/import-qr/", {
        method: "POST",
        body: new URLSearchParams({ qr: raw }),
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "Fetch",
          "X-CSRFToken": (window.Luck && window.Luck.csrfToken()) || "",
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          qrBtn.disabled = false;
          if (!data.ok) {
            var messages = (data.errors && data.errors.qr) || ["Не удалось разобрать строку."];
            setQrMsg([].concat(messages)[0], "error");
            return;
          }
          applyQr(data.fields);
          setQrMsg(
            (data.warning ? data.warning + " " : "") + "Поля заполнены из QR-кода — проверьте их и отправьте форму.",
            data.warning ? "error" : "ok"
          );
        })
        .catch(function () {
          qrBtn.disabled = false;
          setQrMsg("Не удалось разобрать строку на сервере. Проверьте данные вручную.", "error");
        });
    });
  }

  function setQrMsg(text, kind) {
    if (!qrMsg) return;
    qrMsg.textContent = text;
    qrMsg.className = "qr-helper__msg" + (kind ? " qr-helper__msg--" + kind : "");
  }

  function applyQr(fields) {
    Object.keys(fields || {}).forEach(function (key) {
      var input = form.querySelector('[name="' + key + '"]');
      if (input && typeof fields[key] === "string") {
        input.value = fields[key];
        clearError(key);
      }
    });
    // Дата и время приходят одним полем из HTML5-инпутов
    var dateInput = form.querySelector('[name="purchase_date"]');
    if (dateInput && fields.purchase_date) dateInput.value = fields.purchase_date;
    var timeInput = form.querySelector('[name="purchase_time"]');
    if (timeInput && fields.purchase_time) timeInput.value = fields.purchase_time;
  }
})();