(() => {
  const BRAND_NAME = "KAHLE-Vinci";
  const LOGO_URL = "/static/kahle/logo.png";
  const BACKGROUND_URL = "/static/kahle/chat-background.jpg";
  const PRIVILEGED_GROUPS = new Set(["administrator", "geschaftsleitung", "geschaeftsleitung", "ai-pilot"]);
  const HIDDEN_SETTINGS_LABELS = new Set([
    "benutzeroberflache",
    "benutzeroberflaeche",
    "user interface",
    "interface",
    "verbindungen",
    "connections",
    "integrationen",
    "integrations",
    "audio",
    "datenkontrolle",
    "data controls",
    "data control"
  ]);
  const HIDDEN_ADVANCED_LABELS = new Set([
    "erweiterte parameter",
    "advanced parameters",
    "advanced params",
    "system-prompt",
    "system prompt"
  ]);
  let isPrivileged = false;
  let authLoaded = false;
  let accessLoadInFlight = false;
  let lastAccessLoadAt = 0;

  const normalizeLabel = (value) =>
    (value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\u00c3\u00a4/g, "a")
      .replace(/\u00c3\u0084/g, "a")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();

  const jsonFetch = async (url) => {
    const response = await fetch(url, {
      credentials: "include",
      headers: localStorage.token ? { Authorization: `Bearer ${localStorage.token}` } : {}
    });
    if (!response.ok) {
      throw new Error(`${url} returned ${response.status}`);
    }
    return response.json();
  };

  const loadAccess = async () => {
    if (accessLoadInFlight) {
      return;
    }
    accessLoadInFlight = true;
    lastAccessLoadAt = Date.now();
    try {
      const user = await jsonFetch("/api/v1/auths/");
      if (user?.role === "admin") {
        isPrivileged = true;
        return;
      }

      const groups = await jsonFetch("/api/v1/groups/");
      isPrivileged =
        Array.isArray(groups) &&
        groups.some((group) => PRIVILEGED_GROUPS.has(normalizeLabel(group?.name)));
    } catch {
      isPrivileged = false;
    } finally {
      accessLoadInFlight = false;
      authLoaded = true;
      document.body.classList.toggle("kahle-hide-advanced-settings", !isPrivileged);
      applyBranding();
    }
  };

  const refreshAccessSoon = () => {
    if (Date.now() - lastAccessLoadAt > 2500) {
      void loadAccess();
    }
  };

  const textOf = (element) => (element?.textContent || "").replace(/\s+/g, " ").trim();

  const isVisibleBox = (element) => {
    const rect = element?.getBoundingClientRect?.();
    return Boolean(rect && rect.width > 0 && rect.height > 0);
  };

  const normalizedTextOf = (element) => normalizeLabel(textOf(element));

  const setAttributeIfChanged = (element, name, value) => {
    if (element?.getAttribute?.(name) !== value) {
      element?.setAttribute?.(name, value);
    }
  };

  const matchesHiddenLabel = (label) =>
    HIDDEN_SETTINGS_LABELS.has(label) ||
    HIDDEN_ADVANCED_LABELS.has(label) ||
    (label.length <= 140 && [...HIDDEN_ADVANCED_LABELS].some((hiddenLabel) => label.includes(hiddenLabel)));

  const findSettingsRow = (element) => {
    const interactive = element.closest("button,a,[role='button'],li");
    if (interactive && isVisibleBox(interactive)) {
      return interactive;
    }

    let current = element;
    let best = element;
    while (current?.parentElement && current.parentElement !== document.body) {
      const rect = current.getBoundingClientRect();
      const ownText = normalizedTextOf(current);
      const parentText = normalizedTextOf(current.parentElement);

      if (rect.height > 0 && rect.height <= 140 && ownText && parentText.length <= Math.max(160, ownText.length + 80)) {
        best = current;
      }

      if (
        parentText.includes("webui-einstellungen") ||
        parentText.includes("settings") ||
        parentText.length > 500
      ) {
        break;
      }
      current = current.parentElement;
    }
    return best;
  };

  const hideMatchingLabels = () => {
    if (!authLoaded) {
      return;
    }

    if (isPrivileged) {
      document.querySelectorAll("[data-kahle-hidden='true']").forEach((element) => {
        element.removeAttribute("data-kahle-hidden");
      });
      return;
    }

    document.querySelectorAll("button, a, [role='button'], li, div, label, span").forEach((element) => {
      const label = normalizedTextOf(element);
      if (!label || !matchesHiddenLabel(label)) {
        return;
      }
      setAttributeIfChanged(findSettingsRow(element), "data-kahle-hidden", "true");
    });
  };

  const replaceBrandText = () => {
    document.querySelectorAll("title, h1, h2, button, a, span, div").forEach((element) => {
      for (const node of element.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && node.nodeValue?.includes("Open WebUI")) {
          node.nodeValue = node.nodeValue.replaceAll("Open WebUI", BRAND_NAME);
        }
      }
    });
    document.title = document.title.replaceAll("Open WebUI", BRAND_NAME);
  };

  const replaceLogoImages = () => {
    document.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src") || "";
      const alt = img.getAttribute("alt") || "";
      if (src.includes("/static/favicon") || src.includes("/static/logo") || alt.includes("Open WebUI")) {
        img.setAttribute("src", LOGO_URL);
        img.setAttribute("alt", BRAND_NAME);
      }
    });
  };

  const applyBackgroundFallback = () => {
    document.documentElement.style.setProperty("--kahle-chat-background", `url("${BACKGROUND_URL}")`);
    document.body.classList.add("kahle-branding-ready");
    document.body.classList.remove("kahle-chat-background-active");
    document.getElementById("kahle-chat-background-layer")?.remove();
    document.querySelectorAll("[data-kahle-chat-transparent], [data-kahle-app-foreground]").forEach((element) => {
      element.removeAttribute("data-kahle-chat-transparent");
      element.removeAttribute("data-kahle-app-foreground");
    });
  };

  const applyBranding = () => {
    replaceBrandText();
    replaceLogoImages();
    applyBackgroundFallback();
    hideMatchingLabels();
    refreshAccessSoon();
  };

  const observer = new MutationObserver(() => {
    window.requestAnimationFrame(applyBranding);
  });

  const start = () => {
    applyBranding();
    observer.observe(document.documentElement, { childList: true, subtree: true });
    loadAccess();
    window.addEventListener("focus", loadAccess);
    window.addEventListener("popstate", loadAccess);
    window.setInterval(refreshAccessSoon, 5000);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
