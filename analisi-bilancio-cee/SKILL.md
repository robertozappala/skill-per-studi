---
name: analisi-bilancio-cee
description: "Riclassifica uno o più bilanci CEE italiani (XBRL depositato al Registro imprese o PDF nativo; ordinario, abbreviato, micro) e calcola su più anni gli indici di liquidità, solidità, redditività, indebitamento e ciclo del circolante, con Excel, JSON e commento. Usare quando l'utente chiede di analizzare o riclassificare un bilancio, calcolare gli indici (current ratio, ROE, ROI, PFN, margini di struttura, copertura degli interessi), capire «com'è messa» una società dai numeri, o passa un file .xbrl o il PDF di un bilancio. I conti li fanno due script deterministici, mai il modello a mano. Non giudica il merito creditizio e non dà consigli fiscali."
license: MIT
metadata:
  autore: "ztax.it"
  versione: "1.1"
---

# Analisi di bilancio CEE

Riclassifica il bilancio (artt. 2424-2425 c.c.) con il criterio finanziario e il conto economico
a valore aggiunto, e calcola gli indici principali. **I numeri non li fai tu.** L'XBRL lo legge
`scripts/estrai_xbrl.py`, i conti li fa `scripts/calcola_indici.py`: tu scegli la fonte, leggi il
PDF quando non c'è altro, guardi gli esiti e scrivi il commento. Nel commento non entra un
numero che non venga dagli script.

