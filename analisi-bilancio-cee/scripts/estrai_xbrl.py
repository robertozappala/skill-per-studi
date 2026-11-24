#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 ztax.it - https://ztax.it
# Licenza MIT: vedi il file LICENSE della skill.
"""Legge un bilancio XBRL depositato (tassonomia InfoCamere itcc-ci) e scrive l'estratto.json
che calcola_indici.py si aspetta.

Uso: python3 estrai_xbrl.py bilancio.xbrl [altro.xbrl ...] --azienda NOME --out CARTELLA

Scrive CARTELLA/estratto-<ultimo esercizio>.json, e crea la cartella se non c'è. Il -2, -3
è la versione dell'analisi, comune a estratto, Excel, risultati e commento: prende il primo
numero che nessuno dei quattro usa; un estratto uguale già scritto non si ripete.

Perché è uno script: lo stesso file deve dare sempre gli stessi numeri. La tabella delle
voci è fissa; le voci che la tabella non nomina si ricavano per differenza dai totali che il
bilancio stesso dichiara, e ogni differenza è controllata contro un altro totale. Se un
controllo non torna, o la tassonomia non è quella nota, lo script si ferma e dice dove.

Con più file, per ogni anno vale il bilancio più recente; le differenze sullo stesso anno
fra due bilanci (riclassificazioni per comparabilità) si stampano.

Esce 0 se l'estratto è scritto; 1 se un controllo non torna; 2 se il file non si legge."""
import argparse, glob, html.entities, json, os, re, sys
import xml.etree.ElementTree as ET

NS_ITCC = "http://www.infocamere.it/itnn/fr/itcc/ci/2018-11-04"
NS_XBRLI = "http://www.xbrl.org/2003/instance"
TOLL = 2  # euro: arrotondamenti all'unità

# tag dello stato patrimoniale (contesto istantaneo) -> chiave dell'estratto
SP = {
    "TotaleImmobilizzazioniImmateriali": "B_I_immateriali",
    "TotaleImmobilizzazioniMateriali": "B_II_materiali",
    "TotaleImmobilizzazioniFinanziarie": "B_III_finanziarie",
    "TotaleRimanenze": "C_I_rimanenze",
    "CreditiVersoClientiTotaleCreditiVersoClienti": "C_II_1_clienti",
    "TotaleAttivitaFinanziarieNonCostituisconoImmobilizzazioni": "C_III_att_fin",
    "TotaleDisponibilitaLiquide": "C_IV_liquidita",
    "AttivoRateiRisconti": "D_ratei_risconti_att",
    "TotaleAttivo": "TOT_ATTIVO",
    "TotalePatrimonioNetto": "A_PN",
    "PatrimonioNettoUtilePerditaEsercizio": "A_IX_utile",
    "TotaleFondiRischiOneri": "B_fondi",
    "TrattamentoFineRapportoLavoroSubordinato": "C_TFR",
    "DebitiDebitiVersoFornitoriTotaleDebitiVersoFornitori": "D_7_fornitori",
    "PassivoRateiRisconti": "E_ratei_risconti_pass",
    "TotalePassivo": "TOT_PASSIVO",
    "TotaleDipendentiNumeroMedio": "dipendenti_medi",
}
# tag del conto economico (contesto di durata) -> chiave dell'estratto
CE = {
    "ValoreProduzioneRicaviVenditePrestazioni": "A1_ricavi",
    "ValoreProduzioneAltriRicaviProventiTotaleAltriRicaviProventi": "A5_altri_ricavi",
    "CostiProduzioneMateriePrimeSussidiarieConsumoMerci": "B6",
    "CostiProduzioneServizi": "B7",
    "CostiProduzioneGodimentoBeniTerzi": "B8",
    "CostiProduzionePersonaleTotaleCostiPersonale": "B9_personale",
    "CostiProduzioneAmmortamentiSvalutazioniTotaleAmmortamentiSvalutazioni": "B10_ammortamenti",
    "CostiProduzioneVariazioniRimanenzeMateriePrimeSussidiarieConsumoMerci": "B11_var_rim_materie",
    "CostiProduzioneOneriDiversiGestione": "B14_oneri_diversi",
    "TotaleProventiOneriFinanziari": "C_fin_netto",
    "ProventiOneriFinanziariInteressiAltriOneriFinanziariTotaleInteressiAltriOneriFinanziari": "C17_oneri_fin",
    "ImposteRedditoEsercizioCorrentiDifferiteAnticipateTotaleImposteRedditoEsercizioCorrentiDifferiteAnticipate": "imposte_20",
    "UtilePerditaEsercizio": "utile_21",
}
# totali che servono ai controlli e alle differenze: senza questi non si procede
OBBLIGATORI_SP = ["TotaleAttivo", "TotalePassivo", "TotalePatrimonioNetto",
                  "PatrimonioNettoUtilePerditaEsercizio"]
