from playwright.sync_api import sync_playwright
import pandas as pd
import time
import os
from pathlib import Path

# --- CONFIGURAÇÕES GERAIS ---
URL = "https://www.linkedin.com/feed/"
EXCEL_FILE = "ranking_engajamento.xlsx"
CSV_FILE = "ranking_engajamento_com_urls.csv"
STORAGE_STATE = Path("linkedin_state.json")

def realizar_login(page, context, url_destino):
    precisa_logar = False
    
    if "signup" in page.url or "authwall" in page.url or "login" in page.url:
        precisa_logar = True
    elif page.locator('a[href*="/login"], button:has-text("Entrar"), button:has-text("Sign in")').first.is_visible(timeout=3000):
        precisa_logar = True

    if precisa_logar:
        print("\n[!] O LinkedIn está pedindo login. Indo para a tela de acesso...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        
        print("\n" + "="*60)
        print("⏰ O SCRIPT ESTÁ PAUSADO PARA VOCÊ FAZER O LOGIN!")
        print("1. Vá até a janela do Chrome que o robô abriu.")
        print("2. Faça seu login normalmente.")
        input("👉 QUANDO O FEED CARREGAR, APERTE 'ENTER' AQUI NO TERMINAL: ")
        print("="*60 + "\n")
        
        time.sleep(5) 
        
        print("Indo para a página da empresa...")
        try:
            page.goto(url_destino, wait_until="domcontentloaded")
        except Exception:
            time.sleep(3)
            page.goto(url_destino, wait_until="domcontentloaded")
        time.sleep(4)

    context.storage_state(path=str(STORAGE_STATE))


def obter_url_post_ativo(page):
    """
    Escaneia a tela atual do navegador para descobrir qual post está mais visível 
    no centro da tela no momento em que você apertou ENTER, e extrai o URN dele.
    """
    urn = page.evaluate("""() => {
        let posts = document.querySelectorAll("div[data-urn*='activity']:not([data-urn*='activity'] [data-urn*='activity'])");
        let targetUrn = null;
        let maxVisibleArea = 0;
        
        for (let p of posts) {
            let rect = p.getBoundingClientRect();
            // Calcula qual post está ocupando mais espaço na tela
            let visibleHeight = Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0);
            if (visibleHeight > maxVisibleArea) {
                maxVisibleArea = visibleHeight;
                targetUrn = p.getAttribute("data-urn");
            }
        }
        return targetUrn;
    }""")
    
    if urn:
        return f"https://www.linkedin.com/feed/update/{urn}/"
    return "URL não identificada"


def extrair_reacoes(page, ranking_engajamento, post_url):
    base_modal_selector = "div[role='dialog'].social-details-reactors-modal"
    modal = page.locator(base_modal_selector).first
    
    if not modal.is_visible():
        print("❌ ERRO: A janela de curtidas não está aberta! Clique nas curtidas no navegador e tente de novo.")
        return False

    print(f"🔗 Link identificado: {post_url}")
    print("✅ Janela detectada! Rolando para carregar todas as reações...")
    
    seletor_scroll = f"{base_modal_selector} .artdeco-modal__content"
    seletor_nomes = f"{base_modal_selector} .artdeco-entity-lockup__title, {base_modal_selector} .artdeco-entity-title"

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    
    while tentativas_sem_novo_nome < 3:
        quantidade_atual = page.locator(seletor_nomes).count()
        if quantidade_atual == pessoas_carregadas:
            tentativas_sem_novo_nome += 1
        else:
            tentativas_sem_novo_nome = 0
            pessoas_carregadas = quantidade_atual

        page.evaluate(f"""
            var objDiv = document.querySelector("{seletor_scroll}");
            if(objDiv) {{ objDiv.scrollTop = objDiv.scrollHeight; }}
        """)
        time.sleep(1.5)

    elementos_nome = page.locator(seletor_nomes).all_inner_texts()
    novas_reacoes = 0
    
    for texto in elementos_nome:
        nome_limpo = texto.split('\n')[0].strip()
        if nome_limpo:
            # Cria o dicionário do usuário incluindo o "Set" de URLs para evitar links duplicados
            ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0, "urls": set()})
            ranking_engajamento[nome_limpo]["reacoes"] += 1
            ranking_engajamento[nome_limpo]["urls"].add(post_url) # Salva o link
            novas_reacoes += 1

    print(f"🎉 {novas_reacoes} reações mapeadas neste post.")
    page.keyboard.press("Escape")
    time.sleep(1)
    return True


