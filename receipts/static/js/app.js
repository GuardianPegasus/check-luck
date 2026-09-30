/* Общие мелочи: CSRF-токен, мелкие утилиты. */
(function () {
  "use strict";

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : "";
  }

  window.Luck = {
    csrfToken: function () {
      const input = document.querySelector("[name=csrfmiddlewaretoken]");
      return (input && input.value) || getCookie("csrftoken");
    },

    getJSON: function (url) {
      return fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw Object.assign(new Error("HTTP " + response.status), { data: data });
          return data;
        });
      });
    },
  };
})();