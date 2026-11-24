#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 ztax.it - https://ztax.it
# Licenza MIT: vedi il file LICENSE della skill.
"""Riclassifica un bilancio CEE e ne calcola gli indici, esercizio per esercizio.

Uso:
  python3 calcola_indici.py estratto.json [--regole regole.json] [--out cartella]

Legge l'estratto (lo schema è in references/schema-e-regole.md), riclassifica lo stato
patrimoniale col criterio finanziario e il conto economico a valore aggiunto, calcola gli
indici e controlla le quadrature.

Uscite:
  0  quadrature tutte a posto: scrive analisi-<azienda>-<anno>.xlsx e
     risultati-<azienda>-<anno>.json, con <anno> l'ultimo esercizio e il numero di versione
     dell'estratto (estratto-2025-2.json dà -2025-2); se quella versione ha già risultati
     diversi apre la prima libera e ci copia l'estratto, se sono uguali non scrive niente
  1  almeno una quadratura non torna: stampa voce e differenza e non scrive niente
  2  estratto o regole malformati (chiave sconosciuta, valore non numerico, regola non ammessa)
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import sys
import zipfile

REGOLE_BASE = {
    "fondi_rischi_in": "consolidate",
    "A5_in_valore_produzione": True,
    "crediti_soci": "rettifica_pn",
    "roe_base": "finale",
    "roi_base": "totale",
    "iva": 0.22,
    "tolleranza": 2,
}
VALORI_AMMESSI = {
    "fondi_rischi_in": ("consolidate", "correnti"),
    "A5_in_valore_produzione": (True, False),
    "crediti_soci": ("rettifica_pn", "liquidita_differite"),
    "roe_base": ("finale", "media"),
    "roi_base": ("totale", "operativo"),
}

VOCI_ATTIVO = ["A_crediti_soci", "B_I_immateriali", "B_II_materiali", "B_III_finanziarie",
               "C_I_rimanenze", "C_II_crediti_entro", "C_II_crediti_oltre", "C_III_att_fin",
               "C_IV_liquidita", "D_ratei_risconti_att"]
VOCI_PASSIVO = ["A_PN", "B_fondi", "C_TFR", "D_debiti_entro", "D_debiti_oltre",
                "E_ratei_risconti_pass"]
VOCI_CE = ["A1_ricavi", "A2_var_rim_prodotti", "A3_var_lavori", "A4_incrementi",
           "A5_altri_ricavi", "B6", "B7", "B8", "B9_personale", "B10_ammortamenti",
           "B11_var_rim_materie", "B12_accantonamenti", "B13_altri_acc", "B14_oneri_diversi",
           "C_fin_netto", "D_rettifiche", "imposte_20", "utile_21"]
VOCI_ALTRE = ["C_II_1_clienti", "TOT_ATTIVO", "A_IX_utile", "D_fin_entro", "D_fin_oltre",
              "D_fin_totale", "D_7_fornitori", "TOT_PASSIVO", "C17_oneri_fin", "dipendenti_medi"]
VOCI = set(VOCI_ATTIVO + VOCI_PASSIVO + VOCI_CE + VOCI_ALTRE)

# formato di cella per gli indici: percentuale, giorni, euro; gli altri sono rapporti
PERCENTUALI = ("ROE", "ROI", "ROS", "EBITDA margin", "Oneri finanziari / MOL",
               "Oneri finanziari / ricavi", "Costo del personale / valore della produzione")
GIORNI = ("Giorni incasso clienti", "Giorni pagamento fornitori", "Giorni di magazzino",
          "Ciclo del circolante (giorni)")
IN_EURO = ("Capitale circolante netto", "Margine di tesoreria",
           "Margine di struttura primario", "Margine di struttura secondario", "PFN",
           "Valore aggiunto per dipendente")


class Malformato(Exception):
    pass


def rapporto(numeratore, denominatore):
    """None se il rapporto non ha senso: dato mancante o denominatore nullo."""
    if numeratore is None or denominatore in (None, 0):
        return None
    return numeratore / denominatore


class Esercizio:
    """Le voci di un esercizio, con lo zero per ciò che il bilancio non porta."""

    def __init__(self, voci):
        self.voci = voci

    def __getitem__(self, chiave):
        return float(self.voci.get(chiave) or 0)

    def presente(self, chiave):
        return self.voci.get(chiave) is not None

    def somma(self, *chiavi):
        return sum(self[k] for k in chiavi)


def stato_patrimoniale(e, regole):
    soci = e["A_crediti_soci"]
    soci_in_pn = regole["crediti_soci"] == "rettifica_pn"
    fondi_lunghi = regole["fondi_rischi_in"] == "consolidate"
    sp = {
        # i crediti oltre l'esercizio sono impieghi a lungo: vanno con le immobilizzazioni
        "Immobilizzazioni": e.somma("B_I_immateriali", "B_II_materiali", "B_III_finanziarie",
                                    "C_II_crediti_oltre"),
        "Rimanenze": e["C_I_rimanenze"],
        "Liquidità differite": e.somma("C_II_crediti_entro", "C_III_att_fin",
                                       "D_ratei_risconti_att") + (0 if soci_in_pn else soci),
        "Liquidità immediate": e["C_IV_liquidita"],
    }
    sp["Attivo corrente"] = sp["Rimanenze"] + sp["Liquidità differite"] + sp["Liquidità immediate"]
    sp["Capitale investito"] = sp["Immobilizzazioni"] + sp["Attivo corrente"]
    sp["Patrimonio netto"] = e["A_PN"] - (soci if soci_in_pn else 0)
    sp["Passività consolidate"] = e.somma("C_TFR", "D_debiti_oltre") \
        + (e["B_fondi"] if fondi_lunghi else 0)
    sp["Passività correnti"] = e.somma("D_debiti_entro", "E_ratei_risconti_pass") \
        + (0 if fondi_lunghi else e["B_fondi"])
    sp["Totale fonti"] = sp["Patrimonio netto"] + sp["Passività consolidate"] \
        + sp["Passività correnti"]
    return sp


def conto_economico(e, regole):
    a5 = e["A5_altri_ricavi"]
    a5_caratteristico = regole["A5_in_valore_produzione"]
    ce = {"Ricavi (A1)": e["A1_ricavi"]}
    ce["Valore della produzione"] = e.somma("A1_ricavi", "A2_var_rim_prodotti", "A3_var_lavori",
                                            "A4_incrementi") + (a5 if a5_caratteristico else 0)
    ce["Costi esterni"] = e.somma("B6", "B7", "B8", "B11_var_rim_materie", "B14_oneri_diversi")
    ce["Valore aggiunto"] = ce["Valore della produzione"] - ce["Costi esterni"]
    ce["Costo del personale"] = e["B9_personale"]
    ce["MOL (EBITDA)"] = ce["Valore aggiunto"] - ce["Costo del personale"]
    ce["Ammortamenti, svalutazioni e accantonamenti"] = e.somma(
        "B10_ammortamenti", "B12_accantonamenti", "B13_altri_acc")
    # A5 fuori dalla gestione caratteristica rientra dopo il MOL, prima dell'EBIT
    ce["Risultato operativo (EBIT)"] = ce["MOL (EBITDA)"] \
        - ce["Ammortamenti, svalutazioni e accantonamenti"] + (0 if a5_caratteristico else a5)
    ce["Gestione finanziaria"] = e["C_fin_netto"]
    ce["Rettifiche attività finanziarie"] = e["D_rettifiche"]
    ce["Risultato ante imposte"] = ce["Risultato operativo (EBIT)"] \
        + ce["Gestione finanziaria"] + ce["Rettifiche attività finanziarie"]
    ce["Imposte"] = e["imposte_20"]
    ce["Utile (perdita)"] = ce["Risultato ante imposte"] - ce["Imposte"]
    return ce


def debiti_finanziari(e):
    if e.presente("D_fin_entro") or e.presente("D_fin_oltre"):
        return e.somma("D_fin_entro", "D_fin_oltre")
    if e.presente("D_fin_totale"):
        return e["D_fin_totale"]
    return None


def indici(e, sp, ce, regole, pn_precedente, note):
    fin = debiti_finanziari(e)
    if fin is None:
        note.append("PFN n.d.: debiti finanziari (D1-D5) non ricavabili dal bilancio.")
    pfn = None if fin is None else fin - sp["Liquidità immediate"] - e["C_III_att_fin"]

    pn = sp["Patrimonio netto"]
    pn_roe = pn
    if regole["roe_base"] == "media":
        if pn_precedente is None:
            note.append("ROE sul PN finale: manca l'esercizio precedente per la media.")
        else:
            pn_roe = (pn + pn_precedente) / 2
    if pn <= 0:
        note.append("PN nullo o negativo: ROE, Debt/Equity e leverage non hanno significato.")

    capitale_roi = sp["Capitale investito"]
    if regole["roi_base"] == "operativo":
        capitale_roi -= e.somma("B_III_finanziarie", "C_III_att_fin") + sp["Liquidità immediate"]

    con_iva = 1 + regole["iva"]
    acquisti = e.somma("B6", "B7", "B8")
    liquidita = sp["Liquidità immediate"] + sp["Liquidità differite"]
    passivita = sp["Passività consolidate"] + sp["Passività correnti"]
    ricavi = ce["Ricavi (A1)"]

    def giorni(voce, base):
        if not e.presente(voce):
            return None
        return rapporto(e[voce] * 365, base * con_iva)

    fonti_durevoli = pn + sp["Passività consolidate"]
    oneri = e["C17_oneri_fin"] if e.presente("C17_oneri_fin") else None
    if oneri is None:
        note.append("Indici sugli oneri finanziari n.d.: interessi passivi (C.17) non ricavabili.")
    # magazzino sui consumi di materie e merci (B6 + B11), senza IVA: per un'industria con
    # molti prodotti finiti è una stima, e il commento lo deve dire
    consumi = e.somma("B6", "B11_var_rim_materie")
    giorni_mag = rapporto(sp["Rimanenze"] * 365, consumi) if sp["Rimanenze"] else (
        0.0 if consumi else None)
    g_cli, g_for = giorni("C_II_1_clienti", ricavi), giorni("D_7_fornitori", acquisti)
    ciclo = None if None in (g_cli, g_for, giorni_mag) else g_cli + giorni_mag - g_for
    dip = e["dipendenti_medi"] if e.presente("dipendenti_medi") else None

    return {
        "Current ratio": rapporto(sp["Attivo corrente"], sp["Passività correnti"]),
        "Quick ratio": rapporto(liquidita, sp["Passività correnti"]),
        "Capitale circolante netto": sp["Attivo corrente"] - sp["Passività correnti"],
        "Margine di tesoreria": liquidita - sp["Passività correnti"],
        "Margine di struttura primario": pn - sp["Immobilizzazioni"],
        "Indice di autocopertura immobilizzazioni": rapporto(pn, sp["Immobilizzazioni"]),
        "Margine di struttura secondario": fonti_durevoli - sp["Immobilizzazioni"],
        "Indice di copertura con fonti durevoli": rapporto(fonti_durevoli,
                                                           sp["Immobilizzazioni"]),
        "Debt/Equity": rapporto(passivita, pn),
        "Leverage (CI/PN)": rapporto(sp["Capitale investito"], pn),
        "PFN": pfn,
        "PFN/EBITDA": rapporto(pfn, ce["MOL (EBITDA)"]),
        "PFN/PN": rapporto(pfn, pn),
        "Oneri finanziari / MOL": rapporto(oneri, ce["MOL (EBITDA)"]),
        "Oneri finanziari / ricavi": rapporto(oneri, ricavi),
        "Copertura interessi (MOL / oneri finanziari)": rapporto(ce["MOL (EBITDA)"], oneri),
        "ROE": rapporto(ce["Utile (perdita)"], pn_roe),
        "ROI": rapporto(ce["Risultato operativo (EBIT)"], capitale_roi),
        "ROS": rapporto(ce["Risultato operativo (EBIT)"], ricavi),
        "EBITDA margin": rapporto(ce["MOL (EBITDA)"], ricavi),
        "Rotazione capitale investito": rapporto(ricavi, sp["Capitale investito"]),
        "Giorni incasso clienti": g_cli,
        "Giorni pagamento fornitori": g_for,
        "Giorni di magazzino": giorni_mag,
        "Ciclo del circolante (giorni)": ciclo,
        "Costo del personale / valore della produzione": rapporto(
            ce["Costo del personale"], ce["Valore della produzione"]),
        "Valore aggiunto per dipendente": rapporto(ce["Valore aggiunto"], dip),
    }


def euro(x):
    """Importo per le note, col punto delle migliaia: «-1,006» si leggerebbe un euro."""
    return f"{x:,.0f}".replace(",", ".")


def variazioni(corrente, precedente):
    """Variazione percentuale di ogni voce di SP e CE sull'esercizio immediatamente precedente.
    n.d. se manca l'anno prima o se il valore di partenza è zero; su una base negativa la
    variazione si misura sul suo valore assoluto, così un miglioramento resta positivo."""
    out = {}
    for sez in ("sp", "ce"):
        for voce, v in corrente[sez].items():
            base = precedente[sez][voce] if precedente else None
            out[f"{voce} ({sez.upper()})"] = None if not base else (v - base) / abs(base)
    return out


def note_variazioni(corrente, precedente, note):
    """Dove la percentuale inganna: base sotto lo 0,5% del valore della produzione
    dell'anno prima, o segno che cambia. Lì il commento dà i due importi."""
    if not precedente:
        return
    soglia = 0.005 * abs(precedente["ce"]["Valore della produzione"])
    for sez in ("sp", "ce"):
        for voce, v in corrente[sez].items():
            base = precedente[sez][voce]
            if not base:
                continue
            if (base < 0) != (v < 0) and v:
                motivo = "cambia segno"
            elif abs(base) < soglia:
                motivo = "base sotto lo 0,5% del valore della produzione"
            else:
                continue
            note.append(f"Variazione di {voce} ({sez.upper()}): {motivo}, da {euro(base)} a "
                        f"{euro(v)}; nel commento gli importi, non la percentuale.")


