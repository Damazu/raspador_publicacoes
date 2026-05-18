# Raspador de engajamento em redes sociais

Este projeto coleta **reações** e **comentários** de posts em **redes sociais** e gera um ranking de engajamento por pessoa.

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
- Conta na **rede social** em que for coletar, com acesso aos posts desejados

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

1. Gere o build:

```bash
python -m PyInstaller --noconfirm --windowed --name raspador_social_media --collect-all playwright --collect-all tksvg --add-data "ui/assets;ui/assets" app.py
```

1. Arquivo gerado:

- `dist/raspador_social_media/raspador_social_media.exe`

Importante: esse build e no formato de pasta (`onedir`). Para funcionar, distribua a pasta inteira `dist/raspador_social_media` (incluindo `_internal`).

## Criar instalador do Windows (Inno Setup)

Para gerar um instalador `.exe`:

1. Instale o [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Crie um arquivo `installer.iss` na raiz do projeto com o conteudo abaixo
3. Abra o arquivo no Inno Setup e clique em **Compile**

Exemplo de `installer.iss`:

```iss
[Setup]
AppId={{9E19E5FE-2F26-4A64-A88D-3E3E3FA6E001}
AppName=Raspador Social Media
AppVersion=1.0.0
AppPublisher=David Dias Pinto
DefaultDirName={autopf}\Raspador Social Media
DefaultGroupName=Raspador Social Media
OutputDir=.\installer_output
OutputBaseFilename=RaspadorSocialMedia-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "portuguesebrazil"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "dist\raspador_social_media\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Raspador Social Media"; Filename: "{app}\raspador_social_media.exe"
Name: "{autodesktop}\Raspador Social Media"; Filename: "{app}\raspador_social_media.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\raspador_social_media.exe"; Description: "Abrir Raspador Social Media"; Flags: nowait postinstall skipifsilent
```

## Estrutura do projeto

- `app.py`: ponto de entrada da aplicacao.
- `ui/app_gui.py`: toda a interface grafica (telas e botoes).
- `linkedin/linkedin.py`: logica de scraping para a integracao com uma rede social (LinkedIn).
- `instagram/instagram.py`: logica de scraping para a integracao com outra rede social (Instagram).

## Interface grafica

Agora o projeto abre uma tela com os aplicativos de **redes sociais**.

- **LinkedIn**: disponivel
- **Instagram**: em breve
- **Facebook**: em breve

## Tutorial de uso (simples)

1. Abra o app com `python app.py`.
2. Na tela de aplicativos, escolha a **rede social** (por exemplo, **LinkedIn**).
3. Clique em **Comecar** para abrir o Chrome.
4. Se pedir login, faça login na **rede escolhida** no Chrome.
5. Quando o feed estiver pronto, clique em **Confirmar** na interface.
6. Abra a janela de **reacoes** de um post na **mesma rede**.
7. Clique em **Confirmar** para coletar esse post.
8. Repita para quantos posts quiser.
9. Quando terminar, clique em **Sair** na interface.

Pronto: os arquivos CSV e Excel serao gerados na pasta do projeto.

## Dicas rápidas

- Se o script não encontrar a janela de reações, abra novamente essa janela na **rede em uso** e tente de novo.
- Na primeira execução, pode demorar um pouco por causa de instalação/configuração do navegador do Playwright.
- Arquivos como `linkedin_state.json` guardam a sessão da **rede correspondente** para evitar login em toda execução.
- Ao distribuir para outra maquina, valide se o antivirus/SmartScreen nao bloqueou o executavel.

## Problemas comuns

- `**ModuleNotFoundError`**: ative o ambiente virtual e rode `pip install playwright pandas openpyxl`.
- **Erro relacionado ao Playwright/navegador**: rode `python -m playwright install`.
- **Excel não abre**: feche o arquivo `.xlsx` se ele já estiver aberto durante nova geração.
