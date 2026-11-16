# 🏗️ FiscalizaObras-MS

Painel de inteligência e fiscalização para consulta de **contratos públicos de obras e serviços de Engenharia, Agronomia e Geociências** celebrados pelos **79 municípios de Mato Grosso do Sul**.

O painel busca os contratos do exercício na **API oficial do PNCP** (Portal Nacional de Contratações Públicas — Lei 14.133/2021), filtra o que é técnico, localiza os documentos (**Contrato, Ordem de Serviço e Empenho**), aponta indícios para fiscalização (ART/RRT, licenças, certificações) e exporta tudo para uma planilha `.xlsx`.

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
│   └── regioes_ms.py               # Fiscais fixos, 18 regiões, códigos IBGE, URLs e sistemas dos portais
├── scrapers/
│   └── coletor_contratos.py        # Coleta PNCP (paralela) + conectores Betha/Fiorilli/Elotech/IPM/GovBR/Coplan
├── utils/
│   ├── classificador_tecnico.py    # Classificação por categoria PNCP, CNAE e palavras-chave + indícios de ART
│   └── exportador_excel.py         # Planilha .xlsx estilizada (openpyxl)
├── scripts/
│   └── verificar_portais.py        # Testa quais URLs de portais municipais respondem
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
6. **Empenhos** — registros do tipo "Empenho" publicados no PNCP para a mesma compra e o mesmo fornecedor são vinculados ao contrato.

**Regra de resiliência dos anexos:** quando um documento não é encontrado, o link abre a **página do contrato no PNCP** e o status mostra:
- `Documento localizado` — link direto para o arquivo;
- `Disponível na página do contrato` — há anexos publicados, mas nenhum identificado como esse documento;
- `Não publicado no portal` — o órgão não publicou anexos.

> ⏱️ A API do PNCP é lenta (até 40 s por página de 500 contratos) e às vezes derruba conexões. O coletor repete automaticamente as requisições que falham e guarda o resultado em cache por 6 horas. Uma região leva de 1 a 3 minutos na primeira consulta. Campo Grande sozinho pode levar mais.

### Conectores municipais (Betha, Fiorilli, Elotech, IPM, GovBR, Coplan)

Os portais municipais mudam de endereço e de fornecedor com frequência, e cada versão tem um formato diferente. Por isso:

- Por padrão **todos os municípios são consultados apenas pelo PNCP**, e o link "Site oficial" aponta para `https://www.<municipio>.ms.gov.br/`.
- Para ativar o conector de um município, preencha `PORTAIS_CONFIRMADOS` em `config/regioes_ms.py`:

```python
PORTAIS_CONFIRMADOS = {
    "NOME DO MUNICÍPIO": {
        "url_portal": "https://<endereco-real-do-portal>/",
        "sistema": "FIORILLI",            # BETHA | FIORILLI | ELOTECH | IPM | GOVBR | COPLAN
        "cnpj_prefeitura": "00000000000000",
    },
}
```

- Rode `python scripts/verificar_portais.py` para ver quais URLs respondem.
- Os conectores completam o **valor empenhado** e os links quando conseguem ler o portal. Se o portal falhar, o painel continua apenas com o PNCP.

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

- **Cobertura depende do PNCP:** o painel só mostra o que o município publicou no PNCP. Municípios sem publicação aparecem em um aviso na tela.
- **Empenhos:** poucos municípios publicam notas de empenho no PNCP. Sem conector municipal configurado, "Valor Empenhado" costuma ficar `n/d`.
- **Ordem de Serviço:** raramente é publicada como anexo separado. Na maioria dos casos o status será "Disponível na página do contrato".
- **Classificação técnica:** é automática. Confira o critério ("Critério da classificação") no Inspetor antes de concluir.
- **Conectores municipais:** foram escritos de forma genérica e **não foram validados contra cada portal real**. Valide cada município ao configurá-lo em `PORTAIS_CONFIRMADOS`.

---

## 📄 Fontes de dados

- PNCP — API de Consulta: https://pncp.gov.br/api/consulta/swagger-ui/index.html
- PNCP — API de Integração (arquivos e termos): https://pncp.gov.br/api/pncp/swagger-ui/index.html
- BrasilAPI — CNPJ (opcional): https://brasilapi.com.br/docs#tag/CNPJ