def composizione(sp, ce):
    """Peso di ogni voce: impieghi sul capitale investito, fonti sul totale fonti, conto
    economico sul valore della produzione."""
    impieghi = ("Immobilizzazioni", "Rimanenze", "Liquidità differite", "Liquidità immediate")
    fonti = ("Patrimonio netto", "Passività consolidate", "Passività correnti")
    out = {f"{v} / capitale investito": rapporto(sp[v], sp["Capitale investito"])
           for v in impieghi}
    out.update({f"{v} / totale fonti": rapporto(sp[v], sp["Totale fonti"]) for v in fonti})
    out.update({f"{v} / valore della produzione": rapporto(x, ce["Valore della produzione"])
                for v, x in ce.items() if v != "Valore della produzione"})
    return out


def quadrature(e, sp, ce):
    """Differenza di ogni controllo: entro la tolleranza vuol dire che torna."""
    return {
        "Somma voci attivo = Totale attivo": e.somma(*VOCI_ATTIVO) - e["TOT_ATTIVO"],
        "Somma voci passivo = Totale passivo": e.somma(*VOCI_PASSIVO) - e["TOT_PASSIVO"],
        "Totale attivo = Totale passivo": e["TOT_ATTIVO"] - e["TOT_PASSIVO"],
        "Utile ricalcolato = utile CE (21)": ce["Utile (perdita)"] - e["utile_21"],
        "Utile CE (21) = utile SP (A.IX)": e["utile_21"] - e["A_IX_utile"],
        "Impieghi = fonti nel riclassificato": sp["Capitale investito"] - sp["Totale fonti"],
    }


