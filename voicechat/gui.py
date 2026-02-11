"""GUI – interfejs użytkownika w tkinter."""

import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .upnp import UPnPManager
from .audio import AudioEngine
from .network import VoiceNetwork, Peer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Kolory i styl
# ---------------------------------------------------------------
BG_DARK = "#1e1e2e"
BG_MID = "#2a2a3d"
BG_LIGHT = "#363650"
FG_TEXT = "#cdd6f4"
FG_DIM = "#6c7086"
ACCENT = "#89b4fa"
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"


class VoiceChatGUI:
    """Główne okno aplikacji Voice Chat."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎙️ Voice Chat P2P")
        self.root.geometry("700x550")
        self.root.minsize(600, 450)
        self.root.configure(bg=BG_DARK)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Komponenty aplikacji
        self.upnp = UPnPManager()
        self.network: VoiceNetwork | None = None
        self.audio: AudioEngine | None = None

        self._username = "User"
        self._is_connected = False
        self._upnp_enabled = True

        # Zbuduj interfejs
        self._create_styles()
        self._build_ui()

        # Aktualizacja GUI
        self._update_interval = 100  # ms
        self._schedule_updates()

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------
    def _create_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background=BG_DARK)
        style.configure("Mid.TFrame", background=BG_MID)
        style.configure("Light.TFrame", background=BG_LIGHT)

        style.configure(
            "Dark.TLabel",
            background=BG_DARK,
            foreground=FG_TEXT,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Title.TLabel",
            background=BG_DARK,
            foreground=ACCENT,
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=BG_MID,
            foreground=FG_DIM,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Peer.TLabel",
            background=BG_MID,
            foreground=FG_TEXT,
            font=("Segoe UI", 10),
        )

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=BG_DARK,
            font=("Segoe UI", 10, "bold"),
            padding=(12, 6),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#74a8f7"), ("disabled", FG_DIM)],
        )

        style.configure(
            "Danger.TButton",
            background=ACCENT_RED,
            foreground=BG_DARK,
            font=("Segoe UI", 10, "bold"),
            padding=(12, 6),
        )

        style.configure(
            "Mute.TButton",
            background=ACCENT_YELLOW,
            foreground=BG_DARK,
            font=("Segoe UI", 10),
            padding=(8, 4),
        )

    # ------------------------------------------------------------------
    # Budowanie UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- Nagłówek ---
        header = ttk.Frame(self.root, style="Dark.TFrame")
        header.pack(fill=tk.X, padx=16, pady=(12, 4))

        ttk.Label(header, text="🎙️ Voice Chat P2P", style="Title.TLabel").pack(
            side=tk.LEFT
        )

        self._status_label = ttk.Label(
            header, text="⚪ Rozłączony", style="Dark.TLabel"
        )
        self._status_label.pack(side=tk.RIGHT)

        # --- Sekcja konfiguracji ---
        config_frame = ttk.Frame(self.root, style="Dark.TFrame")
        config_frame.pack(fill=tk.X, padx=16, pady=8)

        # Nazwa użytkownika
        name_frame = ttk.Frame(config_frame, style="Dark.TFrame")
        name_frame.pack(fill=tk.X, pady=2)

        ttk.Label(name_frame, text="Nazwa:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self._name_var = tk.StringVar(value="User")
        name_entry = tk.Entry(
            name_frame,
            textvariable=self._name_var,
            bg=BG_LIGHT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=20,
        )
        name_entry.pack(side=tk.LEFT, padx=(0, 16))

        # Port
        ttk.Label(name_frame, text="Port:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self._port_var = tk.StringVar(value="50000")
        port_entry = tk.Entry(
            name_frame,
            textvariable=self._port_var,
            bg=BG_LIGHT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=8,
        )
        port_entry.pack(side=tk.LEFT, padx=(0, 16))

        # UPnP checkbox
        self._upnp_var = tk.BooleanVar(value=True)
        upnp_cb = tk.Checkbutton(
            name_frame,
            text="UPnP",
            variable=self._upnp_var,
            bg=BG_DARK,
            fg=FG_TEXT,
            selectcolor=BG_LIGHT,
            activebackground=BG_DARK,
            activeforeground=FG_TEXT,
            font=("Segoe UI", 10),
        )
        upnp_cb.pack(side=tk.LEFT)

        # --- Przyciski Start / Stop ---
        btn_frame = ttk.Frame(self.root, style="Dark.TFrame")
        btn_frame.pack(fill=tk.X, padx=16, pady=4)

        self._start_btn = ttk.Button(
            btn_frame,
            text="▶  Uruchom",
            style="Accent.TButton",
            command=self._on_start,
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._stop_btn = ttk.Button(
            btn_frame,
            text="⏹  Zatrzymaj",
            style="Danger.TButton",
            command=self._on_stop,
            state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 16))

        self._mute_btn = ttk.Button(
            btn_frame,
            text="🔇  Mute",
            style="Mute.TButton",
            command=self._on_mute,
            state=tk.DISABLED,
        )
        self._mute_btn.pack(side=tk.LEFT, padx=(0, 8))

        # --- Łączenie z peerem ---
        connect_frame = ttk.Frame(self.root, style="Dark.TFrame")
        connect_frame.pack(fill=tk.X, padx=16, pady=4)

        ttk.Label(connect_frame, text="Połącz z:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self._peer_host_var = tk.StringVar()
        peer_entry = tk.Entry(
            connect_frame,
            textvariable=self._peer_host_var,
            bg=BG_LIGHT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            width=25,
        )
        peer_entry.pack(side=tk.LEFT, padx=(0, 4))
        peer_entry.insert(0, "ip:port")
        peer_entry.bind("<FocusIn>", lambda e: self._clear_placeholder(e, "ip:port"))

        self._connect_btn = ttk.Button(
            connect_frame,
            text="🔗  Połącz",
            style="Accent.TButton",
            command=self._on_connect_peer,
            state=tk.DISABLED,
        )
        self._connect_btn.pack(side=tk.LEFT, padx=8)

        # --- Info UPnP ---
        self._upnp_info = ttk.Label(
            self.root,
            text="",
            style="Dark.TLabel",
        )
        self._upnp_info.pack(fill=tk.X, padx=16, pady=2)

        # --- Lista peerów ---
        peers_label = ttk.Label(
            self.root, text="Połączeni rozmówcy:", style="Dark.TLabel"
        )
        peers_label.pack(fill=tk.X, padx=16, pady=(8, 2))

        peers_frame = tk.Frame(self.root, bg=BG_MID, relief=tk.FLAT, bd=1)
        peers_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 4))

        self._peers_listbox = tk.Listbox(
            peers_frame,
            bg=BG_MID,
            fg=FG_TEXT,
            selectbackground=ACCENT,
            selectforeground=BG_DARK,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            bd=4,
            highlightthickness=0,
        )
        self._peers_listbox.pack(fill=tk.BOTH, expand=True)

        # --- Wskaźniki poziomu audio ---
        levels_frame = ttk.Frame(self.root, style="Dark.TFrame")
        levels_frame.pack(fill=tk.X, padx=16, pady=(2, 4))

        ttk.Label(levels_frame, text="🎤 Mikrofon:", style="Dark.TLabel").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        self._input_level = ttk.Progressbar(
            levels_frame, length=200, mode="determinate", maximum=100
        )
        self._input_level.grid(row=0, column=1, sticky=tk.EW, padx=(0, 16))

        ttk.Label(levels_frame, text="🔊 Głośnik:", style="Dark.TLabel").grid(
            row=0, column=2, sticky=tk.W, padx=(0, 8)
        )
        self._output_level = ttk.Progressbar(
            levels_frame, length=200, mode="determinate", maximum=100
        )
        self._output_level.grid(row=0, column=3, sticky=tk.EW)

        levels_frame.columnconfigure(1, weight=1)
        levels_frame.columnconfigure(3, weight=1)

        # --- Pasek statusu ---
        status_bar = tk.Frame(self.root, bg=BG_MID, height=28)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._statusbar_label = tk.Label(
            status_bar,
            text="Gotowy",
            bg=BG_MID,
            fg=FG_DIM,
            font=("Segoe UI", 9),
            anchor=tk.W,
            padx=12,
        )
        self._statusbar_label.pack(fill=tk.X)

        # --- Suwaki głośności ---
        vol_frame = ttk.Frame(self.root, style="Dark.TFrame")
        vol_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        ttk.Label(vol_frame, text="Głośność wejścia:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self._input_vol = tk.Scale(
            vol_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            bg=BG_DARK,
            fg=FG_TEXT,
            troughcolor=BG_LIGHT,
            highlightthickness=0,
            length=120,
            command=self._on_input_vol_change,
        )
        self._input_vol.set(100)
        self._input_vol.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(vol_frame, text="Głośność wyjścia:", style="Dark.TLabel").pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self._output_vol = tk.Scale(
            vol_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            bg=BG_DARK,
            fg=FG_TEXT,
            troughcolor=BG_LIGHT,
            highlightthickness=0,
            length=120,
            command=self._on_output_vol_change,
        )
        self._output_vol.set(100)
        self._output_vol.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Placeholder w polu tekstowym
    # ------------------------------------------------------------------
    @staticmethod
    def _clear_placeholder(event, placeholder: str):
        widget = event.widget
        if widget.get() == placeholder:
            widget.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Obsługa zdarzeń
    # ------------------------------------------------------------------
    def _on_start(self):
        """Uruchamia voice chat."""
        self._username = self._name_var.get().strip() or "User"

        try:
            port = int(self._port_var.get())
        except ValueError:
            messagebox.showerror("Błąd", "Nieprawidłowy numer portu.")
            return

        self._set_status("Uruchamiam...")

        def _startup():
            try:
                # 1. Sieć
                self.network = VoiceNetwork(
                    local_port=port,
                    on_audio_received=self._on_audio_from_network,
                    on_peer_connected=self._on_peer_connected,
                    on_peer_disconnected=self._on_peer_disconnected,
                )
                actual_port = self.network.start(username=self._username)

                # 2. UPnP + wykrywanie IP
                upnp_info = ""
                local_ip = self.upnp.get_local_ip()

                if self._upnp_var.get():
                    self._set_status("Konfiguruję UPnP...")
                    if self.upnp.discover():
                        ext_port = self.upnp.add_port_mapping(actual_port)
                        if ext_port:
                            ext_addr = self.upnp.get_external_address()
                            upnp_info = (
                                f"✅ UPnP: {ext_addr[0]}:{ext_addr[1]}  "
                                f"(podaj ten adres rozmówcy)"
                            )
                        else:
                            upnp_info = "⚠️ UPnP: nie udało się zmapować portu"
                    else:
                        # UPnP nie działa – wykryj IP online i pokaż instrukcje
                        self._set_status("UPnP niedostępne – wykrywam IP online...")
                        ext_ip = self.upnp.detect_external_ip()
                        if ext_ip:
                            upnp_info = (
                                f"⚠️ UPnP niedostępne  |  "
                                f"Twoje IP: {ext_ip}  |  "
                                f"LAN: {local_ip}:{actual_port}\n"
                                f"   ℹ️ Przekieruj ręcznie port {actual_port}/UDP na routerze "
                                f"na {local_ip}:{actual_port}"
                            )
                        else:
                            upnp_info = (
                                f"⚠️ UPnP niedostępne  |  "
                                f"LAN: {local_ip}:{actual_port}\n"
                                f"   ℹ️ Przekieruj ręcznie port {actual_port}/UDP na routerze"
                            )
                else:
                    # UPnP wyłączone – pokaż adresy
                    ext_ip = self.upnp.detect_external_ip()
                    if ext_ip:
                        upnp_info = (
                            f"ℹ️ IP: {ext_ip}  |  LAN: {local_ip}:{actual_port}  "
                            f"(UPnP wyłączone)"
                        )
                    else:
                        upnp_info = f"ℹ️ LAN: {local_ip}:{actual_port}  (UPnP wyłączone)"

                # 3. Audio
                self.audio = AudioEngine(
                    send_callback=self.network.send_audio,
                )
                self.audio.start()

                # Aktualizuj GUI z wątku głównego
                self.root.after(0, lambda: self._on_started(actual_port, upnp_info))

            except Exception as exc:
                self.root.after(
                    0,
                    lambda: messagebox.showerror("Błąd", f"Nie udało się uruchomić:\n{exc}"),
                )
                self.root.after(0, lambda: self._set_status("Błąd uruchamiania"))

        threading.Thread(target=_startup, daemon=True).start()

    def _on_started(self, port: int, upnp_info: str):
        """Aktualizuje GUI po pomyślnym uruchomieniu."""
        self._is_connected = True
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._mute_btn.configure(state=tk.NORMAL)
        self._connect_btn.configure(state=tk.NORMAL)
        self._status_label.configure(text=f"🟢 Aktywny (port {port})")
        self._set_status(f"Nasłuchuję na porcie {port}")

        if upnp_info:
            self._upnp_info.configure(text=upnp_info)

    def _on_stop(self):
        """Zatrzymuje voice chat."""
        self._is_connected = False

        if self.audio:
            self.audio.stop()
            self.audio = None

        if self.network:
            self.network.stop()
            self.network = None

        self.upnp.cleanup()

        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self._mute_btn.configure(state=tk.DISABLED)
        self._connect_btn.configure(state=tk.DISABLED)
        self._status_label.configure(text="⚪ Rozłączony")
        self._upnp_info.configure(text="")
        self._peers_listbox.delete(0, tk.END)
        self._set_status("Zatrzymano")

    def _on_mute(self):
        """Przełącza wyciszenie mikrofonu."""
        if self.audio:
            is_muted = self.audio.toggle_mute()
            self._mute_btn.configure(
                text="🔊  Unmute" if is_muted else "🔇  Mute"
            )

    def _on_connect_peer(self):
        """Łączy się z podanym peerem."""
        addr_str = self._peer_host_var.get().strip()
        if not addr_str or addr_str == "ip:port":
            messagebox.showwarning("Uwaga", "Podaj adres IP i port rozmówcy (np. 1.2.3.4:50000)")
            return

        try:
            if ":" in addr_str:
                host, port_str = addr_str.rsplit(":", 1)
                port = int(port_str)
            else:
                host = addr_str
                port = 50000
        except ValueError:
            messagebox.showerror("Błąd", "Nieprawidłowy format adresu. Użyj: ip:port")
            return

        if self.network:
            self.network.connect_to_peer(host, port)
            self._set_status(f"Łączę z {host}:{port}...")

    def _on_input_vol_change(self, value):
        if self.audio:
            self.audio.input_volume = int(value) / 100.0

    def _on_output_vol_change(self, value):
        if self.audio:
            self.audio.output_volume = int(value) / 100.0

    # ------------------------------------------------------------------
    # Callbacki sieciowe (z wątku sieciowego!)
    # ------------------------------------------------------------------
    def _on_audio_from_network(self, audio_data: bytes, addr):
        """Odebrano dane audio z sieci."""
        if self.audio:
            self.audio.receive_audio(audio_data)

    def _on_peer_connected(self, peer: Peer):
        """Nowy peer się połączył."""
        self.root.after(0, lambda: self._update_peers_list())
        self.root.after(
            0,
            lambda: self._set_status(f"Połączono z {peer.name} ({peer.address[0]}:{peer.address[1]})"),
        )

    def _on_peer_disconnected(self, peer: Peer):
        """Peer się rozłączył."""
        self.root.after(0, lambda: self._update_peers_list())
        self.root.after(
            0,
            lambda: self._set_status(f"{peer.name} rozłączył się"),
        )

    # ------------------------------------------------------------------
    # Aktualizacja GUI
    # ------------------------------------------------------------------
    def _update_peers_list(self):
        """Odświeża listę peerów."""
        self._peers_listbox.delete(0, tk.END)
        if self.network:
            for peer in self.network.get_peers():
                latency_str = f"{peer.latency_ms:.0f}ms" if peer.latency_ms > 0 else "?"
                loss_rate = (
                    f"{peer.packets_lost / max(peer.packets_received, 1) * 100:.1f}%"
                    if peer.packets_received > 0
                    else "0%"
                )
                status = "🟢" if peer.is_alive() else "🔴"
                line = f" {status}  {peer.name}  |  {peer.address[0]}:{peer.address[1]}  |  ping: {latency_str}  |  utrata: {loss_rate}"
                self._peers_listbox.insert(tk.END, line)

    def _schedule_updates(self):
        """Planuje cykliczne aktualizacje GUI."""
        self._periodic_update()

    def _periodic_update(self):
        """Cykliczna aktualizacja wskaźników."""
        if self.audio and self._is_connected:
            # Poziomy audio
            self._input_level["value"] = self.audio._input_level * 100
            self._output_level["value"] = self.audio._output_level * 100

            # Odśwież listę peerów co 2 sekundy
            if hasattr(self, "_update_counter"):
                self._update_counter += 1
            else:
                self._update_counter = 0

            if self._update_counter % 20 == 0:  # co 20 * 100ms = 2s
                self._update_peers_list()
        else:
            self._input_level["value"] = 0
            self._output_level["value"] = 0

        self.root.after(self._update_interval, self._periodic_update)

    def _set_status(self, text: str):
        """Ustawia tekst na pasku statusu."""
        self._statusbar_label.configure(text=text)

    # ------------------------------------------------------------------
    # Zamykanie
    # ------------------------------------------------------------------
    def _on_close(self):
        """Zamyka aplikację."""
        self._on_stop()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Uruchamianie
    # ------------------------------------------------------------------
    def run(self):
        """Uruchamia główną pętlę GUI."""
        self.root.mainloop()
