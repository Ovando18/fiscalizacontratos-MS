# 🏗️ FiscalizaObras-MS

Painel de inteligência e fiscalização para consulta de **contratos públicos de obras e serviços de Engenharia, Agronomia e Geociências** celebrados pelos **79 municípios de Mato Grosso do Sul**.

O painel busca os contratos do exercício na **API oficial do PNCP** (Portal Nacional de Contratações Públicas — Lei 14.133/2021) e nos **Portais da Transparência municipais** (API de Dados Abertos Fiorilli, sem duplicar registros), filtra o que é técnico, localiza os documentos (**Contrato, Ordem de Serviço e Empenho**), aponta indícios para fiscalização (ART/RRT, licenças, certificações) e exporta tudo para uma planilha `.xlsx`.

---

## ✨ Funcionalidades

| Recurso | Descrição |
|---|---|
| **Bloco A — Fiscais Fixos** | Campo Grande, Dourados, Paranaíba e Três Lagoas, com pesquisa individual e separada |
| **Bloco B — Regiões 1 a 18** | Seletor de região com a opção "TODOS OS MUNICÍPIOS DA REGIÃO" (padrão) ou municípios individuais |
| **Filtros** | Exercício (padrão: ano atual), área de fiscalização, faixa de valor, situação e busca textual (objeto, empresa ou CNPJ) |
| **KPIs** | Total de contratos, valor global, total empenhado e municípios com obras ativas |
| **Tabela interativa** | Links clicáveis para Contrato, OS e Empenho (`st.column_config.LinkColumn`) |
| **Inspetor de contrato** | Cartão técnico completo, botões de abertura dos 3 documentos e indícios para fiscalização |
| **Exportação Excel** | Abas Contratos, Resumo por Município, Resumo por Área e Parâmetros, com `=HYPERLINK`, formato contábil R$ e totais |

---

## 🗂️ Estrutura

```
fiscalizacontratos-MS/
├── app.py                          # Interface Streamlit
├── config/
│   └── regioes_ms.py               # Fiscais fixos, 18 regiões, códigos IBGE e Portais da Transparência (79)
├── scrapers/
│   └── coletor_contratos.py        # Coleta PNCP + API Fiorilli (paralelas) e fusão sem duplicidade
├── utils/
│   ├── classificador_tecnico.py    # Classificação por categoria PNCP, CNAE e palavras-chave + indícios de ART
│   └── exportador_excel.py         # Planilha .xlsx estilizada (openpyxl)
├── scripts/
│   └── verificar_portais.py        # Testa os portais (API Fiorilli e páginas dos demais)
├── tests/
│   └── test_basico.py              # Testes offline (pytest)
├── .streamlit/config.toml          # Tema institucional MS
├── requirements.txt
└── .gitignore
```

---

## ⚙️ Como os dados são obtidos

1. **Descoberta dos órgãos municipais** — para cada município, consulta `contratacoes/publicacao` do PNCP filtrando `uf=MS` e `codigoMunicipioIbge`, e guarda os CNPJs da esfera municipal (Prefeitura, Câmara, Fundos, Fundações, Institutos de Previdência).
2. **Contratos do exercício** — consulta `/v1/contratos` por CNPJ, com paginação paralela.
3. **Classificação técnica** — categoria do processo no PNCP ("Obras", "Serviços de Engenharia"), palavras-chave do objeto e, se você ativar a opção, o CNAE da contratada (BrasilAPI). Compras de material e locações recebem penalidade para evitar falsos positivos.
4. **Remoção de duplicidades** — publicações repetidas do mesmo contrato são descartadas, para não inflar os totais.
5. **Documentos e termos** — busca os anexos do contrato (Contrato, OS, Empenho), os termos aditivos (prorrogação de vigência, acréscimos, suspensão) e a modalidade da licitação.
6. **Empenhos (PNCP)** — registros do tipo "Empenho" publicados no PNCP para a mesma compra e o mesmo fornecedor são vinculados ao contrato.
7. **Portais da Transparência municipais** — consultados em paralelo ao PNCP (veja abaixo) e fundidos **sem duplicar**.

**Regra de resiliência dos anexos:** quando um documento não é encontrado, o link abre a **página do contrato no PNCP** e o status mostra:
- `Documento localizado` — link direto para o arquivo;
- `Disponível na página do contrato` — há anexos publicados, mas nenhum identificado como esse documento;
- `Não publicado no portal` — o órgão não publicou anexos;
- `Disponível no Portal da Transparência` — o link abre o portal do município, onde estão o empenho e os demais documentos.

> ⏱️ A API do PNCP é lenta (até 40 s por página de 500 contratos) e às vezes derruba conexões. O coletor repete automaticamente as requisições que falham e guarda o resultado em cache por 6 horas. Uma região leva de 1 a 3 minutos na primeira consulta. Campo Grande sozinho pode levar mais.

### Portais da Transparência municipais (79 municípios)

Os endereços dos portais dos **79 municípios** vêm da planilha fornecida pela fiscalização e estão em `PORTAIS_TRANSPARENCIA` (`config/regioes_ms.py`). O sistema de cada portal foi identificado pela URL:

| Sistema | Municípios | Uso no painel |
|---|---|---|
| **Fiorilli SCPI** | 39 | **Integrado** via API pública de Dados Abertos: contratos, **valor empenhado, liquidado e saldo a empenhar** |
| Betha | 14 | Link oficial do portal (botão no Inspetor e nos documentos sem anexo) |
| Quality Sistemas | 10 | Link oficial do portal |
| Megasoft / CR2 | 4 | Link oficial do portal |
| Outros (portais próprios) | 12 | Link oficial do portal |

Para os portais Fiorilli, o painel usa o endpoint documentado em `<portal>/versaoJson/DadosAbertos/`:

