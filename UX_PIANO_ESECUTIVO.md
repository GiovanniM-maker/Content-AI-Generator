# PIANO ESECUTIVO — UX Redesign "Content AI Generator"

> Documento di riferimento per la riprogettazione completa dell'esperienza utente.
> Combina due analisi indipendenti in un piano unico, coerente e prioritizzato.

---

## LA PERSONA: MARCO

Marco, 42 anni, consulente aziendale di Brescia.
Ha sentito parlare di "AI per i social" da un collega.
Non sa cosa sia un feed RSS. Ha un profilo LinkedIn che aggiorna ogni morte di papa.
Ha cliccato il CTA perché la landing prometteva "contenuti in 5 minuti".

**Cosa si aspetta Marco:** scrivere qualcosa e ricevere un post da pubblicare.
Input -> Output. Come ChatGPT.

**Cosa vede Marco oggi:** una sidebar con 7 voci in inglese, "Feed Refresh" come prima schermata, e 10 decisioni da prendere prima di vedere il primo contenuto.

**Risultato:** Marco chiude il browser.

---

## JOB-TO-BE-DONE

> "Voglio pubblicare contenuti di qualita senza perdere tempo a pensare a cosa scrivere."

Non e "voglio gestire feed RSS". Non e "voglio fare Feed Refresh".
Quelle sono implementazioni, non obiettivi.

---

## I 10 PROBLEMI DIAGNOSTICATI

| # | Problema | Diagnosi | Gravita |
|---|----------|----------|---------|
| 1 | **Nessun onboarding** | L'utente arriva in dashboard vuota con 7 voci sidebar, non sa da dove partire | CRITICO |
| 2 | **Lingua mista IT/EN** | Sidebar in EN ("Feed Refresh", "Approve", "Source mode"), target italiano | ALTO |
| 3 | **Opinione DOPO la generazione** | Architettura sbagliata: l'opinione e INPUT, non post-processing. Brucia una generazione extra | CRITICO |
| 4 | **Feature bloccate = errore 403** | Dark pattern involontario. L'utente prova a generare Instagram su piano Free, riceve errore. Nessun avviso prima | CRITICO |
| 5 | **3 modalita sorgente confuse** | Tab "Feed RSS / Testo Custom / Ricerca Web" alla pari senza guida su quando usare cosa | ALTO |
| 6 | **Flusso lineare in navigazione ad albero** | Non puoi generare senza selezionare, non puoi selezionare senza refresh. Ma la sidebar permette di saltare ovunque = conflitto strutturale | CRITICO |
| 7 | **RSS e una feature, non un dettaglio tecnico** | Se un utente free non ha configurato RSS, "Feed Refresh" non funziona. L'app appare rotta | CRITICO |
| 8 | **Scheduling poco chiaro** | L'utente pensa di programmare la pubblicazione automatica, ma riceve solo un reminder | MEDIO |
| 9 | **History inutilizzabile** | Elenco piatto senza filtri, ricerca, preview. Con 50+ sessioni diventa inutile | MEDIO |
| 10 | **Monitor e per developer** | Prompt Changelog, Pipeline Log, Feed Health: l'utente medio non sa cosa farsene | BASSO |

---

## I 6 PRINCIPI DEL NUOVO DESIGN

### Principio 1 — Una pagina, un obiettivo
L'utente fa tutto dalla stessa pagina. Il flusso si svela progressivamente.
Mai step che richiedono di navigare via.

### Principio 2 — L'opinione e INPUT, non modifica
Prima di generare, l'utente scrive la sua angolazione.
Campo opzionale ma visibile. Nessuna generazione "sprecata".

### Principio 3 — Le feature bloccate motivano, non frustrano
Le piattaforme Pro sono visibili con lock + tooltip "Disponibile con Pro".
L'utente capisce il valore prima di sbloccare.

### Principio 4 — RSS e un dettaglio tecnico, non una feature
L'utente non deve mai fare "Feed Refresh" manualmente.
Il flusso primario funziona con Web Search out-of-the-box, zero config.

### Principio 5 — Il contatore generazioni e sempre visibile
Si aggiorna in real-time. Mai scoprire il limite da un errore 403.

