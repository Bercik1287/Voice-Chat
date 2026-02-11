"""Moduł sieciowy – transmisja głosu przez UDP z obsługą wielu peerów."""

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Protokół pakietów
# ---------------------------------------------------------------
# Nagłówek: [typ:1B][seq:4B][timestamp:8B][payload_len:2B]
HEADER_FORMAT = "!BIHH"  # typ, seq_nr, timestamp_ms (uint32), payload_len
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Pełny nagłówek z 8-bajtowym timestamp
HEADER_FORMAT = "!BIqH"  # typ(1), seq(4), timestamp(8), payload_len(2)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

MAX_PACKET_SIZE = 65535


class PacketType(IntEnum):
    """Typy pakietów w protokole."""
    AUDIO = 1        # Dane audio
    PING = 2         # Ping (pomiar latencji)
    PONG = 3         # Odpowiedź na ping
    HELLO = 10       # Inicjacja połączenia
    HELLO_ACK = 11   # Potwierdzenie połączenia
    BYE = 20         # Rozłączenie
    KEEPALIVE = 30   # Podtrzymanie połączenia


@dataclass
class Peer:
    """Reprezentuje połączonego rozmówcę."""
    address: tuple[str, int]      # (ip, port)
    name: str = "Unknown"
    last_seen: float = 0.0
    latency_ms: float = 0.0
    packets_received: int = 0
    packets_lost: int = 0
    last_seq: int = -1

    def is_alive(self, timeout: float = 10.0) -> bool:
        return (time.time() - self.last_seen) < timeout


