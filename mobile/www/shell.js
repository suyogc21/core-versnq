// The app's own start page: the rep picks their company once; the native side remembers it and
// opens that company's Core (only that address may talk to the phone part). The offline page
// has no bridge, so it only uses plain links.
(function () {
  var Shell = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.VersnqShell;
  var form = document.getElementById("f");
  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var raw = document.getElementById("addr").value.trim().toLowerCase();
      var slug = raw.replace(/^https?:\/\//, "").split("/")[0].replace(/\.core\.versnq\.in$/, "");
      var err = document.getElementById("err");
      if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(slug)) { err.textContent = "Type just the first part, like acme."; return; }
      if (!Shell) { err.textContent = "Open this inside the Versnq Core app."; return; }
      err.textContent = "";
      Shell.setCompany({ slug: slug }).catch(function (x) { err.textContent = (x && x.message) || "Couldn't open that company."; });
    });
  }
  var retry = document.getElementById("retry");  // the offline page: ?core=<the company's address>
  if (retry) {
    var core = new URLSearchParams(location.search).get("core") || "";
    retry.addEventListener("click", function () {
      if (/^https:\/\/[a-z0-9-]+\.core\.versnq\.in$/.test(core)) location.href = core;
      else location.href = "versnq-core://reset";
    });
  }
})();