### Principio 6 — Tutto in italiano
Ogni label, tooltip, placeholder, errore, CTA. Zero inglese.

---

## ARCHITETTURA NUOVA — DA SIDEBAR 7 VOCI A TOPBAR 3 TAB

### PRIMA (attuale):
```
SIDEBAR (7 voci):
  Feed Refresh
  Topic Selection
  Content Generation
  Programmazione
  History
  Impostazioni
  Monitor
```

### DOPO (nuovo):
```
TOPBAR (3 tab + utility):

  [Crea]  [Pianifica]  [Libreria]          [3/10 gen] [Profilo]
```

**Mappatura:**
- Feed Refresh + Topic Selection + Content Generation = **TAB "Crea"** (tutto in 1 pagina)
- Programmazione = **TAB "Pianifica"** (calendario)
- History + Impostazioni = **TAB "Libreria"** (contenuti passati + config)
- Monitor = nascosto sotto Libreria > Avanzate (solo power user)

---

## ONBOARDING — SOLO PRIMA VOLTA (3 slide)

```
SLIDE 1:
  "Ecco cosa fa Content AI Generator"
  [Illustrazione: 1 articolo entra -> 5 contenuti escono]

SLIDE 2:
  "Scegli un argomento, aggiungi la tua voce"
  [Illustrazione: campo testo + icone piattaforme]

SLIDE 3:
  "Ottieni 5 contenuti pronti in 60 secondi"
  [CTA: "Inizia subito ->"]
```

**Regole:**
- Massimo 3 slide, skippabili
- Zero configurazione richiesta (i feed RSS NON servono per iniziare)
- Il CTA porta direttamente al tab "Crea"
- Flag `onboarding_completed` in user settings per non rimostrarlo

---

## TAB "CREA" — IL CUORE DELL'APP

### Layout: 1 pagina, 3 zone verticali + risultati sotto

