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

No terminal, dentro da pasta do projeto:

```bash
python -m venv .venv
```

No Windows (PowerShell, ):

Instale as dependências:

```bash
pip install playwright pandas openpyxl
python -m playwright install
```

## Como executar

Com o ambiente virtual ativo, rode:

```bash
python app.py
```

## Tutorial de uso (simples)

1. O script abre o Chrome automaticamente.
2. Se pedir login, faça login no LinkedIn na janela aberta.
3. Vá para o feed de posts da empresa.
4. Abra a janela de **reações** de um post.
5. Volte ao terminal e aperte **Enter** para coletar.
6. O script pergunta se quer coletar os **comentários** daquele post.
   - Aperte **Enter** para coletar comentários.
   - Digite `n` para pular comentários.
7. Repita para quantos posts quiser.
8. Quando terminar, digite `sair` no terminal.

Pronto: os arquivos CSV e Excel serão gerados na pasta do projeto.

## Dicas rápidas

- Se o script não encontrar a janela de reações, abra novamente essa janela no LinkedIn e tente de novo.
- Na primeira execução, pode demorar um pouco por causa de instalação/configuração do navegador do Playwright.
- O arquivo `linkedin_state.json` salva sua sessão para evitar login em toda execução.

## Problemas comuns

- **`ModuleNotFoundError`**: ative o ambiente virtual e rode `pip install playwright pandas openpyxl`.
- **Erro relacionado ao Playwright/navegador**: rode `python -m playwright install`.
- **Excel não abre**: feche o arquivo `.xlsx` se ele já estiver aberto durante nova geração.
