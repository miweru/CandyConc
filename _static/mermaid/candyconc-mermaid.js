// Renders the Mermaid diagrams of a page with the copy of Mermaid that ships
// with the documentation. A classic script (not an ES module), so diagrams
// also render when the pages are opened directly from the file system.
(function () {
  function theme() {
    var t = document.documentElement.dataset.theme;
    if (t === "dark") return "dark";
    if (t === "light") return "default";
    var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return dark ? "dark" : "default";
  }

  var lastTheme = null;

  function render() {
    if (!window.mermaid) return;
    var current = theme();
    if (current === lastTheme) return;
    lastTheme = current;
    var nodes = Array.prototype.slice.call(document.querySelectorAll("pre.mermaid"));
    nodes.forEach(function (el) {
      if (el.dataset.source === undefined) {
        el.dataset.source = el.textContent;
      } else {
        el.removeAttribute("data-processed");
        el.textContent = el.dataset.source;
      }
    });
    window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: current });
    window.mermaid.run({ nodes: nodes });
  }

  document.addEventListener("DOMContentLoaded", render);
  // Render again when the reader switches between light and dark mode.
  new MutationObserver(render).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
})();
