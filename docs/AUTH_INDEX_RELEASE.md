# Publicação da autenticação por WhatsApp

Esta branch exige os índices únicos parciais definidos em `backend/auth_index_contract.py`. Não publique o backend novo antes de migrar o Atlas. Não reinicie o backend antigo depois da migração: seu startup tenta criar o índice legado `email_1`.

1. Planeje uma janela de manutenção e interrompa todas as gravações, incluindo processos auxiliares. Confirme o bloqueio para conexões existentes; a lease do utilitário coordena apenas outras migrações, não a aplicação.
2. Confirme as opções reais dos índices, duplicatas e arrays com `python backend/migrate_auth_indexes.py`, usando `MONGO_URL` e `DB_NAME` configurados em ambiente seguro. Sem `--apply`, a ferramenta somente consulta.
3. Preserve um backup recuperável e teste a restauração. O arquivo `--backup-file` do utilitário registra apenas metadados de índices e não substitui um backup de dados.
4. Sob manutenção e após autorização explícita, execute `python backend/migrate_auth_indexes.py --apply --confirm MIGRATE_AUTH_IDENTIFIER_INDEXES --backup-file <arquivo-novo-em-local-seguro>`. O utilitário verifica conflitos, usa lock e tenta recuperar os índices anteriores em caso de erro.
5. Execute novamente a verificação somente leitura e confirme `contract_errors` vazio e os índices `tenant_users_email_unique` e `tenant_users_confirmed_phone_unique`.
6. Publique o backend novo e, após validação, o frontend; restaure o tráfego somente quando ambos estiverem saudáveis. Preserve as variáveis de produção e confirme login, recuperação e primeiro acesso com contas autorizadas.

Se a migração falhar, mantenha as gravações bloqueadas. Verifique os índices existentes e a mensagem de erro; o rollback automático pode também falhar. Compare com os metadados salvos e restaure o índice legado por um operador autorizado antes de reativar o backend antigo. Se já houver contas sem e-mail, verifique previamente a compatibilidade do índice legado: sua recriação pode falhar. Nunca apague documentos para forçar o rollback.
