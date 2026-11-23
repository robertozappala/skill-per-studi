#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scarica-norma — prende una norma da Normattiva e la salva come Markdown, un articolo per sezione.

Perche' esiste: i testi normativi presi da PDF passati per OCR mescolano il testo
dell'articolo con le note a pie' di pagina. Normattiva pubblica lo stesso testo in
Akoma Ntoso, cioe' gia' diviso per articolo e senza scansione di mezzo. Questo comando
lo scarica, lo converte in un file .md con un titolo «## art. N» per articolo, e lo
posa in una cartella dove si puo' cercare.

La data conta piu' del testo: un articolo senza la sua vigenza non si puo' usare in
un atto. Il file la dichiara in testa e la porta nel nome.

Funziona con la sola libreria standard di Python 3, su macOS, Linux e Windows.
Su Windows al posto di «python3» si scrive «python» o «py».

La cartella:
  --cartella <percorso>   dove stanno i testi. Senza, e' «Legislazione» nella cartella
                          da cui si lancia il comando. Vale per tutti i comandi qui sotto.

Uso:
  python3 scarica-norma.py "decreto.legislativo:2000-03-10;74" reati-tributari
        scarica alla vigenza di oggi. Scritto cosi' l'URN e' di un atto dello Stato;
        un decreto ministeriale si scrive per esteso, come lo da' Normattiva:
        python3 scarica-norma.py "urn:nir:ministero.giustizia:decreto:2023-08-07;110" atti-chiari

  python3 scarica-norma.py "decreto.legislativo:1992-12-31;546" processo-tributario --vigenza 2019-03-01
        scarica il testo com'era a quella data, per una causa che lo richiede

  python3 scarica-norma.py --elenco
        i file che ci sono adesso nella cartella, con la vigenza dichiarata

  python3 scarica-norma.py --indice
        riscrive «_indice.md»: che norme ci sono, che versione, quanti articoli.
        Non tocca la rete: legge quello che c'e' sul disco. Si rifa' da se' dopo
        ogni scaricamento

  python3 scarica-norma.py --controlla [pezzo di nome]
        una volta al mese: confronta la versione dei file con Normattiva e dice
        quali sono da riscaricare. Quelle che non riesce a verificare le elenca
        a parte, perche' «non lo so» non e' «va bene»

  python3 scarica-norma.py --verifica-abrogati [pezzo di nome]
        l'altra meta' del controllo: «--controlla» guarda la versione, questo
        guarda dentro. Prende gli articoli ridotti alla sola scritta «abrogato»
        da un atto recente e apre la pagina web di Normattiva alla vigenza del
        file, una per una. Se la pagina da' il testo pieno, l'abrogazione non e'
        ancora efficace e l'articolo va rimesso a mano

  python3 scarica-norma.py --verifica-lettere [pezzo di nome]
        la terza verifica, e la piu' economica: non tocca la rete. Cerca gli
        elenchi a cui manca una lettera - a) b) d) senza la c) - perche' l'export
        XML perde le porzioni che il legislatore ha riscritto. Le altre due
        verifiche guardano l'articolo intero e questo guasto non lo vedono.
        «--controlla» la lancia da se'

L'URN si compone cosi': tipo:AAAA-MM-GG;numero, dove la data e' quella di
EMANAZIONE dell'atto, non di pubblicazione in Gazzetta. Tipi piu' usati:
  legge · decreto.legislativo · decreto.legge · regio.decreto · costituzione
  decreto.del.presidente.della.repubblica

Il comando NON cancella niente. Quando scarica una norma, la copia precedente dello
stesso nome - non congelata, e di data anteriore - la SPOSTA in «_archivio/» dentro la
cartella, col nome che aveva: e' superata, non perduta. Le congelate non si toccano mai.
Gli altri file che sembrano la stessa norma li elenca soltanto: cancellarli e' una
decisione, e la prende una persona.

Le porzioni che il comando non sa ricollocare da se' si annotano a mano in
«_collocazioni.csv» nella cartella, una riga per porzione:
  norma;articolo;comma;inizio del testo
e da allora tornano al loro articolo a ogni scaricamento.
"""

import os
import re
import sys
import time
import http.client
import http.cookiejar
import unicodedata
import urllib.request
from html import unescape
from xml.etree import ElementTree as ET

# La cartella dei testi. La fissa main() da «--cartella»; senza, e' «Legislazione»
# nella cartella da cui si lancia il comando.
LEGGI = os.path.abspath("Legislazione")
AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
SPAZI = re.compile(r"[ \t ]+")
UA = "Mozilla/5.0 scarica-norma"


def data_it(iso):
    a, m, g = iso.split("-")
    return "%s.%s.%s" % (g, m, a)


def apri(vigenza):
    """Sessione con cookie: l'export di Normattiva a freddo risponde una pagina d'errore."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    return op


def scarica(urn, vigenza):
    """Ritorna l'XML Akoma Ntoso dell'atto alla vigenza chiesta."""
    op = apri(vigenza)
    pagina = "https://www.normattiva.it/uri-res/N2Ls?%s!vig=%s" % (urn_pieno(urn), vigenza)
    # Qui l'atto serve intero: niente parziale, solo i tentativi ripetuti.
    html = con_tentativi(lambda: op.open(pagina, timeout=60).read()).decode("utf-8", "replace")
    m = re.search(r"caricaAKN\?dataGU=(\d+)&(?:amp;)?codiceRedaz=([A-Za-z0-9]+)", html)
    if not m:
        raise SystemExit("Normattiva non offre l'export per questo URN.\n"
                         "Controlla tipo, data di emanazione e numero: %s" % urn)
    time.sleep(1.5)                          # e' un servizio pubblico gratuito
    u = ("https://www.normattiva.it/do/atto/caricaAKN"
         "?dataGU=%s&codiceRedaz=%s&dataVigenza=%s" % (m.group(1), m.group(2),
                                                       vigenza.replace("-", "")))
    dati = con_tentativi(lambda: op.open(u, timeout=300).read())
    if b"akomaNtoso" not in dati[:2000]:
        raise SystemExit("Normattiva ha risposto qualcosa che non e' Akoma Ntoso. "
                         "Riprova fra qualche minuto: sotto carico serve una pagina d'errore.")
    return dati, m.group(1), m.group(2)


TIPI = {
    "legge": "Legge",
    "decreto.legislativo": "Decreto legislativo",
    "decreto.legge": "Decreto legge",
    "regio.decreto": "Regio decreto",
    "costituzione": "Costituzione",
    "legge.costituzionale": "Legge costituzionale",
    "decreto.del.presidente.della.repubblica": "Decreto del Presidente della Repubblica",
    "decreto.del.presidente.del.consiglio.dei.ministri":
        "Decreto del Presidente del Consiglio dei Ministri",
    "decreto.ministeriale": "Decreto ministeriale",
}


AUTORITA = {
    "ministero.giustizia": "del Ministero della giustizia",
    "ministero.economia.finanze": "del Ministero dell'economia e delle finanze",
}


def urn_pieno(urn):
    """L'URN come lo vuole Normattiva. Scritto corto («decreto.legislativo:2000-03-10;74»)
    e' un atto dello Stato; scritto per esteso («urn:nir:ministero.giustizia:decreto:
    2023-08-07;110») e' preso com'e': e' la forma dei decreti ministeriali."""
    return urn if urn.startswith("urn:nir:") else "urn:nir:stato:" + urn


def urn_corto(urn):
    """L'inverso, per scriverlo a riga di comando: il prefisso dello Stato si toglie,
    quello di un'altra autorita' resta per esteso perche' e' l'informazione."""
    return urn[len("urn:nir:stato:"):] if urn.startswith("urn:nir:stato:") else urn


def intestazione_da_urn(urn):
    """«decreto.legislativo:2000-03-10;74» -> «Decreto legislativo n. 74/2000»;
    «urn:nir:ministero.giustizia:decreto:2023-08-07;110» ->
    «Decreto del Ministero della giustizia n. 110/2023»."""
    parti = urn_corto(urn).replace("urn:nir:", "").split(":")
    if len(parti) < 2:                       # «costituzione»: senza data e senza numero
        return TIPI.get(parti[0], parti[0].replace(".", " ").capitalize())
    autorita = parti[0] if len(parti) == 3 else "stato"
    tipo, resto = parti[-2], parti[-1]
    data, _, numero = resto.partition(";")
    anno = data[:4]
    nome = TIPI.get(tipo, tipo.replace(".", " ").capitalize())
    if autorita != "stato":
        nome += " " + AUTORITA.get(autorita, autorita.replace(".", " "))
    return "%s n. %s/%s" % (nome, numero, anno) if numero else "%s %s" % (nome, anno)


def righe_articolo(art):
    """Il testo di un articolo, una riga per comma o per lettera.

    Si cammina in ordine di documento su «num», «heading» e «p». Ogni «num» apre una
    riga nuova, il resto le si accoda: viene fuori «1. ...», «a) ...», che e' come
    l'articolo si legge e si cita.

    ⚠️ I tre elementi SI annidano: Normattiva mette la nota dentro il comma, un «p» che
    porta un «authorialNote» con dentro un altro «p». Il testo del «p» esterno contiene
    gia' la nota, quindi quello che sta dentro un elemento gia' letto non si rilegge:
    altrimenti la nota esce due volte.
    """
    righe, corrente = [], []
    letti = set()
    for e in art.iter():
        if e in letti:
            continue
        etichetta = e.tag.split("}")[-1]
        if etichetta not in ("num", "heading", "p"):
            continue
        letti.update(e.iter())
        t = SPAZI.sub(" ", "".join(e.itertext()).replace("\n", " ")).strip()
        if not t:
            continue
        if etichetta == "num" and corrente:
            righe.append(" ".join(corrente))
            corrente = []
        corrente.append(t)
    if corrente:
        righe.append(" ".join(corrente))
    return righe


