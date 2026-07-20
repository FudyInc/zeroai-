const STORAGE_KEY = "zeroai_waitlist";

const form = document.querySelector("#diagnosticForm");
const formNote = document.querySelector("#formNote");
const waitlistCount = document.querySelector("#waitlistCount");
const revealItems = document.querySelectorAll("[data-reveal]");

const getEntries = () => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
};

const setEntries = (entries) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  waitlistCount.textContent = String(entries.length);
};

setEntries(getEntries());

form?.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const entry = Object.fromEntries(formData.entries());
  entry.createdAt = new Date().toISOString();

  const entries = getEntries();
  const existingIndex = entries.findIndex(
    (item) => item.email?.toLowerCase() === entry.email.toLowerCase(),
  );

  if (existingIndex >= 0) {
    entries[existingIndex] = entry;
  } else {
    entries.push(entry);
  }

  setEntries(entries);
  form.reset();
  formNote.textContent =
    "Solicitud guardada. Quedaste en la waitlist para el diagn\u00f3stico gratuito.";
  formNote.classList.add("success");
});

// ---- Chat con Fernanda ----------------------------------------------------
// WhatsApp Business (Meta) aún no está aprobado. El flujo queda LISTO:
// cuando tengamos el número, poner aquí el valor (formato internacional,
// sin "+", ej: "56912345678") y el chat deriva la conversación a wa.me
// con el contexto del lead. Mientras, Fernanda responde en modo simulado
// y cada lead queda guardado en localStorage (zeroai_chat_leads).
const WHATSAPP_NUMBER = "";
const AGENT_NAME = "Fernanda";
const CHAT_KEY = "zeroai_chat_leads";
const CHAT_SEEN_KEY = "zeroai_chat_seen";

const chatFab = document.querySelector("#chatFab");
const chatWidget = document.querySelector("#chatWidget");
const chatClose = document.querySelector("#chatClose");
const chatForm = document.querySelector("#chatForm");
const chatThread = document.querySelector("#chatThread");

const openChat = () => {
  chatWidget.hidden = false;
  sessionStorage.setItem(CHAT_SEEN_KEY, "1");
};

const closeChat = () => {
  chatWidget.hidden = true;
};

chatFab?.addEventListener("click", () => {
  chatWidget.hidden ? openChat() : closeChat();
});
chatClose?.addEventListener("click", closeChat);
document.querySelectorAll("[data-chat-open]").forEach((trigger) => {
  trigger.addEventListener("click", openChat);
});

const addMessage = (kind, text) => {
  const bubble = document.createElement("p");
  bubble.className = `msg ${kind}`;
  bubble.textContent = text;
  chatThread.appendChild(bubble);
  chatThread.scrollTop = chatThread.scrollHeight;
  return bubble;
};

const addTyping = () => {
  const typing = document.createElement("span");
  typing.className = "typing";
  typing.innerHTML = "<i></i><i></i><i></i>";
  chatThread.appendChild(typing);
  chatThread.scrollTop = chatThread.scrollHeight;
  return typing;
};

chatForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(chatForm).entries());
  const fullPhone = `${data.prefix}${data.phone.replace(/\D/g, "")}`;
  const lead = {
    firstName: data.firstName.trim(),
    lastName: data.lastName.trim(),
    email: data.email.trim(),
    phone: fullPhone,
    source: "chat",
    createdAt: new Date().toISOString(),
  };

  try {
    const leads = JSON.parse(localStorage.getItem(CHAT_KEY) || "[]");
    leads.push(lead);
    localStorage.setItem(CHAT_KEY, JSON.stringify(leads));
  } catch {
    localStorage.setItem(CHAT_KEY, JSON.stringify([lead]));
  }

  if (WHATSAPP_NUMBER) {
    const text = encodeURIComponent(
      `Hola, soy ${lead.firstName} ${lead.lastName} (${lead.email}). Quiero saber cómo ZeroAI puede generar leads para mi empresa.`,
    );
    window.open(`https://wa.me/${WHATSAPP_NUMBER}?text=${text}`, "_blank", "noopener");
    return;
  }

  // Modo simulado mientras no está conectado WhatsApp Business.
  chatForm.hidden = true;
  chatThread.hidden = false;
  addMessage("user", `Hola, soy ${lead.firstName}. Quiero saber cómo funciona ZeroAI.`);

  const typing = addTyping();
  setTimeout(() => {
    typing.remove();
    addMessage(
      "agent",
      `¡Hola ${lead.firstName}! Soy ${AGENT_NAME}, de ZeroAI. Ya tengo tus datos — te escribo enseguida por WhatsApp al ${fullPhone} para agendar tu diagnóstico gratuito y contarte cómo armamos tu pipeline.`,
    );
  }, 1400);
});