def analizza(esercizi, regole):
    risultati = {}
    for anno in sorted(esercizi):
        voci = esercizi[anno]
        e = Esercizio(voci)
        note = []
        sp = stato_patrimoniale(e, regole)
        ce = conto_economico(e, regole)
        # la media del ROE vuole l'esercizio immediatamente precedente, non uno qualsiasi
        prec = risultati.get(str(int(anno) - 1))
        pn_prec = prec["sp"]["Patrimonio netto"] if prec else None
        ind = indici(e, sp, ce, regole, pn_prec, note)
        for voce, origine in voci.get("_provenienza", {}).items():
            note.append(f"{voce}: {origine}.")
        note_variazioni({"sp": sp, "ce": ce}, prec, note)
        if ce["Imposte"] > 0 and ce["Imposte"] > ce["Risultato ante imposte"]:
            note.append(f"Imposte ({euro(ce['Imposte'])}) superiori al risultato ante imposte "
                        f"({euro(ce['Risultato ante imposte'])}).")
        risultati[anno] = {"sp": sp, "ce": ce, "indici": ind,
                           "variazioni": variazioni({"sp": sp, "ce": ce}, prec),
                           "composizione": composizione(sp, ce),
                           "controlli": quadrature(e, sp, ce), "note": note}
    return risultati


