# Skill per studi professionali

Skill per [Claude Code](https://claude.com/claude-code) pensate per gli studi professionali
italiani. Ogni cartella è una skill completa, pronta da copiare nella cartella delle skill.

Di ztax.it - https://www.ztax.it. Licenza MIT.

## Skill

| Skill | Che cosa fa | Pacchetto |
| --- | --- | --- |
| [scarica-norma](scarica-norma/) | Scarica da Normattiva il testo ufficiale di una norma italiana, alla vigenza di oggi o a una data passata, e lo salva in Markdown con un titolo per articolo. | [scarica-norma.zip](scarica-norma.zip) |

## Come si installa

Scarica lo zip della skill e scompattalo nella cartella delle skill, così che nasca una
cartella col nome della skill e dentro il suo `SKILL.md`:

- macOS e Linux: `~/.claude/skills/`
- Windows: `%USERPROFILE%\.claude\skills\`

Poi basta chiedere a Claude quello che la skill sa fare: la riconosce da sé.

Gli script usano solo la libreria standard di Python 3: non c'è niente da installare.

## Avvertenza

Le skill aiutano a lavorare, non sostituiscono il controllo professionale: un testo che
finisce in un atto si verifica sulla fonte ufficiale, e la responsabilità resta a chi firma.
