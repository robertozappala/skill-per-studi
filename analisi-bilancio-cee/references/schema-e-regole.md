# Schema dell'estratto e regole di riclassificazione

## 1. Lo schema di `estratto.json`

Lo scrive `estrai_xbrl.py` dall'XBRL; dal PDF lo scrive Claude, con questo schema esatto.
`calcola_indici.py` rifiuta una chiave che non conosce (un refuso farebbe sparire una voce in
silenzio) e un valore non numerico. Le chiavi che cominciano con `_` (`_fonte`,
`_provenienza`, `_riscontro`) sono annotazioni e non entrano nei conti.

```json
{
  "azienda": "Rossi Srl",
  "tipo": "ordinario | abbreviato | micro",
  "_fonte": "bilancio 2025.pdf, pagine 2-4 e 11",
  "esercizi": {
    "2025": {
      "A_crediti_soci": 0,
      "B_I_immateriali": 0, "B_II_materiali": 0, "B_III_finanziarie": 0,
      "C_I_rimanenze": 0,
      "C_II_crediti_entro": 0, "C_II_crediti_oltre": 0,
      "C_II_1_clienti": null,
      "C_III_att_fin": 0, "C_IV_liquidita": 0,
      "D_ratei_risconti_att": 0, "TOT_ATTIVO": 0,
      "A_PN": 0, "A_IX_utile": 0,
      "B_fondi": 0, "C_TFR": 0,
      "D_debiti_entro": 0, "D_debiti_oltre": 0,
      "D_fin_entro": null, "D_fin_oltre": null, "D_fin_totale": null,
      "D_7_fornitori": null,
      "E_ratei_risconti_pass": 0, "TOT_PASSIVO": 0,
      "A1_ricavi": 0, "A2_var_rim_prodotti": 0, "A3_var_lavori": 0,
      "A4_incrementi": 0, "A5_altri_ricavi": 0,
      "B6": 0, "B7": 0, "B8": 0, "B9_personale": 0, "B10_ammortamenti": 0,
      "B11_var_rim_materie": 0, "B12_accantonamenti": 0, "B13_altri_acc": 0,
      "B14_oneri_diversi": 0,
      "C_fin_netto": 0, "C17_oneri_fin": null, "D_rettifiche": 0,
      "imposte_20": 0, "utile_21": 0,
      "dipendenti_medi": null,
      "_riscontro": {"B7": "p. 4, riga B.7", "D_fin_entro": "p. 11, nota integrativa, debiti"}
    }
  }
}
```

- Importi in euro, senza separatori. Costi positivi come in bilancio. A2, A3, B11, C e D col
  segno del bilancio.
- **Zero o `null`.** Una voce che entra nelle quadrature (tutte tranne `C_II_1_clienti`,
  `D_7_fornitori`, le tre `D_fin_*`, `C17_oneri_fin` e `dipendenti_medi`) vale **0** quando il
  bilancio non la porta e i totali tornano senza di lei: è quello che fa anche `estrai_xbrl.py`.
  Le voci informative dell'elenco fra parentesi restano `null` quando il bilancio non le dà:
  zero direbbe che non ci sono, `null` che non si sa.
- `_riscontro` (solo dal PDF): per ogni chiave dell'esercizio, la pagina e la riga da cui
  viene l'importo.
- L'anno è la chiave a quattro cifre dell'esercizio.
- `D_fin_entro` / `D_fin_oltre`: debiti finanziari D1-D5 (obbligazioni, convertibili, soci
  per finanziamenti, banche, altri finanziatori) ripartiti. Se c'è solo il totale per voce,
  va in `D_fin_totale`. Se non c'è niente, tutto `null`: la PFN esce n.d. Quando i debiti per
  natura sommano esattamente al totale dei debiti (l'ordinario, o la nota dell'abbreviato che
  li dettaglia), una voce D1-D5 assente vale 0.
- `C17_oneri_fin`: interessi e altri oneri finanziari (C.17), positivi. `C_fin_netto` è il
  saldo della gestione finanziaria e li comprende: `C17_oneri_fin` serve solo agli indici di
  copertura degli interessi, e `null` li lascia n.d.
- `dipendenti_medi`: numero medio dei dipendenti dalla nota integrativa; `null` lascia n.d. il
  valore aggiunto per dipendente.
- `C_II_1_clienti` e `D_7_fornitori` `null` quando il bilancio non li distingue: i giorni
  clienti e fornitori escono n.d. Col dettaglio per natura completo, la voce assente vale 0.
- Con due bilanci che danno valori diversi per lo stesso anno vale il più recente, e la
  differenza va nel commento.

## 2. Le regole di riclassificazione

Un `regole.json` nella cartella `Analisi bilancio/` del cliente cambia i default. Tutte le
chiavi sono facoltative; una chiave sconosciuta o un valore non ammesso fermano lo script.

```json
{
  "fondi_rischi_in": "consolidate",
  "A5_in_valore_produzione": true,
  "crediti_soci": "rettifica_pn",
  "roe_base": "finale",
  "roi_base": "totale",
  "iva": 0.22,
  "tolleranza": 2
}
```

- `fondi_rischi_in`: `consolidate` | `correnti`
- `A5_in_valore_produzione`: con `false`, A5 entra solo sotto l'EBITDA (gestione accessoria)
- `crediti_soci`: `rettifica_pn` | `liquidita_differite`
- `roe_base`: `finale` | `media` (media fra PN iniziale e finale). La media si fa solo con
  l'esercizio immediatamente precedente; dove manca, il ROE resta sul PN finale e il foglio
  «Note» lo dice
- `roi_base`: `totale` (capitale investito) | `operativo` (senza immobilizzazioni
  finanziarie, attività finanziarie e liquidità)
- `iva`: aliquota per i giorni clienti e fornitori
- `tolleranza`: euro di scarto ammessi nelle quadrature (arrotondamenti all'unità)