```
┌─────────────────────────────────────────────────────────┐
│  [Crea]  [Pianifica]  [Libreria]      [3/10 gen] [⚙]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ZONA 1 — DA DOVE PARTIAMO?                            │
│  ┌────────────────────────────────────────────────┐    │
│  │                                                │    │
│  │  🔍 Cerca sul web    📡 Dai tuoi feed   ✏ Scrivi tu │
│  │  [═══════════════]                              │    │
│  │  [campo di ricerca — default attivo]            │    │
│  │                                                │    │
│  │  Risultati / Articoli appaiono qui sotto:      │    │
│  │  ○ Titolo articolo 1              Score: 92    │    │
│  │  ○ Titolo articolo 2              Score: 85    │    │
│  │  ○ Titolo articolo 3              Score: 78    │    │
│  │                                                │    │
│  │  Seleziona fino a 3 fonti                      │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ZONA 2 — LA TUA VOCE                                  │
│  ┌────────────────────────────────────────────────┐    │
│  │  💬 Aggiungi la tua angolazione (facoltativo)  │    │
│  │  ┌──────────────────────────────────────────┐  │    │
│  │  │ Es: "Secondo me questa tecnologia        │  │    │
│  │  │ cambiera il modo in cui..."               │  │    │
│  │  └──────────────────────────────────────────┘  │    │
│  │  Tip: Basta 1-2 frasi. L'AI fara il resto.   │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ZONA 3 — DOVE PUBBLICARE                              │
│  ┌────────────────────────────────────────────────┐    │
│  │  Seleziona piattaforme:                        │    │
│  │  [v] 💼 LinkedIn — Post professionale          │    │
│  │  [v] 📧 Newsletter — Email HTML pronta         │    │
│  │  [🔒] 📸 Instagram — Sblocca con Pro           │    │
│  │  [🔒] 🐦 Twitter — Sblocca con Pro             │    │
│  │  [🔒] 🎬 Video Script — Sblocca con Pro        │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  [🚀 Genera Contenuti — Usera 1 delle tue 3/10 gen]   │
│                                                         │
├ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
│                                                         │
│  RISULTATI (appaiono qui dopo la generazione)           │
│                                                         │
│  Tab per piattaforma: [LinkedIn] [Newsletter]           │
│                                                         │
│  ┌─ LinkedIn ─────────────────────────────────────┐    │
│  │ [Contenuto generato, editabile in-place]        │    │
│  │                                                 │    │
│  │ [📋 Copia] [👍 Approva] [📅 Programma]        │    │
│  │ [🔄 Rigenera con feedback]                      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  [🔄 Ricomincia]     [📚 Vai alla libreria]            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Comportamento dettagliato ZONA 1:

**Tab "Cerca sul web" (DEFAULT):**
- Campo di ricerca con placeholder: "Cerca un argomento, es: intelligenza artificiale nel marketing"
- Risultati appaiono live sotto il campo
- Ogni risultato ha titolo + snippet + score
- L'utente seleziona 1-3 risultati (radio/checkbox)
- FUNZIONA IMMEDIATAMENTE, zero configurazione richiesta

**Tab "Dai tuoi feed":**
- Se l'utente ha feed configurati: mostra articoli gia analizzati (refresh automatico in background, MAI manuale)
- Se NON ha feed: mostra messaggio amichevole "Non hai ancora aggiunto fonti RSS. Vuoi configurarle?" con link a Libreria > Impostazioni, OPPURE "Intanto prova la ricerca web!"
- Mai schermata vuota, mai errore

**Tab "Scrivi tu":**
- Textarea grande
- Placeholder: "Incolla un articolo, un appunto, o scrivi direttamente il tema che vuoi trattare"
- Bottone "Usa questo testo" che attiva Zona 2 e 3

### Comportamento dettagliato ZONA 2:

- Campo SEMPRE visibile (non collassato, non nascosto)
- Label: "Aggiungi la tua angolazione (facoltativo)"
- Placeholder con esempio concreto
- Tip sotto: "Basta 1-2 frasi. L'AI fara il resto."
- Se l'utente non scrive nulla: va bene, si genera senza opinione
- QUESTO RISOLVE IL PROBLEMA #3: l'opinione e INPUT, non post-processing

### Comportamento dettagliato ZONA 3:

- Piattaforme Free: checkbox normale con nome + descrizione 1 riga
- Piattaforme Pro: visibili con icona lock + "Sblocca con Pro" al click apre modal pricing
- Counter live: "Selezionate: 2 piattaforme"
- QUESTO RISOLVE IL PROBLEMA #4: mai errore 403, il lock e preventivo

### CTA "Genera Contenuti":

- Testo: "🚀 Genera Contenuti"
- Sotto-testo: "Usera 1 delle tue 3/10 generazioni"
- Disabilitato se: nessun articolo selezionato O nessuna piattaforma selezionata
- Al click: progress bar animata con ETA stimata ("~30 secondi...")
- QUESTO RISOLVE IL PROBLEMA #5: il contatore e sempre visibile

### Risultati:

- Appaiono NELLA STESSA PAGINA, sotto il form
- Scroll automatico verso i risultati
- Tab per ogni piattaforma generata
- Ogni contenuto e editabile in-place
- Azioni per piattaforma: Copia / Approva / Programma / Rigenera con feedback
- Instagram: carosello visivo inline con preview slide
- Newsletter: toggle preview HTML / codice sorgente
- "Rigenera con feedback": apre campo testo per dire cosa cambiare, poi rigenera

---

## TAB "PIANIFICA" — CALENDARIO

### Layout:
```
┌─────────────────────────────────────────────┐
│  Calendario settimanale (come attuale)      │
│                                              │
│  ⚠ Nota: "Ti avvisiamo quando e ora di     │
│   pubblicare. La pubblicazione la fai tu."  │
│                                              │
│  [Lun] [Mar] [Mer] [Gio] [Ven] [Sab] [Dom]│
│  ┌──┐                                       │
│  │LI│ 10:00 - Post su AI e marketing       │
│  └──┘                                       │
│       ┌──┐                                   │
│       │NL│ 14:00 - Newsletter settimanale   │
│       └──┘                                   │
└─────────────────────────────────────────────┘
```

### Regole:
- Label chiara IN ALTO: "Ti avvisiamo noi — la pubblicazione la fai tu"
- MAI usare "Pubblica automaticamente" o simili
- Ogni evento ha: piattaforma (colore), titolo (troncato), orario
- Click su evento: mostra preview contenuto + azioni (Copia / Modifica orario / Rimuovi)
- Se nessun contenuto programmato: empty state "Nessun contenuto programmato. Crea il tuo primo contenuto!"

---

## TAB "LIBRERIA" — HISTORY + IMPOSTAZIONI

### Layout:
```
┌─────────────────────────────────────────────┐
│  LIBRERIA                                    │
│                                              │
│  [🔍 Cerca nei tuoi contenuti...]           │
│                                              │
│  Filtri: [Tutte] [LinkedIn] [Instagram]      │
│          [Newsletter] [Twitter] [Video]      │
│  Stato:  [Tutti] [Approvati] [Bozze]        │
│          [Programmati]                        │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │ 📋 "AI nel marketing B2B"            │   │
│  │    10 Mar 2026 — LinkedIn, Newsletter │   │
│  │    [Apri] [Rigenera] [Elimina]        │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ 📋 "Trend social media 2026"         │   │
│  │    8 Mar 2026 — LinkedIn              │   │
│  │    [Apri] [Rigenera] [Elimina]        │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ─────────────────────────────────────────   │
│  ⚙ Impostazioni                             │
│    > Feed RSS (configura le tue fonti)       │
│    > Preferenze (tono, lingua, brand)        │
│    > Piano e fatturazione                     │
│    > Avanzate (Monitor, Prompt Log)          │
│                                              │
└─────────────────────────────────────────────┘
```

### Regole History:
- Barra di ricerca in alto (cerca per titolo, contenuto, data)
- Filtri per piattaforma (chip cliccabili)
- Filtri per stato (chip cliccabili)
- Ogni sessione mostra: titolo articolo, data, piattaforme generate
- Click "Apri": espande inline la preview dei contenuti
- "Rigenera": riapre il tab Crea con lo stesso articolo + opinione precompilati

### Regole Impostazioni:
- Sezione collassabile sotto la history
- "Feed RSS": lista feed con nome + URL, aggiungi/rimuovi
- "Preferenze": tono di voce, lingua output, brand guidelines
- "Piano e fatturazione": piano corrente, counter generazioni, bottone upgrade
- "Avanzate": Monitor, Prompt Changelog, Pipeline Log — visibile solo se espanso

---

## TRADUZIONI — MAPPA COMPLETA IT

| Attuale (EN/misto) | Nuovo (IT) |
|---------------------|------------|
| Feed Refresh | (rimosso — automatico in background) |
| Topic Selection | (rimosso — incluso in "Crea") |
| Content Generation | (rimosso — incluso in "Crea") |
| Scheduling | Pianifica |
| History | Libreria |
| Settings | Impostazioni |
| Monitor | Avanzate (nascosto) |
| Approve | Approva |
| Schedule | Programma |
| Source mode | Tipo di fonte |
| Smart Brief | Riepilogo intelligente |
| Fetch & Analyze Articles | (rimosso) |
| Score | Rilevanza |
| Custom Text | Scrivi tu |
| Web Search | Cerca sul web |
| Feed RSS | Dai tuoi feed |
| Generate Drafts | Genera Contenuti |
| Feedback | La tua opinione |
| Pipeline Log | Registro attivita |
| Prompt Changelog | Storico prompt |
| Feed Health | Stato dei feed |

---

## CONTATORE GENERAZIONI — SPECIFICHE

### Posizione: topbar, sempre visibile
```
[3/10 gen]   ← verde se >50%
[2/10 gen]   ← arancione se 20-50%
[1/10 gen]   ← rosso se <20%
```

### Comportamento:
- Click sul contatore: apre modal pricing con piani
- Si aggiorna in real-time dopo ogni generazione
- Tooltip: "Hai 3 generazioni rimaste su 10 questo mese. Si rinnovano il 1 aprile."
- Nella CTA "Genera": "Usera 1 delle tue 3/10 generazioni"
- DOPO la generazione: "Generazione completata! Ti restano 2/10 generazioni."
- Quando arriva a 0: CTA disabilitata + "Hai esaurito le generazioni. Passa a Pro per generazioni illimitate."

---

## FEATURE BLOCCATE — SPECIFICHE

### Piano Free:
- LinkedIn: SBLOCCATO
- Newsletter: SBLOCCATO
- Instagram: BLOCCATO (lock + "Sblocca con Pro")
- Twitter: BLOCCATO (lock + "Sblocca con Pro")
- Video Script: BLOCCATO (lock + "Sblocca con Pro")

### Comportamento lock:
- Checkbox disabilitata con icona lock
- Testo grigio: "📸 Instagram — Carosello + caption"
- Sotto: link "Sblocca con Pro" che apre modal pricing
- MAI errore 403. MAI "questa funzione non e disponibile"
- L'utente VEDE cosa otterrebbe con Pro = motivazione all'upgrade

---

## PIANO DI IMPLEMENTAZIONE — FASI

### FASE 0 — Quick Win (1-2 giorni)
Cambiamenti minimi al codice attuale, massimo impatto:

- [ ] **Opinione PRIMA della generazione** — Spostare il campo opinione nella schermata Topic Selection, sopra il bottone "Genera"
- [ ] **Counter generazioni nella sidebar** — Aggiungere barra visuale con X/10 e colore
- [ ] **Traduzioni IT** — Rinominare tutte le label in sidebar e UI
- [ ] **Lock piattaforme** — Mostrare checkbox disabilitate con lock per piattaforme Pro invece di errore 403

### FASE 1 — Nuovo Layout (3-5 giorni)
Ristrutturazione completa del layout:

- [ ] **Rimuovere sidebar** — Sostituire con topbar 3 tab (Crea / Pianifica / Libreria)
- [ ] **Tab Crea: pagina unica con 3 zone** — Fonte + Opinione + Piattaforme in verticale
- [ ] **Web Search come default** — La prima tab attiva e "Cerca sul web", funziona subito
- [ ] **Feed refresh automatico** — Se l'utente ha feed, refresh in background all'apertura tab "Dai tuoi feed"
- [ ] **Risultati inline** — I contenuti generati appaiono sotto nella stessa pagina

### FASE 2 — Onboarding + Libreria (2-3 giorni)

- [ ] **Onboarding 3 slide** — Solo al primo accesso, skippabile
- [ ] **Libreria con filtri** — Ricerca, filtri per piattaforma e stato
- [ ] **Preview inline** — Click su sessione espande i contenuti senza navigare
- [ ] **Azione "Rigenera"** — Riapre il tab Crea precompilato

### FASE 3 — Polish (2-3 giorni)

- [ ] **Calendario migliorato** — Label "ti avvisiamo noi" + preview al click
- [ ] **Progress bar con ETA** — Durante generazione mostrare "~30 secondi..."
- [ ] **Empty states** — Messaggi amichevoli per ogni stato vuoto
- [ ] **Monitor nascosto** — Spostato sotto Libreria > Impostazioni > Avanzate
- [ ] **Responsive mobile** — Il tab Crea deve funzionare su mobile

---

## METRICHE DI SUCCESSO

| Metrica | Attuale (stimato) | Target |
|---------|-------------------|--------|
| Step per primo contenuto | 10 | 3 |
| Tempo per primo contenuto | ~5 min | <90 sec |
| Tasso abbandono primo uso | ~70% | <30% |
| Generazioni "sprecate" (senza opinione) | ~60% | <10% |
| Utenti che scoprono il limite da errore 403 | ~80% | 0% |
| Utenti che configurano RSS al primo uso | necessario | non necessario |

---

## NOTA FINALE

Il flusso attuale e costruito dal punto di vista del developer.
Il developer conosce l'architettura: RSS -> analisi -> selezione -> generazione.
Ha costruito la UI seguendo il flusso tecnico del backend.

Il nuovo flusso e costruito dal punto di vista di Marco:
"Cerco qualcosa, dico la mia, scelgo dove, e ottengo i contenuti."

La complessita tecnica (RSS, scoring, prompt enrichment, feedback loop)
esiste ancora nel backend. Ma e invisibile all'utente.

Come Spotify: metti la canzone e la senti.
Non ti chiede di scegliere il codec audio.
