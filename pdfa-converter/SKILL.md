---
name: pdfa-converter
description: "Converte documenti Word, OpenDocument, RTF e PDF, scansioni comprese, in PDF/A-1a o PDF/A-1b per il deposito telematico degli atti, e consegna solo file che veraPDF ha validato. Tutto in locale: nessun documento esce dal computer. Usare quando l'utente chiede di convertire un atto o un allegato in PDF/A («convertimi il ricorso in PDF/A», «prepara i file per il deposito», «mi serve il PDF/A di questa scansione»), di preparare i file per il processo telematico, o di controllare se un PDF è davvero PDF/A («questo file è PDF/A?», «il portale mi rifiuta il PDF»). Il lavoro lo fa uno script che usa LibreOffice, Ghostscript e veraPDF, su macOS, Linux e Windows."
license: MIT
metadata:
  autore: "ztax.it"
  versione: "1.0"
---

# Convertitore PDF/A per il deposito telematico

`scripts/converti_pdfa.py` converte un documento in PDF/A-1a o, dove l'1a non si raggiunge,
in PDF/A-1b, e **scrive come valido solo ciò che veraPDF ha validato**. La conversione non la
fai tu a mano: scegli i file, lanci lo script e riferisci all'utente quello che lo script ha
detto, con le sue parole.

Se `scripts/converti_pdfa.py` non c'è (è stato installato solo questo testo), fermati e di'
all'utente di scaricare il pacchetto completo da
<https://github.com/robertozappala/skill-per-studi> - il file `pdfa-converter.zip`, da
scompattare nella cartella delle skill. Non ricostruire i comandi a memoria: una conversione
improvvisata produce file che sembrano PDF/A e non lo sono.

## Prima volta: gli strumenti

```bash
python3 scripts/converti_pdfa.py --strumenti
```

- **Il Python.** Su macOS e Linux `python3`; su Windows `python` o `py`. Serve la 3.9 o
  successiva. Il percorso dello script è relativo alla cartella di questa skill: componilo
  per intero.
- Il comando elenca che cosa trova e che cosa manca, con la riga per installarlo. Servono
  **LibreOffice** (documenti e PDF digitali), **Ghostscript** (scansioni), **veraPDF** con
  Java (la validazione) e la libreria Python **pikepdf**.
- **Prima di installare qualcosa chiedi all'utente**: sono programmi che finiscono sul suo
  computer. Se `pip` rifiuta di installare nel Python di sistema, crea un ambiente dedicato
  (`python3 -m venv ~/.venv-pdfa`), installa lì pikepdf e da allora lancia lo script con
  quel Python.
- Un programma installato fuori dal `PATH` si indica con una variabile d'ambiente:
  `PDFA_SOFFICE`, `PDFA_GS`, `PDFA_VERAPDF`, `PDFA_ICC`.
- **Senza veraPDF lo script non converte niente**, ed è giusto così: un PDF/A non validato è
  un file di cui non si sa nulla. Non aggirarlo.

## Convertire

```bash
python3 scripts/converti_pdfa.py "atto.docx" "allegato 1.pdf" "ricevuta scansionata.pdf"
```

Lo script sceglie la strada dal file:

| In ingresso | Strada | Dove arriva |
| --- | --- | --- |
| Word, OpenDocument, RTF (`.docx .doc .odt .rtf .fodt`) | LibreOffice | di norma PDF/A-1a |
| PDF digitale, nato da un programma | LibreOffice Draw | 1a o 1b, e il layout può cambiare |
| PDF scansionato | Ghostscript | PDF/A-1b, mai 1a |

**Se l'utente ha sia il documento sia il PDF che ne ha ricavato, converti il documento.** È la
strada che arriva all'1a e che non altera l'impaginazione.

L'esito nasce accanto all'originale, o nella cartella data con `--uscita`, e il nome dice che
cos'è:

- `<nome>_PDFA-1a.pdf` - valido PDF/A-1a;
- `<nome>_PDFA-1b.pdf` - valido PDF/A-1b;
- `<nome>_PDFA-NON-VALIDO.pdf` - **non depositabile**: serve a guardare che cosa è andato
  storto, non a essere usato.

L'originale non viene mai toccato e un file che c'è già non viene sovrascritto: se lo script
si ferma perché l'esito esiste, dillo all'utente e lascia a lui spostarlo.

## Che cosa riferire

