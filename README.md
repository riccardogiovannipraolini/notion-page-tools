# notion-page-tools

Plugin per [Hermes Agent](https://github.com/NousResearch/hermes-agent) che permette a un agente AI di spostare pagine Notion nel cestino e di ripristinarle, senza mai poterle cancellare in modo definitivo.

## Perché esiste

Un agente che lavora su un workspace personale prima o poi deve eliminare qualcosa. Il rischio non è l'eliminazione in sé, ma l'eliminazione sbagliata: la pagina sbagliata, più pagine in un colpo solo, oppure un'azione confermata su un'anteprima ormai superata. Il plugin rende l'operazione reversibile e chiede la conferma esplicita dell'utente, una pagina alla volta.

## Come funziona

Ogni operazione richiede due chiamate.

1. **Anteprima.** L'agente passa l'ID o l'URL della pagina. Il plugin la legge e restituisce titolo, posizione e stato, insieme a un token di conferma monouso valido dieci minuti.
2. **Esecuzione.** Solo dopo la conferma dell'utente, l'agente richiama il tool con quel token. Il plugin rilegge la pagina subito prima di scrivere e rifiuta l'operazione se il titolo è cambiato. Poi esegue e controlla con una lettura finale che lo stato sia quello richiesto.

Garanzie:

- una sola pagina per chiamata;
- nessuna cancellazione definitiva: il plugin usa solo il cestino di Notion (`in_trash`);
- il token vale per una sola pagina e una sola azione, e si consuma all'uso;
- la credenziale non compare mai nell'output.

## Tool

- `notion_trash_page`: sposta una pagina nel cestino.
- `notion_restore_page`: la ripristina dal cestino.

## Installazione

1. Copia la cartella in `~/.hermes/plugins/notion-page-tools` e abilita il plugin in Hermes.
2. Crea un Personal Access Token Notion su <https://www.notion.so/developers/tokens> con la capability *Notion API*.
3. Salvalo come `NOTION_API_KEY` in `~/.hermes/.env`. In alternativa, `python3 scripts/set_credential.py` lo chiede senza mostrarlo a schermo, lo verifica con Notion e lo scrive solo se è valido, conservando un backup del file.
4. Verifica in sola lettura con `python3 scripts/verify_credential.py`.

## Nota sulla credenziale

Il token OAuth del server MCP di Notion non è accettato dall'API REST pubblica usata per il cestino, che risponde `401`. Serve un Personal Access Token. Un PAT agisce con i permessi di chi lo crea, quindi le pagine non devono essere condivise con un'integrazione. I PAT scadono (di default dopo un anno), e anche un token scaduto restituisce `401`.

`GET /v1/users/me` restituisce `"type": "bot"` sia per un PAT sia per un'integrazione interna, quindi quel campo non basta a distinguerli. Servono invece:

- `bot.owner.type`: `"user"` indica un PAT, `"workspace"` un'integrazione interna;
- `GET /v1/users`: un PAT riceve `403 Personal access tokens cannot list users`, un'integrazione interna riceve l'elenco.

Il plugin usa la versione `2026-03-11` dell'API di Notion.

## Test

```bash
python3 tests/test_tools.py
```

Sei test offline, con la rete simulata e nessuna scrittura su Notion. Coprono l'anteprima obbligatoria, la verifica dopo la scrittura, il token monouso e non trasferibile ad altre pagine, gli ID non validi e la credenziale mancante segnalata senza esporre segreti.
