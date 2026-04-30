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

Ative o ambiente virtual:

- PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

- CMD:

```cmd
.venv\Scripts\activate.bat
```

Instale as dependências:

```bash
pip install playwright pandas openpyxl
python -m playwright install
```

## Como executar

Com o ambiente virtual ativo, rode (PowerShell, CMD, Terminal):

```bash
python app.py
```

## Gerar executavel (.exe)

Se quiser distribuir o app sem exigir que a pessoa rode `python app.py`, gere um executavel com PyInstaller.

1. Com o ambiente virtual ativo, instale o empacotador:

```bash
pip install pyinstaller
```

2. Gere o build:

```bash
python -m PyInstaller --noconfirm --windowed --name raspador_linkedin --collect-all playwright app.py
```

3. Arquivo gerado:

- `dist/raspador_linkedin/raspador_linkedin.exe`

Importante: esse build e no formato de pasta (`onedir`). Para funcionar, distribua a pasta inteira `dist/raspador_linkedin` (incluindo `_internal`).

## Criar instalador do Windows (Inno Setup)

Para gerar um instalador `.exe`:

1. Instale o [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Crie um arquivo `installer.iss` na raiz do projeto com o conteudo abaixo
3. Abra o arquivo no Inno Setup e clique em **Compile**

Exemplo de `installer.iss`:

```iss
[Setup]
AppId={{9E19E5FE-2F26-4A64-A88D-3E3E3FA6E001}
AppName=Raspador LinkedIn
AppVersion=1.0.0
AppPublisher=David Dias Pinto
DefaultDirName={autopf}\Raspador LinkedIn
DefaultGroupName=Raspador LinkedIn
OutputDir=.\installer_output
OutputBaseFilename=RaspadorLinkedIn-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "portuguesebrazil"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "dist\raspador_linkedin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Raspador LinkedIn"; Filename: "{app}\raspador_linkedin.exe"
Name: "{autodesktop}\Raspador LinkedIn"; Filename: "{app}\raspador_linkedin.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\raspador_linkedin.exe"; Description: "Abrir Raspador LinkedIn"; Flags: nowait postinstall skipifsilent
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
- Ao distribuir para outra maquina, valide se o antivirus/SmartScreen nao bloqueou o executavel.

## Problemas comuns

- `**ModuleNotFoundError`**: ative o ambiente virtual e rode `pip install playwright pandas openpyxl`.
- **Erro relacionado ao Playwright/navegador**: rode `python -m playwright install`.
- **Excel não abre**: feche o arquivo `.xlsx` se ele já estiver aberto durante nova geração.

