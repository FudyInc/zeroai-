# Voz — ElevenLabs (acento chileno ABC1)

ZERO escribe **qué decir**; ElevenLabs pone **cómo suena**. El acento NO se entrena en
el LLM — viene de la *voz*. Para el santiaguino ABC1, la jugada es **clonar una voz real**
(las voces de catálogo suenan neutras/mexicanas, no chilenas).

## Lo que haces tú en ElevenLabs (yo no puedo: es tu cuenta)

1. **Cuenta + plan.** Crea cuenta en elevenlabs.io. La **clonación instantánea** requiere
   un plan pago (Starter ~US$5/mes). El plan free no clona.
2. **API key.** Profile → API Keys → copiá la key.
3. **Muestra de voz.** Conseguí audio limpio (sin ruido, sin música) de un/a chileno/a
   santiaguino/a ABC1 con tono neutro:
   - Clon **instantáneo**: ~1–3 min de audio basta.
   - Clon **profesional** (mejor calidad): 30+ min, y aprobación.
   - Puede ser tu propia voz, o la de alguien (con su permiso).
   - Que lea variado: saludo, una frase de venta, números, preguntas.
4. **Clonar.** En ElevenLabs → **Voices → Add Voice → Instant Voice Clone** → subí el
   audio → ponele nombre ("Fernanda CL") → te queda un **Voice ID**.

## Lo que ZERO ya tiene listo (mi parte)

[`zero/voice.py`](../zero/voice.py) — convierte texto en audio con tu voz clonada:

```bash
export ELEVENLABS_API_KEY=tu_key

# ver tus voces y sus ids (encontrá el de tu clon)
python3 -m zero.voice --voices

# generar audio con el guion de venta
python3 -m zero.voice --voice-id TU_VOICE_ID \
  --text "Hola, soy Fernanda de ZeroAI. Te llamo porque ayudamos a empresas como la tuya a conseguir leads B2B ya calificados..." \
  --out fernanda.mp3
```

Usa el modelo `eleven_multilingual_v2` (español natural). El acento lo da tu voz clonada.

## Lo honesto: esto es solo la VOZ, no el agente de llamadas completo

Hacer que *llame de verdad y converse* necesita además:
`STT` (oír al prospecto) + `LLM` (conversación) + **telefonía** (Twilio) + orquestación en
tiempo real. Eso lo arman plataformas como **Vapi / Retell / Bland / ElevenLabs
Conversational AI** (todas con tu cuenta/keys).

Y siempre: **no se ofrece por cuenta propia, pero si preguntan directo, no se niega**
("trabajo con ayuda de IA, pero esto es real"). Voz natural ✓; negar que hay IA ✗.
