import os
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext
import tksvg
from instagram.instagram import InstagramRunner
from linkedin.linkedin import LinkedInRunner


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        text="",
        command=None,
        width=170,
        height=44,
        image=None,
        radius=16,
        bg="#2F81F7",
        fg="white",
        hover_bg="#3B8CFF",
        disabled_bg="#C9D1D9",
        disabled_fg="#6E7781",
        font=("Segoe UI", 10, "bold"),
        state="normal",
    ):
        super().__init__(parent, width=width, height=height, bd=0, highlightthickness=0, bg=parent.cget("bg"))
        self._text = text
        self._command = command
        self._width = width
        self._height = height
        self._image = image
        self._radius = radius
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg
        self._disabled_bg = disabled_bg
        self._disabled_fg = disabled_fg
        self._font = font
        self._state = state
        self._is_hover = False

        self._shape_id = None
        self._text_id = None
        self._draw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

        # CORREÇÃO: Usando self._image e self._text com o underline
        if self._image:
            self.create_image(width/2, height/2, image=self._image, anchor="center")
        elif self._text:
            self._text_id = self.create_text(width/2, height/2, text=self._text, fill=self._fg, font=self._font)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        
    def _draw(self):
        
        self.delete("all")

        
        fill_color, text_color = self._current_colors()
        self._shape_id = self._create_round_rect(
            1, 1, self._width - 1, self._height - 1, self._radius, fill=fill_color, outline=""
        )
        self._text_id = self.create_text(
            self._width / 2, self._height / 2, text=self._text, fill=text_color, font=self._font
        )
        if self._image:
            self.create_image(self._width/2, self._height/2, image=self._image, anchor="center")
        elif self._text:
            # Pega a cor certa dependendo se o botão está desativado ou não
            cor_texto = self._disabled_fg if self._state == "disabled" else self._fg
            self._text_id = self.create_text(
                self._width/2, self._height/2, 
                text=self._text, fill=cor_texto, font=self._font
            )

    def _create_round_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _current_colors(self):
        if self._state == "disabled":
            return self._disabled_bg, self._disabled_fg
        if self._is_hover:
            return self._hover_bg, self._fg
        return self._bg, self._fg

    def _on_enter(self, _event):
        if self._state != "disabled":
            self._is_hover = True
            self._draw()

    def _on_leave(self, _event):
        self._is_hover = False
        self._draw()

    def _on_click(self, _event):
        if self._state != "disabled" and callable(self._command):
            self._command()

    def configure(self, cnf=None, **kwargs):
        params = {}
        if cnf and isinstance(cnf, dict):
            params.update(cnf)
        params.update(kwargs)

        if "text" in params:
            self._text = params["text"]
        if "state" in params:
            self._state = params["state"]
            if self._state == "disabled":
                self._is_hover = False
        if "command" in params:
            self._command = params["command"]
        if "bg" in params:
            self._bg = params["bg"]
        if "fg" in params:
            self._fg = params["fg"]
        if "hover_bg" in params:
            self._hover_bg = params["hover_bg"]
        if "font" in params:
            self._font = params["font"]

        self._draw()

    config = configure


class AppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Central de Raspadores")
        self.root.geometry("880x560")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.linkedin_runner = LinkedInRunner(
            log_callback=self.log,
            waiting_callback=self.show_waiting_message,
            finished_callback=self.on_runner_finished,
            stage_callback=self.on_linkedin_stage_change,
        )
        self.instagram_runner = InstagramRunner(
            log_callback=self.log,
            waiting_callback=self.show_waiting_message,
            finished_callback=self.on_runner_finished,
        )
        self.current_runner = None
        self.linkedin_reset_available = False

        self.main_frame = tk.Frame(root, padx=20, pady=20)
        self.automation_frame = tk.Frame(root, padx=20, pady=20)
        self.page_title_var = tk.StringVar(value="Automacao")
        self.waiting_var = tk.StringVar(value="Escolha uma rede social para comecar.")

        self._build_main_page()
        self._build_automation_page()
        self.show_main_page()

    def resource_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def _build_main_page(self):
        tk.Label(self.main_frame, text="Aplicativos", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(
            self.main_frame,
            text="Escolha qual rede social deseja automatizar.",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(4, 20))

        cards = tk.Frame(self.main_frame)
        cards.pack(fill="x")

        RoundedButton(
            cards,
            text="in",
            command=lambda: self.show_automation_page("linkedin"),
            bg="#0A66C2",
            hover_bg="#0D74DE",
            width=190,
            height=84,
            radius=22,
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, padx=(0, 14), pady=8, sticky="w")

        caminho_logo = self.resource_path("ui/assets/logo_instagram.svg")
        self.ig_icon = tksvg.SvgImage(file=caminho_logo, scaletowidth=40)

        RoundedButton(
            cards,
            image=self.ig_icon,
            command=lambda: self.show_automation_page("instagram"),
            bg="#C13584",
            hover_bg="#D94A96",
            width=190,
            height=84,
            radius=22,
            font=("Segoe UI Symbol", 18, "bold"),
        ).grid(row=0, column=1, padx=14, pady=8, sticky="w")

        RoundedButton(
            cards,
            text="f\nEm breve",
            command=lambda: None,
            state="disabled",
            width=190,
            height=84,
            radius=22,
            bg="#8C959F",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=2, padx=14, pady=8, sticky="w")

    def _build_automation_page(self):
        top = tk.Frame(self.automation_frame)
        top.pack(fill="x")

        self.btn_voltar = RoundedButton(
            top,
            text="← Voltar",
            command=self.show_main_page,
            width=116,
            height=40,
            radius=20,
            bg="#111827",
            hover_bg="#1F2937",
            font=("Segoe UI", 10, "bold"),
        )
        self.btn_voltar.pack(side="left", pady=(2, 0))
        tk.Label(top, textvariable=self.page_title_var, font=("Segoe UI", 15, "bold")).pack(
            side="left", padx=12
        )

        tk.Label(
            self.automation_frame,
            textvariable=self.waiting_var,
            font=("Segoe UI", 10, "italic"),
            justify="left",
            anchor="w",
            wraplength=820,
        ).pack(fill="x", pady=(16, 8))

        botoes = tk.Frame(self.automation_frame)
        botoes.pack(fill="x", pady=(4, 10))

        self.btn_comecar = RoundedButton(
            botoes,
            text="Comecar",
            command=self.start_current_runner,
            bg="#1A7F37",
            hover_bg="#238F43",
            width=140,
            height=42,
            radius=18,
            font=("Segoe UI", 10, "bold"),
        )
        self.btn_comecar.pack(side="left")

        self.btn_confirmar = RoundedButton(
            botoes,
            text="Confirmar",
            command=self.confirm_step,
            state="disabled",
            bg="#2F81F7",
            hover_bg="#4C92F7",
            width=140,
            height=42,
            radius=18,
            font=("Segoe UI", 10, "bold"),
        )
        self.btn_confirmar.pack(side="left", padx=12)

        self.btn_sair = RoundedButton(
            botoes,
            text="Finalizar",
            command=self.stop_current_runner,
            state="disabled",
            bg="#CF222E",
            hover_bg="#E04652",
            width=140,
            height=42,
            radius=18,
            font=("Segoe UI", 10, "bold"),
        )
        self.btn_sair.pack(side="left")

        self.log_box = scrolledtext.ScrolledText(
            self.automation_frame,
            height=20,
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_box.tag_configure("lifecycle", foreground="#1A7F37")
        self.log_box.tag_configure("collect", foreground="#0969DA")
        self.log_box.tag_configure("error", foreground="#CF222E")
        self.log_box.pack(fill="both", expand=True)

    def show_main_page(self):
        self.automation_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)

    def show_automation_page(self, platform):
        if platform == "linkedin":
            self.current_runner = self.linkedin_runner
            self.page_title_var.set("LinkedIn - Coleta de Engajamento")
            self.waiting_var.set("Clique em 'Comecar' para abrir o LinkedIn.")
        elif platform == "instagram":
            self.current_runner = self.instagram_runner
            self.page_title_var.set("Instagram - Fluxo Inicial de Curtidas")
            self.waiting_var.set("Clique em 'Comecar' para abrir o Instagram.")
        else:
            return

        self.main_frame.pack_forget()
        self.automation_frame.pack(fill="both", expand=True)

    def start_current_runner(self):
        if self.current_runner is None or self.current_runner.running:
            return
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state="disabled")
        self.waiting_var.set("Iniciando automacao e abrindo o Chrome...")
        self.current_runner.start()
        if self.current_runner is self.linkedin_runner:
            self.linkedin_reset_available = False
            self.btn_comecar.configure(
                text="Parar",
                command=self.reset_linkedin_post,
                bg="#CF222E",
                hover_bg="#E04652",
                state="disabled",
            )
        else:
            self.btn_comecar.configure(state="disabled")
        self.btn_confirmar.configure(state="normal")
        self.btn_sair.configure(state="normal")

    def reset_linkedin_post(self):
        if self.current_runner is not self.linkedin_runner or not self.current_runner.running:
            return
        if not self.linkedin_reset_available:
            messagebox.showinfo(
                "Aguarde etapa 1",
                "O botao 'Parar' so fica ativo apos concluir a etapa 1 (reacoes).",
            )
            return
        self.linkedin_runner.request_skip_current_post()
        self.linkedin_reset_available = False
        self.btn_comecar.configure(state="disabled")
        self.waiting_var.set("Reset solicitado. Preparando validacao do proximo post...")

    def confirm_step(self):
        if self.current_runner is not None and self.current_runner.running:
            self.current_runner.confirm()

    def stop_current_runner(self):
        if self.current_runner is None or not self.current_runner.running:
            return
        if messagebox.askyesno("Encerrar coleta", "Deseja sair e finalizar a coleta agora?"):
            self.current_runner.stop()
            self.waiting_var.set("Encerrando processo...")

    def show_waiting_message(self, message):
        self.root.after(0, lambda: self.waiting_var.set(message))

    def on_runner_finished(self):
        def _finish():
            self.waiting_var.set("Processo finalizado.")
            self.linkedin_reset_available = False
            self.btn_comecar.configure(
                text="Comecar",
                command=self.start_current_runner,
                bg="#1A7F37",
                hover_bg="#238F43",
                state="normal",
            )
            self.btn_confirmar.configure(state="disabled")
            self.btn_sair.configure(state="disabled")

        self.root.after(0, _finish)

    def on_linkedin_stage_change(self, stage):
        def _update():
            if self.current_runner is not self.linkedin_runner:
                return
            if stage == "etapa1_concluida":
                self.linkedin_reset_available = True
                self.btn_comecar.configure(state="normal")
            elif stage in ("aguardando_etapa1", "idle"):
                self.linkedin_reset_available = False
                if self.linkedin_runner.running:
                    self.btn_comecar.configure(state="disabled")

        self.root.after(0, _update)

    @staticmethod
    def _infer_log_tag(message):
        text = (message or "").strip()
        if text.upper().startswith("ERRO:") or text.startswith("Erro inesperado"):
            return "error"
        prefixes_lifecycle = (
            "Acessando:",
            "LinkedIn pediu login",
            "Instagram pediu login",
            "Coleta iniciada",
            "Modo inicial ativo.",
            "Finalizando coleta",
            "SUCESSO:",
            "Arquivos gerados:",
            "Nenhum dado de engajamento",
        )
        if any(text.startswith(p) for p in prefixes_lifecycle):
            return "lifecycle"
        return "collect"

    def log(self, message, tag=None):
        chosen = tag if tag in ("lifecycle", "collect", "error") else self._infer_log_tag(message)

        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert(tk.END, f"{message}\n", (chosen,))
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")

        self.root.after(0, _append)

    def on_close(self):
        if self.linkedin_runner.running:
            self.linkedin_runner.stop()
        if self.instagram_runner.running:
            self.instagram_runner.stop()
        self.root.destroy()