Il perché: le quadrature scoprono una voce mancante, non due voci scambiate dentro lo stesso
totale (B6 al posto di B7, un debito entro l'esercizio letto come oltre). Quell'errore passa
tutti i controlli e cambia EBITDA e liquidità. Sull'XBRL lo toglie la tabella fissa dello
script; sul PDF lo toglie solo il riscontro voce per voce.

Skill di ztax.it (https://ztax.it), licenza MIT. È un supporto al professionista: i
risultati vanno verificati da chi firma il lavoro.

## 0. Prima dell'uso

- **La skill è fatta di più file.** Se accanto a questo `SKILL.md` non c'è la cartella
  `scripts/` con `estrai_xbrl.py` e `calcola_indici.py`, fermati: la skill non è installata per
  intero. Di' all'utente di scaricare il pacchetto completo da
  <https://github.com/robertozappala/skill-per-studi> - il file `analisi-bilancio-cee.zip` - e
  installarlo per intero, con le sue cartelle: in Claude Code si scompatta in
  `~/.claude/skills/`, nelle app di Claude si carica lo zip fra le skill. Non riscrivere gli script a memoria: la loro ragion d'essere è
  dare sempre gli stessi numeri.
- **Python.** Serve Python 3.9 o successivo, e nient'altro: i due script usano solo la libreria
  standard, Excel compreso. Non c'è niente da installare. Su Windows il comando può chiamarsi
  `python` invece di `python3`.
- **Dove si scrive.** Chiedi la cartella di lavoro del cliente, se non è chiara, e scrivi tutto
  in una sottocartella `Analisi bilancio/`. I bilanci di partenza non si toccano. Gli script non
  usano la rete e non mandano fuori niente.

Nei comandi che seguono `<skill>` è il **percorso assoluto della cartella che contiene questo
`SKILL.md`** (in Claude Code di solito `~/.claude/skills/analisi-bilancio-cee`), e `<cartella>`
quello della cartella del cliente. Scrivi ogni comando per esteso, coi percorsi veri fra
virgolette: non metterli in variabili di shell, perché zsh non spezza una variabile che
contiene uno spazio o un'opzione. Su Windows, `python` al posto di `python3`.

**Nessun file si sovrascrive, e ogni analisi ha il suo numero.** I file portano l'ultimo
esercizio analizzato e il numero di versione, uguale per estratto, Excel, risultati e commento
(`estratto-2025-2.json`, `analisi-<cliente>-2025-2.xlsx`, `commento-2025-2.md`; la prima
versione è senza numero). L'estratto prende il primo numero che nessuno dei quattro usa; i
conti prendono quello dell'estratto e, se quella versione ha già risultati diversi (regole
cambiate), aprono la successiva e ci copiano l'estratto. Un file uguale già scritto non si
ripete. Usa sempre il nome che lo script stampa; il JSON dei risultati porta anche il nome
dell'estratto da cui viene.

## 1. Scegli la fonte

1. **XBRL** (`.xbrl` del deposito al Registro imprese): è la fonte da preferire sempre, perché
   i numeri sono quelli depositati e la lettura è deterministica. Se l'utente passa solo il PDF
   di un bilancio depositato, chiedi prima se ha l'XBRL.
2. **PDF nativo** (con il testo selezionabile): quando l'XBRL non c'è, per esempio un bilancio
   non ancora depositato. Si legge con riscontro, §3.
3. **PDF scansionato** (nessun testo estraibile): **non si usa.** L'OCR sbaglia le cifre e la
   cifra sbagliata resta plausibile: fermati e chiedi l'XBRL o un PDF nativo.

Ogni bilancio porta anche l'esercizio precedente: con due bilanci si coprono tre anni.

## 2. Percorso XBRL

```bash
python3 "<skill>/scripts/estrai_xbrl.py" "<bilancio.xbrl>" ["<altro.xbrl>" ...] \
  --azienda "<Cliente>" --out "<cartella>/Analisi bilancio"
```

Scrive `estratto-<ultimo anno>.json` in `Analisi bilancio/`, e crea la cartella se non c'è.

Lo script:
- accetta solo la tassonomia InfoCamere `itcc/ci/2018-11-04`, e su un'altra si ferma;
- ricava per differenza dai totali dichiarati le voci che la sua tabella non nomina (crediti
  verso soci, A2+A3+A4, B12+B13, rettifiche D), e le accetta solo se le voci fuori tabella del
  file le spiegano esattamente; stampa la provenienza di ognuna che non sia zero (una
  differenza zero vuol dire che i totali tornano con le voci in tabella); il risultato prima
  delle imposte che il file non scrive lo ricava e lo controlla su utile più imposte;
- nell'ordinario stampa anche le voci lette in altro modo: entro e oltre «sommati voce per
  voce», e la voce che manca in un dettaglio per natura completo «assente: zero» (clienti,
  fornitori, D1-D5). Non sono stime ma letture del bilancio; la nota «voce generica fa tutto
  il totale» dice invece che giorni clienti o fornitori e PFN di quell'anno non valgono;
- con più file, per ogni anno tiene il bilancio più recente e stampa le differenze sullo stesso
  anno (riclassificazioni per comparabilità); con un file solo non c'è niente da riportare;
- si ferma (uscita 1) su un totale mancante, una voce fuori tabella non spiegata o due bilanci
  dello stesso esercizio.

**Se si ferma, non aggirarlo** scrivendo l'estratto a mano: riporta all'utente il messaggio
esatto. Una tassonomia nuova o una voce non in tabella si risolvono estendendo la tabella dello
script su un file vero.

## 3. Percorso PDF nativo

1. Leggi il PDF pagina per pagina con lo strumento di lettura dei file e individua stato patrimoniale e conto
   economico, con le due colonne (esercizio e precedente). Negli abbreviati la ripartizione dei
   debiti per natura e gli interessi passivi stanno in nota integrativa: cercali prima di
   lasciarli `null`.
2. Scrivi `Analisi bilancio/estratto-<ultimo anno>.json` (col primo numero di versione libero)
   sullo schema di [references/schema-e-regole.md](references/schema-e-regole.md) §1. Una voce
   che il bilancio non porta vale 0 o `null` secondo la regola dello schema, **mai stimata**.
   Nell'estratto metti `"_fonte"`: il PDF e le pagine usate.
3. **Riscontro voce per voce sul PDF**, prima di lanciare i conti: per ogni chiave annota in
   `"_riscontro"` dell'esercizio la pagina e la riga da cui viene, e rileggila lì. È il solo
   presidio contro le voci scambiate.
4. **Mostra all'utente la tabella voce - importo - pagina e fermati**: i conti partono solo
   dopo la sua conferma, o dopo le sue correzioni.

## 4. Calcola e controlla

```bash
python3 "<skill>/scripts/calcola_indici.py" "<cartella>/Analisi bilancio/estratto-<anno>.json" \
  [--regole "<cartella>/Analisi bilancio/regole.json"] --out "<cartella>/Analisi bilancio"
```

- Uscita 0: tutte le quadrature tornano; scrive `analisi-<cliente>-<anno>.xlsx` (SP
  riclassificato, CE valore aggiunto, Indici, Variazioni, Composizione, Controlli, Note) e
  `risultati-<cliente>-<anno>.json`, con l'eventuale `-2`, `-3`. Nel nome del file gli spazi
  diventano trattini bassi. Le «Note» portano anche le voci ricavate per differenza
  dall'XBRL, le variazioni che non si leggono in percentuale e le imposte superiori al
  risultato ante imposte.
- Uscita 1: una quadratura non torna; stampa voce e differenza e **non scrive niente**.
  Ricontrolla le voci coinvolte sul PDF e rilancia. Dopo due tentativi fermati e mostra la
  differenza e le voci sospette.
- Uscita 2: estratto o regole malformati. Correggi il file, non lo script.

Le regole di riclassificazione hanno default dichiarati; un `regole.json` li cambia: opzioni in
[references/schema-e-regole.md](references/schema-e-regole.md) §2. Usane uno solo se l'utente
lo chiede.

## 5. Il commento

Scrivi `Analisi bilancio/commento-<ultimo anno>.md`, con lo stesso suffisso `-2`, `-3` dei
risultati da cui viene, e mettigli come titolo il nome del cliente e gli esercizi analizzati.
Indici, margini, variazioni e composizioni vengono da quel `risultati-*.json`, le voci di
bilancio dall'estratto; un numero che servirebbe calcolare a mano non si scrive. Nel JSON gli
indici percentuali sono frazioni (0,0568 è il 5,68%): nel commento si scrivono con la virgola e
due decimali, gli importi in euro col punto delle migliaia.

Una variazione percentuale non sempre si legge. Dove le «Note» la segnalano (base sotto lo
0,5% del valore della produzione, o segno che cambia), scrivi i due importi e non la
percentuale. Su una base negativa scrivi la variazione a parole: «la perdita si riduce da
-100.000 a -20.000», non «+80%».

- sintesi in tre righe: come sta la società e come è cambiata;
- liquidità e ciclo del circolante, solidità patrimoniale (margini primario e secondario),
  redditività, indebitamento (PFN e copertura degli interessi): due-quattro righe ciascuna,
  col trend;
- segnali d'attenzione: PN negativo o in calo forte, margine di struttura negativo, current
  ratio sotto 1, PFN/EBITDA alto, MOL che non copre gli interessi, EBITDA negativo, imposte
  superiori al risultato ante imposte, e una voce di conto economico che cambia molto a ricavi
  stabili (imposte, oneri diversi: spesso una
  riclassificazione). Per «forte» e «alto» non c'è una soglia fissa: decidi e di' il numero su
  cui decidi;
- limiti: fonte (XBRL o PDF con le pagine), tipo di bilancio, voci n.d., voci ricavate per
  differenza, regole usate, note del foglio «Note», differenze fra bilanci.

Una PFN negativa è cassa netta, non debito: dillo così. Niente giudizi sul merito creditizio e
niente consigli fiscali. Chiudi il commento con: «Analisi di supporto, da verificare sul
bilancio da chi firma il lavoro.»

## Limiti noti

- **Tassonomia**: la tabella XBRL è costruita sulla 2018-11-04 (`itcc-ci-abb` e
  `itcc-ci-ese`), verificata su abbreviati e ordinari. Su una versione nuova o una voce che non
  conosce lo script si ferma. Le entità HTML nel testo della nota le sostituisce da sé, con un
  avviso.
- **Abbreviati e micro**: senza debiti per natura PFN e giorni fornitori sono n.d.; nell'XBRL
  dell'esercizio precedente la ripartizione entro/oltre è spesso solo nel totale.
- **Giorni clienti, fornitori e magazzino**: stima sui saldi di fine anno, con l'IVA ordinaria
  per clienti e fornitori; poco affidabile con molte operazioni esenti, estere o in split
  payment, e con un'attività stagionale. Segnalalo. Giorni clienti a zero con clienti
  «assente: zero» vuol dire che il bilancio non ha crediti verso clienti, non che si incassa
  subito: dillo nel commento.
- **PN nullo o negativo**: ROE, Debt/Equity e leverage perdono significato; lo script lo
  annota, e il commento lo dice invece di commentarli.
- **Debt/Equity** è sul totale delle passività, non sui soli debiti finanziari.
- **Niente rendiconto finanziario** e niente indicatori della crisi d'impresa.