ALFA_IT = "abcdefghilmnopqrstuvz"      # alfabeto italiano: niente j, k, w, x, y
SUFFISSI = ("bis ter quater quinquies sexies septies octies novies decies undecies "
            "duodecies terdecies quaterdecies quindecies sexdecies septiesdecies "
            "duodevicies undevicies vicies").split()
MARCA = re.compile(r"^\(*\s*(?:(\d+)\.|([a-z]+(?:-[a-z]+)?)\))")
INSERIMENTO = re.compile(
    r'<textualMod eId="[^"]+" type="insertion">.*?<destination href="#(ins_\d+)"/>'
    r'.*?<nakn:text>(.*?)</nakn:text>', re.S)


def piatto(s):
    """Il testo ridotto a lettere e cifre: serve solo a confrontare, non si scrive."""
    s = unicodedata.normalize("NFD", s.replace("’", "'"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ordine_lettera(marca):
    """Chiave d'ordine di « b-quinquies) » nell'elenco: prima la lettera, poi il suffisso."""
    base, _, suff = marca.partition("-")
    if base not in ALFA_IT:
        return None
    return (ALFA_IT.index(base), SUFFISSI.index(suff) + 1 if suff in SUFFISSI else 0)


def porzioni_novellate(xml):
    """Le porzioni che il legislatore ha riscritto, come Normattiva le dichiara.

    Normattiva marca fra doppie parentesi il testo novellato e lo ripete nei
    metadati dentro «textualMod type=insertion». Quando la novella ha riscritto un
    intero punto o un intero comma, il corpo dell'articolo non lo contiene affatto:
    resta solo qui. E' il caso dell'art. 8 del codice della crisi, che nel corpo e'
    il solo titolo, e della lettera c) dell'art. 25-novies.

    Si tengono solo le porzioni che cominciano con le doppie parentesi: le altre
    «textualMod» portano la nota sulla modifica («ha disposto l'abrogazione di...»),
    che e' cronaca dell'atto e non testo di legge.
    """
    testo = xml.decode("utf-8", "replace") if isinstance(xml, bytes) else xml
    fuori = []
    for eid, grezzo in INSERIMENTO.findall(testo):
        t = SPAZI.sub(" ", re.sub(r"<[^>]+>", "", grezzo).replace("\n", " ")).strip()
        if t.startswith("((") and len(t) > 25:
            fuori.append((int(eid[4:]), t))
    return fuori


def ins_per_articolo(xml):
    """Dove sta ogni segnaposto «ins», e in che ordine stanno gli articoli.

    Ritorna la mappa «numero dell'ins -> articolo» e la sequenza degli articoli
    nell'ordine del documento: la seconda serve a dire che fra l'art. 416 e l'art.
    418 c'e' il 417, che e' quello che cercavamo.
    """
    testo = xml.decode("utf-8", "replace") if isinstance(xml, bytes) else xml
    dove, ordine = {}, []
    for m in re.finditer(r'<article eId="([^"]+)"', testo):
        fine = testo.find("</article>", m.start())
        num = SPAZI.sub("", m.group(1)[4:].replace("-", ""))
        ordine.append(num)
        for k, t in re.findall(r'<ins eId="ins_(\d+)">(.*?)</ins>',
                               testo[m.start():fine], re.S):
            dove[int(k)] = (num, SPAZI.sub(" ", re.sub(r"<[^>]+>", "", t)).strip())
    return dove, ordine


def elenchi(righe, segno):
    """Le sequenze crescenti di marcatori dentro l'articolo, una per elenco.

    Un articolo puo' avere piu' elenchi: l'art. 25-novies ne ha uno al comma 1 e uno
    al comma 4, e tutti e due ripartono dalla a). Guardando l'articolo come una
    sequenza sola la c) del comma 4 farebbe credere che la c) del comma 1 ci sia gia'.
    Quando il marcatore torna indietro, l'elenco e' un altro.
    """
    fuori, corrente = [], []
    for i, r in enumerate(righe):
        m = re.match(r"^\(*\s*(\d+)\." if segno == "comma"
                     else r"^\(*\s*([a-z]+(?:-[a-z]+)?)\)", r)
        if not m:
            continue
        k = int(m.group(1)) if segno == "comma" else ordine_lettera(m.group(1))
        if k is None:
            continue
        if corrente and k <= corrente[-1][1]:
            fuori.append(corrente)
            corrente = []
        corrente.append((i, k))
    if corrente:
        fuori.append(corrente)
    return fuori


def collocazioni_decise(nome):
    """Le collocazioni che una persona ha gia' deciso, da «_collocazioni.csv».

    Quando la sequenza non basta il comando si ferma e stampa la porzione. Il posto
    lo trova una persona sulla pagina di Normattiva, e lo scrive li' una volta sola:
    da allora la porzione torna al suo articolo a ogni scaricamento, senza che
    qualcuno debba ricordarsene.
    """
    percorso = os.path.join(LEGGI, "_collocazioni.csv")
    if not os.path.exists(percorso):
        return []
    fuori = []
    for riga in open(percorso, encoding="utf-8"):
        riga = riga.strip()
        if not riga or riga.startswith("//") or riga.startswith("norma;"):
            continue
        pezzi = riga.split(";")
        if len(pezzi) != 4:
            continue
        norma, articolo, comma, inizio = (p.strip() for p in pezzi)
        if norma and norma not in nome:
            continue
        fuori.append((SPAZI.sub("", articolo), comma, piatto(inizio)))
    return fuori


def dentro_il_comma(righe, comma):
    """I due indici fra cui sta il comma indicato, o (None, None) se non serve."""
    if not comma:
        return None, None
    inizio = None
    for i, r in enumerate(righe):
        m = re.match(r"^\(*\s*(\d+)\.", r)
        if not m:
            continue
        if m.group(1) == comma:
            inizio = i
        elif inizio is not None:
            return inizio, i
    return inizio, (len(righe) if inizio is not None else None)


def riga_con(righe, testo):
    """L'indice della riga che porta quel testo, o None: serve a stringere il posto."""
    p = piatto(testo)
    if len(p) < 4:
        return None
    for i, r in enumerate(righe):
        if p in piatto(r):
            return i
    return None


def confine(righe, dove, num, n, verso):
    """Fin dove puo' scendere o salire la porzione dentro l'articolo.

    I segnaposti dell'articolo sono numerati nell'ordine del testo: quelli che
    vengono prima della porzione le fanno da pavimento, quelli che vengono dopo da
    soffitto. Si guardano tutti, non solo il piu' vicino, perche' il piu' vicino
    puo' essere un testo troppo corto per riconoscerlo («((95))»).
    """
    righe_trovate = []
    for k, (art, testo) in dove.items():
        if art != num:
            continue
        if (k < n) != (verso == "prima"):
            continue
        i = riga_con(righe, testo)
        if i is not None:
            righe_trovate.append(i)
    if not righe_trovate:
        return None
    return max(righe_trovate) if verso == "prima" else min(righe_trovate)


def collocazione(righe, marca):
    """I posti in cui la porzione puo' stare dentro l'articolo.

    Il posto lo decide la sequenza che c'e' gia': la lettera c) sta fra la b) e la
    d), e se la b) o la d) non ci sono il posto non e' determinato e non si indovina.
    Ritorna una lista, perche' un articolo con piu' elenchi puo' avere piu' di un
    buco buono: allora la porzione non si colloca.
    """
    if marca.endswith("."):                       # un comma intero: « 1. »
        chiave, segno = int(marca[:-1]), "comma"
    else:
        chiave, segno = ordine_lettera(marca[:-1]), "lettera"
        if chiave is None:
            return []

    gruppi = elenchi(righe, segno)
    if not gruppi:
        # Articolo senza sequenza: se e' vuoto, la porzione e' tutto il suo testo.
        return [(len(righe), "dentro")] if segno == "comma" and not righe[1:] else []

    posti = []
    for gruppo in gruppi:
        if any(k == chiave for _, k in gruppo):
            continue                              # in questo elenco c'e' gia'
        prima = [i for i, k in gruppo if k < chiave]
        dopo = [i for i, k in gruppo if k > chiave]
        if prima and dopo:
            posti.append((min(dopo), "dentro"))   # fra due voci che ci sono: determinato
        elif prima:
            # La lettera chiude l'elenco: l'art. 22 del t.u.i.r. ha la a) e la b) e
            # la c) va in coda. Il posto e' plausibile, non determinato: quasi ogni
            # elenco accetta una voce in coda, e vale solo se non c'e' di meglio.
            posti.append((max(prima) + 1, "in coda"))
    return posti


def reinserisci(xml, sezioni, nome="", allegati=()):
    """Rimette nel testo le porzioni novellate che il corpo dell'XML non contiene.

    Non e' un'aggiunta: il testo e' quello di Normattiva, verbatim, e ci si limita a
    rimetterlo dove la sequenza dice che stava. Le porzioni che la sequenza non
    colloca in modo univoco NON si collocano a naso: escono nell'elenco che il
    comando stampa in coda, e le mette a posto una persona.
    """
    dove, ordine = ins_per_articolo(xml)
    decise = collocazioni_decise(nome)
    per_numero = {}
    for arts in sezioni.values():
        for num, righe in arts:
            per_numero.setdefault(num, []).append(righe)

    # Il confronto si fa sull'articolo intero, non riga per riga: una porzione puo'
    # essere gia' nel corpo spezzata su piu' righe, e riga per riga sembrerebbe persa.
    gia = [piatto(" ".join(righe))
           for arts in sezioni.values() for _, righe in arts]
    # Anche le tabelle allegate contano: il testo che cerchiamo puo' stare li',
    # e nel decreto IVA l'inciso sulle imprese sociali sta proprio nella Tabella A.
    gia += [piatto(" ".join(righe)) for _, righe in allegati]

    def dentro(t):
        campione = " ".join(piatto(t).split()[:12])
        return any(campione in g for g in gia)

    def vicinato(n):
        """Il segnaposto che precede e quello che segue, con il loro testo."""
        prima = max([k for k in dove if k < n], default=None)
        dopo = min([k for k in dove if k > n], default=None)
        return dove.get(prima), dove.get(dopo)

    def candidati(n):
        """Gli articoli in cui la porzione puo' stare: quelli compresi fra il
        segnaposto precedente e il successivo, estremi inclusi. Fra l'art. 416 e
        l'art. 418 c'e' anche il 417, ed e' li' che di solito sta la porzione."""
        pa, pb = vicinato(n)
        a = pa[0] if pa else None
        b = pb[0] if pb else None
        if a in ordine and b in ordine:
            i, j = ordine.index(a), ordine.index(b)
            if i <= j:
                # Prima i due estremi, poi quelli in mezzo: la porzione sta in
                # ordine di documento subito dopo il segnaposto precedente, e
                # l'articolo di quel segnaposto e' di gran lunga il piu' probabile.
                return [a, b] + [x for x in ordine[i + 1:j] if x not in (a, b)]
        return [x for x in (a, b) if x]

    messe, orfane = [], []
    for n, testo in porzioni_novellate(xml):
        if dentro(testo):
            continue                              # il corpo la porta gia': non e' persa
        vicini = candidati(n)
        m = MARCA.match(testo)
        marca = (m.group(1) + ".") if m and m.group(1) else (m.group(2) + ")" if m else None)
        # Il posto dev'essere uno solo in tutto l'intervallo. Fermarsi al primo
        # articolo che ne offre uno sarebbe una scommessa: una lettera in coda la
        # accetta quasi ogni elenco, e qui la scommessa e' un pezzo di legge messo
        # dove non sta. Se il posto non e' determinato la porzione non si colloca:
        # esce nell'elenco in coda e la mette una persona, che ha la pagina davanti.
        # Se qualcuno ha gia' deciso dove va, si guarda solo li'.
        deciso = next(((a, c) for a, c, inizio in decise if inizio in piatto(testo)),
                      (None, None))
        cerca_in = ([deciso[0]] if deciso[0] and deciso[0] in per_numero
                    else dict.fromkeys(vicini))

        posti = []
        if marca:
            for num in cerca_in:
                for righe in per_numero.get(num, []):
                    # I segnaposti vicini stringono anche dentro l'articolo: la
                    # porzione viene dopo la riga che porta il precedente e prima
                    # di quella che porta il successivo. Nell'art. 131 del t.u.
                    # spese di giustizia e' questo che dice «comma 4» e non «comma 2».
                    sotto = confine(righe, dove, num, n, "prima")
                    sopra = confine(righe, dove, num, n, "dopo")
                    if num == deciso[0]:
                        a, b = dentro_il_comma(righe, deciso[1])
                        sotto = a if a is not None else sotto
                        sopra = b if b is not None else sopra
                    for i, forza in collocazione(righe, marca):
                        if sotto is not None and i <= sotto:
                            continue
                        if sopra is not None and i > sopra:
                            continue
                        posti.append((num, righe, i, forza))
        # Prima i posti determinati; quelli in coda valgono solo se non ce ne sono.
        forti = [p for p in posti if p[3] == "dentro"]
        posti = forti or posti
        if len(posti) == 1:
            num, righe, i, forza = posti[0]
            righe.insert(i, testo)
            messe.append((num, marca))
        else:
            estremi = [vicini[0], vicini[-1]] if vicini else []
            orfane.append((sorted(set(estremi), key=estremi.index), testo))
    return messe, orfane


# Normattiva intitola gli allegati che portano un articolo in due modi: «CODICE
# CIVILE-art. 1» e «Testo Unico ... - Art. 4 bis». Sono la stessa cosa, e a
# riconoscerne una sola si perde un testo unico intero.
# La numerazione basta che cominci con una cifra: ci sono l'art. 4 bis del t.u.
# successioni e l'art. 314/2 del codice civile, e pretendere una forma sola ne
# fa cadere 163 in silenzio. Quello che non comincia con una cifra - «Tariffa»,
# «Prospetto dei coefficienti» - non e' un articolo ed e' un allegato.
ALLEGATO_ART = re.compile(r"^(.*?)\s*-\s*art\.\s*(\d.*?)\s*$", re.I)


def taglia_prefisso(etichetta, sezioni):
    """Toglie dal nome dell'allegato il nome della parte che gia' lo contiene."""
    for sez in sezioni:
        if sez and etichetta.startswith(sez):
            return etichetta[len(sez):].lstrip(" -").strip() or etichetta
    return etichetta


def sezioni_di(xml, urn, nome_norma=""):
    """Gli articoli, raggruppati per parte dell'atto.

    Normattiva usa due forme. Gli atti ordinari hanno elementi «article» dentro il
    corpo. I codici approvati con Regio Decreto hanno invece un allegato per ogni
    articolo, perche' un solo decreto porta piu' testi: il c.c. contiene il codice e
    le disposizioni sulla legge in generale, ognuna con i suoi articoli 1, 2, 3. In
    un file solo avrebbero «## art. 1» ripetuto con contenuti diversi, quindi ogni
    parte va nel suo file.
    """
    radice = ET.fromstring(xml)
    ident = radice.find(".//" + AKN + "identification")
    alias = ident.find(".//" + AKN + "FRBRalias[@name='urn:nir']")
    eli = ident.find(".//" + AKN + "FRBRalias[@name='eli']")
    consolidato = None
    if eli is not None:
        m = re.search(r"CONSOLIDATED/(\d{4})(\d{2})(\d{2})", eli.get("value"))
        if m:
            consolidato = "%s-%s-%s" % m.groups()

    sezioni = {}
    allegati = []
    for doc in radice.iter(AKN + "doc"):                 # forma «un allegato per articolo»
        etichetta = doc.get("name") or ""
        righe = []
        letti = set()                                    # la nota annidata: cfr. righe_articolo
        for p in doc.iter(AKN + "p"):
            if p in letti:
                continue
            letti.update(p.iter())
            t = SPAZI.sub(" ", "".join(p.itertext()).replace("\n", " ")).strip()
            if t:
                righe.append(t)
        m = ALLEGATO_ART.match(etichetta)
        if not m:
            # Parte che non e' fatta di articoli: tabelle, tariffe, prospetti.
            # Non ha numerazione, quindi non entra fra le sezioni, ma e' norma a
            # tutti gli effetti: nel decreto IVA le aliquote ridotte stanno nella
            # Tabella A, e nel t.u. sulle successioni le aliquote e le franchigie
            # stanno nella Tariffa. Senza questo ramo il file usciva senza.
            if righe:
                allegati.append((etichetta.strip(), righe))
            continue
        # «42 bis» diventa «42bis»: cosi' si cita e cosi' lo vuole l'URN (~art42bis)
        sezioni.setdefault(m.group(1).strip(), []).append(
            (SPAZI.sub("", m.group(2).strip()), righe))

    # «Testo Unico ... - Tariffa» si intitola «Tariffa»: il nome della parte e' gia'
    # il titolo del file, e ripeterlo in ogni intestazione non aggiunge niente.
    if allegati and sezioni:
        allegati = [(taglia_prefisso(e, sezioni), r) for e, r in allegati]

    if len(sezioni) > 1:
        # Le parti si tengono separate solo se la numerazione si scontra. Il c.c. ha
        # il codice e le disposizioni sulla legge in generale, tutti e due con gli
        # articoli 1, 2, 3: due file. Il D.Lgs. 271/1989 invece e' un testo solo, ma
        # Normattiva intitola l'articolo 1 «Norme di attuazione del codice di
        # procedura penale» e i successivi «Norme»: numerazione continua, un file.
        numeri = [set(n for n, _ in arts) for arts in sezioni.values()]
        scontro = any(numeri[i] & numeri[j]
                      for i in range(len(numeri)) for j in range(i + 1, len(numeri)))
        if not scontro:
            titolo = max(sezioni, key=len)               # il nome piu' esteso e' il vero titolo
            sezioni = {titolo: [a for arts in sezioni.values() for a in arts]}

    # Il corpo dell'atto si legge SEMPRE, non solo quando di allegati non ce ne sono:
    # un atto puo' avere tutte e due le forme insieme. Il D.Lgs. 231/2007 porta 88
    # articoli nel corpo e un «Allegato Tecnico» con quattro articoli suoi, e finche'
    # il corpo si leggeva solo «if not sezioni» ne usciva un file di quattro articoli
    # abrogati al posto della norma. Corpo e allegato restano separati: l'allegato
    # non e' l'atto, e la fusione qui sopra vale fra allegati.
    corpo = []
    for art in radice.iter(AKN + "article"):
        eid = art.get("eId") or ""
        num = eid[4:].replace("-", "") if eid.startswith("art_") else ""
        if not num:
            m = re.search(r"Art\.?\s*([0-9]+(?:[\-\s]?[a-z]+)*)",
                          "".join(art.itertext()))
            num = SPAZI.sub("", m.group(1).replace("-", "")) if m else "?"
        corpo.append((num, righe_articolo(art)))

    dal_corpo = None
    if corpo:
        dal_corpo = intestazione_da_urn(urn)
        if dal_corpo in sezioni:                         # un allegato omonimo non prende il posto del corpo
            dal_corpo += " (corpo dell'atto)"
        sezioni = dict([(dal_corpo, corpo)] + list(sezioni.items()))

    # Le porzioni riscritte dal legislatore stanno nei metadati, e quando la novella
    # ha rifatto un punto o un comma intero il corpo non le contiene: senza questo
    # passaggio il file esce muto proprio dove la norma e' cambiata.
    messe, orfane = reinserisci(xml, sezioni, nome_norma, allegati)

    return (sezioni, (alias.get("value") if alias is not None else ""),
            consolidato, dal_corpo, messe, orfane, allegati)


# La formula che approva o rende esecutivo un testo: «E' approvato il testo…», «Il Presidente
# della Repubblica e' autorizzato a ratificare…», «Piena ed intera esecuzione…», l'entrata in
# vigore, gli oneri, l'originale depositato, il sigillo. Il corpo e' formula se lo e' OGNI suo
# articolo, oppure se e' breve (fino a tre articoli, come i codici regi) e uno di essi approva
# o ratifica il testo.
FORMULA = re.compile(r"approvat|autorizzat\w* a ratificare|piena (?:ed|e) intera esecuzione|"
                     r"(?:e'|è|e`) data (?:piena )?esecuzione|entra(?:no)? in vigore|entrer\w* in vigore|"
                     r"oneri|copertura finanziaria|originale|depositat\w* e custodit|sigillo", re.I)
APPROVA = re.compile(r"(?:e'|è|sono) approvat|autorizzat\w* a ratificare", re.I)

def e_formula(articoli):
    testi = [" ".join(righe) for _, righe in articoli]
    return (all(FORMULA.search(t) for t in testi)
            or (len(testi) <= 3 and any(APPROVA.search(t) for t in testi)))


CONSULTA = re.compile(r"Corte Costituzionale.{0,140}?ha dichiarato", re.I | re.S)
AVVISO = ("⚠️ La Corte costituzionale è intervenuta su questo articolo: "
          "leggere la nota in coda prima di citarlo.")


def toccato_dalla_consulta(righe):
    """Vero se all'articolo è allegata una pronuncia della Consulta.

    Normattiva, per le dichiarazioni di illegittimita', NON toglie le parole colpite:
    lascia il testo intero e mette la notizia in una nota in coda. Chi legge l'art. 58
    comma 3 del D.Lgs. 546/1992 trova ancora «il deposito delle deleghe, delle procure
    e degli altri atti di conferimento di potere», che e' proprio cio' che la sentenza
    n. 36/2025 ha espunto, e lo scopre venti righe dopo. L'avviso serve a non far
    citare per intero un testo che per intero non vale piu'.

    L'avviso dice che c'e' stato un intervento e rimanda alla nota: non pretende di
    dire che cosa sia caduto, perche' quello si legge nel dispositivo.
    """
    return bool(CONSULTA.search("\n".join(righe)))


MESI = ("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre "
        "novembre dicembre").split()
DECORRENZA = re.compile(
    r"(?:entra(?:no)? in vigore|si applica(?:no)?|ha(?:nno)? effetto|acquista(?:no)? "
    r"efficacia)[^.]{0,80}?(?:dal|il)\s+\(*\s*(\d{1,2})[°º]?\s+(%s)\s+(\d{4})"
    % "|".join(MESI), re.I)
NOTA_AGGIORNAMENTO = re.compile(
    r"AGGIORNAMENTO \(\w+\)(.*?)(?=-{5,}|AGGIORNAMENTO \(|Note all|Avvertenza:|\Z)", re.S)
AVVISO_FUTURO = ("⚠️ Le note danno in vigore dal %s modifiche a questo articolo: il testo fra "
                 "doppie parentesi può non essere ancora vigente alla data di questo file. "
                 "Leggere le note prima di citarlo.")


def decorrenze_future(righe, vigenza):
    """Le decorrenze successive alla vigenza che le note annunciano, se l'articolo ha
    testo novellato fra doppie parentesi. Date ISO, in ordine.

    ⚠️ Normattiva scrive la modifica nel testo anche prima che morda, e la decorrenza la
    mette nella sola nota: l'art. 27 del D.Lgs. 116/2017 sposta competenze dal tribunale
    al giudice di pace dal 31.10.2027, e prima di quella data l'art. 1211 c.c. dice
    gia' «((giudice di pace))», nell'export e sulla pagina. E' l'anticipo delle
    abrogazioni appiattite su una sostituzione di parole, e la pagina web non aiuta
    perche' anche lei da' il testo nuovo. Come per la Consulta, l'avviso non dice quale
    parola valga: rimanda alla nota, dove sta la data.

    La data si cerca SOLO nelle note «AGGIORNAMENTO (N)» di Normattiva. L'articolo di
    decorrenza di un testo unico porta la data futura nel suo testo, ed e' la norma; e le
    «Note all'art. N» della Gazzetta riportano il testo di altre leggi con le loro date.
    """
    testo = "\n".join(righe)
    if "((" not in testo:
        return []
    note = " ".join(m.group(1) for m in NOTA_AGGIORNAMENTO.finditer(testo))
    date = set()
    for m in DECORRENZA.finditer(note):
        d = "%s-%02d-%02d" % (m.group(3), MESI.index(m.group(2).lower()) + 1, int(m.group(1)))
        if d > vigenza:
            date.add(d)
    return sorted(date)


def avvisi_articolo(righe, vigenza):
    """Le righe d'avviso da scrivere sotto «## art. N», nell'ordine."""
    avvisi = [AVVISO] if toccato_dalla_consulta(righe) else []
    future = decorrenze_future(righe, vigenza)
    if future:
        avvisi.append(AVVISO_FUTURO % ", ".join(data_it(d) for d in future))
    return avvisi


ABROGATO = re.compile(r'(?:ARTICOLO|PROVVEDIMENTO) ABROGAT\w+ DAL\w?\s+([^)]{0,140})', re.I)


def articoli_svuotati(sezioni, soglia=2023):
    """Articoli ridotti alla sola scritta «abrogato» da un atto recente.

    L'export XML di Normattiva NON rispetta la data di vigenza sulle abrogazioni di
    singolo articolo: restituisce «ARTICOLO ABROGATO» anche quando quell'abrogazione
    non e' ancora efficace, mentre la pagina web, alla stessa vigenza, da' il testo
    pieno. Esempio: l'art. 21bis del D.Lgs. n. 74/2000, abrogato dal D.Lgs. n.
    175/2024 con effetto dal 01.01.2027: prima di quella data l'XML lo da' per
    abrogato, la pagina no. Il caso riguarda soprattutto le norme tributarie.

    Le abrogazioni vecchie sono quasi sempre vere e non si segnalano: si guarda solo
    agli atti degli ultimi anni, dove il differimento e' la regola.
    """
    fuori = []
    for articoli in sezioni.values():
        for num, righe in articoli:
            corpo = "\n".join(righe).strip()
            if len(corpo) > 400:
                continue
            m = ABROGATO.search(corpo)
            if not m:
                continue
            anni = [int(a) for a in re.findall(r"\b(19\d\d|20\d\d)\b", m.group(1))]
            if anni and max(anni) >= soglia:
                fuori.append((num, SPAZI.sub(" ", m.group(1)).strip()[:60]))
    return fuori


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def simili(nome, urn):
    """File gia' presenti che sembrano la stessa norma: solo da segnalare."""
    coda = urn.split(":")[-1]                # «2000-03-10;74», anche dall'URN per esteso
    numeri = set(re.findall(r"\d+", coda.split(";")[-1] + " " + coda[:4]))
    fuori = []
    for f in sorted(os.listdir(LEGGI)):
        if f.startswith("."):
            continue
        base = slug(os.path.splitext(f)[0])
        if slug(nome) in base or (numeri and numeri <= set(re.findall(r"\d+", f))):
            fuori.append(f)
    return fuori


# Le versioni superate. Il file nuovo non si affianca al vecchio: la copia che sostituisce
# va in «_archivio/», col suo nome, cosi' non torna fra le «da riscaricare» a ogni
# --controlla e non esce accanto alla copia viva. Nulla si perde.
ARCHIVIO = "_archivio"
NOME_VERSIONE = re.compile(r"(.+)_vigenza-(\d{4}-\d{2}-\d{2})\.md")
# La testa di un file dichiara il testo che non viene dall'export: «rimesso a mano»,
# «Scritto a mano». ⚠️ Non basta «a mano»: «Guardato a mano il ...» e' un controllo fatto
# sulla pagina, non testo scritto. Si prende il verbo che scrive.
A_MANO = re.compile(r"\b(?:ri)?(?:mess|scritt|aggiunt|innestat|ripristinat|copiat)[oaie]\s+a\s+mano",
                    re.I)


def archivia_superate(scritti, congelata=False):
    """Sposta in «_archivio/» le copie che i file appena scritti sostituiscono.
    Ritorna (spostate, lasciate): nomi di file, e per le lasciate anche il perche'.

    Con `congelata` non sposta niente: un testo chiesto con --vigenza a una data passata
    e' un documento storico che si AFFIANCA, non la versione che sostituisce. Il controllo
    sta qui dentro e non in chi chiama, perche' e' il caso che fa danno: congelando al
    01.10 una norma la cui copia viva e' del 20.09, la data da sola direbbe «anteriore» e
    la radice resterebbe senza copia viva.

    Una copia e' superata solo se ha lo STESSO nome fino a «_vigenza-» - identico, non
    simile: «codice-civile» non e' «codice-civile_disposizioni-sulla-legge-in-generale» -
    una data ANTERIORE a quella del file nuovo, e non e' congelata. Tutto il resto resta
    dov'e'. Non sovrascrive: se nell'archivio c'e' gia' un file con quel nome la copia
    resta nella radice e lo si dice, perche' due testi diversi con lo stesso nome non si
    decidono da qui. E non sposta niente se il file nuovo non c'e' o e' vuoto: la radice
    non deve restare senza copia viva."""
    spostate, lasciate = [], []
    if congelata:
        return spostate, lasciate
    for nuovo in scritti:
        m = NOME_VERSIONE.fullmatch(nuovo)
        pieno = os.path.join(LEGGI, nuovo)
        if not m or not os.path.isfile(pieno) or not os.path.getsize(pieno):
            continue
        for f in sorted(os.listdir(LEGGI)):
            v = NOME_VERSIONE.fullmatch(f)
            if not v or f == nuovo or v.group(1) != m.group(1) or v.group(2) >= m.group(2):
                continue
            vecchio = os.path.join(LEGGI, f)
            with open(vecchio, encoding="utf-8", errors="replace") as fh:
                testa = fh.read(3000).split("\n## ")[0]
            if "Vigenza congelata:" in testa:
                continue
            arrivo = os.path.join(LEGGI, ARCHIVIO, f)
            if os.path.exists(arrivo):
                lasciate.append((f, "in «%s/» c'e' gia' un file con questo nome" % ARCHIVIO))
                continue
            os.makedirs(os.path.join(LEGGI, ARCHIVIO), exist_ok=True)
            os.rename(vecchio, arrivo)
            spostate.append((f, bool(A_MANO.search(testa))))
    return spostate, lasciate


def elenco():
    print("Legislazione: %s\n" % LEGGI)
    for f in sorted(os.listdir(LEGGI)):
        if not f.endswith(".md") or f.startswith("."):
            continue
        vig = re.search(r"vigenza-(\d{4}-\d{2}-\d{2})", f)
        print("  %-64s %s" % (f, data_it(vig.group(1)) if vig
                              else "vigenza NON dichiarata"))
    return 0


# Il preambolo dell'atto dentro l'articolo 1. Gli allegati del Codice privacy sono
# delibere del Garante recepite come regole deontologiche, e Normattiva ci mette
# davanti il provvedimento intero - visti, ritenuti, firme - senza staccarlo dal
# primo articolo, tutto su una riga sola. Nell'allegato A.6 sono 5.970 caratteri su
# 7.437, l'80%: chi cerca «investigazioni difensive» riceve il preambolo etichettato
# «art. 1», e siccome e' una riga sola viene stampato per intero.
#
# Il testo non si butta - e' la fonte, e li' dentro c'e' il numero della delibera e
# la ragione per cui quelle regole sono in vigore - e non si riscrive: si sposta
# verbatim in una sezione sua, e l'articolo 1 torna a essere l'articolo 1.
#
# La soglia e' alta apposta. Sulle 44 norme in cartella il fenomeno riguarda i soli
# sette allegati del Codice privacy, dal 71% al 96% del primo articolo, e nessun
# altro atto arriva a 800 caratteri prima della rubrica: sotto quella misura si
# tratta della rubrica stessa o di un inciso, e non si tocca niente.
PREAMBOLO_MINIMO = 800
# la rubrica, non un rimando: Normattiva scrive «Art. 1. ((Ambito di applicazione))»
# con la maiuscola e il punto dopo il numero, mentre i richiami dentro il testo
# suonano «dell'art. 1 del decreto» o «articolo 1, comma 2». La maiuscola e il punto
# insieme sono il discrimine; il lookbehind esclude i casi attaccati a una parola.
RUBRICA_PRIMA = re.compile(r"(?<![\w'’])Art(?:icolo)?\.?\s*1\.")


def stacca_preambolo(articoli):
    """(righe di preambolo, articoli) staccando il preambolo dal primo articolo."""
    if not articoli:
        return [], articoli
    num, righe = articoli[0]
    if num != "1" or not righe:
        return [], articoli
    for i, riga in enumerate(righe):
        m = RUBRICA_PRIMA.search(riga)
        if not m:
            continue
        # il preambolo e' quanto precede la rubrica, sulla stessa riga o nelle righe
        # prima: si conta tutto, perche' la soglia guarda il peso, non la forma
        prima = righe[:i] + ([riga[:m.start()]] if m.start() else [])
        if sum(len(r) for r in prima) < PREAMBOLO_MINIMO:
            return [], articoli
        dopo = ([riga[m.start():]] if m.start() else [riga]) + righe[i + 1:]
        return [r for r in prima if r.strip()], [(num, dopo)] + articoli[1:]
    return [], articoli


def indice():
    """Riscrive «_indice.md»: la prima pagina della banca dati normativa.

    E' corto apposta. Il testo delle norme sta nei file e si pesca al bisogno con una
    ricerca sul titolo «## art. N»; questo dice soltanto che cosa si ha in mano e di
    che versione, che e' la domanda da farsi prima di citare.
    """
    righe = []
    for f in sorted(os.listdir(LEGGI)):
        if not f.endswith(".md") or f.startswith((".", "_")):
            continue
        with open(os.path.join(LEGGI, f), encoding="utf-8", errors="replace") as fh:
            t = fh.read()
        titolo = re.search(r"^# (.+)$", t, re.M)
        urn = re.search(r"URN: `([^`]+)`", t)
        vig = re.search(r"vigenza-(\d{4}-\d{2}-\d{2})", f)
        ver = re.search(r"Ultima versione dell'atto: ([\d.]+)", t)
        art = len(re.findall(r"^## art\. \S+$", t, re.M))
        righe.append((titolo.group(1).strip() if titolo else f[:-3],
                      f, urn.group(1) if urn else "",
                      data_it(vig.group(1)) if vig else "NON DICHIARATA",
                      (ver.group(1) or "").rstrip(".") if ver else "", art))

    percorso = os.path.join(LEGGI, "_indice.md")
    with open(percorso, "w", encoding="utf-8") as fh:
        fh.write("# Legislazione — indice\n\n")
        fh.write("Che norme ci sono in questa cartella e di che versione. "
                 "Riscritto da `scarica-norma --indice` il %s.\n\n"
                 % data_it(time.strftime("%Y-%m-%d")))
        fh.write("**Il testo di una norma si prende da qui, non a memoria.** Ogni "
                 "articolo sta sotto il suo titolo «## art. N». Se la norma "
                 "non c'e', o la sua versione non copre la data che rileva nella causa, "
                 "si dice e non si tira a indovinare.\n\n")
        fh.write("| Norma | Atto | Articoli | Vigenza del file | Ultima versione |\n")
        fh.write("| --- | --- | ---: | --- | --- |\n")
        for titolo, f, urn, vig, ver, art in righe:
            # il nome comune e' quello del file, cioe' come chi scarica chiama la norma;
            # il titolo ufficiale da solo non fa trovare niente
            comune = f.split("_vigenza-")[0].replace("-", " ").replace("_", " — ").capitalize()
            fh.write("| [%s](%s) | %s | %d | %s | %s |\n"
                     % (comune, f.replace(" ", "%20"), titolo, art, vig, ver or "—"))
        fh.write("\n## URN per riscaricare\n\n")
        fh.write("Con `scarica-norma.py \"<urn>\" <nome>`.\n\n")
        for titolo, f, urn, vig, ver, art in righe:
            if urn:
                fh.write("- %s — `%s`\n" % (titolo, urn_corto(urn)))
    print("scritto: %s  (%d norme)" % (percorso, len(righe)))
    return 0


# Le connessioni con Normattiva si spezzano a meta' (IncompleteRead), soprattutto dietro
# un proxy o una sandbox. Si legge quindi a pezzi, ci si ferma appena compare cio' che serve, e se la connessione
# cade si tiene il parziale; se il parziale non basta si ritenta, con attese crescenti.
PEZZO = 8192
ATTESE = (5, 20, 60)
LINK_AKN = re.compile(rb"caricaAKN\?dataGU=(\d+)&(?:amp;)?codiceRedaz=([A-Za-z0-9]+)")
# Solo l'alias ELI: «gu:tables/versions#ORIGINAL» sta anche negli XML consolidati.
ALIAS_ELI = re.compile(rb"eli/id/[^\"<\s]*?/(?:CONSOLIDATED/(\d{4})(\d{2})(\d{2})|ORIGINAL)\b")
ORIGINALE = "ORIGINAL"


def leggi_fino(op, richiesta, timeout, cerca=None):
    """Legge la risposta a pezzi da 8 KB. Con `cerca`, si ferma al primo pezzo che lo
    contiene; se la connessione cade dopo, il parziale basta. Se cade prima, rilancia
    l'errore: lo raccoglie con_tentativi."""
    dati = bytearray()

    def trovato(nuovi):
        return cerca is not None and cerca.search(dati, max(0, len(dati) - nuovi - 512))

    try:
        r = op.open(richiesta, timeout=timeout)
        try:
            while True:
                pezzo = r.read(PEZZO)
                if not pezzo:
                    break
                dati += pezzo
                if trovato(len(pezzo)):
                    break
        finally:
            r.close()
    except http.client.IncompleteRead as e:
        dati += e.partial
        if not trovato(len(e.partial)):
            raise
    return bytes(dati)


def con_tentativi(fare):
    """Quattro tentativi: subito, poi dopo 5, 20 e 60 secondi. Un errore 4xx non si
    ritenta, perche' non e' un intoppo della rete ma una richiesta sbagliata."""
    for attesa in ATTESE + (None,):
        try:
            return fare()
        except (OSError, http.client.HTTPException) as e:
            if attesa is None or (isinstance(e, urllib.error.HTTPError)
                                  and 400 <= e.code < 500 and e.code != 429):
                raise
            time.sleep(attesa)


def versione_su_normattiva(op, urn, vigenza):
    """La data dell'ultima versione consolidata dell'atto, letta da Normattiva, oppure
    ORIGINALE se l'atto non e' mai stato modificato.

    La data sta nell'alias ELI dei primi 8 KB dell'XML, e l'atto intero puo' pesare dieci
    megabyte: si legge a pezzi e ci si ferma li'. L'intestazione Range non si manda,
    perche' Normattiva la ignora e risponde comunque con l'atto intero.
    """
    pagina = "https://www.normattiva.it/uri-res/N2Ls?%s!vig=%s" % (urn_pieno(urn), vigenza)
    html = con_tentativi(lambda: leggi_fino(op, pagina, 45, LINK_AKN))
    m = LINK_AKN.search(html)
    if not m:
        raise RuntimeError("nessun export per questo URN")
    time.sleep(1.5)
    u = ("https://www.normattiva.it/do/atto/caricaAKN"
         "?dataGU=%s&codiceRedaz=%s&dataVigenza=%s" % (m.group(1).decode(), m.group(2).decode(),
                                                       vigenza.replace("-", "")))
    testa = con_tentativi(lambda: leggi_fino(op, u, 90, ALIAS_ELI))
    e = ALIAS_ELI.search(testa)
    if not e:
        raise RuntimeError("l'intestazione non porta la data di consolidamento")
    if e.group(1) is None:
        return ORIGINALE
    return "%s-%s-%s" % tuple(g.decode() for g in e.groups())


def controlla(filtro=None):
    """Confronta la versione dei file locali con quella su Normattiva.

    Da lanciare una volta al mese. Quando non riesce a leggere lo dice: un controllo
    che fallisce in silenzio e conclude «tutto a posto» e' peggio di nessun controllo,
    perche' da' una tranquillita' falsa.
    """
    oggi = time.strftime("%Y-%m-%d")
    op = apri(oggi)
    vecchie, uguali, rotte, congelate, fuori = [], 0, [], [], []
    for f in sorted(os.listdir(LEGGI)):
        if not f.endswith(".md") or f.startswith((".", "_")):
            continue
        if filtro and filtro.lower() not in f.lower():
            continue
        t = open(os.path.join(LEGGI, f), encoding="utf-8", errors="replace").read()
        u = re.search(r"URN: `(urn:nir:[^`]+)`", t)
        v = re.search(r"Ultima versione dell'atto: ([\d.]+)", t)
        nome = f.split("_vigenza-")[0]
        # Un testo congelato non e' indietro e non si riscarica: si dice e si passa oltre,
        # senza toccare la rete. Proporre di riscaricarlo metterebbe in cartella un file
        # col nome di una data passata e il testo di oggi.
        if "Vigenza congelata:" in t:
            congelate.append(nome)
            print("  ~ %-46s congelata alla vigenza del file, non si riscarica" % nome)
            continue
        if not u:
            # Senza URN non c'e' niente da chiedere a Normattiva, e quasi sempre e'
            # perche' la norma non e' italiana: le europee vengono da EUR-Lex. «Non
            # verificata» le metterebbe accanto alle ignote vere, e quella parola va
            # trattata come un allarme. Sono fuori perimetro, che e' un'altra cosa e si
            # dice diversamente.
            fuori.append((f, "non viene da Normattiva: nessun URN nel file"))
            continue
        locale = v.group(1).rstrip(".") if v else None
        try:
            su_normattiva = versione_su_normattiva(op, u.group(1), oggi)
        except Exception as e:
            rotte.append((f, "%s: %s" % (type(e).__name__, e))); continue
        # ORIGINAL: l'atto non e' mai stato modificato, e Normattiva non da' una data. Il
        # file senza la riga della versione e' allineato; quello che una data la dichiara
        # contraddice Normattiva, e una contraddizione non si scioglie da soli.
        if su_normattiva == ORIGINALE:
            if locale is None:
                uguali += 1
                print("  = %-46s mai modificata" % nome)
            else:
                rotte.append((f, "su Normattiva l'atto non e' mai stato modificato (ORIGINAL), "
                                 "ma il file dichiara la versione %s" % locale))
                continue
            time.sleep(1.5)
            continue
        adesso = data_it(su_normattiva)
        if locale == adesso:
            uguali += 1
            print("  = %-46s %s" % (nome, adesso))
        else:
            vecchie.append((nome, u.group(1), locale, adesso))
            print("  ! %-46s locale %s -> su Normattiva %s"
                  % (nome, locale or "?", adesso))
        time.sleep(1.5)

    print("\naggiornate: %d | da riscaricare: %d | congelate: %d | "
          "fuori perimetro: %d | non verificate: %d"
          % (uguali, len(vecchie), len(congelate), len(fuori), len(rotte)))
    if congelate:
        print("\nCONGELATE — chieste apposta a una vigenza passata, non si riscaricano:")
        for nome in congelate:
            print("  %s" % nome)
    if fuori:
        print("\nFUORI PERIMETRO — questo controllo interroga Normattiva, e queste non "
              "sono sue:")
        for f, m in fuori:
            print("  %s  (%s)" % (f, m))
    if rotte:
        print("\nNON VERIFICATE — non si sa se siano aggiornate:")
        for f, m in rotte:
            print("  %s  (%s)" % (f, m))
    if vecchie:
        print("\nPer riscaricarle:")
        for urn, nome in comandi_per_riscaricare(vecchie):
            print('  scarica-norma "%s" %s' % (urn, nome))

    # Il controllo delle lettere non tocca la rete e non costa niente, quindi si fa
    # sempre insieme a questo: e' l'unico che vede i pezzi mangiati dentro un comma,
    # dove il file resta della versione giusta e il guasto non lascia segno.
    print("\nLettere negli elenchi:")
    lettere = verifica_lettere(filtro)
    return 1 if (vecchie or rotte or lettere) else 0


def comandi_per_riscaricare(vecchie):
    """I comandi da stampare sotto «Per riscaricarle»: uno per URN, col nome BASE.

    ⚠️ Una norma che Normattiva divide in parti
    sta in cartella come piu' file - «...-2027_vigenza-x.md» e
    «...-2027_allegato-3_vigenza-x.md» - e il suffisso «_allegato-3» **lo aggiunge questo
    comando**, ricavandolo dal nome della sezione. Stampare un comando per file passava
    quel suffisso come se fosse il nome, e rieseguirlo alla lettera creava un doppione col
    nome storto («...-2027-allegato-3_allegato-3_vigenza-x.md»), identico byte per byte al
    gemello giusto.

    Il nome base e' il **piu' corto** fra i file che portano lo stesso URN, ed e' quello
    con cui la norma fu scaricata: riscaricare quello rifa' da se' tutte le sue parti.
    """
    per_urn = {}
    for nome, urn, _, _ in vecchie:
        if urn not in per_urn or len(nome) < len(per_urn[urn]):
            per_urn[urn] = nome
    return sorted((urn, nome) for urn, nome in per_urn.items())


def solo_testo(pagina):
    """Il testo leggibile di una pagina HTML, senza tag e senza spazi doppi."""
    p = re.sub(r"<script.*?</script>|<style.*?</style>", "", pagina, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", p))).strip()


def sigla(s):
    """«art. 473 bis.67» e «473bis.67» devono essere la stessa cosa."""
    return re.sub(r"[^a-z0-9.]", "", s.lower())


def albero_articoli(op, urn, vigenza):
    """La pagina dell'atto alla vigenza voluta, e i link ai singoli articoli.

    Serve a due cose insieme: fissa la vigenza nella sessione e raccoglie i
    «caricaArticolo» dell'albero. I codici li hanno; certi atti, come il testo unico
    delle spese di giustizia, no, e li' l'articolo arriva dentro la pagina stessa.
    """
    url = "https://www.normattiva.it/uri-res/N2Ls?%s!vig=%s" % (urn_pieno(urn), vigenza)
    pagina = con_tentativi(lambda: leggi_fino(op, url, 90)).decode("utf-8", "replace")
    mappa = {}
    for m in re.finditer(r"showArticle\('([^']+)'[^>]*>\s*art\.\s*([^<]+)</a>", pagina):
        mappa[sigla(m.group(2))] = "https://www.normattiva.it" + unescape(m.group(1))
    return mappa


def corpo_articolo(op, urn, vigenza, num, mappa):
    """Il testo dell'articolo come lo mostra la PAGINA, non l'export XML."""
    url = mappa.get(sigla(num))
    if not url:
        # Senza albero si chiede l'articolo per URN: la pagina se lo porta dentro.
        url = ("https://www.normattiva.it/uri-res/N2Ls?%s~art%s!vig=%s"
               % (urn_pieno(urn), num, vigenza))
    t = solo_testo(con_tentativi(lambda: leggi_fino(op, url, 90)).decode("utf-8", "replace"))
    if "aggiornamenti all'articolo" not in t:
        raise RuntimeError("la pagina non mostra il testo dell'articolo")
    corpo = t.split("aggiornamenti all'articolo", 1)[1]
    return corpo.split("articolo precedente", 1)[0].strip()


def verifica_abrogati(filtro=None):
    """Apre su Normattiva gli articoli che la cartella da' per abrogati di recente.

    «--controlla» verifica la forma: che il file sia alla versione giusta. Questo
    verifica il contenuto: un controllo che guarda la forma e non il contenuto
    certifica anche una cartella di articoli vuoti.
    """
    op = apri(time.strftime("%Y-%m-%d"))
    confermati, pieni, rotti, fuori = 0, [], [], []
    for f in sorted(os.listdir(LEGGI)):
        if not f.endswith(".md") or f.startswith((".", "_")):
            continue
        if filtro and filtro.lower() not in f.lower():
            continue
        # ⚠️ La cartella e' viva: fra il listdir e la lettura un file puo' sparire - un
        # doppione tolto, una rinomina, un altro giro che lavora. La norma si dichiara non
        # verificata e il giro prosegue, invece di morire a meta' perdendo quelle gia'
        # guardate.
        try:
            testo = open(os.path.join(LEGGI, f), encoding="utf-8", errors="replace").read()
        except OSError as e:
            rotti.append((f.split("_vigenza-")[0],
                          "non si e' potuto leggere: %s" % e.__class__.__name__))
            continue
        nome = f.split("_vigenza-")[0]
        v = re.search(r"_vigenza-(\d{4}-\d{2}-\d{2})\.md$", f)
        u = re.search(r"URN: `(urn:nir:[^`]+)`", testo)
        # Stessa distinzione che fa gia' `--controlla`, e per la stessa ragione: una
        # norma senza URN di Normattiva non e' «non verificata», e' FUORI PERIMETRO -
        # quasi sempre e' europea e viene da EUR-Lex, dove questo comando non arriva.
        # Tenerla fra le non verificate la mette accanto alle ignote vere, e «non
        # verificata» si legge come un allarme che nessun giro potrebbe chiudere.
        if not u:
            fuori.append((nome, "non viene da Normattiva: nessun URN nel file"))
            continue
        if not v:
            rotti.append((nome, "-", "il file non dichiara la vigenza"))
            continue
        urn, vigenza = u.group(1), v.group(1)

        da_vedere = []
        for pezzo in re.split(r"\n## art\. ", testo)[1:]:
            num = pezzo.split("\n", 1)[0].strip()
            corpo = (pezzo.split("\n", 1)[1] if "\n" in pezzo else "").strip()
            if len(corpo) > 400:
                continue
            m = ABROGATO.search(corpo)
            if not m:
                continue
            anni = [int(a) for a in re.findall(r"\b(19\d\d|20\d\d)\b", m.group(1))]
            if anni and max(anni) >= 2023:
                da_vedere.append(num)
        if not da_vedere:
            continue

        print("\n%s — %d da verificare alla vigenza del %s"
              % (nome, len(da_vedere), data_it(vigenza)))
        try:
            mappa = albero_articoli(op, urn, vigenza)
        except Exception as e:
            print("  ! atto non aperto: %s" % e)
            for num in da_vedere:
                rotti.append((nome, num, "atto non aperto"))
            continue
        for num in da_vedere:
            try:
                corpo = corpo_articolo(op, urn, vigenza, num, mappa)
            except Exception as e:
                print("  ? art. %-16s non verificato (%s)" % (num, e))
                rotti.append((nome, num, str(e)))
                time.sleep(1.5)
                continue
            if ABROGATO.search(corpo):
                confermati += 1
                print("  = art. %-16s abrogato anche sulla pagina" % num)
            else:
                pieni.append((nome, num, urn, vigenza))
                print("  ! art. %-16s la pagina da' il TESTO PIENO: %s"
                      % (num, corpo[:70]))
            time.sleep(1.5)

    print("\nabrogazioni confermate: %d | articoli da rimettere: %d | "
          "fuori perimetro: %d | non verificati: %d"
          % (confermati, len(pieni), len(fuori), len(rotti)))
    if fuori:
        print("\nFUORI PERIMETRO — non vengono da Normattiva, e non e' un guasto:")
        for nome, perche in fuori:
            print("  %-46s %s" % (nome, perche))
    if rotti:
        print("\nNON VERIFICATI — «non lo so» non e' «va bene»:")
        for nome, num, perche in rotti:
            print("  %s art. %s  (%s)" % (nome, num, perche))
    if pieni:
        print("\nDA RIMETTERE A MANO — l'abrogazione non e' ancora efficace e il\n"
              "testo vero sta sulla pagina, non nell'export:")
        for nome, num, urn, vigenza in pieni:
            print("  %s art. %s" % (nome, num))
            print("    https://www.normattiva.it/uri-res/N2Ls?%s~art%s!vig=%s"
                  % (urn_pieno(urn), num, vigenza))
    return 1 if (pieni or rotti) else 0


ALFA = "abcdefghilmnopqrstuvz"   # alfabeto italiano: niente j, k, w, x, y


def verifica_lettere(filtro=None):
    """Cerca gli elenchi a cui manca una lettera: a) b) d), senza la c).

    Terzo difetto noto dell'export XML, e il piu' silenzioso dei tre. Gli altri due riguardano l'articolo intero: «--controlla» vede il file
    vecchio, «--verifica-abrogati» vede l'articolo svuotato. Questo mangia una
    lettera dentro un comma e non lascia segno: l'articolo c'e', e' della versione
    giusta, ha il suo testo, e quello che manca non manca visibilmente.

    Sparisce quello che il legislatore ha riscritto, cioe' le porzioni che
    Normattiva marca fra doppie parentesi. Nel D.Lgs. n. 14/2019 era sparita la
    soglia IVA che fa scattare la segnalazione dell'Agenzia (art. 25-novies, comma
    1, lettera c); nel c.p.p. la lettera e) dell'art. 546, cioe' la motivazione
    della sentenza penale.

    Non tocca la rete: legge quello che c'e' sul disco. Un salto non e' per forza
    un guasto, perche' una lettera puo' essere stata abrogata davvero; per questo
    il comando segnala e non ripara, e la verifica si fa aprendo la pagina.
    """
    art_re = re.compile(r"^## (art\. \S+)\s*$")
    # « c) » e anche « ((c) », che e' la forma delle lettere novellate: se il
    # controllo non riconoscesse la seconda, non vedrebbe le riparazioni fatte.
    let_re = re.compile(r"^\(*([a-z])\)")
    # Gli elenchi europei sono annidati e la nidificazione va a numeri romani:
    # « a) ... i) ii) iii) ... b) ». Le sigle « i) », « v) » e « x) » sono a un solo
    # carattere e finirebbero dentro la sequenza delle lettere: un regolamento europeo
    # uscirebbe con falsi «manca b), c), d), e), f), g), h)», cioe' il salto da a) a i). I romani a piu' caratteri (ii, iii, iv, vi...) non possono
    # essere lettere, e sono l'aggancio che rivela il gruppo: da li' si allarga indietro
    # e avanti finche' le sigle continuano a essere romane, e quel tratto si salta.
    rom_re = re.compile(r"^\(*((?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})\)|[ivx]\))")
    rom_lungo_re = re.compile(r"^\(*(i{2,3}|iv|vi{1,3}|ix|xi{1,3})\)")
    # EUR-Lex non cancella in silenzio: dove una lettera e' stata abrogata resta il suo
    # marcatore di modifica seguito da una fila di trattini lunghi. Il buco e' dichiarato
    # dalla fonte, quindi non e' un buco. E' il caso dell'art. 2 lett. e) della direttiva
    # ePrivacy, abrogata dalla direttiva 2009/136/CE.
    tolto_re = re.compile(r"^▼\w*\s*—{3,}")

    buchi, guardati = [], 0
    for f in sorted(os.listdir(LEGGI)):
        if not f.endswith(".md") or f.startswith((".", "_")):
            continue
        if filtro and filtro.lower() not in f.lower():
            continue
        guardati += 1
        nome, art, seq = f.split("_vigenza-")[0], None, []

        def chiudi(seq=seq):
            for i in range(1, len(seq)):
                prec, cur = seq[i - 1], seq[i]
                # «—» e' il salto dichiarato dalla fonte: di la' non si guarda.
                if prec == "—" or cur == "—":
                    continue
                if prec not in ALFA or cur not in ALFA:
                    continue
                ip, ic = ALFA.index(prec), ALFA.index(cur)
                if ic > ip + 1:
                    buchi.append((nome, art, prec, cur, ALFA[ip + 1:ic]))
            del seq[:]

        righe = open(os.path.join(LEGGI, f), encoding="utf-8",
                     errors="replace").read().splitlines()
        # Prima passata: quali righe portano una sigla di elenco, e dove stanno i romani
        # lunghi. Poi da ogni romano lungo si allarga in tutte e due le direzioni sulle
        # sigle contigue che possono essere romane, e si marca il gruppo.
        sigle = [i for i, r in enumerate(righe)
                 if let_re.match(r) or rom_re.match(r)]
        posto = {i: n for n, i in enumerate(sigle)}
        romane = set()
        for i in sigle:
            if not rom_lungo_re.match(righe[i]):
                continue
            romane.add(i)
            for passo in (-1, 1):
                n = posto[i] + passo
                while 0 <= n < len(sigle) and rom_re.match(righe[sigle[n]]):
                    romane.add(sigle[n]); n += passo

        for i, riga in enumerate(righe):
            if riga.startswith("## "):
                # Ogni intestazione chiude la sequenza, non solo quelle d'articolo:
                # in coda al file stanno le tabelle allegate, e i loro elenchi non
                # sono la continuazione dell'ultimo articolo.
                m = art_re.match(riga)
                chiudi(); art = m.group(1) if m else riga[3:].strip(); continue
            if tolto_re.match(riga):
                seq.append("—"); continue
            if i in romane:
                continue          # sigla di un elenco annidato: non e' una lettera
            m = let_re.match(riga)
            if m:
                l = m.group(1)
                if seq and seq[-1] != "—" and ALFA.find(l) <= ALFA.find(seq[-1]):
                    chiudi()          # la lettera torna indietro: e' un elenco nuovo
                seq.append(l)
        chiudi()

    if not buchi:
        print("%d norme guardate: nessun elenco con lettere mancanti." % guardati)
        return 0

    print("%d norme guardate, %d lettere mancanti:\n" % (guardati, len(buchi)))
    for nome, art, prec, cur, manca in buchi:
        print("  ! %-28s %-14s %s) -> %s)   manca %s"
              % (nome, art or "?", prec, cur, ", ".join(m + ")" for m in manca)))
    print("\nDa verificare una per una sulla pagina, alla vigenza del file: se la")
    print("pagina la porta, la lettera va rimessa a mano; se dice che e' abrogata,")
    print("il salto e' vero e il file va bene cosi'.")
    return 1


def main():
    global LEGGI
    # Su Windows, dentro una pipe, la console usa la codifica di sistema, che non ha i
    # simboli dei messaggi (⚠️, «»): senza questa riga lo script cadrebbe al primo avviso.
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = sys.argv[1:]
    if "--cartella" in argv:
        i = argv.index("--cartella")
        if i + 1 >= len(argv):
            raise SystemExit("--cartella vuole un percorso.")
        LEGGI = os.path.abspath(os.path.expanduser(argv[i + 1]))
        del argv[i:i + 2]
    if argv and argv[0] in ("--elenco", "--indice", "--controlla", "--verifica-abrogati",
                            "--verifica-lettere") and not os.path.isdir(LEGGI):
        raise SystemExit("La cartella dei testi non c'e': %s\n"
                         "Indicala con --cartella <percorso>." % LEGGI)
    if any(a in ("-h", "--aiuto", "--help") for a in argv):
        print(__doc__)
        return 0
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--elenco":
        return elenco()
    if argv[0] == "--indice":
        return indice()
    if argv[0] == "--controlla":
        return controlla(argv[1] if len(argv) > 1 else None)
    if argv[0] == "--verifica-abrogati":
        return verifica_abrogati(argv[1] if len(argv) > 1 else None)
    if argv[0] == "--verifica-lettere":
        return verifica_lettere(argv[1] if len(argv) > 1 else None)

    # `congelata` distingue le due cose che finora si somigliavano sul disco: il testo
    # scaricato per avere l'ultima versione, e il testo chiesto **apposta** a una data
    # passata perche' e' quella che rileva nella causa. Il secondo non e' indietro: e' un
    # documento storico, e riscaricarlo lo distrugge. La differenza non si puo' indovinare
    # dalla data (un file rilavorato ha spesso la vigenza diversa dal giorno di
    # scaricamento), quindi si registra qui, dove la
    # si sa: l'ha chiesta l'utente con `--vigenza`.
    vigenza = time.strftime("%Y-%m-%d")
    congelata = False
    if "--vigenza" in argv:
        i = argv.index("--vigenza")
        if i + 1 >= len(argv):
            raise SystemExit("--vigenza vuole una data AAAA-MM-GG.")
        vigenza = argv[i + 1]
        del argv[i:i + 2]
        congelata = vigenza != time.strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", vigenza):
        raise SystemExit("La vigenza si scrive AAAA-MM-GG: %s" % vigenza)
    if len(argv) < 2:
        print(__doc__)
        return 2

    urn, nome = argv[0], slug(argv[1])
    print("Scarico %s alla vigenza del %s ..." % (urn, data_it(vigenza)))
    xml, gu, cod = scarica(urn, vigenza)
    print("  %s byte, dataGU=%s codiceRedaz=%s" % (format(len(xml), ","), gu, cod))

    (sezioni, urn_vero, consolidato, dal_corpo,
     messe, orfane, allegati) = sezioni_di(xml, urn, nome)
    if not sezioni:
        raise SystemExit("Nell'atto non ci sono articoli: controlla l'URN.")

    # Il nome dato a riga di comando spetta alla parte piu' corposa, che e' la norma
    # che si cercava; le altre se lo vedono allungare con il proprio titolo. Non si
    # puo' dire «il nome va al corpo dell'atto», perche' nei codici approvati con
    # Regio Decreto il corpo e' la formula di approvazione, due articoli, e il codice
    # sta negli allegati: `codice-civile_vigenza-...` finirebbe per essere la firma di
    # Vittorio Emanuele al posto dei 3.249 articoli.
    principale = max(sezioni, key=lambda s: len(sezioni[s]))

    # Quando il testo dell'atto sta negli allegati, il corpo e' la sola formula di
    # approvazione: «E' approvato il testo del Codice civile», e la firma. Non e'
    # norma e non si scrive. Non si perde in silenzio: il comando dice quanti
    # articoli ha lasciato fuori, e su Normattiva ci sono.
    # ⚠️ Ma «l'allegato e' piu' lungo» non basta a dirlo formula: il D.P.R. 642/1972 ha
    # 43 articoli di norma e una tariffa di 54, la L. 99/1993 accanto alla ratifica ha
    # gli articoli 3-6 che il testo unico riprende. Se il corpo non e' formula, il nome
    # base va a lui e l'allegato prende il suffisso.
    formula = None
    if dal_corpo is not None and dal_corpo != principale:
        if e_formula(sezioni[dal_corpo]):
            formula = (dal_corpo, len(sezioni.pop(dal_corpo)))
        else:
            principale = dal_corpo

    # ⚠️ Il nome che arriva da fuori non deve portare gia' il suffisso di una parte: quello
    # lo aggiunge questo blocco, e passarlo genera «...-allegato-3_allegato-3_vigenza-x.md».
    # Ci si ferma solo quando il suffisso coincide con una sezione che si sta per scrivere,
    # cioe' quando l'errore e' certo: un «_» qualunque nel nome resta lecito.
    for sez in sezioni:
        if len(sezioni) > 1 and sez != principale and nome.endswith("_" + slug(sez)):
            raise SystemExit(
                "il nome «%s» porta gia' il suffisso «_%s», che e' il nome di una PARTE "
                "di questa norma.\nLe parti le aggiunge il comando da se': passa il nome "
                "base «%s» e le riscrive tutte.\nAltrimenti nasce un doppione col nome "
                "storto." % (nome, slug(sez), nome[:-len("_" + slug(sez))]))

    os.makedirs(LEGGI, exist_ok=True)
    scritti = []
    for sez, articoli in sezioni.items():
        preambolo, articoli = stacca_preambolo(articoli)
        parte = "" if len(sezioni) == 1 or sez == principale else "_" + slug(sez)
        percorso = os.path.join(LEGGI, "%s%s_vigenza-%s.md" % (nome, parte, vigenza))
        titolo = (sez.capitalize() if sez.isupper() else sez).replace(
            " (corpo dell'atto)", "")            # serve a distinguere le chiavi, non da titolo
        # Normattiva a volte intitola la parte «Allegato» o «Testo», che non dice
        # quale norma sia: in quel caso vale di piu' il nome ricavato dall'URN.
        if slug(sez) in ("allegato", "norme", "testo", "testo-unico", "parte-i"):
            titolo = intestazione_da_urn(urn)
        with open(percorso, "w", encoding="utf-8") as fh:
            fh.write("# %s\n\n" % titolo)
            fh.write("URN: `%s`\n\n" % (urn_vero or urn))
            fh.write("Testo consolidato alla vigenza del %s.\n" % data_it(vigenza))
            if congelata:
                fh.write("Vigenza congelata: si', chiesta con --vigenza. Questo testo "
                         "non\nsi riscarica per aggiornarlo: vale ratione temporis "
                         "alla sua data.\n")
            if consolidato:
                fh.write("Ultima versione dell'atto: %s.\n" % data_it(consolidato))
            fh.write("Articoli: %d.\n\n" % len(articoli))
            fh.write("Fonte: Normattiva, formato Akoma Ntoso, scaricato il %s.\n"
                     "Il testo non e' estratto da scansione: per controllarlo si apre\n"
                     "Normattiva alla stessa vigenza, non un PDF.\n\n---\n\n"
                     % data_it(time.strftime("%Y-%m-%d")))
            if preambolo:
                fh.write("## preambolo\n\n%s\n\n" % "\n".join(preambolo))
            for num, righe in articoli:
                fh.write("## art. %s\n" % num)
                for avviso in avvisi_articolo(righe, vigenza):
                    fh.write("%s\n" % avviso)
                fh.write("\n%s\n\n" % "\n".join(righe))
            # Le tabelle e i prospetti allegati vanno in coda alla parte principale:
            # non hanno numero d'articolo, ma sono norma, e nel decreto IVA sono
            # l'unico posto in cui stanno le aliquote.
            if sez == principale:
                for etichetta, righe in allegati:
                    fh.write("## %s\n\n%s\n\n" % (etichetta, "\n".join(righe)))
        scritti.append((os.path.basename(percorso), len(articoli)))

    print("\nScritti in %s:" % LEGGI)
    for f, n in scritti:
        print("  %s  (%d articoli)" % (f, n))

    if formula:
        print("\nNon ho scritto il corpo dell'atto (%s, %d articoli): e' la formula\n"
              "che approva il testo, e il testo sta nelle parti qui sopra.\n"
              "Se servisse, e' su Normattiva alla stessa vigenza." % formula)

    if messe:
        print("\nRimesse nel testo %d porzioni riscritte dal legislatore, che il corpo\n"
              "    dell'XML non porta (il testo e' quello di Normattiva, non aggiunto):"
              % len(messe))
        for num, marca in messe:
            print("      art. %-12s %s" % (num, marca))

    if orfane:
        print("\n⚠️  %d porzioni riscritte dal legislatore non hanno un posto\n"
              "    determinato: la sequenza non dice dove vadano, e indovinarlo\n"
              "    sarebbe peggio che lasciarle fuori. Vanno messe a mano, aprendo\n"
              "    Normattiva alla stessa vigenza:" % len(orfane))
        for vicini, testo in orfane:
            print("      [fra art. %s] %s" % (" e ".join(vicini) or "?", testo[:110]))

    svuotati = articoli_svuotati(sezioni)
    if svuotati:
        print("\n⚠️  %d articoli sono ridotti alla sola scritta «abrogato» da un atto\n"
              "    recente. L'export XML appiattisce le abrogazioni non ancora efficaci:\n"
              "    la pagina web, alla stessa vigenza, puo' dare il testo pieno.\n"
              "    Da verificare uno per uno prima di usarli:" % len(svuotati))
        for num, chi in svuotati:
            print("      art. %-12s abrogato da %s" % (num, chi))
    if consolidato:
        print("\nUltima versione dell'atto su Normattiva: %s" % data_it(consolidato))

    # Le copie che questo scarico sostituisce vanno in archivio. Solo ora, a file scritti,
    # e mai per un testo congelato: quello non sostituisce niente, si affianca.
    spostate, lasciate = archivia_superate([s[0] for s in scritti], congelata)
    if spostate:
        print("\nSpostate in «%s/», perche' superate dalla versione appena scritta:"
              % ARCHIVIO)
        for f, a_mano in spostate:
            print("  %s" % f)
            if a_mano:
                print("    ⚠️  la sua testa parla di testo messo A MANO: e' in archivio, non "
                      "perduto.\n        Confronta col file nuovo e riporta cio' che "
                      "l'export non da'.")
    for f, perche in lasciate:
        print("\n⚠️  NON ho spostato %s: %s.\n    Resta nella radice, e a --controlla "
              "risultera' da riscaricare: va guardato a mano." % (f, perche))

    vecchi = [f for f in simili(nome, urn)
              if f not in [s[0] for s in scritti] and f != ARCHIVIO]
    if vecchi:
        print("\nIn cartella ci sono anche questi, che potrebbero essere la stessa norma:")
        for f in vecchi:
            print("  %s" % f)
        print("Non li tocco. Guardarli e cancellarli e' una decisione da prendere.")

    # L'indice si rifa' da se', in coda a ogni scarico riuscito: appena si scrive un file
    # nella cartella, «_indice.md» non e' piu' vero, e affidarlo alla memoria di una
    # persona vuol dire che prima o poi resta indietro. Non tocca il testo di nessuna
    # norma: riscrive solo la tabella, ed e' reversibile rilanciando «--indice».
    print("\nRifaccio l'indice, che dopo uno scarico non e' piu' vero:")
    indice()
    return 0


if __name__ == "__main__":
    sys.exit(main())
