# Atualizar do Pulso Social CRM v2 para Pulso Social CRM v3

Siga estas etapas se você já cadastrou contatos, planos ou criou um login na versão anterior.

1. **Encerre completamente** o aplicativo anterior (feche a janela do terminal que executa `iniciar-windows.bat`).
2. Copie **a pasta antiga inteira** como backup, com atenção aos arquivos `.env` e `data/pulso.db`. Guarde em lugar seguro.
3. Extraia o novo ZIP em **outra pasta**, por exemplo `C:\PulsoCRM-v3`.
4. Copie **apenas** o arquivo `data/pulso.db` da pasta anterior para `data/pulso.db` da nova versão, **substituindo o banco vazio que vem no ZIP**. Não copie pastas de campanhas ou o código Python antigo.
5. Copie seu arquivo `.env` anterior ou crie um novo `.env` a partir de `.env.example`. Preserve `APP_SETUP_KEY` se desejar. Remova deste arquivo os antigos tokens e segredos de APIs de mensagens que não serão mais utilizados.
6. Inicie o novo aplicativo com `iniciar-windows.bat`, acesse `http://127.0.0.1:8000` e entre com seu **mesmo e-mail e senha**, se o banco antigo já possuía administrador.
7. Confira se seus contatos, fichas, planos, valores e históricos aparecem. Faça novo backup depois de confirmar.

**ATENÇÃO:** Não substitua seu banco antigo pelo banco vazio desta versão caso queira manter os dados anteriores.

### O que acontece com registros de disparos antigos?

Se o banco anterior tinha tabelas de campanhas/mensagens, o novo servidor **não possui endpoints, fila ou worker para executar disparos**. Essas tabelas antigas podem permanecer **inativas** no arquivo SQLite para não apagar histórico sem sua decisão. Elas não aparecem no novo painel. Se você desejar eliminá-las definitivamente, primeiro faça backup e consulte um profissional para uma exclusão segura conforme sua política de retenção de dados.

### Se mudar de computador

Copie somente os arquivos de configuração, seu banco e o novo aplicativo. Evite manter duas instalações abertas escrevendo no mesmo SQLite ao mesmo tempo.
