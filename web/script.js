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

// Popup automático (una vez por sesión), como Nexor.
if (!sessionStorage.getItem(CHAT_SEEN_KEY)) {
  setTimeout(openChat, 3500);
}

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