def leggi_json(percorso, cosa):
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as err:
        raise Malformato(f"{cosa} illeggibile ({percorso}): {err}")


def valida_estratto(dati):
    esercizi = dati.get("esercizi") if isinstance(dati, dict) else None
    if not isinstance(esercizi, dict) or not esercizi:
        raise Malformato("l'estratto non ha la sezione «esercizi».")
    for anno, voci in esercizi.items():
        if not re.fullmatch(r"\d{4}", anno):
            raise Malformato(f"esercizio «{anno}»: la chiave dev'essere l'anno a quattro cifre.")
        # una chiave scritta male farebbe sparire una voce senza che nessuno se ne accorga
        sconosciute = sorted(k for k in voci if k not in VOCI and not k.startswith("_"))
        if sconosciute:
            raise Malformato(f"esercizio {anno}, chiavi sconosciute: {', '.join(sconosciute)}")
        for k in VOCI.intersection(voci):
            v = voci[k]
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise Malformato(f"esercizio {anno}, {k}: valore non numerico «{v}».")
    return esercizi


def carica_regole(percorso):
    regole = dict(REGOLE_BASE)
    if percorso:
        if not os.path.exists(percorso):
            raise Malformato(f"file delle regole inesistente: {percorso}")
        regole.update(leggi_json(percorso, "regole"))
    ignote = sorted(set(regole) - set(REGOLE_BASE))
    if ignote:
        raise Malformato(f"regole sconosciute: {', '.join(ignote)}")
    for k, ammessi in VALORI_AMMESSI.items():
        if regole[k] not in ammessi:
            raise Malformato(f"regola {k}: «{regole[k]}» non ammesso "
                             f"({', '.join(map(str, ammessi))}).")
    return regole


