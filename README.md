# Skill per studi professionali

Skill per le AI che lavorano sul tuo computer, pensate per gli studi professionali italiani.
Sono nel formato aperto delle skill: le abbiamo provate con
[Claude Code](https://claude.com/claude-code) e con [Codex](https://github.com/openai/codex).
Ogni cartella è una skill completa, pronta da copiare nella cartella delle skill.

Di ztax.it - https://ztax.it. Licenza MIT.

## Skill

| Skill | Che cosa fa | Pacchetto |
| --- | --- | --- |
| [scarica-norma](scarica-norma/) | Scarica da Normattiva il testo ufficiale di una norma italiana, alla vigenza di oggi o a una data passata, e lo salva in Markdown con un titolo per articolo. | [scarica-norma.zip](scarica-norma.zip) |
| [analisi-bilancio-cee](analisi-bilancio-cee/) | Riclassifica uno o più bilanci CEE italiani (XBRL depositato o PDF nativo; ordinario, abbreviato, micro) e calcola su più anni gli indici di liquidità, solidità e redditività e la PFN, con Excel, JSON e commento. I conti li fanno due script, non il modello. | [analisi-bilancio-cee.zip](analisi-bilancio-cee.zip) |
| [pdfa-converter](pdfa-converter/) | Converte documenti Word, OpenDocument, RTF e PDF, scansioni comprese, in PDF/A-1a o PDF/A-1b per il deposito telematico, e consegna solo file validati da veraPDF. Non converte il PDF firmato digitalmente e ferma l'esito con pagine annerite o mancanti. Tutto in locale. | [pdfa-converter.zip](pdfa-converter.zip) |

## Come si installa

Scarica lo zip della skill e scompattalo nella cartella delle skill del tuo assistente, così
che nasca una cartella col nome della skill e dentro il suo `SKILL.md`:

- **Claude Code:** `~/.claude/skills/` (su Windows `%USERPROFILE%\.claude\skills\`)
- **Codex:** `.agents/skills/` nella cartella del progetto

Poi basta chiedere all'assistente quello che la skill sa fare, con parole tue: la riconosce da
sé.

Gli script di scarica-norma e di analisi-bilancio-cee usano solo la libreria standard di
Python 3 (per analisi-bilancio-cee il 3.9 o successivo): non c'è niente da installare.
pdfa-converter invece si appoggia a programmi gratuiti - LibreOffice, Ghostscript, veraPDF con
Java e la libreria Python pikepdf - e al primo uso dice quali mancano e come si installano. Le
skill sono provate su macOS; sono scritte anche per Windows, ma lì non sono state provate.

## Avvertenza

Le skill aiutano a lavorare, non sostituiscono il controllo professionale: l'output va sempre
verificato.
