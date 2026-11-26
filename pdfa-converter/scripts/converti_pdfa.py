#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 ztax.it - https://ztax.it - Licenza MIT (vedi LICENSE)
"""converti_pdfa.py - converte documenti in PDF/A-1a o PDF/A-1b e consegna solo file
che veraPDF ha validato. Tutto in locale: nessun file esce dalla macchina.

Tre strade, scelte dal file in ingresso:
  documento Office (.docx .doc .odt .rtf .fodt)  LibreOffice -> PDF/A-1b taggato ->
                                                 metadati elevati a 1a -> veraPDF
  PDF digitale                                   LibreOffice Draw -> come sopra
  PDF scansionato                                Ghostscript -> PDF/A-1b -> veraPDF

L'esito nasce accanto all'originale (o in --uscita) e il nome dice che cos'e':
  <nome>_PDFA-1a.pdf          valido PDF/A-1a
  <nome>_PDFA-1b.pdf          valido PDF/A-1b
  <nome>_PDFA-NON-VALIDO.pdf  NON depositabile: da guardare, non da usare
L'originale non si tocca mai, e un file che c'e' gia' non si sovrascrive.

Uso (su Windows «python» o «py» al posto di «python3»):
  python3 converti_pdfa.py atto.docx allegato.pdf      converte
  python3 converti_pdfa.py --verifica file.pdf         dice se un PDF e' PDF/A, senza convertire
  python3 converti_pdfa.py --strumenti                 dice quali programmi trova e quali mancano

Serve: Python 3.9+, la libreria pikepdf, LibreOffice, Ghostscript, veraPDF (con Java).
Se un programma non sta nel PATH lo si indica con una variabile d'ambiente:
PDFA_SOFFICE, PDFA_GS, PDFA_VERAPDF, PDFA_ICC (profilo colore sRGB).

Uscita: 0 tutti gli esiti validi; 1 almeno un file senza esito valido; 2 comando
sbagliato; 3 veraPDF non parte (senza validatore non si consegna niente);
4 manca un programma o una libreria.
"""
import argparse
import glob
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

VERSIONE = "1.0"
OFFICE_EXT = {".docx", ".doc", ".odt", ".rtf", ".fodt"}
SOGLIA_PIXEL = 800_000        # immagine a piena pagina: da ~0,8 Mpixel in su
T_SOFFICE, T_GS, T_VERAPDF = 600, 900, 600   # tempi massimi, in secondi
WINDOWS = os.name == "nt"

for _flusso in (sys.stdout, sys.stderr):      # la console di Windows non e' UTF-8
    try:
        _flusso.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg=""):
    print(msg, flush=True)


class ValidatoreNonDisponibile(Exception):
    """veraPDF non ha dato un verdetto: non e' un «non valido», e' un «non ho potuto guardare»."""


# --- ricerca degli strumenti -----------------------------------------------------
def _primo(candidati):
    for c in candidati:
        if c and os.path.isfile(c):
            return c
    return None


def trova_soffice():
    env = os.environ.get("PDFA_SOFFICE")
    if env:
        return env if os.path.isfile(env) else None
    for nome in ("soffice", "libreoffice"):
        p = shutil.which(nome)
        if p:
            return p
    return _primo([
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
    ])


