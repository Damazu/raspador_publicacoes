# Raspador de Engajamento no LinkedIn

Este projeto coleta **reações** e **comentários** de posts de uma página no LinkedIn e gera um ranking de engajamento por pessoa.

## O que o script gera

Ao finalizar a coleta, o script cria estes arquivos:

- `ranking_engajamento_com_urls.csv`
- `ranking_engajamento.xlsx`

Cada linha representa uma pessoa com:

- quantidade de reações
- quantidade de comentários
- engajamento total
- URLs dos posts onde ela interagiu

## Requisitos

- Python 3.10+ instalado
- Google Chrome instalado
- Conta do LinkedIn com acesso aos posts da página

## Instalação (passo a passo)

No terminal, dentro da pasta do projeto: (pesquise no windows um dos 3: PowerShell, CMD, Terminal )

```bash
python -m venv .venv
```

e ache a pasta do projeto (ex: se a pasta do projeto estiver na pasta downloads: (cd downloads/scrap)

### Instale as dependências:

intale o Pyhton (pode ser na store do windows ou no google)

```bash
pip install playwright pandas openpyxl
python -m playwright install
```

## Como executar

Com o ambiente virtual ativo, rode (PowerShell, CMD, Terminal):

```bash
python app.py
```

## Estrutura do projeto

- `app.py`: ponto de entrada da aplicacao.
- `ui/app_gui.py`: toda a interface grafica (telas e botoes).
- `scraper/linkedin.py`: toda a logica de scraping do LinkedIn.

## Interface grafica

Agora o projeto abre uma tela com os aplicativos.

- **LinkedIn**: disponivel
- **Instagram**: em breve
- **Facebook**: em breve

## Tutorial de uso (simples)

1. Abra o app com `python app.py`.
2. Na tela de aplicativos, clique em **LinkedIn**.
3. Clique em **Comecar** para abrir o Chrome.
4. Se pedir login, faça login no LinkedIn no Chrome.
5. Quando o feed estiver pronto, clique em **Confirmar** na interface.
6. Abra a janela de **reacoes** de um post no LinkedIn.
7. Clique em **Confirmar** para coletar esse post.
8. Repita para quantos posts quiser.
9. Quando terminar, clique em **Sair** na interface.

Pronto: os arquivos CSV e Excel serao gerados na pasta do projeto.

## Dicas rápidas

- Se o script não encontrar a janela de reações, abra novamente essa janela no LinkedIn e tente de novo.
- Na primeira execução, pode demorar um pouco por causa de instalação/configuração do navegador do Playwright.
- O arquivo `linkedin_state.json` salva sua sessão para evitar login em toda execução.

## Problemas comuns

- `**ModuleNotFoundError`**: ative o ambiente virtual e rode `pip install playwright pandas openpyxl`.
- **Erro relacionado ao Playwright/navegador**: rode `python -m playwright install`.
- **Excel não abre**: feche o arquivo `.xlsx` se ele já estiver aberto durante nova geração.

