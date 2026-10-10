# Pulso Social CRM v3 — edição exclusiva de CRM

Aplicativo local para uma agência de social media administrar sua carteira de leads, clientes, propostas, contratos e agenda comercial.

**Esta edição não tem campanhas, envio automático, integração com WhatsApp/Instagram, webhooks de mensagens ou trabalhador de disparo.** O campo de telefone é apenas uma informação de contato. O campo de Instagram permite registrar o @perfil do lead.

## Funções disponíveis

- **Visão geral:** leads e clientes, propostas aceitas e recusadas, planos fechados, receita mensal contratada e retornos pendentes.
- **Contatos e clientes:** cadastro, atualização, ficha completa, anotações e exclusão com proteção para históricos de contratos.
- **Funil de vendas:** novo lead, contatado, reunião, proposta, cliente, perdido.
- **Propostas:** pendente, aceitou ou recusou.
- **Planos fechados:** um cliente pode ter vários planos, cada um com nome, valor mensal, data, status (ativo, concluído, cancelado) e observações.
- **Retornos e tarefas:** data de próximo acompanhamento, vencidos e futuros.
- **Relatórios:** funil, status das propostas, receita mensal prevista, exportação CSV.
- **Importação e exportação CSV** de contatos e dados comerciais.
- **Acesso protegido:** cadastro inicial de administrador, login, cookie HttpOnly e proteção CSRF para alterações.
- **Banco de dados SQLite local** com persistência; inicia vazio.

### Antes de instalar

1. Instale **Python 3.11+** em https://www.python.org/downloads/ (no Windows selecione "Add Python to PATH" se disponível).
2. Extraia a pasta deste ZIP para um local estável como `C:\PulsoCRM`. Não execute de dentro do ZIP.
3. Na pasta do aplicativo, faça uma cópia de `.env.example`, renomeie-a para `.env` e substitua `APP_SETUP_KEY` por uma chave longa e particular.
4. Execute `iniciar-windows.bat` (Windows) ou `sh iniciar-linux-mac.sh` (Linux/macOS).
5. Abra `http://127.0.0.1:8000` em seu navegador.
6. Na primeira abertura, informe seu e-mail, uma senha de pelo menos 12 caracteres e a **mesma chave configurada em `.env`**.
7. Faça login e comece a cadastrar seus contatos.

Para visualizar arquivos que começam com ponto, habilite a exibição de arquivos ocultos no explorador ou use o bloco de notas em "Todos os arquivos". O instalador Windows cria uma cópia de `.env.example` automaticamente, se `.env` não existir, porém **é obrigatório personalizar `APP_SETUP_KEY`**.

O aplicativo precisa de conexão com a internet na primeira execução para instalar dependências Python. Depois os dados ficam no computador (não se sincronizam automaticamente entre máquinas).

## Base de dados e cópias de segurança

O arquivo com seus dados é `data/pulso.db`. Este ZIP contém um banco **com as tabelas criadas, porém nenhum administrador, contato, cliente, proposta, plano ou interação cadastrados**.

Faça backup regularmente: feche o aplicativo e copie **o arquivo inteiro `data/pulso.db`** para um local seguro, guardando também seu `.env` com cuidado (não compartilhe sua senha ou chave). Evite editar ou sobrescrever um banco de dados aberto.

## Como atualizar a partir do Pulso Social CRM v2

Leia `ATUALIZAR-SEM-PERDER-DADOS.md`. Em resumo: encerre a versão anterior, guarde a pasta como backup e use o **arquivo de banco anterior** junto com o novo `app.py` e os novos arquivos de interface. A migração do esquema mantém contatos e planos. As antigas tabelas de mensagens que eventualmente existam no banco **não serão usadas nem expostas** pela edição CRM. A aplicação não apaga essas tabelas, para evitar perda acidental de histórico.

## Modelo CSV

Use `modelo-contatos.csv` ou baixe o modelo no aplicativo. Principais colunas: `nome`, `telefone`, `email`, `empresa`, `origem`, `etapa`, `proposta`, `retorno`, `etiquetas`, `observacoes`.

Telefones, quando preenchidos, precisam de DDI, por exemplo `+5511999999999`. Para um lead, basta informar pelo menos telefone, e-mail ou identificador de Instagram. Para importar o perfil, inclua `instagram_id`.

## Segurança e implantação

Este projeto é para uso local por **uma empresa/administrador**. **Não publique a porta 8000 diretamente na internet.** Para acesso remoto por vários colaboradores, serão necessários HTTPS, autenticação com permissões por usuário, backup automático e uma estratégia de hospedagem segura. O projeto não tem integração nativa com aplicativos externos.

### Testes

Se instalar `pytest` e `httpx` no ambiente de desenvolvimento, execute:

```bash
python -m pytest -q tests
```

Os testes usam bancos temporários e **não precisam inserir dados no seu banco de produção**.
