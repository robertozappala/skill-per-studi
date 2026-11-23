---
name: scarica-norma
description: "Scarica da Normattiva il testo ufficiale di una norma italiana - legge, decreto legislativo, decreto legge, D.P.R., codici, Costituzione, decreti ministeriali - alla vigenza di oggi o a una data passata, e lo salva in Markdown, un articolo per sezione, con la vigenza dichiarata nel nome e in testa al file. Usare quando l'utente chiede di scaricare, procurarsi o aggiornare una norma («scaricami il D.Lgs. 74/2000», «mi serve il codice civile», «il 546 com'era nel 2019», «prendi lo Statuto del contribuente da Normattiva»), quando serve il testo vigente di un articolo da citare invece di scriverlo a memoria, o quando chiede di controllare se le norme già scaricate sono aggiornate. Il lavoro lo fa uno script con la sola libreria standard di Python, su macOS, Linux e Windows."
license: MIT
metadata:
  autore: "ztax.it"
  versione: "1.1"
---

# Scarica norma da Normattiva

Normattiva pubblica i testi consolidati in **Akoma Ntoso**, un XML già diviso per articolo,
comma e lettera. `scripts/scarica-norma.py` lo scarica e lo converte in un `.md` con un titolo
`## art. N` per articolo, così un articolo si trova con una ricerca e si cita col testo vero.
**Il testo non lo scrivi tu:** lo prende lo script, e tu scegli URN, vigenza e cartella, lanci
il comando e riferisci all'utente quello che lo script ha segnalato.

Se `scripts/scarica-norma.py` non c'è (è stato installato solo questo testo), fermati e di'
all'utente di scaricare il pacchetto completo da
<https://github.com/robertozappala/skill-per-studi> - il file `scarica-norma.zip`, da
scompattare nella cartella delle skill. Senza lo script la skill non funziona, e ricostruirlo a
mano darebbe un testo di legge non verificato.

## Come si lancia

```bash
python3 scripts/scarica-norma.py "<urn>" <nome> [--vigenza AAAA-MM-GG] [--cartella <percorso>]
```

- **Il Python.** Su macOS e Linux `python3`; su Windows `python` o `py`. Prova in quest'ordine
  e usa il primo che risponde a `--version` con un 3.x. Non serve installare niente.
- **Il percorso dello script** è relativo alla cartella di questa skill: componilo per intero.
- **La cartella** (`--cartella`). Senza, lo script usa `Legislazione/` nella cartella da cui
  lo lanci. Se l'utente ha già una cartella di norme, usa quella; altrimenti proponi
  `Legislazione/` nel progetto e dillo. Passa la stessa cartella a **tutti** i comandi, anche
  alle verifiche.
- **Il nome** è il nome comune della norma, in minuscolo coi trattini: `statuto-contribuente`,
  `codice-civile`, `processo-tributario`. Lo script ci aggiunge `_vigenza-AAAA-MM-GG.md`.

## L'URN

Si scrive `tipo:AAAA-MM-GG;numero`. ⚠️ La data è quella di **emanazione** dell'atto, non della
pubblicazione in Gazzetta: è l'errore più frequente, e lo script risponde «Normattiva non
offre l'export per questo URN». Se non sei sicuro della data, cercala (Normattiva, Gazzetta
Ufficiale) o chiedila: non tirare a indovinare.

| Atto | URN |
| --- | --- |
| Costituzione | `costituzione` |
| Codice civile | `regio.decreto:1942-03-16;262` |
| Codice di procedura civile | `regio.decreto:1940-10-28;1443` |
| Codice penale | `regio.decreto:1930-10-19;1398` |
| D.P.R. 600/1973 (accertamento) | `decreto.del.presidente.della.repubblica:1973-09-29;600` |
| D.P.R. 633/1972 (IVA) | `decreto.del.presidente.della.repubblica:1972-10-26;633` |
| D.Lgs. 546/1992 (processo tributario) | `decreto.legislativo:1992-12-31;546` |
| L. 212/2000 (Statuto del contribuente) | `legge:2000-07-27;212` |

Altri tipi: `legge`, `decreto.legislativo`, `decreto.legge`, `regio.decreto`,
`decreto.del.presidente.della.repubblica`. Un decreto ministeriale si scrive per esteso, come
lo dà Normattiva: `urn:nir:ministero.giustizia:decreto:2023-08-07;110`.

## La vigenza

- **Senza `--vigenza`** lo script scarica il testo di oggi. È quello da usare per avere la
  norma aggiornata.
- **Con `--vigenza AAAA-MM-GG`** scarica il testo com'era a quella data: serve quando conta la
  norma in vigore a un momento passato (il periodo d'imposta, la data dell'atto, il fatto). Il
  file si dichiara **congelato**: le verifiche non lo propongono da riscaricare, e il testo di
  oggi non lo sostituisce mai.
- Se l'utente cita un fatto datato e non dice quale vigenza vuole, chiediglielo: la versione
  sbagliata di una norma è un errore che non si vede.

## Che cosa riferire dopo lo scarico

Riporta all'utente **il nome del file e il numero di articoli**, e poi ogni avviso dello
script, con le sue parole. Sono i punti in cui l'export di Normattiva non è affidabile:

- **porzioni senza posto**: testo riscritto dal legislatore che lo script non sa dove
  collocare. Va messo a mano aprendo Normattiva alla stessa vigenza. Se l'utente lo colloca,
  annotalo in `_collocazioni.csv` nella cartella - una riga
  `norma;articolo;comma;inizio del testo` - e da allora torna al suo posto da solo;
- **articoli ridotti a «abrogato» da un atto recente**: l'export può dare per abrogato un
  articolo la cui abrogazione non è ancora efficace. Proponi `--verifica-abrogati`;
- **avvisi sotto un articolo** (pronuncia della Corte costituzionale, modifiche con decorrenza
  futura): il testo dell'articolo può non valere per intero. Leggi la nota prima di citarlo;
- **file spostati in `_archivio/`**: versioni superate, non cancellate.

## Le verifiche

```bash
python3 scripts/scarica-norma.py --elenco             --cartella <percorso>
python3 scripts/scarica-norma.py --controlla [pezzo]  --cartella <percorso>
python3 scripts/scarica-norma.py --verifica-abrogati [pezzo] --cartella <percorso>
python3 scripts/scarica-norma.py --verifica-lettere [pezzo]  --cartella <percorso>
python3 scripts/scarica-norma.py --indice             --cartella <percorso>
```

`--controlla` dice quali file sono indietro rispetto a Normattiva e stampa i comandi per
riscaricarli; `--verifica-abrogati` apre la pagina web degli articoli dati per abrogati;
`--verifica-lettere`, senza rete, cerca elenchi a cui manca una lettera (a, b, d senza la c),
che è il guasto più silenzioso dell'export. `--indice` riscrive `_indice.md`, e si rifà da sé
dopo ogni scarico. Le norme **non verificate** si riferiscono come tali: «non lo so» non è
«va bene».

## Cosa lo script fa e non fa

- Si collega solo a `www.normattiva.it`, con una pausa fra le richieste: è un servizio
  pubblico gratuito, non va martellato.
- **Non cancella niente.** Sposta in `_archivio/` la versione che sostituisce; i file che
  sembrano la stessa norma li elenca soltanto.
- Il testo viene da Normattiva, non da una scansione: per controllarlo si apre Normattiva alla
  stessa vigenza. Ricordalo all'utente quando il testo finisce in un atto: **la verifica
  finale sulla fonte ufficiale resta a chi firma.**