OBBLIGATORI_CE = ["TotaleValoreProduzione", "TotaleCostiProduzione",
                  "DifferenzaValoreCostiProduzione", "RisultatoPrimaImposte", "UtilePerditaEsercizio"]
IMPOSTE = "ImposteRedditoEsercizioCorrentiDifferiteAnticipateTotaleImposteRedditoEsercizioCorrentiDifferiteAnticipate"
# A2, A3 e la voce che nell'abbreviato li raggruppa
A2 = "ValoreProduzioneVariazioniRimanenzeProdottiCorsoLavorazioneSemilavoratiFiniti"
A3 = "ValoreProduzioneVariazioniLavoriCorsoOrdinazione"
A23 = A2 + "LavoriCorsoOrdinazione"
# debiti finanziari D1-D5, per la PFN
FIN = ["DebitiObbligazioni", "DebitiObbligazioniConvertibili", "DebitiDebitiVersoSociFinanziamenti",
       "DebitiDebitiVersoBanche", "DebitiDebitiVersoAltriFinanziatori"]
FIN_TOT = {"DebitiObbligazioni": "DebitiObbligazioniTotaleObbligazioni",
           "DebitiObbligazioniConvertibili": "DebitiObbligazioniConvertibiliTotaleObbligazioniConvertibili",
           "DebitiDebitiVersoSociFinanziamenti": "DebitiDebitiVersoSociFinanziamentiTotaleDebitiVersoSociFinanziamenti",
           "DebitiDebitiVersoBanche": "DebitiDebitiVersoBancheTotaleDebitiVersoBanche",
           "DebitiDebitiVersoAltriFinanziatori": "DebitiDebitiVersoAltriFinanziatoriTotaleDebitiVersoAltriFinanziatori"}


class Fermo(Exception):
    pass


def euro(x):
    """Importo per i messaggi, col punto delle migliaia: «-1,006» si leggerebbe un euro."""
    return f"{x:,.0f}".replace(",", ".")


def analizza(path):
    """Il nodo radice. Alcuni programmi scrivono nel testo della nota entità HTML (&nbsp;,
    &euro;) che l'XML non definisce: si sostituiscono col carattere e si riprova. Stanno nel
    testo, che lo script non legge, e gli importi non ne sono toccati."""
    try:
        return ET.parse(path).getroot()  # ElementTree non risolve entità esterne
    except ET.ParseError as e:
        if "undefined entity" not in str(e):
            raise
    with open(path, encoding="utf-8") as f:
        testo = f.read()
    testo = re.sub(r"&([A-Za-z][A-Za-z0-9]*);",
                   lambda m: m.group(0) if m.group(1) in ("amp", "lt", "gt", "quot", "apos")
                   else html.entities.html5.get(m.group(1) + ";", m.group(0)), testo)
    root = ET.fromstring(testo)
    print(f"AVVISO: {path}: entità HTML nel testo della nota sostituite col carattere.",
          file=sys.stderr)
    return root


def per_voce(i, prefisso):
    """Entro e oltre sommati sulle voci per natura (C.II.1-5, D.1-14), che l'ordinario
    ripartisce una per una senza un totale; None se il file non ne ha nessuna."""
    entro = [x for t, x in i.items() if t.startswith(prefisso)
             and t.endswith("EsigibiliEntroEsercizioSuccessivo")]
    oltre = [x for t, x in i.items() if t.startswith(prefisso)
             and t.endswith("EsigibiliOltreEsercizioSuccessivo")]
    if not entro and not oltre:
        return None, None
    return sum(entro), sum(oltre)