class VoiceNetwork:
    """Sieciowy silnik do transmisji głosu UDP."""

    def __init__(
        self,
        local_port: int = 50000,
        on_audio_received=None,
        on_peer_connected=None,
        on_peer_disconnected=None,
    ):
        """
        Args:
            local_port: Port lokalny do nasłuchiwania.
            on_audio_received: callback(audio_data: bytes, peer_addr)
            on_peer_connected: callback(peer: Peer)
            on_peer_disconnected: callback(peer: Peer)
        """
        self.local_port = local_port
        self.on_audio_received = on_audio_received
        self.on_peer_connected = on_peer_connected
        self.on_peer_disconnected = on_peer_disconnected

        self._socket: socket.socket | None = None
        self._running = False
        self._recv_thread: threading.Thread | None = None
        self._keepalive_thread: threading.Thread | None = None

        self._peers: dict[tuple[str, int], Peer] = {}
        self._peers_lock = threading.Lock()

        self._seq_counter: int = 0
        self._username: str = "User"

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def start(self, username: str = "User") -> int:
        """Uruchamia nasłuchiwanie na porcie UDP.

        Returns:
            Numer portu, na którym nasłuchuje.
        """
        self._username = username
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Zwiększ bufory socketowe
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 256)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 256)

        self._socket.bind(("0.0.0.0", self.local_port))
        self._socket.settimeout(1.0)

        actual_port = self._socket.getsockname()[1]
        self.local_port = actual_port

        self._running = True

        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

        self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive_thread.start()

        logger.info("Sieć uruchomiona na porcie %d.", actual_port)
        return actual_port

    def stop(self):
        """Zatrzymuje sieć i rozłącza peerów."""
        self._running = False

        # Wyślij BYE do wszystkich peerów
        with self._peers_lock:
            addrs = list(self._peers.keys())
            self._peers.clear()

        for addr in addrs:
            self._send_packet(PacketType.BYE, b"", addr)

        if self._socket:
            self._socket.close()
            self._socket = None

        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        if self._keepalive_thread:
            self._keepalive_thread.join(timeout=3)

        logger.info("Sieć zatrzymana.")

    # ------------------------------------------------------------------
    # Łączenie z peerem
    # ------------------------------------------------------------------
    def connect_to_peer(self, host: str, port: int):
        """Inicjuje połączenie z peerem (wysyła HELLO)."""
        addr = (host, port)
        payload = self._username.encode("utf-8")
        self._send_packet(PacketType.HELLO, payload, addr)
        logger.info("Wysłano HELLO do %s:%d", host, port)

    def disconnect_peer(self, addr: tuple[str, int]):
        """Rozłącza peera."""
        self._send_packet(PacketType.BYE, b"", addr)
        with self._peers_lock:
            peer = self._peers.pop(addr, None)
        if peer and self.on_peer_disconnected:
            self.on_peer_disconnected(peer)

    # ------------------------------------------------------------------
    # Wysyłanie audio
    # ------------------------------------------------------------------
    def send_audio(self, encoded_audio: bytes):
        """Wysyła dane audio do wszystkich podłączonych peerów."""
        if not self._running or not self._peers:
            return

        with self._peers_lock:
            addrs = list(self._peers.keys())

        for addr in addrs:
            self._send_packet(PacketType.AUDIO, encoded_audio, addr)

    # ------------------------------------------------------------------
    # Budowanie i wysyłanie pakietów
    # ------------------------------------------------------------------
    def _send_packet(self, ptype: PacketType, payload: bytes, addr: tuple[str, int]):
        """Pakuje i wysyła pakiet UDP."""
        if not self._socket:
            return

        self._seq_counter = (self._seq_counter + 1) % (2 ** 32)
        timestamp = int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF

        header = struct.pack(HEADER_FORMAT, int(ptype), self._seq_counter, timestamp, len(payload))
        try:
            self._socket.sendto(header + payload, addr)
        except OSError as exc:
            logger.debug("Błąd wysyłania do %s: %s", addr, exc)

    # ------------------------------------------------------------------
    # Odbieranie pakietów
    # ------------------------------------------------------------------
    def _receive_loop(self):
        """Główna pętla odbierania pakietów UDP."""
        while self._running:
            try:
                data, addr = self._socket.recvfrom(MAX_PACKET_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < HEADER_SIZE:
                continue

            ptype, seq, timestamp, payload_len = struct.unpack(
                HEADER_FORMAT, data[:HEADER_SIZE]
            )
            payload = data[HEADER_SIZE: HEADER_SIZE + payload_len]

            self._handle_packet(PacketType(ptype), seq, timestamp, payload, addr)

    def _handle_packet(
        self,
        ptype: PacketType,
        seq: int,
        timestamp: int,
        payload: bytes,
        addr: tuple[str, int],
    ):
        """Obsługuje odebrany pakiet."""

        if ptype == PacketType.HELLO:
            name = payload.decode("utf-8", errors="replace") if payload else "Unknown"
            self._register_peer(addr, name)
            # Odpowiedz HELLO_ACK
            ack_payload = self._username.encode("utf-8")
            self._send_packet(PacketType.HELLO_ACK, ack_payload, addr)
            logger.info("Odebrano HELLO od %s (%s:%d)", name, *addr)

        elif ptype == PacketType.HELLO_ACK:
            name = payload.decode("utf-8", errors="replace") if payload else "Unknown"
            self._register_peer(addr, name)
            logger.info("Połączono z %s (%s:%d)", name, *addr)

        elif ptype == PacketType.BYE:
            with self._peers_lock:
                peer = self._peers.pop(addr, None)
            if peer:
                logger.info("Peer %s rozłączył się.", peer.name)
                if self.on_peer_disconnected:
                    self.on_peer_disconnected(peer)

        elif ptype == PacketType.AUDIO:
            # Szybka ścieżka – bez locka dla audio (odczyt dict jest thread-safe w CPython)
            peer = self._peers.get(addr)
            if peer:
                peer.last_seen = time.time()
                peer.packets_received += 1

                # Wykrywanie utraty pakietów
                if peer.last_seq >= 0:
                    expected = (peer.last_seq + 1) % (2 ** 32)
                    if seq != expected:
                        lost = (seq - peer.last_seq - 1) % (2 ** 32)
                        if lost < 100:  # rozsądny zakres
                            peer.packets_lost += lost
                peer.last_seq = seq

                if self.on_audio_received:
                    self.on_audio_received(payload, addr)

        elif ptype == PacketType.PING:
            self._send_packet(PacketType.PONG, payload, addr)

        elif ptype == PacketType.PONG:
            peer = self._peers.get(addr)
            if peer and payload:
                try:
                    sent_ts = struct.unpack("!q", payload)[0]
                    peer.latency_ms = (int(time.time() * 1000) - sent_ts) / 2
                except Exception:
                    pass

        elif ptype == PacketType.KEEPALIVE:
            peer = self._peers.get(addr)
            if peer:
                peer.last_seen = time.time()

    # ------------------------------------------------------------------
    # Zarządzanie peerami
    # ------------------------------------------------------------------
    def _register_peer(self, addr: tuple[str, int], name: str):
        """Rejestruje nowego peera."""
        new_peer = None
        with self._peers_lock:
            if addr not in self._peers:
                peer = Peer(address=addr, name=name, last_seen=time.time())
                self._peers[addr] = peer
                new_peer = peer
                logger.info("Nowy peer: %s @ %s:%d", name, *addr)
            else:
                self._peers[addr].last_seen = time.time()
                self._peers[addr].name = name
        # Callback POZA lockiem – zapobiega deadlockowi z GUI
        if new_peer and self.on_peer_connected:
            self.on_peer_connected(new_peer)

    def _keepalive_loop(self):
        """Wysyła keepalive i sprawdza timeout peerów."""
        while self._running:
            time.sleep(3)

            alive_addrs = []
            dead_peers_list = []

            with self._peers_lock:
                dead_addrs = []
                for addr, peer in self._peers.items():
                    if not peer.is_alive(timeout=15.0):
                        dead_addrs.append(addr)
                    else:
                        alive_addrs.append(addr)

                for addr in dead_addrs:
                    peer = self._peers.pop(addr)
                    dead_peers_list.append(peer)
                    logger.info("Peer %s – timeout.", peer.name)

            # Callbacki i wysyłanie POZA lockiem
            for peer in dead_peers_list:
                if self.on_peer_disconnected:
                    self.on_peer_disconnected(peer)

            for addr in alive_addrs:
                self._send_packet(PacketType.KEEPALIVE, b"", addr)
                ts_bytes = struct.pack("!q", int(time.time() * 1000))
                self._send_packet(PacketType.PING, ts_bytes, addr)

    def get_peers(self) -> list[Peer]:
        """Zwraca listę podłączonych peerów."""
        with self._peers_lock:
            return list(self._peers.values())

    @property
    def peer_count(self) -> int:
        with self._peers_lock:
            return len(self._peers)