def extrair_comentarios(page, ranking_engajamento, comentarios_processados, post_url):
    print("   🔎 Procurando botão 'Carregar mais comentários'...")
    
    while True:
        btn_carregar = page.locator("button.comments-comments-list__load-more-comments-button:visible").first
        if btn_carregar.is_visible():
            try:
                btn_carregar.click(timeout=3000)
                print("   ⏳ Clicou em carregar mais... Aguardando...")
                time.sleep(2)
            except Exception:
                break
        else:
            break

    comentarios_html = page.locator(".comments-comment-item").all()
    novos_comentarios = 0
    
    for comentario in comentarios_html:
        urn = comentario.get_attribute("data-urn") or comentario.get_attribute("data-id")
        if not urn or urn in comentarios_processados:
            continue
        
        if comentario.is_visible():
            seletor_nome_comentario = ".comments-post-meta__name-text, .comments-post-meta__name, a[data-control-name='comment_actor']"
            nome_el = comentario.locator(seletor_nome_comentario).first
            
            if nome_el.is_visible():
                nome_limpo = nome_el.inner_text().split('\n')[0].strip()
                if nome_limpo:
                    ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0, "urls": set()})
                    ranking_engajamento[nome_limpo]["comentarios"] += 1
                    ranking_engajamento[nome_limpo]["urls"].add(post_url) # Salva o link
                    comentarios_processados.add(urn)
                    novos_comentarios += 1
    
    print(f"   💬 {novos_comentarios} novos comentários mapeados!\n")


def salvar_relatorio(ranking_engajamento):
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        total_engajamento = dados["reacoes"] + dados["comentarios"]
        
        # Junta todas as URLs onde a pessoa interagiu separadas por vírgula e espaço
        urls_formatadas = ", ".join(dados["urls"])
        
        dados_finais.append({
            "Nome": nome,
            "Qtd_Reacoes": dados["reacoes"],
            "Qtd_Comentarios": dados["comentarios"],
            "Engajamento_Total": total_engajamento,
            "URLs_dos_Posts": urls_formatadas  # <--- NOVA COLUNA AQUI
        })
    
    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        print(f"✅ SUCESSO TOTAL! {len(dados_finais)} pessoas diferentes estão no ranking.")
        print(f"📁 Relatório completo salvo em: {CSV_FILE}")
    else:
        print("⚠️ Nenhum dado de engajamento foi coletado.")

def salvar_relatorio_excel(ranking_engajamento):
    """
    Consolida os dados e exporta diretamente para um arquivo do Excel (.xlsx)
    """
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        total_engajamento = dados["reacoes"] + dados["comentarios"]
        
        urls_formatadas = ", ".join(dados["urls"])
        
        dados_finais.append({
            "Nome": nome,
            "Qtd_Reacoes": dados["reacoes"],
            "Qtd_Comentarios": dados["comentarios"],
            "Engajamento_Total": total_engajamento,
            "URLs_dos_Posts": urls_formatadas
        })
    
    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        
        # Aqui acontece a mágica do Excel usando o motor openpyxl
        df.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
        
        print(f"✅ SUCESSO TOTAL! {len(dados_finais)} pessoas diferentes estão no ranking.")
        print(f"📁 Relatório completo salvo em formato Excel: {EXCEL_FILE}")
    else:
        print("⚠️ Nenhum dado de engajamento foi coletado.")

def main():
    ranking_engajamento = {}
    comentarios_processados = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
        
        if STORAGE_STATE.is_file():
            ctx_opts["storage_state"] = str(STORAGE_STATE)

        context = browser.new_context(**ctx_opts)
        page = context.new_page()

        print(f"Acessando: {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        time.sleep(4)

        realizar_login(page, context, URL)

        print("\n" + "="*65)
        print("🤖 MODO SEMI-AUTOMÁTICO ATIVADO")
        print("👉 Deixe a janela de Reações aberta e aperte ENTER.")
        print("👉 Digite 'sair' a qualquer momento para gerar o Excel.")
        print("="*65 + "\n")

        contador_posts = 0

        while True:
            comando = input(f"👉 [Post {contador_posts + 1}] Janela de REAÇÕES aberta? Aperte ENTER (ou 'sair'): ").strip().lower()

            if comando == 'sair':
                break
            
            # Descobre a URL do post que o usuário está visualizando agora
            post_url = obter_url_post_ativo(page)

            sucesso_reacoes = extrair_reacoes(page, ranking_engajamento, post_url)
            
            if sucesso_reacoes:
                contador_posts += 1
                
                comando_coment = input(f"   💬 Quer extrair os COMENTÁRIOS agora? Deixe-os visíveis e aperte ENTER (ou 'n'): ").strip().lower()
                if comando_coment != 'n':
                    extrair_comentarios(page, ranking_engajamento, comentarios_processados, post_url)

        print("\n=========================================")
        print("COLETA FINALIZADA! Encerrando navegador...")
        browser.close()

    salvar_relatorio(ranking_engajamento)
    salvar_relatorio_excel(ranking_engajamento)

if __name__ == "__main__":
    main()