def leggi(path):
    """Ritorna (tipo, {anno: {'i': {tag: valore}, 'd': {tag: valore}}})."""
    try:
        root = analizza(path)
    except (OSError, UnicodeDecodeError, ET.ParseError) as e:
        print(f"ERRORE: {path} non si legge come XML: {e}", file=sys.stderr)
        sys.exit(2)
    ns_usati = {e.tag[1:].split("}")[0] for e in root if e.tag.startswith("{")}
    if NS_ITCC not in ns_usati:
        altri = sorted(n for n in ns_usati if "itcc" in n) or sorted(ns_usati)
        raise Fermo(f"{path}: tassonomia non nota ({', '.join(altri)}). La tabella delle voci "
                    f"è costruita su {NS_ITCC}: va estesa, non si indovina.")
    ref = root.find(f"{{http://www.xbrl.org/2003/linkbase}}schemaRef")
    href = ref.get("{http://www.w3.org/1999/xlink}href", "") if ref is not None else ""
    tipo = "abbreviato" if "-abb-" in href else "ordinario" \
        if href.startswith(("itcc-ci-2018", "itcc-ci-ese-2018")) \
        else f"da verificare ({href or 'schemaRef assente'})"

    contesti = {}
    for c in root.iter(f"{{{NS_XBRLI}}}context"):
        # lo scenario «Depositato» c'è in tutti i contesti; si scartano solo quelli con
        # dimensioni (segment, explicitMember, typedMember), che sono dettagli di nota
        if c.find(f".//{{{NS_XBRLI}}}segment") is not None or \
           any(x.tag.endswith(("}explicitMember", "}typedMember")) for x in c.iter()):
            continue
        ist = c.find(f".//{{{NS_XBRLI}}}instant")
        fine = c.find(f".//{{{NS_XBRLI}}}endDate")
        if ist is not None:
            contesti[c.get("id")] = (ist.text.strip()[:4], "i")
        elif fine is not None:
            contesti[c.get("id")] = (fine.text.strip()[:4], "d")

    dati = {}
    for e in root:
        if not e.tag.startswith(f"{{{NS_ITCC}}}") or e.get("contextRef") not in contesti:
            continue
        if e.get("unitRef") is None:
            continue  # testo, non importi
        tag = e.tag.split("}")[1]
        anno, k = contesti[e.get("contextRef")]
        try:
            val = float((e.text or "").strip())
        except ValueError:
            raise Fermo(f"{path}: {tag} {anno} non è un numero: «{e.text}»")
        d = dati.setdefault(anno, {"i": {}, "d": {}})[k]
        if tag in d and d[tag] != val:
            raise Fermo(f"{path}: {tag} {anno} compare due volte con valori diversi.")
        d[tag] = val
    return tipo, dati