Leggi il **RIEPILOGO** in fondo all'uscita, non la cartella: dice file per file che cosa è
stato prodotto in questo lancio. Riporta all'utente, per ogni file, il nome dell'esito, il
livello raggiunto e ogni avviso. Il codice di uscita riassume: `0` tutti validi, `1` almeno
un file senza esito valido, `3` veraPDF non parte, `4` manca un programma.

- **Non rinominare mai un `NON-VALIDO`** e non presentarlo come pronto.
- **Un 1b non è un fallimento**: è un PDF/A valido. Dillo com'è - «valido 1b, l'1a non è
  stato raggiunto» - e riporta i controlli falliti che lo script elenca.
- Se lo script dice che non ha potuto fare una cosa (verificare, confrontare la resa, aprire
  il file), riferiscilo così: «non verificato» non è «va bene».

## Guardare il risultato, sempre

veraPDF certifica la forma del file, non quello che si vede. È successo davvero: scansioni
uscite con le pagine nere e dichiarate «PDF/A valido». Per i PDF in ingresso lo script
confronta da sé, in piccolo, ogni pagina con l'originale e marca `NON-VALIDO` l'esito che ha
pagine in meno, una pagina annerita, svuotata o con una zona sparita. È un controllo
grossolano: non vede un carattere sostituito né una riga spostata, e per i documenti Word non
ha un originale con cui confrontare.

Quindi, dopo ogni conversione:

1. apri l'esito e guardane le pagine (se puoi leggere i PDF, fallo; altrimenti chiedi
   all'utente di aprirlo);
2. ricorda all'utente che **il controllo finale prima del deposito è suo**: pagine, firme,
   allegati, leggibilità.

## Le trappole che lo script segnala

- **PDF firmato digitalmente.** Non viene convertito: la conversione riscrive il file e la
  firma andrebbe persa. Si converte prima e si firma dopo.
- **PDF che non si apre** (danneggiato o con password). Non viene convertito. Togliere la
  protezione è una scelta dell'utente, non tua.
- **Clausola 6.3.5 su un documento Word.** Il carattere del documento è installato in formato
  OTF: LibreOffice lo incorpora in un modo che il PDF/A-1 non accetta, e il file esce non
  valido né 1a né 1b. Va installato lo stesso carattere in TTF, poi si riconverte.
- **Testo OCR scartato.** Molte scansioni portano un testo invisibile con caratteri
  difettosi. Se il primo 1b non passa, lo script riprova togliendo quel testo: l'immagine
  resta identica, ma il PDF non è più ricercabile. Va detto all'utente.
- **Scansioni: 1b e basta.** L'1a su una scansione richiederebbe un OCR strutturato, che
  questa skill non fa.
- **LibreOffice che si interrompe subito.** Se lavori dentro una sandbox, LibreOffice può non
  riuscire a partire, e lo script lo riporta come errore di conversione su ogni documento e
  PDF digitale, mentre le scansioni passano. Non è un difetto del file: chiedi all'utente il
  permesso di rilanciare il comando fuori dalla sandbox, e se non puoi diglielo.
- **Cartelle sincronizzate** (Google Drive, OneDrive, iCloud). Lo script lavora su una copia
  locale e scrive solo l'esito. Se un file risulta vuoto, non è ancora stato scaricato dalla
  nuvola: va aperto una volta o reso disponibile offline.

## Controllare un PDF che c'è già

```bash
python3 scripts/converti_pdfa.py --verifica "file.pdf"
```

Risponde con uno di questi: `PDF/A-1a VALIDO`, `PDF/A-1b VALIDO`, `si DICHIARA PDF/A ma NON è
valido`, `PDF semplice`, oppure `NON HO POTUTO VERIFICARE`. L'ultimo non è un giudizio sul
file: veraPDF non è riuscito a leggerlo o non è partito.

## Limiti

- La catena è fatta di programmi gratuiti. I documenti di testo ben formati arrivano
  normalmente all'1a, ma **l'1a non è garantito su qualunque documento**: quando non si
  raggiunge, lo script consegna l'1b valido e lo dice.
- Lo script valida la conformità al PDF/A-1. **Quale formato chieda il portale su cui si
  deposita, e con quali limiti di dimensione e di nome dei file, lo dicono le sue specifiche
  tecniche**: se l'utente non lo sa, invitalo a controllarle, e non affermarlo a memoria.
- Non si collega a internet e non manda i documenti da nessuna parte.