def trova_gs():
    env = os.environ.get("PDFA_GS")
    if env:
        return env if os.path.isfile(env) else None
    for nome in ("gs", "gswin64c", "gswin32c"):
        p = shutil.which(nome)
        if p:
            return p
    return _primo(sorted(glob.glob(r"C:\Program Files\gs\gs*\bin\gswin64c.exe"), reverse=True)
                  + sorted(glob.glob(r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"), reverse=True))


def trova_verapdf():
    env = os.environ.get("PDFA_VERAPDF")
    if env:
        return env if os.path.isfile(env) else None
    for nome in ("verapdf", "verapdf.bat"):
        p = shutil.which(nome)
        if p:
            return p
    casa = os.path.expanduser("~")
    return _primo([
        os.path.join(casa, "verapdf", "verapdf"),
        os.path.join(casa, "verapdf", "verapdf.bat"),
        r"C:\Program Files\veraPDF\verapdf.bat",
        "/opt/verapdf/verapdf",
    ])


def trova_icc(gs):
    """Un profilo colore sRGB: quello di Ghostscript se c'e', altrimenti quello del sistema."""
    env = os.environ.get("PDFA_ICC")
    if env:
        return env if os.path.isfile(env) else None
    cand = []
    radici = ["/opt/homebrew/share/ghostscript", "/usr/local/share/ghostscript", "/usr/share/ghostscript"]
    if gs:
        vera = os.path.realpath(gs)
        radici.insert(0, os.path.join(os.path.dirname(os.path.dirname(vera)), "share", "ghostscript"))
        cand.append(os.path.join(os.path.dirname(os.path.dirname(vera)), "iccprofiles", "srgb.icc"))  # Windows
    for r in radici:
        cand.append(os.path.join(r, "iccprofiles", "srgb.icc"))
        cand += sorted(glob.glob(os.path.join(r, "*", "iccprofiles", "srgb.icc")), reverse=True)
    cand += [
        "/usr/share/color/icc/ghostscript/srgb.icc",
        "/usr/share/color/icc/colord/sRGB.icc",
        "/usr/share/color/icc/sRGB.icc",
        "/System/Library/ColorSync/Profiles/sRGB Profile.icc",
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "spool", "drivers",
                     "color", "sRGB Color Space Profile.icm"),
    ]
    return _primo(cand)


def importa_pikepdf():
    try:
        import pikepdf
        return pikepdf
    except ImportError:
        return None


INSTALLA = {
    "pikepdf": "python3 -m pip install pikepdf   (se il sistema rifiuta: creare un ambiente con "
               "«python3 -m venv ~/.venv-pdfa» e usare il suo python)",
    "LibreOffice": "macOS: brew install --cask libreoffice · Linux: pacchetto «libreoffice» · "
                   "Windows: winget install TheDocumentFoundation.LibreOffice",
    "Ghostscript": "macOS: brew install ghostscript · Linux: pacchetto «ghostscript» · "
                   "Windows: winget install ArtifexSoftware.GhostScript",
    "veraPDF": "macOS: brew install verapdf · Linux e Windows: installatore da https://verapdf.org "
               "(serve Java)",
}


class Strumenti:
    def __init__(self, icc=None):
        self.pikepdf = importa_pikepdf()
        self.soffice = trova_soffice()
        self.gs = trova_gs()
        self.verapdf = trova_verapdf()
        self.icc = icc if icc and os.path.isfile(icc) else trova_icc(self.gs)
        self._gs_versione = None

    def gs_versione(self):
        if self._gs_versione is None:
            self._gs_versione = (0, 0)
            try:
                r = subprocess.run([self.gs, "--version"], capture_output=True, text=True, timeout=30)
                m = re.match(r"(\d+)\.(\d+)", (r.stdout or "").strip())
                if m:
                    self._gs_versione = (int(m.group(1)), int(m.group(2)))
            except Exception:
                pass
        return self._gs_versione

    def verapdf_parte(self):
        if not self.verapdf:
            return False
        try:
            r = subprocess.run([self.verapdf, "--version"], capture_output=True, text=True,
                               timeout=T_VERAPDF)
            return r.returncode == 0 and "veraPDF" in (r.stdout or "")
        except Exception:
            return False

    def rapporto(self):
        log("Strumenti per la conversione in PDF/A")
        voci = [
            ("pikepdf", "libreria Python" if self.pikepdf else None, "tutte le conversioni"),
            ("LibreOffice", self.soffice, "documenti Office e PDF digitali"),
            ("Ghostscript", self.gs, "PDF scansionati e controllo della resa"),
            ("veraPDF", self.verapdf, "la validazione: senza, non si consegna niente"),
        ]
        mancano = 0
        for nome, dove, serve in voci:
            if dove:
                log(f"  ✓ {nome}: {dove}")
            else:
                mancano += 1
                log(f"  ✗ {nome}: NON TROVATO (serve per: {serve})")
                log(f"      {INSTALLA[nome]}")
        if self.verapdf:
            if self.verapdf_parte():
                log("  ✓ veraPDF parte")
            else:
                mancano += 1
                log("  ✗ veraPDF c'e' ma NON PARTE: di solito manca Java (installare un JRE 11 o successivo)")
        if self.gs:
            if self.icc:
                log(f"  ✓ profilo colore sRGB: {self.icc}")
            else:
                mancano += 1
                log("  ✗ profilo colore sRGB: NON TROVATO (serve per le scansioni). Indicarne uno con "
                    "--icc <file.icc> o con la variabile PDFA_ICC")
        return mancano


# --- che cosa c'e' dentro un PDF ---------------------------------------------------
def pdf_pagine(pikepdf, path):
    """Numero di pagine, o None se il file non si apre."""
    try:
        with pikepdf.open(path) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def pdf_firmato(pikepdf, path):
    """True se il PDF porta una firma digitale (campo /Sig valorizzato)."""
    try:
        with pikepdf.open(path) as pdf:
            af = pdf.Root.get("/AcroForm")
            if af is None:
                return False

            def cerca(campi, livello=0):
                if campi is None:
                    return False
                for c in campi:
                    if c.get("/FT") == pikepdf.Name("/Sig") and c.get("/V") is not None:
                        return True
                    if livello < 8 and "/Kids" in c and cerca(c["/Kids"], livello + 1):
                        return True
                return False
            return cerca(af.get("/Fields"))
    except Exception:
        return False


def _risorse_pagina(page):
    o = page.obj
    for _ in range(12):
        if "/Resources" in o:
            return o["/Resources"]
        if "/Parent" not in o:
            return None
        o = o["/Parent"]
    return None


def _pixel_disegnati(pikepdf, contenitore, risorse, visti, livello=0):
    """Somma i pixel delle immagini che il contenuto DISEGNA davvero (operatore Do),
    entrando nei Form XObject: una scansione puo' stare annidata in un contenitore o
    essere divisa in strisce, e un'immagine soltanto elencata nelle risorse non conta."""
    tot = 0
    nomi = []
    for operandi, op in pikepdf.parse_content_stream(contenitore):
        o = str(op)
        if o == "Do" and operandi:
            nomi.append(str(operandi[0]))
        elif o == "INLINE IMAGE" and operandi:
            try:
                tot += int(operandi[0].width) * int(operandi[0].height)
            except Exception:
                pass
    if risorse is None or "/XObject" not in risorse:
        return tot
    xobj = risorse["/XObject"]
    for nome in nomi:
        if nome not in xobj:
            continue
        xo = xobj[nome]
        sub = xo.get("/Subtype")
        if sub == pikepdf.Name("/Image"):
            tot += int(xo.get("/Width", 0)) * int(xo.get("/Height", 0))
        elif sub == pikepdf.Name("/Form") and livello < 6:
            chiave = xo.objgen
            if chiave != (0, 0) and chiave in visti:
                continue
            visti.add(chiave)
            tot += _pixel_disegnati(pikepdf, xo, xo.get("/Resources", risorse), visti, livello + 1)
            visti.discard(chiave)
    return tot


def pdf_scansione(pikepdf, path):
    """True se almeno meta' delle pagine disegna immagini per ~0,8 Mpixel o piu'.
    La presenza di testo NON esclude la scansione: molte hanno un livello OCR.
    None se non e' stato possibile guardare."""
    try:
        with pikepdf.open(path) as pdf:
            n = len(pdf.pages)
            if n == 0:
                return False
            piene = sum(1 for p in pdf.pages
                        if _pixel_disegnati(pikepdf, p, _risorse_pagina(p), set()) >= SOGLIA_PIXEL)
            return piene * 2 >= n
    except Exception:
        return None


# --- conversioni -------------------------------------------------------------------
def _soffice(st, filtro, src, outdir, profilo):
    cmd = [st.soffice, "-env:UserInstallation=" + pathlib.Path(profilo).as_uri(),
           "--headless", "--norestore", "--convert-to", filtro, "--outdir", outdir, src]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=T_SOFFICE)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise RuntimeError("LibreOffice non ha prodotto il PDF")
    return out


def office_a_1b(st, src, outdir, profilo):
    return _soffice(st, 'pdf:writer_pdf_Export:{'
                        '"SelectPdfVersion":{"type":"long","value":"1"},'
                        '"UseTaggedPDF":{"type":"boolean","value":"true"},'
                        '"EnableTextAccess":{"type":"boolean","value":"true"}}',
                    src, outdir, profilo)


def pdf_a_1b_via_draw(st, src, outdir, profilo):
    """Riconversione vera di un PDF digitale, non una rietichettatura."""
    return _soffice(st, 'pdf:draw_pdf_Export:{'
                        '"SelectPdfVersion":{"type":"long","value":"1"},'
                        '"UseTaggedPDF":{"type":"boolean","value":"true"}}',
                    src, outdir, profilo)


PDFA_DEF = """%!
% Dichiara il profilo colore di uscita (OutputIntent) richiesto dal PDF/A-1.
[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark
[{icc_PDFA} << /N 3 >> /PUT pdfmark
[{icc_PDFA} (@ICC@) (r) file /PUT pdfmark
[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark
[{OutputIntent_PDFA} <<
  /Type /OutputIntent
  /S /GTS_PDFA1
  /DestOutputProfile {icc_PDFA}
  /OutputConditionIdentifier (sRGB)
>> /PUT pdfmark
[{Catalog} << /OutputIntents [ {OutputIntent_PDFA} ] >> /PUT pdfmark
"""


def _stringa_ps(percorso):
    """Percorso dentro una stringa PostScript: barre dritte, parentesi protette."""
    return percorso.replace("\\", "/").replace("(", "\\(").replace(")", "\\)")


def scansione_a_1b(st, src, workdir, senza_testo=False):
    """Scansione -> PDF/A-1b via Ghostscript: l'immagine resta com'e'.
    Il profilo colore va LETTO da Ghostscript: senza il permesso di lettura
    l'OutputIntent manca e il file sembra fatto ma non e' conforme."""
    if not st.icc:
        raise RuntimeError("profilo colore sRGB non trovato: indicarne uno con --icc o PDFA_ICC")
    icc = os.path.join(workdir, "srgb.icc")     # copia in un percorso senza sorprese
    if not os.path.isfile(icc):
        shutil.copyfile(st.icc, icc)
    defps = os.path.join(workdir, "pdfa_def.ps")
    with open(defps, "w", encoding="latin-1") as f:
        f.write(PDFA_DEF.replace("@ICC@", _stringa_ps(icc)))
    out = os.path.join(workdir, "gs_1b_senza_testo.pdf" if senza_testo else "gs_1b.pdf")
    permesso = ["--permit-file-read=" + icc] if st.gs_versione() >= (9, 50) else ["-dNOSAFER"]
    cmd = [st.gs] + permesso + ["-dPDFA=1", "-dBATCH", "-dNOPAUSE", "-dNOOUTERSAVE", "-q",
                                "-sColorConversionStrategy=RGB", "-sDEVICE=pdfwrite",
                                "-dPDFACompatibilityPolicy=1"]
    if senza_testo:
        cmd.append("-dFILTERTEXT")
    subprocess.run(cmd + ["-sOutputFile=" + out, defps, src],
                   check=True, capture_output=True, text=True, timeout=T_GS)
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise RuntimeError("Ghostscript non ha prodotto il PDF")
    return out


def eleva_a_1a(pikepdf, src, dst, lingua):
    """Copia src->dst dichiarando PDF/A-1a nei metadati e impostando la lingua.
    La dichiarazione da sola non vale niente: decide veraPDF, subito dopo."""
    with pikepdf.open(src) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["pdfaid:part"] = "1"
            meta["pdfaid:conformance"] = "A"
        pdf.Root.Lang = pikepdf.String(lingua)
        pdf.save(dst)


# --- veraPDF -------------------------------------------------------------------------
def valida(st, path, livello):
    """True o False secondo veraPDF. In formato testo la prima riga e' «PASS <file>» o
    «FAIL <file>»: se non c'e' ne' l'una ne' l'altra, veraPDF non ha dato un verdetto."""
    try:
        r = subprocess.run([st.verapdf, "-f", livello, "--format", "text", path],
                           capture_output=True, text=True, timeout=T_VERAPDF)
    except Exception as e:
        raise ValidatoreNonDisponibile(str(e))
    righe = (r.stdout or "").strip().split("\n")
    if righe[0].startswith("PASS"):
        return True
    if righe[0].startswith("FAIL"):
        return False
    raise ValidatoreNonDisponibile((r.stderr or r.stdout or "").strip().split("\n")[-1][:160]
                                   or "nessuna risposta")


def controlli_falliti(st, path, livello):
    """Le clausole della norma su cui il file cade, dal rapporto esteso di veraPDF."""
    try:
        r = subprocess.run([st.verapdf, "-f", livello, path], capture_output=True, text=True,
                           timeout=T_VERAPDF)
    except Exception:
        return []
    visti, res = set(), []
    for spec, clausola in re.findall(
            r'<rule[^>]*specification="([^"]*)"[^>]*clause="([^"]*)"[^>]*status="failed"', r.stdout or ""):
        if (spec, clausola) not in visti:
            visti.add((spec, clausola))
            res.append(f"{spec} §{clausola}")
    return res


# --- controllo della resa --------------------------------------------------------------
def _pagine_in_grigio(st, pdf, workdir, sigla):
    """Ogni pagina resa a bassa risoluzione come griglia 8x8 di luminosita' medie (0-255)."""
    modello = os.path.join(workdir, sigla + "-%04d.pgm")
    subprocess.run([st.gs, "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pgmraw", "-r24",
                    "-sOutputFile=" + modello, pdf],
                   check=True, capture_output=True, timeout=T_GS)
    pagine = []
    for f in sorted(glob.glob(os.path.join(workdir, sigla + "-*.pgm"))):
        with open(f, "rb") as fh:
            dati = fh.read()
        m = re.match(rb"P5\s+(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s+(\d+)\s", dati)
        if not m:
            return None
        w, h = int(m.group(1)), int(m.group(2))
        px = dati[m.end():m.end() + w * h]
        if len(px) < w * h or w < 8 or h < 8:
            return None
        griglia = []
        for gy in range(8):
            for gx in range(8):
                x0, x1 = gx * w // 8, (gx + 1) * w // 8
                tot = n = 0
                for y in range(gy * h // 8, (gy + 1) * h // 8):
                    riga = px[y * w + x0:y * w + x1]
                    tot += sum(riga)
                    n += len(riga)
                griglia.append(tot / n if n else 255.0)
        pagine.append(griglia)
    return pagine


def resa_diversa(st, originale, prodotto, workdir):
    """Confronta a vista, in piccolo, l'originale e il convertito. Ritorna una frase se
    una pagina e' cambiata in modo evidente (annerita, svuotata, un pezzo sparito), ""
    se la resa regge, None se il confronto non si e' potuto fare. veraPDF certifica la
    forma del file, non quello che si vede: una pagina nera puo' essere «valida»."""
    if not st.gs:
        return None
    try:
        a = _pagine_in_grigio(st, originale, workdir, "prima")
        b = _pagine_in_grigio(st, prodotto, workdir, "dopo")
    except Exception:
        return None
    if not a or not b or len(a) != len(b):
        return None
    for i, (ga, gb) in enumerate(zip(a, b), 1):
        media = abs(sum(ga) / 64 - sum(gb) / 64)
        blocco = max(abs(x - y) for x, y in zip(ga, gb))
        if media > 20 or blocco > 80:
            return f"pagina {i}: la resa e' diversa dall'originale (luminosita' media {media:.0f}, zona peggiore {blocco:.0f} su 255)"
        # L'inchiostro: una pagina di testo che esce bianca cambia poco la luminosita'
        # media, ma perde tutto il suo scuro.
        ia, ib = 255 - sum(ga) / 64, 255 - sum(gb) / 64
        if max(ia, ib) >= 0.1 and min(ia, ib) < max(ia, ib) * 0.5:
            return f"pagina {i}: il contenuto e' {'sparito o molto ridotto' if ib < ia else 'molto aumentato'} rispetto all'originale"
    return ""


# --- un file ------------------------------------------------------------------------------
class Esito:
    def __init__(self, src):
        self.src = src
        self.livello = None      # "1a", "1b", "non-valido", None = nessun file scritto
        self.file = None
        self.note = []

    def nota(self, testo):
        self.note.append(testo)
        log("   " + testo)


def converti(st, src, uscita, lingua):
    pikepdf = st.pikepdf
    e = Esito(src)
    nome = os.path.basename(src)
    radice, ext = os.path.splitext(nome)
    ext = ext.lower()
    log(f"\n=== {nome} ===")
    if not os.path.isfile(src):
        e.nota("✗ File non trovato.")
        return e
    if ext not in OFFICE_EXT and ext != ".pdf":
        e.nota(f"✗ Estensione non gestita: {ext or '(nessuna)'}")
        return e
    if re.search(r"_PDFA-(1a|1b|NON-VALIDO)$", radice):
        e.nota("✗ E' gia' un esito di questo script: non lo riconverto.")
        return e
    cartella = uscita or os.path.dirname(os.path.abspath(src))
    finali = {k: os.path.join(cartella, f"{radice}_PDFA-{k}.pdf") for k in ("1a", "1b", "NON-VALIDO")}
    gia = [os.path.basename(p) for p in finali.values() if os.path.exists(p)]
    if gia:
        e.nota(f"✗ C'e' gia' {', '.join(gia)}: non sovrascrivo. Spostalo o rinominalo e rilancia.")
        return e

    workdir = tempfile.mkdtemp(prefix="pdfa_")
    try:
        # Si lavora su una copia locale: da una cartella sincronizzata (Google Drive,
        # OneDrive) LibreOffice puo' leggere un file vuoto senza dare errore.
        os.makedirs(os.path.join(workdir, "in"))
        os.makedirs(os.path.join(workdir, "out"))
        copia = os.path.join(workdir, "in", nome)
        shutil.copyfile(src, copia)
        if os.path.getsize(copia) == 0:
            e.nota("✗ Il file e' vuoto (o non ancora scaricato dalla cartella sincronizzata).")
            return e
        profilo = os.path.join(workdir, "profilo-libreoffice")
        outdir = os.path.join(workdir, "out")

        def consegna(prodotto, livello):
            dst = finali["NON-VALIDO" if livello == "non-valido" else livello]
            shutil.copyfile(prodotto, dst)
            e.livello, e.file = livello, dst

        da_pdf = ext == ".pdf"
        if da_pdf:
            pagine = pdf_pagine(pikepdf, copia)
            if pagine is None:
                e.nota("✗ Il PDF non si apre: e' danneggiato o protetto da password. NON convertito.")
                return e
            if pdf_firmato(pikepdf, copia):
                e.nota("✗ PDF firmato digitalmente: la conversione toglierebbe la firma. NON convertito.")
                return e
            scan = pdf_scansione(pikepdf, copia)
            if scan is None:
                e.nota("⚠ Non sono riuscito a guardare dentro il PDF: lo tratto come scansione (Ghostscript non altera la resa).")
            if scan is None or scan:
                if not st.gs:
                    e.nota("✗ E' una scansione e Ghostscript non c'e'. " + INSTALLA["Ghostscript"])
                    return e
                log("• PDF scansionato: Ghostscript → PDF/A-1b (l'immagine resta com'e')")
                pdf1b = scansione_a_1b(st, copia, workdir)
                ok = valida(st, pdf1b, "1b")
                if not ok:
                    log("• 1b non valido: ritento scartando il testo OCR invisibile")
                    pdf1b = scansione_a_1b(st, copia, workdir, senza_testo=True)
                    ok = valida(st, pdf1b, "1b")
                    if ok:
                        e.nota("⚠ Testo OCR scartato: il PDF non e' piu' ricercabile, l'immagine e' intatta.")
                difetto = _difetto_rispetto_all_originale(st, pikepdf, copia, pdf1b, pagine, workdir, e)
                if ok and not difetto:
                    consegna(pdf1b, "1b")
                    log(f"✓ PDF/A-1b VALIDO → {os.path.basename(e.file)} (su una scansione l'1a richiederebbe un OCR strutturato)")
                else:
                    consegna(pdf1b, "non-valido")
                    e.nota("✗ " + (difetto or "PDF/A-1b non valido: " + "; ".join(controlli_falliti(st, pdf1b, "1b")[:8]))
                           + f". Salvato come {os.path.basename(e.file)}: NON depositabile.")
                return e
            if not st.soffice:
                e.nota("✗ LibreOffice non c'e'. " + INSTALLA["LibreOffice"])
                return e
            log("• PDF digitale: LibreOffice Draw → PDF/A (riconversione vera)")
            pdf1b = pdf_a_1b_via_draw(st, copia, outdir, profilo)
            difetto = _difetto_rispetto_all_originale(st, pikepdf, copia, pdf1b, pagine, workdir, e)
            if difetto:
                consegna(pdf1b, "non-valido")
                e.nota(f"✗ {difetto}. Salvato come {os.path.basename(e.file)}: NON depositabile.")
                return e
        else:
            if not st.soffice:
                e.nota("✗ LibreOffice non c'e'. " + INSTALLA["LibreOffice"])
                return e
            log("• Documento Office: LibreOffice → PDF/A-1b taggato")
            pdf1b = office_a_1b(st, copia, outdir, profilo)

        cand = os.path.join(workdir, "candidato_1a.pdf")
        eleva_a_1a(pikepdf, pdf1b, cand, lingua)
        if valida(st, cand, "1a"):
            consegna(cand, "1a")
            log(f"✓ PDF/A-1a VALIDO → {os.path.basename(e.file)}")
            return e
        falliti = controlli_falliti(st, cand, "1a")
        if valida(st, pdf1b, "1b"):
            consegna(pdf1b, "1b")
            log(f"✓ PDF/A-1b VALIDO → {os.path.basename(e.file)}")
            e.nota("⚠ L'1a non e' stato raggiunto. Controlli falliti: " + ("; ".join(falliti[:8]) or "non elencati"))
        else:
            falliti = controlli_falliti(st, pdf1b, "1b") or falliti
            consegna(pdf1b, "non-valido")
            e.nota(f"✗ Ne' 1a ne' 1b validi. Salvato come {os.path.basename(e.file)}: NON depositabile. "
                   "Controlli falliti: " + ("; ".join(falliti[:8]) or "non elencati"))
        if any("6.3.5" in f for f in falliti):
            e.nota("   La clausola 6.3.5 riguarda i caratteri incorporati: succede quando il carattere del "
                   "documento e' installato in formato OTF. Installarlo in TTF e riconvertire.")
        if da_pdf and e.livello != "1a":
            e.nota("   Per l'1a conviene ripartire dal documento originale (.docx): un PDF gia' fatto non ha la struttura richiesta.")
        return e
    except ValidatoreNonDisponibile as err:
        e.livello, e.file = None, None
        e.nota(f"✗ veraPDF non ha dato un verdetto ({err}): nessun file consegnato.")
        return e
    except subprocess.TimeoutExpired as err:
        e.nota(f"✗ Tempo scaduto ({int(err.timeout)} s): il programma di conversione non ha risposto.")
        return e
    except subprocess.CalledProcessError as err:
        programma = os.path.basename(str(err.cmd[0])) if isinstance(err.cmd, (list, tuple)) and err.cmd else "il programma"
        dettaglio = (err.stderr or "").strip().split("\n")[-1][:200]
        e.nota(f"✗ Errore di conversione: {programma} si e' interrotto (uscita {err.returncode})"
               + (f": {dettaglio}" if dettaglio else "") + ".")
        if "soffice" in programma.lower() or "libreoffice" in programma.lower():
            e.nota("   Se il comando gira dentro una sandbox (quella di un assistente AI, per esempio), "
                   "LibreOffice puo' non riuscire a partire: va rilanciato fuori dalla sandbox.")
        return e
    except Exception as err:
        e.nota(f"✗ Errore: {err}")
        return e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _difetto_rispetto_all_originale(st, pikepdf, originale, prodotto, pagine, workdir, e):
    """Per un PDF in ingresso: stesse pagine e stessa resa. Ritorna la frase del difetto, o ""."""
    dopo = pdf_pagine(pikepdf, prodotto)
    if dopo != pagine:
        return f"pagine diverse dall'originale (in ingresso {pagine}, in uscita {dopo if dopo is not None else 'non contabili'})"
    resa = resa_diversa(st, originale, prodotto, workdir)
    if resa is None:
        e.nota("⚠ Confronto automatico della resa non riuscito: il file va guardato a vista, pagina per pagina.")
        return ""
    return resa


# --- verifica senza conversione -------------------------------------------------------------
def verifica(st, path):
    nome = os.path.basename(path)
    if not os.path.isfile(path):
        log(f"✗ {nome} — file non trovato")
        return False
    workdir = tempfile.mkdtemp(prefix="pdfa_")
    try:
        copia = os.path.join(workdir, "verifica.pdf")
        shutil.copyfile(path, copia)
        try:
            for livello in ("1a", "1b"):
                if valida(st, copia, livello):
                    log(f"✓ {nome} — PDF/A-{livello} VALIDO")
                    return True
        except ValidatoreNonDisponibile as err:
            log(f"✗ {nome} — NON HO POTUTO VERIFICARE: veraPDF non ha dato un verdetto ({err})")
            return False
        dichiarato = False
        try:
            with st.pikepdf.open(copia) as pdf:
                with pdf.open_metadata() as meta:
                    dichiarato = bool(meta.get("pdfaid:part"))
        except Exception:
            pass
        if dichiarato:
            log(f"⚠ {nome} — si DICHIARA PDF/A ma NON e' valido: non depositabile")
        else:
            log(f"• {nome} — PDF semplice, nessuna codifica PDF/A")
        return False
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --- comando ------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        prog="converti_pdfa.py",
        description="Converte in PDF/A-1a o 1b e consegna solo file validati da veraPDF. Tutto in locale.")
    ap.add_argument("file", nargs="*", help="documenti da convertire (.docx .doc .odt .rtf .fodt .pdf)")
    ap.add_argument("--verifica", action="store_true", help="dice se i PDF indicati sono PDF/A, senza convertire")
    ap.add_argument("--strumenti", action="store_true", help="dice quali programmi trova e quali mancano")
    ap.add_argument("--uscita", metavar="CARTELLA", help="dove scrivere gli esiti (di norma accanto all'originale)")
    ap.add_argument("--lingua", default="it-IT", help="lingua dichiarata nel PDF (predefinita: it-IT)")
    ap.add_argument("--icc", metavar="FILE", help="profilo colore sRGB da usare per le scansioni")
    ap.add_argument("--versione", action="version", version="converti_pdfa.py " + VERSIONE)
    a = ap.parse_args()

    st = Strumenti(icc=a.icc)
    if a.strumenti:
        sys.exit(4 if st.rapporto() else 0)
    if not a.file:
        ap.print_usage()
        sys.exit(2)
    if a.icc and not os.path.isfile(a.icc):
        log(f"✗ Il profilo colore indicato non esiste: {a.icc}")
        sys.exit(2)
    if a.uscita and not os.path.isdir(a.uscita):
        log(f"✗ La cartella di uscita non esiste: {a.uscita}")
        sys.exit(2)
    if not st.pikepdf:
        log("✗ Manca la libreria pikepdf. " + INSTALLA["pikepdf"])
        sys.exit(4)
    if not st.verapdf:
        log("✗ veraPDF non trovato: senza validatore non si consegna niente come PDF/A. " + INSTALLA["veraPDF"])
        sys.exit(4)
    if not st.verapdf_parte():
        log("✗ veraPDF c'e' ma non parte (di solito manca Java): senza validatore non si consegna niente.")
        sys.exit(3)

    if a.verifica:
        esiti = [verifica(st, f) for f in a.file]
        sys.exit(0 if all(esiti) else 1)

    esiti = [converti(st, os.path.abspath(f), a.uscita and os.path.abspath(a.uscita), a.lingua) for f in a.file]
    log("\nRIEPILOGO")
    etichetta = {"1a": "PDF/A-1a valido", "1b": "PDF/A-1b valido", "non-valido": "NON VALIDO, non depositabile"}
    for e in esiti:
        if e.livello:
            log(f"  {os.path.basename(e.src)}  →  {os.path.basename(e.file)}  [{etichetta[e.livello]}]")
        else:
            motivo = next((n for n in e.note if n.startswith("✗")), e.note[-1] if e.note else "errore")
            log(f"  {os.path.basename(e.src)}  →  NESSUN FILE  [{motivo.lstrip('✗ ')}]")
    if any(e.livello in ("1a", "1b") for e in esiti):
        log("\nveraPDF certifica la forma del file, non quello che si vede: ogni PDF convertito va aperto "
            "e guardato prima di depositarlo.")
    sys.exit(0 if all(e.livello in ("1a", "1b") for e in esiti) else 1)


if __name__ == "__main__":
    main()