def esercizio(path, anno, i, d):
    def v(dz, tag):
        return dz.get(tag, 0.0)

    def controlla(nome, a, b):
        if abs(a - b) > TOLL:
            raise Fermo(f"{path}, {anno}: {nome} non torna (differenza {euro(a - b)}).")

    out, prov = {}, {}
    # il risultato prima delle imposte a zero può mancare dal file: si ricava da A - B + C + D
    # e si controlla contro utile più imposte
    if "RisultatoPrimaImposte" not in d and \
            {"DifferenzaValoreCostiProduzione", "UtilePerditaEsercizio"} <= d.keys():
        rpi = d["DifferenzaValoreCostiProduzione"] + v(d, "TotaleProventiOneriFinanziari") \
            + v(d, "TotaleRettificheValoreAttivitaPassivitaFinanziarie")
        controlla("A - B + C + D = utile + imposte", rpi, d["UtilePerditaEsercizio"] + v(d, IMPOSTE))
        d = dict(d, RisultatoPrimaImposte=rpi)
        prov["RisultatoPrimaImposte"] = "assente nel file: A - B + C + D, controllato su utile + imposte"
    manca = [t for t in OBBLIGATORI_SP if t not in i] + [t for t in OBBLIGATORI_CE if t not in d]
    if manca:
        raise Fermo(f"{path}, {anno}: mancano i totali {', '.join(manca)}.")
    for tag, k in SP.items():
        if tag in i:
            out[k] = i[tag]
    for tag, k in CE.items():
        if tag in d:
            out[k] = d[tag]
    for k in ("C_II_1_clienti", "D_7_fornitori", "C17_oneri_fin", "dipendenti_medi"):
        out.setdefault(k, None)  # assente non vuol dire zero: resta n.d.

    # crediti dell'attivo circolante e debiti, entro e oltre: lo schema, poi la nota
    # integrativa, poi la somma per voce, poi la differenza; e il totale controlla la somma
    def entro_oltre(chiave, nome, totale, tag_entro, tag_oltre, prefisso):
        tot = v(i, totale)
        entro = i.get(tag_entro[0], i.get(tag_entro[1]))
        oltre = i.get(tag_oltre[0], i.get(tag_oltre[1]))
        if entro is None and oltre is None:
            entro, oltre = per_voce(i, prefisso)
            if entro is not None and tot:
                prov[chiave + "entro"] = "entro e oltre sommati voce per voce"
        if entro is None and oltre is None:
            if tot:
                raise Fermo(f"{path}, {anno}: {nome} senza ripartizione entro/oltre l'esercizio.")
            entro = oltre = 0.0
        # la voce ricavata per differenza si annota solo se non è zero, come le altre
        if oltre is None:
            oltre = tot - entro
            if abs(oltre) > TOLL:
                prov[chiave + "oltre"] = f"{totale} - {nome} entro"
        if entro is None:
            entro = tot - oltre
            if abs(entro) > TOLL:
                prov[chiave + "entro"] = f"{totale} - {nome} oltre"
        out[chiave + "entro"], out[chiave + "oltre"] = entro, oltre
        controlla(f"{nome} entro + oltre = {totale}", entro + oltre, tot)
        return tot

    tot_cred = entro_oltre(
        "C_II_crediti_", "crediti", "TotaleCrediti",
        ("CreditiEsigibiliEntroEsercizioSuccessivo",
         "TotaleCreditiIscrittiAttivoCircolanteQuotaScadenteEntroEsercizio"),
        ("CreditiEsigibiliOltreEsercizioSuccessivo",
         "TotaleCreditiIscrittiAttivoCircolanteQuotaScadenteOltreEsercizio"), "Crediti")
    tot_deb = entro_oltre(
        "D_debiti_", "debiti", "TotaleDebiti",
        ("DebitiEsigibiliEntroEsercizioSuccessivo", "TotaleDebitiQuotaScadenteEntroEsercizio"),
        ("DebitiEsigibiliOltreEsercizioSuccessivo", "TotaleDebitiQuotaScadenteOltreEsercizio"),
        "Debiti")

    # dettaglio per natura completo (l'ordinario): le voci per natura sommano al totale, e
    # allora una voce assente è zero, non n.d.; se una voce generica fa da sola il totale, il
    # dettaglio dell'anno non dice niente su clienti, fornitori e debiti finanziari
    def natura(prefisso, tot):
        tags = [t for t in i if t.startswith(prefisso) and "Totale" in t
                and not t.endswith("EsercizioSuccessivo")]
        return bool(tags) and tot > TOLL and abs(sum(i[t] for t in tags) - tot) <= TOLL

    nat_cred, nat_deb = natura("Crediti", tot_cred), natura("Debiti", tot_deb)
    if nat_cred and out["C_II_1_clienti"] is None:
        out["C_II_1_clienti"] = 0.0
        prov["C_II_1_clienti"] = "assente nel dettaglio per natura completo: zero"
    if nat_deb and out["D_7_fornitori"] is None:
        out["D_7_fornitori"] = 0.0
        prov["D_7_fornitori"] = "assente nel dettaglio per natura completo: zero"
    if nat_cred and abs(v(i, "CreditiVersoAltriTotaleCreditiVersoAltri") - tot_cred) <= TOLL:
        prov["C_II_crediti_natura"] = ("tutti i crediti in C.II.5-quater «verso altri»: giorni "
                                       "clienti dell'anno non significativi")
    if nat_deb and abs(v(i, "DebitiAltriDebitiTotaleAltriDebiti") - tot_deb) <= TOLL:
        prov["D_debiti_natura"] = ("tutti i debiti in D.14 «altri debiti»: giorni fornitori e "
                                   "PFN dell'anno non significativi")

    # debiti finanziari D1-D5: per voce entro/oltre se ci sono tutte, sennò i totali per voce;
    # col dettaglio per natura completo una voce assente è zero
    e_tag = [f + "EsigibiliEntroEsercizioSuccessivo" for f in FIN]
    o_tag = [f + "EsigibiliOltreEsercizioSuccessivo" for f in FIN]
    t_tag = [FIN_TOT[f] for f in FIN]
    fin_tot = sum(v(i, t) for t in t_tag)
    if nat_deb and abs(sum(v(i, t) for t in e_tag + o_tag) - fin_tot) <= TOLL:
        out["D_fin_entro"] = sum(v(i, t) for t in e_tag)
        out["D_fin_oltre"] = sum(v(i, t) for t in o_tag)
        if not all(t in i for t in t_tag):
            prov["D_fin_entro"] = "le voci D1-D5 assenti valgono zero (dettaglio per natura completo)"
    elif nat_deb:
        out["D_fin_totale"] = fin_tot
        prov["D_fin_totale"] = "totali D1-D5, senza ripartizione entro/oltre"
    elif all(t in i for t in e_tag + o_tag):
        out["D_fin_entro"] = sum(i[t] for t in e_tag)
        out["D_fin_oltre"] = sum(i[t] for t in o_tag)
    elif all(t in i for t in t_tag):
        out["D_fin_totale"] = sum(i[t] for t in t_tag)
        prov["D_fin_totale"] = "totali D1-D5, senza ripartizione entro/oltre"
    else:
        out["D_fin_totale"] = None
        prov["D_fin_totale"] = "debiti per natura non presenti: PFN n.d."

    # A - crediti verso soci: per differenza dai totali dell'attivo
    tot_imm = v(i, "TotaleImmobilizzazioni")
    controlla("B.I + B.II + B.III = TotaleImmobilizzazioni",
              v(i, "TotaleImmobilizzazioniImmateriali") + v(i, "TotaleImmobilizzazioniMateriali")
              + v(i, "TotaleImmobilizzazioniFinanziarie"), tot_imm)
    controlla("C.I + C.II + C.III + C.IV = TotaleAttivoCircolante",
              v(i, "TotaleRimanenze") + tot_cred
              + v(i, "TotaleAttivitaFinanziarieNonCostituisconoImmobilizzazioni")
              + v(i, "TotaleDisponibilitaLiquide"), v(i, "TotaleAttivoCircolante"))
    cs = i["TotaleAttivo"] - tot_imm - v(i, "TotaleAttivoCircolante") - v(i, "AttivoRateiRisconti")
    if cs < -TOLL:
        raise Fermo(f"{path}, {anno}: attivo incoerente, crediti verso soci negativi ({euro(cs)}).")
    out["A_crediti_soci"] = max(cs, 0.0)
    if abs(cs) > TOLL:
        prov["A_crediti_soci"] = "TotaleAttivo - immobilizzazioni - circolante - ratei"
    controlla("PN + fondi + TFR + debiti + ratei = TotalePassivo",
              i["TotalePatrimonioNetto"] + v(i, "TotaleFondiRischiOneri")
              + v(i, "TrattamentoFineRapportoLavoroSubordinato") + tot_deb
              + v(i, "PassivoRateiRisconti"), i["TotalePassivo"])

    # A2+A3+A4 e B12+B13 non hanno un tag in tabella: la differenza dal totale si accetta
    # solo se è fatta esattamente dalle voci del file che la tabella non nomina, così un
    # costo dal nome diverso non finisce negli accantonamenti senza che nessuno lo veda
    def resto(nome, totale, prefisso, dettagli_noti, parole, esclusi=()):
        r = d[totale] - sum(v(d, t) for t, k in CE.items() if t.startswith(prefisso))
        if abs(r) <= TOLL:
            return 0.0, None
        cand = [t for t in d if t.startswith(prefisso) and t not in CE and t != totale
                and not t.startswith(tuple(dettagli_noti)) and t not in esclusi]
        estranee = [t for t in cand if not any(p in t for p in parole)]
        if estranee:
            raise Fermo(f"{path}, {anno}: voci fuori tabella che non sono {nome}: "
                        f"{', '.join(estranee)}. Va estesa la tabella.")
        if abs(sum(d[t] for t in cand) - r) > TOLL:
            raise Fermo(f"{path}, {anno}: {nome} = {euro(r)} per differenza, ma le voci non in "
                        f"tabella ({', '.join(cand) or 'nessuna'}) non lo spiegano. "
                        "Va estesa la tabella.")
        return r, f"{nome}, per differenza: {', '.join(cand)}"

    # l'abbreviato può raggruppare A2 e A3 in una voce, e il file porta anche il dettaglio con
    # lo stesso importo: vale la voce raggruppata, e il dettaglio deve tornare con lei
    esclusi = ()
    if A23 in d:
        esclusi = tuple(t for t in (A2, A3) if t in d)
        if esclusi:
            controlla("A2 + A3 = voce raggruppata", sum(d[t] for t in esclusi), d[A23])
    out["A2_var_rim_prodotti"], pa = resto(
        "A2+A3+A4", "TotaleValoreProduzione", "ValoreProduzione",
        ["ValoreProduzioneAltriRicaviProventi"], ["Variazion", "Incrementi", "Lavori"], esclusi)
    out["B12_accantonamenti"], pb = resto(
        "B12+B13", "TotaleCostiProduzione", "CostiProduzione",
        ["CostiProduzionePersonale", "CostiProduzioneAmmortamentiSvalutazioni"], ["Accantonament"])
    if pa:
        prov["A2_var_rim_prodotti"] = pa
    if pb:
        prov["B12_accantonamenti"] = pb
    controlla("A - B = DifferenzaValoreCostiProduzione",
              d["TotaleValoreProduzione"] - d["TotaleCostiProduzione"],
              d["DifferenzaValoreCostiProduzione"])
    rett = d["RisultatoPrimaImposte"] - d["DifferenzaValoreCostiProduzione"] \
        - v(d, "TotaleProventiOneriFinanziari")
    out["D_rettifiche"] = rett
    if abs(rett) > TOLL:
        prov["D_rettifiche"] = "per differenza dal risultato prima delle imposte"
    if prov:
        out["_provenienza"] = prov
    return out


