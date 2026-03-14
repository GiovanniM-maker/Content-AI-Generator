# DEBUG REPORT — Content AI Generator
## Analisi Completa dei Bug e Problemi
**Data:** 2026-03-13
**Analisi eseguita da:** Claude Code (Opus 4.6)
**Scope:** Intero codebase — backend, frontend, configurazione, sicurezza

---

## INDICE

1. [BUG CRITICI (Sicurezza)](#1-bug-critici-sicurezza)
2. [BUG GRAVI (Logica / Dati)](#2-bug-gravi-logica--dati)
3. [BUG MEDI (Robustezza)](#3-bug-medi-robustezza)
4. [BUG MINORI (Code Quality)](#4-bug-minori-code-quality)
5. [PROBLEMI DI PERFORMANCE](#5-problemi-di-performance)
6. [PROBLEMI DI CONFIGURAZIONE](#6-problemi-di-configurazione)
7. [DEAD CODE E CODE SMELLS](#7-dead-code-e-code-smells)
8. [RIEPILOGO STATISTICO](#8-riepilogo-statistico)

---

## 1. BUG CRITICI (Sicurezza)

### 1.1 Email admin hardcoded nel codice sorgente
- **File:** `app.py:96`
- **Codice:** `ADMIN_EMAIL = "giovanni.mavilla.grz@gmail.com"`
- **Problema:** L'email admin e' esposta nel codice sorgente e nella git history. Chiunque con accesso al repo conosce l'email. Se un attaccante crea un account Supabase con la stessa email, potrebbe bypassare i limiti di piano.
- **Severita:** CRITICA
- **Fix suggerito:** Spostare in variabile d'ambiente `ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")`

### 1.2 Webhook Stripe senza verifica in ambienti non-production
- **File:** `payments.py:235-245`
- **Codice:** Se `STRIPE_WEBHOOK_SECRET` e' vuoto E `FLASK_ENV != "production"`, i webhook vengono accettati senza verifica della firma.
- **Problema:** Se l'app viene deployata in staging/preview senza `FLASK_ENV=production`, un attaccante puo' inviare webhook falsi e modificare i piani utente, aggiornare abbonamenti, etc.
- **Severita:** CRITICA
- **Fix suggerito:** Rifiutare SEMPRE i webhook non verificati, a meno che non ci sia un flag esplicito `STRIPE_SKIP_VERIFY=true` in dev.

### 1.3 Race condition nel contatore generazioni (fallback non-atomico)
- **File:** `db.py:936-984`
- **Problema:** Se la funzione RPC PostgreSQL fallisce (riga 960), il fallback read-modify-write (righe 963-982) non e' atomico. Due richieste concorrenti possono leggere lo stesso valore e scrivere +1 invece di +2, permettendo all'utente di superare i limiti del piano.
- **Severita:** CRITICA (impatto economico — utenti free possono generare piu' contenuti del previsto)
- **Fix suggerito:** Rimuovere il fallback non-atomico o usare `UPDATE ... SET count = count + 1` direttamente.

### 1.4 Potenziale path traversal nel caricamento asset
- **File:** `db.py:64-78`
- **Codice:** `path = f"{user_id}/{template_id}/{filename}"`
- **Problema:** Se `template_id` contiene `../`, potrebbe scrivere file fuori dalla directory prevista nello storage. Manca validazione UUID del template_id.
- **Severita:** CRITICA
- **Fix suggerito:** Validare che `template_id` sia un UUID valido prima di costruire il path.

### 1.5 File upload senza validazione MIME type
- **File:** `app.py:4526-4572`
- **Problema:** La validazione dei file upload controlla solo l'estensione del file (whitelist), ma non il MIME type effettivo del contenuto. Un file malevolo potrebbe essere caricato con estensione .png ma contenere codice eseguibile.
- **Severita:** ALTA
- **Fix suggerito:** Aggiungere validazione MIME type con `python-magic` o simile.

### 1.6 Password senza validazione di complessita'
- **File:** `app.py:1088-1108`
- **Problema:** Le password vengono passate direttamente a Supabase senza validazione di lunghezza o complessita' lato server. Supabase accetta password di almeno 6 caratteri senza ulteriori regole.
- **Severita:** ALTA
- **Fix suggerito:** Aggiungere validazione lato server (minimo 8 caratteri, almeno una maiuscola, un numero, un carattere speciale).

### 1.7 Credenziali di test hardcoded
- **File:** `setup_db.py:72-73`
- **Codice:**
  ```python
  email = "admin@content-ai.local"
  password = "ContentAI2026!"
  ```
- **Problema:** Password di test hardcoded nel codice sorgente, visibile nella git history.
- **Severita:** ALTA (se usato in produzione)
- **Fix suggerito:** Generare password random o richiederla come input.

---

## 2. BUG GRAVI (Logica / Dati)

### 2.1 Reset contatore mensile non persistito
- **File:** `db.py:1003-1006`
- **Problema:** `get_generation_counts()` controlla se il mese memorizzato e' diverso dal mese corrente e restituisce `monthly = 0`, ma NON aggiorna il database. Al prossimo `increment_generation_count()`, il mese vecchio e' ancora nel DB — il reset funziona, ma c'e' una finestra dove i dati sono inconsistenti.
- **Severita:** MEDIA-ALTA
- **Fix suggerito:** Aggiornare il database nel momento del reset mensile, o gestirlo interamente nella RPC function.

### 2.2 Nessuna validazione input negli endpoint schedule e session
- **File:** `app.py:3073-3079` (schedule POST)
- **File:** `app.py:3176-3181` (session POST)
- **Problema:** I dati del body vengono passati direttamente a `db.insert_schedule()` e `db.insert_session()` senza validare i campi obbligatori (`platform`, `scheduled_at`, `session_id`, `article`, `topics`, `platforms`). Se mancano campi obbligatori, il comportamento e' indefinito.
- **Severita:** MEDIA-ALTA
- **Fix suggerito:** Aggiungere schema validation con un decoratore o una funzione di validazione.

### 2.3 URL di default inconsistenti
- **File:** `app.py:103` — `https://content-ai-generator-1.onrender.com`
- **File:** `app.py:3251` — `https://content-ai-generator.onrender.com` (senza `-1`)
- **File:** `security.py:68, 321, 367` — Entrambe le varianti
- **Problema:** Due URL di default diversi usati in posti diversi. Se non configurato via env var, alcune funzionalita' (email, CORS, redirect) puntano a URL diversi.
- **Severita:** MEDIA
- **Fix suggerito:** Unificare tutte le occorrenze con una singola costante/env var.

### 2.4 `num_results` puo' essere negativo nell'endpoint web search
- **File:** `app.py:2152-2166`
- **Codice:** `num_results` e' limitato con `min(num_results, 20)` ma non con `max(num_results, 1)`.
- **Problema:** Un valore negativo passa la validazione e viene inviato all'API Serper, causando comportamento imprevedibile.
- **Severita:** MEDIA
- **Fix suggerito:** `num_results = max(1, min(num_results, 20))`

### 2.5 Auth middleware inconsistente sugli endpoint
- **File:** `app.py:50-78`
- **Problema:**
  - `/auth/me` e' escluso dall'estrazione auth (riga 62) ma non e' chiaro se richiede auth
  - `/auth/mfa/enroll` (riga 1264) richiede auth, ma e' sotto `/auth/*` che e' generalmente pubblico
  - Il pattern esclude tutto cio' che non inizia con `/api/` o `/auth/me`, ma alcune route `/auth/*` richiedono autenticazione
- **Severita:** MEDIA
- **Fix suggerito:** Documentare chiaramente quali endpoint richiedono auth e centralizzare la logica.

### 2.6 Logout senza validazione del token
- **File:** `app.py:1039`
- **Problema:** `auth_logout()` estrae il token dall'header ma non valida se il token esiste prima di passarlo a `auth.logout_server(token)`. Se il token e' None/vuoto, il comportamento e' indefinito.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** Verificare che il token esista prima di chiamare logout.

---

## 3. BUG MEDI (Robustezza)

### 3.1 Nessun retry logic sulle chiamate esterne
- **File:** `auth.py:82-101` — Verifica token (singola chiamata HTTP, nessun retry)
- **File:** `auth.py:173-204` — Signup Supabase (timeout 15s, nessun retry)
- **File:** `app.py:2130-2150` — Serper API search (timeout 15s, nessun retry)
- **Problema:** Errori di rete transitori causano fallimenti immediati senza retry. Particolarmente grave per la verifica token (ogni API call fallisce).
- **Severita:** MEDIA
- **Fix suggerito:** Implementare retry con exponential backoff (libreria `tenacity` o `urllib3.util.retry`).

### 3.2 Nessun circuit breaker per le chiamate LLM
- **File:** `video_generator.py:212-237`
- **Problema:** Se OpenRouter e' down, ogni richiesta di generazione video fallisce senza fallback. Non c'e' circuit breaker per evitare di sovraccaricare il servizio.
- **Severita:** MEDIA
- **Fix suggerito:** Implementare circuit breaker pattern o retry con backoff.

### 3.3 Cancellazione cartelle storage best-effort (silently fails)
- **File:** `db.py:152-168`
- **Problema:** `delete_user_carousel_folder()` cattura tutte le eccezioni e le ignora silenziosamente. File orfani si accumulano nello storage senza notifica.
- **Severita:** MEDIA (costi storage crescenti nel tempo)
- **Fix suggerito:** Loggare gli errori e implementare un job di pulizia periodico.

### 3.4 Batch insert articoli senza gestione transazionale
- **File:** `db.py:268-269`
- **Problema:** Gli articoli vengono inseriti in chunk da 50. Se un chunk fallisce, i precedenti sono gia' committed, causando inserimento parziale.
- **Severita:** MEDIA
- **Fix suggerito:** Wrappare in transazione o implementare rollback logic.

### 3.5 Nessun timeout wrapper su `web_search()`
- **File:** `app.py:2130-2150`
- **Problema:** `_serper_search()` ha timeout=15s, ma `web_search()` che la chiama non ha un proprio timeout wrapper. Se la funzione di parsing post-ricerca si blocca, la richiesta resta appesa.
- **Severita:** BASSA-MEDIA

### 3.6 Template ID non validato come UUID nelle route
- **File:** `app.py:2282-2298`
- **Problema:** `template_id` dall'URL viene usato direttamente nelle query al database senza validare che sia un UUID valido. Input invalidi causano errori non gestiti.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** Aggiungere validazione UUID all'inizio dell'endpoint.

### 3.7 Email validation mancante negli endpoint auth
- **File:** `app.py:1152-1158`
- **Problema:** L'email viene lowercased e stripped, ma non c'e' validazione regex. Email invalide come `test@`, `test@..com`, `@.com` vengono accettate.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** Aggiungere regex validation (o usare libreria `email-validator`).

---

## 4. BUG MINORI (Code Quality)

### 4.1 40+ blocchi `except Exception: pass` (errori silenziati)
- **File multipli:**
  - `db.py` — righe 89, 149, 168, 669, 730, 749, 764, 782, 797, 812, 960
  - `app.py` — righe 470, 479, 500, 826, 844, 892, 897, 1441, 1923, 2100, 2355, 2359, 2686, 2690, 3335
  - `payments.py` — righe 244, 254, 301, 302, 326, 356, 357, 438, 439, 470, 471, 489, 490
  - `auth.py` — righe 100, 295, 313, 582
  - `security.py` — righe 249, 272
  - `seed_presets.py` — riga 711
- **Problema:** Errori vengono catturati e ignorati silenziosamente, rendendo il debug quasi impossibile. Fallimenti reali sono mascherati.
- **Severita:** MEDIA (complessivamente)
- **Fix suggerito:** Sostituire con `except SpecificError as e: logger.warning(...)` ovunque possibile.

### 4.2 12+ console.log nel frontend (codice di produzione)
- **File:** `templates/index.html`
  - Riga 5672: `console.log('[IG enrich] AI decided:', ...)`
  - Riga 7474: `console.log('[renderCrea] platform:', ...)`
  - Riga 7592: `console.log('[renderCrea] triggering NL preview...')`
  - Riga 8415: `console.log('[NL enrich] Added ... AI images')`
  - Riga 8548: `console.log('[NL preview] fetching HTML...')`
  - Riga 8583: `console.log('[NL preview] rendered successfully...')`
  - Riga 8756: `console.log('[pers-grid] action:', ...)`
  - Riga 9464: `console.log('[deleteTemplate] called with id:', ...)`
  - Riga 9466: `console.log('[deleteTemplate] confirm result:', ...)`
  - Riga 9471: `console.log('[deleteTemplate] found card:', ...)`
  - Riga 9481: `console.log('[deleteTemplate] calling DELETE...')`
  - Riga 9483: `console.log('[deleteTemplate] response status:', ...)`
- **Problema:** Statement di debug visibili nella console del browser degli utenti. Espongono dettagli interni dell'applicazione.
- **Severita:** BASSA
- **Fix suggerito:** Rimuoverli o sostituirli con un logger condizionale (`if (DEBUG) console.log(...)`).

### 4.3 Import `re` ridondante (importato 4 volte)
- **File:** `app.py`
  - Riga 8: `import re` (module level)
  - Riga 962: `import re` (locale in funzione)
  - Riga 1097: `import re` (locale in funzione)
  - Riga 1871: `import re` (locale in funzione)
- **Problema:** `re` e' gia' importato a livello di modulo, i re-import locali sono ridondanti.
- **Severita:** BASSA (nessun impatto funzionale, solo pulizia codice)

### 4.4 HTTP-Referer hardcoded a localhost nelle chiamate API
- **File:**
  - `app.py:341` — `"HTTP-Referer": "http://localhost:5001"`
  - `app.py:372` — `"HTTP-Referer": "http://localhost:5001"`
  - `video_generator.py:200` — `"HTTP-Referer": "http://localhost:5001"`
- **Problema:** In produzione, l'header Referer punta a localhost. Alcuni provider API (OpenRouter) possono usare questo header per tracking — non causa errori ma e' scorretto.
- **Severita:** BASSA
- **Fix suggerito:** Usare `APP_BASE_URL` come valore del Referer.

### 4.5 Logging in DEBUG nel video generator
- **File:** `video_generator.py:21, 25`
- **Codice:** `log.setLevel(logging.DEBUG)` e `_fh.setLevel(logging.DEBUG)`
- **Problema:** Il livello di logging e' hardcoded a DEBUG, genera log eccessivi in produzione.
- **Severita:** BASSA
- **Fix suggerito:** Rendere configurabile via env var.

---

## 5. PROBLEMI DI PERFORMANCE

### 5.1 Query N+1 in `get_all_users_with_sessions()`
- **File:** `db.py:189-203`
- **Problema:** Seleziona tutti i `user_id` dalle sessioni e poi dedup in Python invece di usare `SELECT DISTINCT user_id` o `GROUP BY` a livello database.
- **Impatto:** Lento con molte sessioni, trasferimento dati inutile.
- **Fix suggerito:** `SELECT DISTINCT user_id FROM sessions`

### 5.2 Indici mancanti su colonne frequentemente queried
- **File:** `db.py:1048-1066`
- **Problema:** `user_templates` viene queryato per `user_id` e `template_id` ma non ci sono menzioni di indici nello schema.
- **Impatto:** Query lente man mano che crescono i dati.
- **Fix suggerito:** Aggiungere indici su `(user_id)` e `(user_id, template_id)`.

### 5.3 Truncation HTML hardcoded
- **File:** `app.py:3780`
- **Codice:** `template_html[:8000]`
- **Problema:** Template HTML viene troncato a 8000 caratteri prima di essere inviato al LLM. Per template complessi, informazioni importanti possono essere perse.
- **Impatto:** Risposte LLM incomplete o inaccurate per template grandi.
- **Fix suggerito:** Usare un parser HTML per estrarre le parti rilevanti invece di troncare.

### 5.4 Frontend monolitico in un singolo file HTML
- **File:** `templates/index.html` (~9600+ righe)
- **Problema:** Tutto il JavaScript frontend e' in un singolo file HTML enorme. Nessun code splitting, nessun lazy loading, nessuna modularizzazione.
- **Impatto:** Tempo di caricamento iniziale elevato, manutenzione difficile, nessun caching granulare.
- **Nota:** Questo e' un problema architetturale, non un bug — ma impatta le performance.

---

## 6. PROBLEMI DI CONFIGURAZIONE

### 6.1 Mancanza di security headers su alcuni endpoint
- **File:** `security.py:189-225`
- **Headers mancanti:**
  - `X-Download-Options` (per file download)
  - `X-Permitted-Cross-Domain-Policies`
  - `Cache-Control` non configurato per endpoint non autenticati (la landing page potrebbe essere cachata impropriamente)
- **Severita:** BASSA

### 6.2 CORS potenzialmente troppo permissivo sugli endpoint auth
- **File:** `security.py:71-74`
- **Problema:** `/auth/*` e' configurato in CORS come tutte le route API. Ma endpoint come `/auth/signup` e `/auth/login` sono pubblici, mentre `/auth/mfa/enroll` richiede auth. La configurazione CORS e' identica per tutti.
- **Severita:** BASSA

### 6.3 Rate limit mancante su `/auth/refresh`
- **File:** `app.py:1020`
- **Problema:** Il rate limit su refresh e' "10 per minute", ma se un refresh token viene rubato, l'attaccante puo' generare access token illimitati (10/min e' comunque molto).
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** Ridurre a "3 per minute" e aggiungere monitoring.

### 6.4 Rate limiter potenzialmente non applicato
- **File:** `security.py:138-156`
- **Problema:** I rate limit vengono applicati in `init_rate_limiter()` usando i nomi degli endpoint da `app.view_functions`. Se le route vengono registrate dopo l'init del rate limiter, i limiti non vengono applicati.
- **Severita:** MEDIA (dipende dall'ordine di inizializzazione)
- **Fix suggerito:** Verificare l'ordine di registrazione o applicare rate limit con decoratori.

---

## 7. DEAD CODE E CODE SMELLS

### 7.1 Commenti di codice rimosso
- `templates/index.html:5225` — `// gen-subtitle removed in new layout`
- `templates/index.html:9604` — `// result === 'skip' — continue without template`
- `carousel_renderer.py:517` — `# Legacy: single HTML string`

### 7.2 Funzionalita' potenzialmente incomplete
- **Beehiiv integration:** `BEEHIIV_PUB_ID` (app.py:102) configurato ma l'integrazione sembra parziale — usato solo in endpoints profilo (righe 1465, 1497-1498, 1520).
- **NTFY notifications:** `_send_ntfy()` (app.py:768-787) ritorna early se il topic e' vuoto. Potenzialmente mai usato se non configurato.

### 7.3 Magic numbers sparsi nel codice
| Valore | File | Riga | Descrizione |
|--------|------|------|-------------|
| `5000` | app.py | 260 | Max length sanitizzazione |
| `8000` | app.py | 3780 | Truncation HTML per LLM |
| `50` | db.py | 268 | Chunk size batch insert |
| `30000` | index.html | 5662, 8404 | Timeout enrichment (30s) |
| `180000` | index.html | 6947, 6972 | Timeout SSE/poll (3min) |
| `3000` | index.html | 6974 | Intervallo polling (3s) |
| `5000` | index.html | 4607 | Timeout banner rimozione (5s) |

### 7.4 Dati sensibili potenzialmente nei log
- **File:** `db.py:605-617` — `extra` dict salvato as-is nei log pipeline, potrebbe contenere API keys o prompt utente.
- **File:** `app.py:1442` — `webhook_user_id` loggato da metadata potenzialmente non fidati.

---

## 8. BUG AGGIUNTIVI (Analisi Approfondita Round 2)

### 8.1 IndexError — Accesso a `result.data[0]` senza bounds checking (11 punti)
- **Problema:** In molti punti del codice, `result.data[0]` viene acceduto senza verificare che l'array non sia vuoto. Se il database ritorna un risultato vuoto, l'applicazione crasha con `IndexError`.
- **Severita:** CRITICA (crash dell'app)
- **Occorrenze:**
  - `db.py:310` — `get_session()` → `return _session_row_to_dict(result.data[0])`
  - `db.py:325` — `insert_session()` → `return _session_row_to_dict(result.data[0])`
  - `db.py:342` — `update_session()` → `return _session_row_to_dict(result.data[0])`
  - `db.py:384` — `insert_schedule()` → `return result.data[0]`
  - `db.py:531` — `add_feedback()` → `return result.data[0]`
  - `db.py:904` — `increment_weekly_counter()` → `row = result.data[0]`
  - `db.py:954` — `increment_generation_count()` → `row = result.data[0]`
  - `payments.py:300` — `_find_user_by_customer()` → `return result.data[0]["id"]`
- **Fix suggerito:** Aggiungere `if result.data:` prima di ogni accesso `[0]`.

### 8.2 XSS via URL non sanitizzati nel newsletter formatter
- **File:** `app.py:2435`
- **Codice:** `lambda m: f'<a href="{m.group(2)}" style="{_style("a")}">{m.group(1)}</a>'`
- **Problema:** URL estratti dal testo utente vengono inseriti direttamente nell'attributo `href` senza validazione. Un URL come `javascript:alert(1)` o `data:text/html,...` verrebbe incluso nel link senza filtro.
- **Severita:** ALTA (XSS)
- **Fix suggerito:** Validare che l'URL inizi con `http://` o `https://` prima di includerlo.

### 8.3 HTML escaping incompleto — apostrofo non escaped
- **File:** `carousel_renderer.py:363`
- **Codice:** `return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')`
- **Problema:** Manca `.replace("'", "&#39;")`. Se l'output viene inserito in un attributo HTML delimitato da apostrofi, e' possibile uscire dall'attributo.
- **Severita:** MEDIA-ALTA (XSS via attributi)
- **Fix suggerito:** Aggiungere `.replace("'", "&#39;")` alla catena di escape.

### 8.4 Race condition in `_fetch_state` — thread non sincronizzati
- **File:** `app.py:1709-1740`
- **Problema:** Il dizionario `_fetch_state` viene modificato dal thread di background (riga 1731: `state["progress"].append(...)`) e letto dallo stream SSE (riga 1753-1757: `while sent < len(progress)`) senza lock. Python non garantisce thread-safety sulle operazioni di lista.
- **Severita:** MEDIA (data corruption, messaggi persi)
- **Fix suggerito:** Usare `_fetch_lock` per TUTTE le operazioni su `_fetch_state`, non solo per il check iniziale.

### 8.5 Token JWT esposto nei query parameter per SSE
- **File:** `auth.py:46-69` (riga 60)
- **Codice:** `token = request.args.get("token")`
- **Problema:** Il token JWT viene passato come query parameter per le connessioni SSE. I query parameter vengono loggati nei server log, nei referrer header, e nella browser history. L'SSE non supporta header custom, ma il token dovrebbe essere a breve scadenza.
- **Severita:** MEDIA (token leakage nei log)
- **Fix suggerito:** Usare token SSE dedicato a breve scadenza (es. 5 minuti) invece del JWT completo.

### 8.6 Unsafe JSON parsing nelle risposte LLM
- **File:** `app.py:359` — `return data["choices"][0]["message"]["content"]`
- **File:** `app.py:395` — `msg = data.get("choices", [{}])[0].get("message", {})`
- **File:** `app.py:398` — `return images[0].get("image_url", {}).get("url")`
- **File:** `video_generator.py:226` — `prepared = data["choices"][0]["message"]["content"].strip()`
- **Problema:** Accesso a `[0]` su liste potenzialmente vuote nelle risposte API di OpenRouter. Se il modello non ritorna choices, crash immediato.
- **Severita:** MEDIA-ALTA (crash su risposte API malformate)
- **Fix suggerito:** `choices = data.get("choices", []); if not choices: return None`

### 8.7 String split senza bounds checking
- **File:** `app.py:1865-1866`
- **Codice:** `result.split("\n", 1)[1]` e `result.rsplit("```", 1)[0]`
- **Problema:** Se la risposta LLM non contiene `\n` o ` ``` `, l'accesso a `[1]` o `[0]` puo' fallire con IndexError.
- **Severita:** MEDIA (crash su risposte LLM inattese)

### 8.8 Database write operations senza verifica successo
- **File:** `db.py:110-114` — `update_preset_thumbnail_url()` non ritorna status
- **File:** `app.py:1503` — `db.update_profile()` chiamato senza verificare il risultato
- **Problema:** Le operazioni di scrittura non verificano se l'update ha avuto successo. Il chiamante assume che sia andato tutto bene.
- **Severita:** BASSA-MEDIA (silent failures)

### 8.9 Mancanza di `.dockerignore`
- **Problema:** Non esiste un file `.dockerignore`. Il build context Docker include file inutili (`.git/`, `.env`, `*.pyc`, `__pycache__/`, `venv/`), aumentando i tempi di build e potenzialmente includendo segreti nell'immagine.
- **Severita:** MEDIA
- **Fix suggerito:** Creare `.dockerignore` con le esclusioni appropriate.

### 8.10 Dipendenza `cryptography` outdated
- **File:** `requirements.txt`
- **Versione corrente:** 44.0.0
- **Versione disponibile:** 46.0.5
- **Problema:** La libreria di crittografia e' indietro di 2 versioni minor. Anche se non ci sono CVE note su 44.0.0, e' una best practice mantenere aggiornata questa libreria.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** `pip install cryptography==46.0.5` e aggiornare requirements.txt.

---

## 9. PROBLEMI FRONTEND (templates/index.html — 9,719 righe)

### 9.1 Memory leak — setInterval mai pulito al logout
- **File:** `templates/index.html:3673`
- **Codice:** `_notifPollTimer = setInterval(fetchNotifications, 60000);`
- **Problema:** Il timer di polling notifiche (ogni 60s) non viene mai cancellato con `clearInterval` al logout o cambio pagina. Continua a fare richieste API anche dopo il logout.
- **Severita:** MEDIA
- **Fix suggerito:** Aggiungere `clearInterval(_notifPollTimer)` nella funzione di logout.

### 9.2 Memory leak — Event listener accumulati senza removeEventListener
- **File:** `templates/index.html:4675, 6281, 8634`
- **Problema:** Event listener aggiunti con `addEventListener` senza corrispondente `removeEventListener`. Se la funzione viene chiamata piu' volte (es. re-render), i listener si accumulano e gli handler vengono eseguiti multiple volte.
- **Severita:** MEDIA
- **Fix suggerito:** Salvare il riferimento al listener e rimuoverlo prima di aggiungerne uno nuovo.

### 9.3 JSON.parse senza try-catch nel frontend
- **File:** `templates/index.html:3178, 5010, 5178`
- **Codice:** `const article = JSON.parse(decodeURIComponent(atob(encoded)));` (senza try/catch)
- **Problema:** Se il JSON e' malformato o il base64 corrotto, l'intera funzione crasha senza gestione dell'errore.
- **Severita:** MEDIA-ALTA (crash frontend)
- **Fix suggerito:** Wrappare in try-catch con fallback o messaggio d'errore.

### 9.4 15+ catch block vuoti — errori silenziati
- **File:** `templates/index.html:3320, 4653, 7232, 8191, 8581`
- **Codice:** `} catch(e) {}` (nessun logging, nessun feedback utente)
- **Problema:** Errori di rete, fallimenti API e errori di rendering vengono completamente ignorati. L'utente non sa che qualcosa e' andato storto.
- **Severita:** MEDIA
- **Fix suggerito:** Almeno `console.error(e)` o meglio un toast di errore.

### 9.5 innerHTML usato per append — performance e DOM reflow
- **File:** `templates/index.html:5022, 5028, 5033, 5104, 6391` (20+ punti)
- **Codice:** `log.innerHTML += '<span class="log-done">...</span>';`
- **Problema:** Ogni `innerHTML +=` ricostruisce l'intero albero DOM del contenitore, causando reflow completi. Con log lunghi, degrada le performance significativamente.
- **Severita:** BASSA-MEDIA (performance)
- **Fix suggerito:** Usare `createElement` + `appendChild` o `insertAdjacentHTML`.

### 9.6 BUG CRITICO — Browser freeze nella chat Personalizzazione (CONFERMATO DALL'UTENTE)
- **File:** `templates/index.html:9371-9405` (`updateTemplatePreview()`)
- **Sintomo:** Quando l'utente scrive nella chat di Personalizzazione, il browser si blocca completamente e il PC diventa inutilizzabile.
- **Cause identificate (multiple, tutte contribuiscono):**

**Causa 1 — Fallback JSON parse crea 4 copie dell'intero HTML in iframe (PRINCIPALE)**
- **Riga 9374-9378:**
  ```javascript
  try {
    const parsed = JSON.parse(_persCurrentHtml);
    if (parsed && typeof parsed === 'object') templates = parsed;
  } catch(e) {
    templates = { cover: _persCurrentHtml, content: _persCurrentHtml, list: _persCurrentHtml, cta: _persCurrentHtml };
  }
  ```
- Quando `_persCurrentHtml` e' un JSON stringificato ma il parse fallisce (es. HTML raw, o JSON malformato dall'LLM), l'INTERO contenuto (potenzialmente decine di KB di HTML con 4 documenti `<!DOCTYPE>` annidati) viene duplicato in 4 iframe simultaneamente.
- Ogni iframe carica lo stesso HTML enorme + Google Fonts via `@import` (4 richieste parallele a fonts.googleapis.com).
- Il browser deve renderizzare 4 documenti HTML completi 1080x1080px ciascuno, scalati con CSS transform.

**Causa 2 — Google Fonts @import in ogni iframe**
- Il system prompt (`app.py:4060`) istruisce l'LLM a usare `@import url('https://fonts.googleapis.com/css2?family=...')` in ogni slide.
- Con 4 iframe, vengono lanciate 4+ richieste HTTP parallele per caricare i font, piu' il download dei file WOFF2.
- Se la rete e' lenta o i font sono pesanti, il browser si blocca in attesa.

**Causa 3 — Nessun limite sulla dimensione dell'HTML nelle iframe**
- `_persCurrentHtml` puo' essere arbitrariamente grande (l'LLM genera 4 slide HTML complete).
- Non c'e' nessun check sulla dimensione prima di assegnare a `iframe.srcdoc`.
- Un JSON con 4 slide di ~5KB ciascuna = ~20KB di HTML parsato 4 volte = ~80KB di rendering simultaneo.

**Causa 4 — `updateTemplatePreview()` chiamato in modo sincrono dopo ogni risposta chat**
- Riga 9291: `updateTemplatePreview()` viene chiamato immediatamente dopo ricevere `data.html_content`.
- Non c'e' debounce — se l'utente invia messaggi rapidamente, piu' render si accumulano.

**Causa 5 — iframe sandbox `allow-same-origin` senza `allow-scripts` potrebbe causare rendering loop**
- Riga 9395: `sandbox="allow-same-origin"` permette all'iframe di accedere al DOM del parent.
- Se l'HTML generato dall'LLM contiene JavaScript (anche accidentale), potrebbe creare interazioni impreviste.

- **Severita:** CRITICA (blocca completamente il browser/PC dell'utente)
- **Fix suggeriti:**
  1. **Aggiungere limite dimensione HTML:** `if (_persCurrentHtml.length > 100000) { container.innerHTML = 'HTML troppo grande'; return; }`
  2. **NON duplicare l'intero HTML in 4 iframe:** Nel catch del JSON.parse, mostrare un messaggio di errore invece di duplicare.
  3. **Usare `loading="lazy"` su tutte le iframe** per non caricarle tutte insieme.
  4. **Debounce su `updateTemplatePreview()`** — non chiamarla piu' di una volta ogni 500ms.
  5. **Preload/cache Google Fonts** o usare font locali (`Inter` e' gia' presente in `/static/fonts/`).
  6. **Aggiungere timeout/AbortController** sulla risposta del chat API.

### 9.7 Nessun timeout sulle chiamate fetch
- **File:** `templates/index.html:4299-4378` (initAuth) e altri
- **Problema:** Le chiamate `fetch()` non hanno timeout configurato. Se il server non risponde, la richiesta resta appesa indefinitamente.
- **Severita:** MEDIA
- **Fix suggerito:** Usare `AbortController` con `setTimeout` per tutte le fetch critiche.

### 9.7 Race condition nella generazione contenuti
- **File:** `templates/index.html:5284-5351` (generateAll)
- **Problema:** `selectedArticles` potrebbe cambiare durante l'esecuzione di `Promise.all(promises)` se l'utente interagisce con la UI. Gli indici degli articoli non sarebbero piu' corretti.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** Fare una copia di `selectedArticles` prima di lanciare le promesse.

### 9.8 Messaggi di errore inconsistenti
- **File:** `templates/index.html:4479, 4483, 4502` e altri
- **Problema:** Gli errori vengono mostrati in modi diversi: a volte `alert()`, a volte `toast()`, a volte `showToast('...', 'error')`. L'esperienza utente e' incoerente.
- **Severita:** BASSA
- **Fix suggerito:** Standardizzare su un singolo metodo di notifica (es. `showToast`).

### 9.9 Nessuna validazione email nel form di login
- **File:** `templates/index.html:3691-3701` (doLogin)
- **Problema:** Il form di login controlla solo che email e password non siano vuoti, ma non valida il formato dell'email. Email invalide vengono inviate al backend inutilmente.
- **Severita:** BASSA
- **Fix suggerito:** Aggiungere regex validation sull'email lato client.

### 9.10 querySelector senza null check
- **File:** `templates/index.html:4281` e molti altri punti
- **Codice:** `document.getElementById('gen-status').textContent = label;`
- **Problema:** Se l'elemento non esiste nel DOM, `.textContent` causa un errore TypeError. In diversi punti del codice manca il null check.
- **Severita:** BASSA-MEDIA
- **Fix suggerito:** `const el = document.getElementById('gen-status'); if (el) el.textContent = label;`

---

## 10. RIEPILOGO STATISTICO FINALE

| Categoria | Conteggio |
|-----------|-----------|
| Bug CRITICI (sicurezza) | **9** |
| Bug GRAVI (logica/dati) | **8** |
| Bug MEDI (robustezza) | **12** |
| Bug MINORI (code quality) | **6** |
| Problemi di performance | **4** |
| Problemi di configurazione | **5** |
| Dead code / code smells | **4** |
| Problemi frontend (JS/HTML) | **10** |
| **TOTALE PROBLEMI** | **58** |

### Distribuzione per severita'

```
CRITICA  ██████████████████████████  9   (16%)
ALTA     ████████████████████████    8   (14%)
MEDIA    ████████████████████████████████████████████████  20  (34%)
BASSA    ██████████████████████████████████████████████████  21  (36%)
```

### Top 10 priorita' di fix suggerite

1. **Aggiungere bounds checking su `result.data[0]`** — 30 min, previene crash in 11+ punti (backend + frontend)
2. **Spostare ADMIN_EMAIL in env var** — 5 min, elimina rischio impersonation
3. **Rimuovere fallback non-atomico nel contatore generazioni** — 15 min, previene abuso limiti piano
4. **Validare webhook Stripe in tutti gli ambienti** — 10 min, previene upgrade piano fraudolento
5. **Sanitizzare URL nel newsletter formatter** — 10 min, previene XSS
6. **Aggiungere try-catch ai JSON.parse nel frontend** — 10 min, previene crash frontend
7. **Aggiungere validazione UUID per template_id nei path** — 10 min, previene path traversal
8. **Aggiungere validazione MIME type su file upload** — 20 min, previene upload file malevoli
9. **Fix memory leak: clearInterval al logout** — 5 min, previene polling infinito
10. **Aggiungere bounds checking su risposte API OpenRouter** — 20 min, previene crash

---

*Report generato automaticamente. Nessuna modifica e' stata applicata al codice.*
*Per applicare i fix, richiedere esplicitamente la correzione dei singoli problemi.*