// ---- Reveal on scroll ------------------------------------------------------
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.14 },
  );

  revealItems.forEach((item) => observer.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

// ---- Cover flow de canales -------------------------------------------------
(() => {
  const stage = document.querySelector("#coverStage");
  if (!stage) return;
  const glow = stage.querySelector(".cover-glow");
  const label = stage.querySelector(".cover-label");

  const CHANNELS = [
    { type: "instagram", name: "Instagram", accent: "#d6249f" },
    { type: "meta", name: "Meta", accent: "#0081FB" },
    { type: "whatsapp", name: "WhatsApp", accent: "#25D366" },
    { type: "phone", name: "Llamadas", accent: "#34C759" },
    { type: "gmail", name: "Gmail", accent: "#EA4335" },
  ];
  const BASE = 112;
  const N = CHANNELS.length;

  const iconSVG = (type, uid) => {
    switch (type) {
      case "instagram":
        return `<svg viewBox="0 0 100 100" width="${BASE}" height="${BASE}">
          <defs><radialGradient id="ig${uid}" cx="30%" cy="107%" r="140%">
            <stop offset="0%" stop-color="#fdf497"/><stop offset="8%" stop-color="#fdf497"/>
            <stop offset="45%" stop-color="#fd5949"/><stop offset="62%" stop-color="#d6249f"/>
            <stop offset="100%" stop-color="#285AEB"/></radialGradient></defs>
          <rect width="100" height="100" rx="24" fill="url(#ig${uid})"/>
          <rect x="26" y="26" width="48" height="48" rx="15" fill="none" stroke="#fff" stroke-width="6"/>
          <circle cx="50" cy="50" r="12.5" fill="none" stroke="#fff" stroke-width="6"/>
          <circle cx="68" cy="32" r="4" fill="#fff"/></svg>`;
      case "meta":
        return `<svg viewBox="0 0 100 100" width="${BASE}" height="${BASE}">
          <defs><linearGradient id="mt${uid}" x1="28" y1="58" x2="72" y2="42" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#0064E1"/><stop offset="55%" stop-color="#0098FF"/><stop offset="100%" stop-color="#00C6FF"/></linearGradient></defs>
          <rect width="100" height="100" rx="24" fill="#fff"/>
          <path d="M31 51 C31 42 37 38 43 41 C47.5 43.2 50 48 50 48 C50 48 52.5 43.2 57 41 C63 38 69 42 69 51 C69 60 63 64 57 61 C52.5 58.8 50 54 50 54 C50 54 47.5 58.8 43 61 C37 64 31 60 31 51 Z"
            fill="none" stroke="url(#mt${uid})" stroke-width="8.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      case "whatsapp":
        return `<svg viewBox="0 0 100 100" width="${BASE}" height="${BASE}">
          <rect width="100" height="100" rx="24" fill="#25D366"/>
          <path fill="#fff" d="M50 24 C36 24 25 35 25 49 C25 54 26.4 58.5 29 62.3 L26 76 L40.2 72.2 C43.8 74 47 74.4 50 74.4 C64 74.4 75 63 75 49 C75 35 64 24 50 24 Z"/>
          <path fill="#25D366" d="M41.5 39.2 C40.7 40 39.6 41.9 40.4 45 C42.4 52.7 49.3 59.6 57.3 61.9 C60.4 62.8 62.4 61.7 63.2 60.9 L66 58.2 C66.9 57.3 66.7 55.6 65.6 55 L60 51.8 C58.9 51.2 57.7 51.9 57 52.9 L55.6 54.7 C52.4 52.8 49.4 49.8 47.5 46.6 L49.3 45.2 C50.3 44.5 51 43.3 50.4 42.2 L47.2 36.6 C46.6 35.5 44.9 35.3 44 36.2 Z"/></svg>`;
      case "phone":
        return `<svg viewBox="0 0 100 100" width="${BASE}" height="${BASE}">
          <defs><linearGradient id="ph${uid}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#61FC7E"/><stop offset="100%" stop-color="#12CE4F"/></linearGradient></defs>
          <rect width="100" height="100" rx="24" fill="url(#ph${uid})"/>
          <path fill="#fff" d="M64.6 60.9 L59.3 55.6 C57.9 54.2 55.7 54.2 54.3 55.6 C52.4 57.5 49.6 57.5 47.9 55.9 C45.1 53.4 42.4 50.7 40 47.9 C38.3 46.2 38.4 43.4 40.3 41.5 C41.7 40.1 41.7 37.9 40.3 36.5 L35 31.2 C33.5 29.7 31 29.7 29.5 31.2 L26.8 33.9 C24.6 36.1 24.3 39.6 26 42.2 C33.4 53.7 43.3 63.6 54.8 71 C57.4 72.7 60.9 72.4 63.1 70.2 L65.8 67.5 C67.3 66 67.3 63.5 65.8 62 Z" transform="rotate(-6 50 50)"/></svg>`;
      case "gmail":
        return `<svg viewBox="0 0 100 100" width="${BASE}" height="${BASE}">
          <rect width="100" height="100" rx="24" fill="#fff"/>
          <rect x="1.5" y="1.5" width="97" height="97" rx="22.5" fill="none" stroke="#ededf0" stroke-width="3"/>
          <line x1="30" y1="64" x2="30" y2="43" stroke="#34A853" stroke-width="9.5" stroke-linecap="round"/>
          <line x1="30" y1="43" x2="50" y2="57" stroke="#EA4335" stroke-width="9.5" stroke-linecap="round"/>
          <line x1="50" y1="57" x2="70" y2="43" stroke="#FBBC05" stroke-width="9.5" stroke-linecap="round"/>
          <line x1="70" y1="43" x2="70" y2="64" stroke="#4285F4" stroke-width="9.5" stroke-linecap="round"/></svg>`;
    }
    return "";
  };

  const hexA = (hex, a) => {
    const h = hex.replace("#", "");
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  };

  const nodes = CHANNELS.map((c, i) => {
    const el = document.createElement("div");
    el.className = "node";
    el.style.width = BASE + "px";
    el.style.height = BASE + "px";
    el.innerHTML = iconSVG(c.type, "A" + i);
    stage.appendChild(el);
    return { c, i, el };
  });

  const render = (phase) => {
    const W = stage.clientWidth || 460;
    const H = stage.clientHeight || 300;
    const cx = W / 2;
    const cy = H / 2;
    const RX = Math.min(170, W * 0.37);
    const RY = 12;
    let front = null;
    let frontDepth = -2;

    const arr = nodes.map((n) => {
      const ang = (n.i / N) * Math.PI * 2 - phase;
      const depth = Math.cos(ang);
      const f = (depth + 1) / 2;
      const o = {
        n,
        depth,
        f,
        x: cx + RX * Math.sin(ang),
        y: cy - RY * Math.cos(ang),
        s: 0.5 + 0.62 * f,
        op: 0.25 + 0.75 * f,
        blur: (1 - f) * 2.6,
        z: Math.round(f * 100),
      };
      if (depth > frontDepth) {
        frontDepth = depth;
        front = o;
      }
      return o;
    });

    arr.forEach((o) => {
      const el = o.n.el;
      el.style.left = o.x + "px";
      el.style.top = o.y + "px";
      el.style.transform = `translate(-50%,-50%) scale(${o.s})`;
      el.style.zIndex = o.z;
      el.style.opacity = o.op;
      el.style.filter = `blur(${o.blur}px) drop-shadow(0 ${10 * o.f + 2}px ${18 * o.f + 6}px rgba(16,24,40,${0.08 + 0.12 * o.f}))`;
    });

    glow.style.left = front.x + "px";
    glow.style.top = front.y + "px";
    glow.style.transform = "translate(-50%,-50%)";
    glow.style.background = `radial-gradient(circle, ${hexA(front.n.c.accent, 0.2)} 0%, rgba(0,0,0,0) 66%)`;

    label.textContent = front.n.c.name;
    label.style.opacity = Math.max(0, (front.depth - 0.4) / 0.6);
  };

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    render(0);
    return;
  }

  let phase = 0;
  let last = null;
  let running = false;

  const frame = (now) => {
    if (!running) return;
    if (last === null) last = now;
    phase += ((now - last) / 1000) * 0.55;
    last = now;
    render(phase);
    requestAnimationFrame(frame);
  };

  const start = () => {
    if (running) return;
    running = true;
    last = null;
    requestAnimationFrame(frame);
  };
  const stop = () => {
    running = false;
  };

  render(0);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(
      (entries) => entries.forEach((e) => (e.isIntersecting ? start() : stop())),
      { threshold: 0.1 },
    ).observe(stage);
  } else {
    start();
  }
})();

// ---- FAQ accordion -----------------------------------------------------
document.querySelectorAll(".faq-q").forEach((btn) => {
  btn.addEventListener("click", () => {
    const expanded = btn.getAttribute("aria-expanded") === "true";
    document.querySelectorAll(".faq-q").forEach((other) => {
      if (other !== btn) other.setAttribute("aria-expanded", "false");
    });
    btn.setAttribute("aria-expanded", String(!expanded));
  });
});

// ---- Precios (fetch en vivo desde /api/public/plans) -------------------
// Mismo criterio que frontend/src/lib/api.js (VITE_API_URL): en desarrollo
// local pega directo al backend en :8800; en producción usa la URL pública
// del backend. La landing no tiene build step (sin Vite), así que no hay una
// env var real que inyectar aquí — esta constante cumple el mismo rol a mano.
//
// GET /api/public/plans ya existe y está desplegado (CORE, 2026-07-15) — sin
// login, exento en _OPEN_PATHS. Igual se deja el estado de error de abajo para
// cualquier falla de red/backend caído: nunca mostramos precios inventados
// como fallback.
const PRICING_API_BASE =
  location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://localhost:8800"
    : "https://handpick-monogamy-spiny.ngrok-free.dev"; // URL pública conocida (ngrok fijo) — confirmar con CORE si cambió

(() => {
  const grid = document.querySelector("#pricingGrid");
  if (!grid) return;

  // Copy propio de cada plan: no viene del backend (el backend solo manda
  // segment/price_clp/leads_per_mo), así que vive acá, a mano, alineado con
  // zero/config.py::TIERS. Sin Instagram ni LinkedIn/SDR-AI como promesa:
  // esos canales están en config.py pero se envían mock/borrador, no reales
  // (ver zero/channels.py: SENDABLE = ("email", "whatsapp")).
  // Política de precio fijo (2026-07-15, decisión de Diego): STARTER/GROWTH/SCALE
  // incluyen las plantillas de WhatsApp en el precio del plan — sin cobro extra
  // por plantilla ni por mensaje. ENTERPRISE queda fuera de esta garantía (volumen
  // y condiciones se negocian aparte, es para empresas más grandes).
  const PLAN_COPY = {
    STARTER: {
      highlight: false,
      checks: [
        "Scoring ICP genérico",
        "Contacto por email y WhatsApp",
        "Plantillas de WhatsApp incluidas, sin cobros extra",
      ],
    },
    GROWTH: {
      highlight: true,
      checks: [
        "Scoring ICP a tu medida",
        "Email, WhatsApp y llamadas",
        "Plantillas de WhatsApp incluidas, sin cobros extra",
      ],
    },
    SCALE: {
      highlight: false,
      checks: [
        "Scoring con señales de intención de compra",
        "Email, WhatsApp y llamadas a mayor volumen",
        "Plantillas de WhatsApp incluidas, sin cobros extra",
      ],
    },
    ENTERPRISE: {
      highlight: false,
      checks: [
        "Modelo de scoring por vertical",
        "Canales y volumen a medida",
        "Condiciones de WhatsApp se acuerdan a medida",
      ],
    },
  };
  const ORDER = ["STARTER", "GROWTH", "SCALE", "ENTERPRISE"];

  const clp = (n) => new Intl.NumberFormat("es-CL").format(n);

  const bindChatButtons = (root) => {
    root.querySelectorAll("[data-chat-open]").forEach((btn) => {
      btn.addEventListener("click", openChat);
    });
  };

  const renderError = () => {
    grid.innerHTML =
      '<p class="pricing-error">No pudimos cargar los precios en este momento. ' +
      '<button type="button" data-chat-open>Escríbenos</button> y te los confirmamos al tiro.</p>';
    bindChatButtons(grid);
  };

  const renderPlans = (plans) => {
    const cards = ORDER.filter((key) => plans[key]).map((key) => {
      const p = plans[key];
      const copy = PLAN_COPY[key] || { checks: [], highlight: false };
      const priceBlock =
        p.price_clp != null
          ? `<div class="price-amount"><strong>$${clp(p.price_clp)}</strong><span>CLP/mes</span></div>`
          : '<div class="price-amount price-amount-custom"><strong>A medida</strong></div>';
      const leadsLine =
        p.leads_per_mo != null
          ? `<p class="price-leads">${clp(p.leads_per_mo)} leads calificados/mes</p>`
          : '<p class="price-leads">Volumen a medida</p>';
      const checksHtml = copy.checks.map((c) => `<li>${c}</li>`).join("");
      const badge = copy.highlight ? '<span class="price-badge">Más elegido</span>' : "";
      return (
        `<article class="price-card${copy.highlight ? " price-card-featured" : ""}">` +
        badge +
        `<span class="price-segment">${p.segment}</span>` +
        priceBlock +
        leadsLine +
        `<ul class="price-checks">${checksHtml}</ul>` +
        '<button class="btn btn-dark" type="button" data-chat-open>Hablar con Fernanda</button>' +
        "</article>"
      );
    });

    grid.innerHTML =
      cards.join("") +
      '<p class="pricing-note">¿Necesitas algo distinto? El plan Enterprise se arma a medida — habla con nosotros.</p>';
    bindChatButtons(grid);
  };

  fetch(PRICING_API_BASE + "/api/public/plans", {
    headers: { "ngrok-skip-browser-warning": "true" },
  })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((data) => {
      if (!data || !data.plans) throw new Error("Respuesta sin plans");
      renderPlans(data.plans);
    })
    .catch(() => renderError());
})();