def occupata(cartella, anno, suf):
    """La versione è presa se c'è anche uno solo dei suoi quattro file."""
    return any(glob.glob(os.path.join(glob.escape(cartella), modello % (anno, suf)))
               for modello in ("estratto-%s%s.json", "analisi-*-%s%s.xlsx",
                               "risultati-*-%s%s.json", "commento-%s%s.md"))


def uguale(percorso, contenuto):
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f) == contenuto
    except (OSError, ValueError):
        return False  # mancante o illeggibile: non è uguale, e non si tocca


def main():
    p = argparse.ArgumentParser()
    p.add_argument("xbrl", nargs="+")
    p.add_argument("--azienda", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    esercizi, fonte, tipi, avvisi = {}, {}, set(), []
    try:
        letti = []
        for path in a.xbrl:
            tipo, dati = leggi(path)
            tipi.add(tipo)
            letti.append((max(dati) if dati else "", path, dati))
        anni_file = [x[0] for x in letti]
        doppi = sorted({y for y in anni_file if anni_file.count(y) > 1})
        if doppi:
            raise Fermo(f"più bilanci dello stesso esercizio ({', '.join(doppi)}): "
                        "quale valga lo decide chi lavora, se ne passa uno solo.")
        for _, path, dati in sorted(letti):  # dal più vecchio: il più recente sovrascrive
            for anno, dz in sorted(dati.items()):
                if not dz["i"] or not dz["d"]:
                    continue  # anno con solo SP o solo CE (es. il 1° gennaio): non è un esercizio
                nuovo = esercizio(path, anno, dz["i"], dz["d"])
                if anno in esercizi:
                    diff = [k for k in nuovo if not k.startswith("_") and nuovo[k] is not None
                            and esercizi[anno].get(k) is not None
                            and abs(nuovo[k] - esercizi[anno][k]) > TOLL]
                    if diff:
                        avvisi.append(f"{anno}: {fonte[anno]} e {path} differiscono su "
                                      f"{', '.join(diff)}; vale {path}.")
                esercizi[anno], fonte[anno] = nuovo, path
    except Fermo as e:
        print(f"FERMO: {e}", file=sys.stderr)
        sys.exit(1)
    if not esercizi:
        print("FERMO: nessun esercizio completo (SP e CE) nei file.", file=sys.stderr)
        sys.exit(1)

    out = {"azienda": a.azienda, "tipo": " / ".join(sorted(tipi)),
           "_fonte": {k: fonte[k] for k in sorted(fonte)}, "esercizi": esercizi}
    out = json.loads(json.dumps(out))  # la forma che avrà riletto dal disco
    os.makedirs(a.out, exist_ok=True)
    anno, n = max(esercizi), 1
    while True:
        suf = "" if n == 1 else f"-{n}"
        percorso = os.path.join(a.out, f"estratto-{anno}{suf}.json")
        if uguale(percorso, out):
            print(f"Estratto identico già scritto: {percorso}; nessun file nuovo.")
            return
        if not occupata(a.out, anno, suf):
            break
        n += 1
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Estratto scritto: {percorso} - esercizi {', '.join(sorted(esercizi))}, tipo {out['tipo']}.")
    for anno in sorted(esercizi):
        for k, pv in esercizi[anno].get("_provenienza", {}).items():
            print(f"  {anno} {k}: {pv}")
    for av in avvisi:
        print("AVVISO: " + av)


if __name__ == "__main__":
    main()
