(() => {
  const BRAND_NAME = "KAHLE-Vinci";
  const LOGO_URL = "/static/kahle/logo.png";
  const BACKGROUND_URL = "/static/kahle/chat-background.jpg";
  const PRIVILEGED_GROUPS = new Set(["Geschaeftsleitung", "Geschäftsleitung", "AI-Pilot"]);
  const HIDDEN_SETTINGS_LABELS = new Set([
    "Benutzeroberfläche",
    "Benutzeroberflaeche",
    "User Interface",
    "Interface",
    "Verbindungen",
    "Connections",
    "Integrationen",
    "Integrations",
    "Audio",
    "Datenkontrolle",
    "Data Controls",
    "Data Control"
  ]);
  const HIDDEN_ADVANCED_LABELS = new Set([
    "Erweiterte Parameter",
    "Advanced Parameters",
    "Advanced Params",
    "System-Prompt",
    "System Prompt"
  ]);

  let isPrivileged = false;
  let authLoaded = false;
  let accessLoadInFlight = false;
  let lastAccessLoadAt = 0;

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
      isPrivileged = Array.isArray(groups) && groups.some((group) => PRIVILEGED_GROUPS.has(group?.name));
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

  const findClickableContainer = (element) =>
    element?.closest("button,a,[role='button'],[data-state],.flex") || element;

  const hideMatchingLabels = () => {
    if (!authLoaded || isPrivileged) {
      return;
    }

    document.querySelectorAll("button, a, [role='button'], div, label").forEach((element) => {
      const label = textOf(element);
      if (!label) {
        return;
      }
      if (HIDDEN_SETTINGS_LABELS.has(label) || HIDDEN_ADVANCED_LABELS.has(label)) {
        findClickableContainer(element)?.setAttribute("data-kahle-hidden", "true");
      }
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