def formato_cella(sezione, voce):
    if sezione in ("variazioni", "composizione"):
        return "0.0%"
    if sezione != "indici" or voce in IN_EURO:
        return "#,##0"
    if voce in PERCENTUALI:
        return "0.0%"
    if voce in GIORNI:
        return "0"
    return "0.00"


# L'Excel si scrive con la sola libreria standard: un .xlsx è uno zip di XML in formato
# pubblico (Office Open XML). Così la skill non chiede di installare niente.
# Stili: 0 normale, 1 grassetto, poi un formato numerico per ciascuno di FORMATI.
FORMATI = {"#,##0": (3, None), "0.0%": (164, "0.0%"), "0.00": (2, None), "0": (1, None)}
STILE = {f: 2 + i for i, f in enumerate(FORMATI)}


def _xml(testo):
    return (str(testo).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _colonna(n):
    lettere = ""
    while n:
        n, r = divmod(n - 1, 26)
        lettere = chr(65 + r) + lettere
    return lettere


def _foglio(righe, larghezze):
    """righe: liste di (valore, stile). Valore None = cella vuota."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           "<cols>"]
    out += ['<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i, i, w)
            for i, w in enumerate(larghezze, 1)]
    out.append("</cols><sheetData>")
    for r, riga in enumerate(righe, 1):
        out.append('<row r="%d">' % r)
        for c, (v, s) in enumerate(riga, 1):
            ref = "%s%d" % (_colonna(c), r)
            if v is None:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                out.append('<c r="%s" s="%d"><v>%r</v></c>' % (ref, s, float(v)))
            else:
                out.append('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s'
                           '</t></is></c>' % (ref, s, _xml(v)))
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def _stili():
    personalizzati = [(n, c) for n, c in FORMATI.values() if c]
    xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>',
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" applyFont="1"/>']
    xfs += ['<xf numFmtId="%d" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>'
            % n for n, _ in FORMATI.values()]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts count="%d">%s</numFmts>'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border>'
            '</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
            'borderId="0"/></cellStyleXfs><cellXfs count="%d">%s</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
            '</cellStyles></styleSheet>'
            % (len(personalizzati),
               "".join('<numFmt numFmtId="%d" formatCode="%s"/>' % (n, _xml(c))
                       for n, c in personalizzati),
               len(xfs), "".join(xfs)))


def scrivi_excel(percorso, risultati, regole):
    anni = sorted(risultati)
    titoli = [("sp", "SP riclassificato"), ("ce", "CE valore aggiunto"),
              ("indici", "Indici"), ("variazioni", "Variazioni"),
              ("composizione", "Composizione"), ("controlli", "Controlli")]
    fogli = []
    for sezione, titolo in titoli:
        righe = [[("Voce", 1)] + [(anno, 1) for anno in anni]]
        for voce in risultati[anni[0]][sezione]:
            stile = STILE[formato_cella(sezione, voce)]
            riga = [(voce, 0)]
            for anno in anni:
                v = risultati[anno][sezione][voce]
                if sezione == "controlli":
                    riga.append(("OK", 0))
                else:
                    riga.append(("n.d.", 0) if v is None else (v, stile))
            righe.append(riga)
        fogli.append((titolo, _foglio(righe, [45] + [16] * len(anni))))
    righe = [[("Esercizio", 1), ("Nota", 1)]]
    righe += [[(anno, 0), (nota, 0)] for anno in anni for nota in risultati[anno]["note"]]
    righe.append([("", 0), ("Regole: " + json.dumps(regole, ensure_ascii=False), 0)])
    fogli.append(("Note", _foglio(righe, [12, 90])))

    ns = "http://schemas.openxmlformats.org/"
    with zipfile.ZipFile(percorso, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="%spackage/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
                   'package.relationships+xml"/><Default Extension="xml" ContentType='
                   '"application/xml"/><Override PartName="/xl/workbook.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.spreadsheetml.styles+xml"/>%s</Types>'
                   % (ns, "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType='
                                  '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
                                  'worksheet+xml"/>' % i for i in range(1, len(fogli) + 1))))
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="%spackage/2006/relationships"><Relationship Id="rId1" '
                   'Type="%sofficeDocument/2006/relationships/officeDocument" '
                   'Target="xl/workbook.xml"/></Relationships>' % (ns, ns))
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="%sspreadsheetml/2006/main" xmlns:r="%sofficeDocument/2006/'
                   'relationships"><sheets>%s</sheets></workbook>'
                   % (ns, ns, "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                                      % (_xml(t), i, i) for i, (t, _) in enumerate(fogli, 1))))
        rels = "".join('<Relationship Id="rId%d" Type="%sofficeDocument/2006/relationships/'
                       'worksheet" Target="worksheets/sheet%d.xml"/>' % (i, ns, i)
                       for i in range(1, len(fogli) + 1))
        rels += ('<Relationship Id="rId%d" Type="%sofficeDocument/2006/relationships/styles" '
                 'Target="styles.xml"/>' % (len(fogli) + 1, ns))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="%spackage/2006/relationships">%s</Relationships>'
                   % (ns, rels))
        z.writestr("xl/styles.xml", _stili())
        for i, (_, xml_foglio) in enumerate(fogli, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, xml_foglio)


def occupata(cartella, anno, suf):
    """La versione è presa se c'è anche uno solo dei suoi quattro file."""
    return any(glob.glob(os.path.join(glob.escape(cartella), modello % (anno, suf)))
               for modello in ("estratto-%s%s.json", "analisi-*-%s%s.xlsx",
                               "risultati-*-%s%s.json", "commento-%s%s.md"))


def uguale(percorso, contenuto):
    try:
        with open(percorso, encoding="utf-8") as f:
            fatto = json.load(f)
        fatto.pop("estratto", None)  # il nome dell'estratto non è un risultato
        return fatto == contenuto
    except (OSError, ValueError, AttributeError):
        return False  # mancante o illeggibile: non è uguale, e non si tocca


def main():
    p = argparse.ArgumentParser(description="Riclassificazione e indici di bilancio CEE.")
    p.add_argument("estratto")
    p.add_argument("--regole")
    p.add_argument("--out", default=".")
    a = p.parse_args()
    try:
        dati = leggi_json(a.estratto, "estratto")
        esercizi = valida_estratto(dati)
        regole = carica_regole(a.regole)
    except Malformato as err:
        print(f"ERRORE: {err}", file=sys.stderr)
        sys.exit(2)
    risultati = analizza(esercizi, regole)
    toll = regole["tolleranza"]
    falliti = [f"{anno}: {nome} (differenza {euro(diff)})"
               for anno, r in sorted(risultati.items())
               for nome, diff in r["controlli"].items() if abs(diff) > toll]
    if falliti:
        print("CONTROLLI FALLITI - nessun file scritto:\n" + "\n".join(falliti))
        sys.exit(1)

    os.makedirs(a.out, exist_ok=True)
    nome = re.sub(r"[^\w.-]+", "_", str(dati.get("azienda") or "azienda")).strip("_") or "azienda"
    contenuto = json.loads(json.dumps({"azienda": dati.get("azienda"), "tipo": dati.get("tipo"),
                                       "regole": regole, "risultati": risultati}))
    anno = max(risultati)

    def file_di(suf):
        return (os.path.join(a.out, f"risultati-{nome}-{anno}{suf}.json"),
                os.path.join(a.out, f"analisi-{nome}-{anno}{suf}.xlsx"))

    def identica(js):
        print(f"Tutti i controlli superati. Analisi identica già scritta: {js}; "
              "nessun file nuovo.")

    # il numero viene dall'estratto: estratto-2025-2.json dà la versione 2. Se quella
    # versione ha già risultati diversi (regole cambiate) si apre la prima libera e ci si
    # copia l'estratto, così ogni numero ha la sua serie intera
    m = re.fullmatch(r"estratto-(\d{4})(?:-(\d+))?\.json", os.path.basename(a.estratto))
    suf, copia = None, False
    if m and m.group(1) == anno and os.path.samefile(
            os.path.dirname(os.path.abspath(a.estratto)), a.out):
        s = f"-{m.group(2)}" if m.group(2) else ""
        js, xl = file_di(s)
        if uguale(js, contenuto):
            return identica(js)
        if not os.path.exists(js) and not os.path.exists(xl):
            suf = s
    if suf is None:
        n = 1
        while True:
            s = "" if n == 1 else f"-{n}"
            if uguale(file_di(s)[0], contenuto):
                return identica(file_di(s)[0])
            if not occupata(a.out, anno, s):
                suf, copia = s, True
                break
            n += 1
    js, xl = file_di(suf)
    origine = os.path.join(a.out, f"estratto-{anno}{suf}.json") if copia else a.estratto
    if copia:
        shutil.copyfile(a.estratto, origine)
    contenuto["estratto"] = os.path.basename(origine)
    scrivi_excel(xl, risultati, regole)
    with open(js, "w", encoding="utf-8") as f:
        json.dump(contenuto, f, ensure_ascii=False, indent=2)
    print(f"Tutti i controlli superati. Versione {suf.lstrip('-') or 1}: scritti {xl}, {js}"
          + (f", e la copia dell'estratto {origine}" if copia else "") + ".")
    for anno, r in sorted(risultati.items()):
        for nota in r["note"]:
            print(f"Nota {anno}: {nota}")


if __name__ == "__main__":
    main()
