# Motor real — estado y cómo encenderlo

Qué se hizo para que ZeroAI deje de "simular" y de verdad **juzgue y redacte** con
un modelo real, adaptándose a cada cliente — y que **no falle** con la salida
imperfecta de un LLM real.

## Mock vs. real (cómo funciona)
- **Mock** (default): cada agente sintetiza salida determinista offline. Sirve para
  desarrollar y demostrar sin red ni costo.
- **Real**: el agente manda su *system prompt* + el task JSON al backend (Anthropic o
  modelo local OpenAI-compatible), y parsea la respuesta. **Mismos prompts, mismo
  contrato** en ambos backends.

## Lo que se mejoró (esta sesión)
1. **Parseo a prueba de balas** (`zero/backends.py`, `zero/contracts.py`,
   `zero/agents/base.py`): los modelos reales devuelven JSON sucio. Ahora se aguanta:
   - code fences ```json```, prosa antes/después,
   - array desnudo (se envuelve como `{"leads": [...]}`),
   - envoltorio ausente (se levantan `leads`/`messages`/`rates`),
   - `status` inválido (se infiere), score como `"85"` o `85.0` (se coacciona),
   - **un fallo del backend (red/timeout) degrada en vez de crashear el pipeline.**
2. **Prompts reales** (`prompts/qualifier.md`, `prospector.md`, `outreach.md`):
   en español, con rúbrica de scoring 0–100, conscientes del **ICP del cliente** para
   adaptarse a su negocio (qué vende, a quién, zonas, medidas, restricciones).
3. **ICP por cliente** (`zero/icp.py`): perfil estructurado que viaja a PROSPECTOR /
   QUALIFIER / OUTREACH. Se normaliza, se **persiste por cliente** (memory) y se
   reutiliza en corridas siguientes. Campos: `industry, sells, buyer_roles,
   company_size, regions, must_have, exclude, context`.
4. **Tests del camino real** (`tests/test_real_engine.py`): un `ScriptedBackend`
   simula un LLM real (salida sucia) y corre el pipeline **completo por el camino real
   sin API key**. 14 tests nuevos; **40/40 verdes** en total.

## Cómo encenderlo
**Opción A — Anthropic (máxima calidad de prueba):**
1. Dashboard → Configuración → Anthropic → pega tu `sk-ant-...` (o `ANTHROPIC_API_KEY` en `.env`).
2. CLI: `python3 main.py --client acme --tier GROWTH --query "fintech LATAM" --live`

**Opción B — modelo local (destino de producción):**
- Levanta Ollama/vLLM y corre con `--local` (usa `LocalBackend`, sin costo por token).

### Config del servidor Ollama (si se reinstala la máquina)
Por defecto Ollama descarga el modelo de la RAM a los 5 minutos de inactividad — el
próximo mensaje después de eso paga el costo completo de recargarlo (~30s medido en
el Ryzen 7 9700X sin GPU, contra ~7-9s con el modelo ya caliente). Se subió a **30
minutos** con un override de systemd (no toca el `.service` original):
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_KEEP_ALIVE=30m"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama.service
```
**Ojo:** el campo `keep_alive` por request **no** funciona pasado por
`/v1/chat/completions` (el endpoint compatible con OpenAI que usa `LocalBackend`,
verificado en vivo 2026-07-06) — solo lo respeta la API nativa de Ollama
(`/api/chat`). Por eso el override va en el **servidor**, no en el código.

## Pasar un ICP por cliente (la adaptación)
Vía API:
```json
POST /api/pipeline
{ "client": "acme", "tier": "GROWTH", "query": "empresas de despacho RM",
  "icp": { "sells": "pallets de madera",
           "buyer_roles": ["Jefe de Logística"],
           "regions": ["RM","Valparaíso"],
           "must_have": ["camión >12m"] } }
```
El ICP queda guardado para ese cliente; las próximas corridas lo reutilizan.

## Lo que falta para "perfecto día 1" (pendiente)
- **Probar la CALIDAD real**: el código del camino real está probado; falta correr con
  tu key/modelo y **evaluar a ojo crítico** si los leads y mensajes son buenos. Eso solo
  se confirma con el modelo real.
- **Escala 10k**: hoy el backend carga datos en memoria por request. Para miles de
  empresas hay que **paginar/filtrar en la DB** (Supabase) — es el siguiente gran paso.
- **Auth/multi-tenant** para equipo + aislamiento por cliente.