```
GET <portal>/VersaoJson/LicitacoesEContratos/?ConectarExercicio=2026&Listagem=Contratos&Ano=2026&Empresa=1&MostraDadosConsolidado=True&ContratosApenasPublicados=False
```

#### Regras contra duplicidade

1. **Na base:** cada município aparece uma única vez em `PORTAIS_TRANSPARENCIA`, e o teste automatizado confere os 79.
2. **No PNCP:** o mesmo contrato publicado duas vezes, seja com numeração diferente ("000064/2026" e "64/2026") ou por dois órgãos (Prefeitura e Fundo Municipal), é contado uma só vez. A chave é município + nº + contratada + valor + data de assinatura.
3. **No portal:** contratos anulados são ignorados, e cada contrato é lido uma única vez (entidade + código + ano).
4. **Entre PNCP e portal:** um contrato do portal é considerado o **mesmo** do PNCP quando tem o mesmo município e o **mesmo CNPJ/CPF da contratada**, além de pelo menos um destes: mesmo nº do contrato, mesmo valor global (±1%) ou mesma data de assinatura.
   - Se casar, **complementa** o registro do PNCP (empenhado, liquidado, saldo) e não cria linha nova.
   - Se casar só com um contrato que já foi complementado, é duplicata e é **descartado**.
   - Se não casar, é um contrato **ausente do PNCP** e entra com a fonte "Portal Fiorilli (SCPI)".

Os avisos da coleta mostram, por município, quantos contratos foram complementados, incluídos ou descartados. Se um portal estiver fora do ar, o painel segue apenas com o PNCP e avisa.

Para checar os portais: `python scripts/verificar_portais.py`. Para Fiorilli, o script conta os contratos que a API devolve no exercício.

---

## 💻 Executar localmente

```bash
git clone https://github.com/Ovando18/fiscalizacontratos-MS.git
```

```bash
cd fiscalizacontratos-MS
```

```bash
python -m venv .venv && source .venv/bin/activate
```

(No Windows: `.venv\Scripts\activate`)

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Testes (opcional):

```bash
pip install pytest && python -m pytest -q tests
```

---

## 🚀 Publicar no GitHub e no Streamlit Community Cloud

### 1. Criar o repositório no GitHub
1. Acesse https://github.com/new
2. Em **Repository name**, digite `fiscalizacontratos-MS`
3. Escolha **Public** (o plano gratuito do Streamlit Cloud precisa de repositório público ou de acesso autorizado a repositórios privados)
4. **Não** marque "Add a README", ".gitignore" nem "license" (o projeto já tem esses arquivos)
5. Clique em **Create repository**

### 2. Enviar o código
Na pasta do projeto (repositório oficial: https://github.com/Ovando18/fiscalizacontratos-MS):

```bash
git remote add origin https://github.com/Ovando18/fiscalizacontratos-MS.git
```

```bash
git push -u origin main
```

Alternativa com GitHub CLI (cria o repositório e envia em um passo):

```bash
gh repo create fiscalizacontratos-MS --public --source=. --remote=origin --push
```

### 3. Publicar no Streamlit Community Cloud
1. Acesse https://share.streamlit.io e entre com sua conta GitHub
2. Clique em **Create app**, depois em **Deploy a public app from GitHub**
3. Preencha:
   - **Repository:** `Ovando18/fiscalizacontratos-MS`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** escolha um subdomínio (ex.: `fiscalizaobras-ms`)
4. Em **Advanced settings**, selecione **Python 3.12** (ou mais recente)
5. Clique em **Deploy**. A instalação das dependências leva de 2 a 4 minutos.

Cada `git push` na branch `main` atualiza o app automaticamente.

---

## 🎨 Identidade visual

| Cor | Hex | Uso |
|---|---|---|
| Azul Institucional MS | `#004B87` | Cabeçalho, botões primários, títulos |
| Verde Pantanal | `#007A33` | Status ativo, destaques positivos |
| Amarelo Ouro | `#F2A900` | Filetes de destaque e alertas |
| Fundo | `#F5F7FA` | Fundo da aplicação |
| Cartões | `#FFFFFF` / borda `#DCE3EC` | Cartões e painéis |

---

## ⚠️ Limitações conhecidas

- **Cobertura:** o painel mostra o que está no PNCP e, nos 39 municípios Fiorilli, também o que está no portal. Nos demais 40 municípios (Betha, Quality, Megasoft, CR2 e portais próprios), a fonte de dados é só o PNCP, e o portal aparece como link.
- **Empenhos:** o valor empenhado é preenchido nos municípios Fiorilli. Nos demais, costuma ficar `n/d`, porque poucos publicam empenhos no PNCP.
- **Ordem de Serviço:** raramente é publicada como anexo separado. O link leva à página do contrato (PNCP) ou ao portal do município.
- **Portais Fiorilli fora do ar:** vários usam IP e porta próprios (ex.: `:8079`, `:5656`) e podem ficar instáveis. Nesse caso aparece um aviso e o painel usa só o PNCP.
- **Câmaras:** os links de Nova Andradina e Novo Horizonte do Sul na planilha apontam para portais da **Câmara Municipal**, não da Prefeitura.
- **Classificação técnica:** é automática. Confira o critério ("Critério da classificação") no Inspetor antes de concluir.

---

## 📄 Fontes de dados

- PNCP — API de Consulta: https://pncp.gov.br/api/consulta/swagger-ui/index.html
- PNCP — API de Integração (arquivos e termos): https://pncp.gov.br/api/pncp/swagger-ui/index.html
- BrasilAPI — CNPJ (opcional): https://brasilapi.com.br/docs#tag/CNPJ
- Fiorilli SCPI — Dados Abertos (por município): `<portal>/versaoJson/DadosAbertos/`
