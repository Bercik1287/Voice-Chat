# 🎙️ Voice Chat P2P z UPnP

Aplikacja do rozmów głosowych peer-to-peer (P2P) z automatycznym przekierowaniem portów UPnP.

## Funkcje

- **P2P** – bezpośrednie połączenie między użytkownikami (bez serwera)
- **UPnP** – automatyczne otwarcie portu na routerze
- **UDP** – transmisja głosu z niskim opóźnieniem
- **Opus** – opcjonalna kompresja audio (~10x mniejsze zużycie pasma)
- **GUI** – ciemny interfejs w tkinter
- **Multi-peer** – możliwość rozmowy z wieloma osobami jednocześnie
- **Monitorowanie** – wskaźniki poziomu audio, ping, utrata pakietów

## Wymagania

- Python 3.10+
- System z dostępem do mikrofonu i głośników
- Router z obsługą UPnP (opcjonalne, ale zalecane do połączeń przez internet)

## Instalacja

```bash
# Utwórz wirtualne środowisko
python -m venv venv
source venv/bin/activate        # Linux/macOS (bash/zsh)
source venv/bin/activate.fish   # Linux/macOS (fish)
venv\Scripts\activate         # Windows

# Zainstaluj zależności
pip install -r requirements.txt

# Opcjonalnie: kompresja Opus (wymaga libopus w systemie)
# Na Ubuntu/Debian: sudo apt install libopus0
# pip install opuslib
```

## Uruchamianie

```bash
python main.py
```

## Jak korzystać

### 1. Uruchomienie
1. Wpisz swoją **nazwę** i wybierz **port** (domyślnie 50000)
2. Zaznacz **UPnP** jeśli chcesz połączenia przez internet
3. Kliknij **▶ Uruchom**
4. Aplikacja wyświetli Twój **adres zewnętrzny** (np. `85.14.23.100:50000`)

### 2. Łączenie
1. Podaj **adres zewnętrzny** rozmówcy (np. `85.14.23.100:50000`)
2. Kliknij **🔗 Połącz**
3. Rozmowa rozpocznie się automatycznie

### 3. W sieci lokalnej
- Użyj adresu lokalnego (np. `192.168.1.50:50000`)
- UPnP nie jest potrzebne

## Architektura

```
main.py                 # Punkt wejścia
voicechat/
├── __init__.py
├── upnp.py             # Zarządzanie UPnP (przekierowanie portów)
├── audio.py            # Przechwytywanie/odtwarzanie audio + codec Opus
├── network.py          # Protokół UDP (pakiety, peery, keepalive)
└── gui.py              # Interfejs użytkownika (tkinter)
```

### Protokół pakietów UDP

| Typ        | ID  | Opis                          |
|------------|-----|-------------------------------|
| AUDIO      | 1   | Dane audio (PCM/Opus)         |
| PING       | 2   | Pomiar latencji               |
| PONG       | 3   | Odpowiedź na ping             |
| HELLO      | 10  | Inicjacja połączenia          |
| HELLO_ACK  | 11  | Potwierdzenie połączenia      |
| BYE        | 20  | Rozłączenie                   |
| KEEPALIVE  | 30  | Podtrzymanie połączenia       |

## Rozwiązywanie problemów

### UPnP nie działa
- Nie wszystkie routery mają działającą implementację UPnP (nawet jeśli opcja jest „włączona")
- **Alternatywa**: ręcznie przekieruj port UDP na routerze:
  1. Wejdź do panelu routera (zazwyczaj `192.168.1.1`)
  2. Znajdź sekcję "Port Forwarding" / "Przekierowanie portów"
  3. Dodaj regułę: port zewnętrzny `50000` → wewnętrzny IP `192.168.1.x:50000`, protokół **UDP**
- Aplikacja automatycznie wykryje Twoje zewnętrzne IP nawet bez UPnP

### Brak dźwięku
- Sprawdź ustawienia mikrofonu w systemie
- Upewnij się, że aplikacja ma dostęp do mikrofonu
- Sprawdź suwaki głośności w aplikacji

### Wysoki ping / utrata pakietów
- UDP nie gwarantuje dostarczenia – niewielka utrata jest normalna
- Sprawdź jakość połączenia internetowego
