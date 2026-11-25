# Publicação da autenticação por WhatsApp

Esta branch exige os índices únicos parciais definidos em `backend/auth_index_contract.py`. Não publique o backend novo antes de migrar o Atlas. Não reinicie o backend antigo depois da migração: seu startup tenta criar o índice legado `email_1`.

1. Planeje uma janela de manutenção e interrompa todas as gravações, incluindo processos auxiliares. Confirme o bloqueio para conexões existentes; a lease do utilitário coordena apenas outras migrações, não a aplicação.
2. Confirme as opções reais dos índices, duplicatas e arrays com `python backend/migrate_auth_indexes.py`, usando `MONGO_URL` e `DB_NAME` configurados em ambiente seguro. Sem `--apply`, a ferramenta somente consulta.
3. Preserve um backup recuperável e teste a restauração. O arquivo `--backup-file` do utilitário registra apenas metadados de índices e não substitui um backup de dados.
4. Sob manutenção e após autorização explícita, execute `python backend/migrate_auth_indexes.py --apply --confirm MIGRATE_AUTH_IDENTIFIER_INDEXES --backup-file <arquivo-novo-em-local-seguro>`. O utilitário verifica conflitos, usa lock e tenta recuperar os índices anteriores em caso de erro.
5. Execute novamente a verificação somente leitura e confirme `contract_errors` vazio e os índices `tenant_users_email_unique` e `tenant_users_confirmed_phone_unique`.
6. Publique o backend novo e, após validação, o frontend; restaure o tráfego somente quando ambos estiverem saudáveis. Preserve as variáveis de produção e confirme login, recuperação e primeiro acesso com contas autorizadas.

Se a migração falhar, mantenha as gravações bloqueadas. Verifique os índices existentes e a mensagem de erro; o rollback automático pode também falhar. Compare com os metadados salvos e restaure o índice legado por um operador autorizado antes de reativar o backend antigo. Se já houver contas sem e-mail, verifique previamente a compatibilidade do índice legado: sua recriação pode falhar. Nunca apague documentos para forçar o rollback.

## Validação local em 25/11/2026

- Primeiro acesso de um proprietário sem e-mail e recuperação de senha pelo WhatsApp passaram com o gateway local. Os links foram exercitados no computador com um cliente TLS que confiou explicitamente no certificado local. A criação e a redefinição de senha, o login após cada etapa e o bloqueio da reutilização dos tokens foram verificados.
- O responsável pelos testes confirmou o recebimento das duas mensagens, sem duplicatas. Ambas apareceram normalmente no iPhone remetente e no WhatsApp Web. A entrega e a sincronização passaram nesta rodada. O sintoma “Aguardando mensagem” não foi reproduzido e a causa da ocorrência original permanece sem comprovação.
- Pendências específicas: abrir e exercitar os links no navegador com HTTPS confiável e validar a abertura dos links no celular. A verificação TLS pelo cliente local não substitui essas duas validações.
- Manter o PR #26 sem merge até a migração dos índices no Atlas e a reativação do SpeedTrail.

### Recorrência da falha de visualização no iPhone

Em 25/11/2026, dois cadastros locais pelo painel dispararam confirmações de WhatsApp. O operador relatou “Aguardando mensagem” no envio à própria conta e no envio seguinte a outra conta. No segundo caso, o destinatário recebeu a mensagem e o WhatsApp Web do remetente a exibiu normalmente.

| Hora de Brasília | Evento registrado na referência do envio |
| --- | --- |
| 00:48:08 | `submitted` PN e, em seguida, `server_ack` LID. O operador confirmou exibição nos dispositivos. |
| 06:29:36 | `submitted` PN e, em seguida, `server_ack` LID. O operador confirmou exibição nos dispositivos. |
| 18:12:50 | `submitted` PN para a primeira confirmação. |
| 18:15:44 | `submitted` PN para a segunda confirmação. |

Os dois pedidos de confirmação foram localizados no registro de idempotência. Cada pedido teve uma única submissão registrada menos de um segundo depois. Os eventos disponíveis para essas duas referências não incluem ACK, erro ou retry. Os eventos `retry_unavailable` da manhã pertencem a outra referência. A ausência de recibos nos registros do gateway não invalida o recebimento observado pelo destinatário.

O gateway registra em `whatsapp_submission` o propósito, se o destino é a própria conta quando identificável, a quantidade de cópias próprias preparadas por classe PN/LID e a presença do candidato base. `whatsapp_retry_scope` classifica, quando possível, a conta do participante que pediu a recuperação. As duas linhas usam a referência HMAC da mensagem já usada nos eventos de entrega. A lista de candidatos é observada antes da criptografia e não identifica um aparelho físico nem confirma que ele conseguiu abrir a mensagem.

A causa da falha intermitente permanece indeterminada. No próximo envio autorizado após ativar o diagnóstico, registre horário, destino próprio ou externo, recebimento e exibição no WhatsApp Web e no iPhone. Compare esses resultados com os eventos da mesma referência.
