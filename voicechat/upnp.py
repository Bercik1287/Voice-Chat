"""Moduł UPnP – automatyczne przekierowanie portów z fallbackiem na wykrywanie IP online."""

import logging
import socket
import urllib.request
import json

logger = logging.getLogger(__name__)

# Próbujemy zaimportować miniupnpc
try:
    import miniupnpc
    HAS_MINIUPNPC = True
except ImportError:
    HAS_MINIUPNPC = False
    logger.warning("miniupnpc niedostępne – UPnP wyłączone.")


class UPnPManager:
    """Zarządza mapowaniem portów UPnP na routerze."""

    def __init__(self):
        if HAS_MINIUPNPC:
            self.upnp = miniupnpc.UPnP()
            self.upnp.discoverdelay = 3000  # ms
        else:
            self.upnp = None
        self.mapped_port: int | None = None
        self.external_ip: str | None = None
        self.local_ip: str | None = None
        self._discovered = False
        self._upnp_available = False

    # ------------------------------------------------------------------
    # Wykrywanie zewnętrznego IP (działa zawsze, bez UPnP)
    # ------------------------------------------------------------------
    def detect_external_ip(self) -> str | None:
        """Wykrywa zewnętrzne IP przez serwisy internetowe.

        Returns:
            Zewnętrzne IP lub None.
        """
        services = [
            ("https://api.ipify.org", lambda r: r.strip()),
            ("https://checkip.amazonaws.com", lambda r: r.strip()),
            ("https://ifconfig.me/ip", lambda r: r.strip()),
        ]
        for url, parser in services:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "VoiceChat/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    ip = parser(resp.read().decode("utf-8"))
                    if ip and self._is_valid_ip(ip):
                        self.external_ip = ip
                        logger.info("Zewnętrzne IP (wykryte online): %s", ip)
                        return ip
            except Exception:
                continue

        logger.warning("Nie udało się wykryć zewnętrznego IP.")
        return None

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Sprawdza czy string to poprawny adres IPv4."""
        try:
            parts = ip.split(".")
            return len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts)
        except (ValueError, AttributeError):
            return False

    # ------------------------------------------------------------------
    # Odkrywanie urządzeń UPnP
    # ------------------------------------------------------------------
    def discover(self) -> bool:
        """Szuka bramki UPnP w sieci lokalnej.

        Returns:
            True jeśli znaleziono bramkę IGD.
        """
        if not HAS_MINIUPNPC or not self.upnp:
            logger.warning("miniupnpc niedostępne – pomijam UPnP.")
            return False

        try:
            logger.info("Szukam urządzeń UPnP w sieci...")
            devices = self.upnp.discover()
            logger.info("Znaleziono %d urządzeń UPnP.", devices)

            if devices == 0:
                logger.warning("Brak urządzeń UPnP w sieci.")
                return False

            self.upnp.selectigd()  # wybierz Internet Gateway Device
            self.external_ip = self.upnp.externalipaddress()
            self.local_ip = self.upnp.lanaddr
            self._discovered = True
            self._upnp_available = True

            logger.info("Zewnętrzne IP (UPnP): %s", self.external_ip)
            logger.info("Lokalne IP:           %s", self.local_ip)
            return True
        except Exception as exc:
            logger.warning("UPnP niedostępne: %s", exc)
            logger.info("Router nie obsługuje UPnP lub usługa jest nieaktywna.")
            self._discovered = False
            self._upnp_available = False
            return False

    # ------------------------------------------------------------------
    # Mapowanie portu
    # ------------------------------------------------------------------
    def add_port_mapping(
        self,
        internal_port: int,
        external_port: int | None = None,
        protocol: str = "UDP",
        description: str = "VoiceChat",
        duration: int = 0,
    ) -> int | None:
        """Dodaje przekierowanie portu na routerze.

        Returns:
            Numer zmapowanego portu zewnętrznego lub None w przypadku błędu.
        """
        if not self._upnp_available:
            if not self.discover():
                return None

        if external_port is None:
            external_port = internal_port

        try:
            existing = self.upnp.getspecificportmapping(external_port, protocol)
            if existing:
                logger.warning(
                    "Port %d/%s jest już zmapowany: %s", external_port, protocol, existing
                )
                if existing[0] == self.local_ip and existing[1] == internal_port:
                    self.mapped_port = external_port
                    return external_port
                external_port = self._find_free_external_port(protocol, external_port)

            result = self.upnp.addportmapping(
                external_port, protocol, self.local_ip,
                internal_port, description, "", duration,
            )

            if result:
                self.mapped_port = external_port
                logger.info(
                    "Zmapowano port %s:%d -> %s:%d (%s)",
                    self.external_ip, external_port,
                    self.local_ip, internal_port, protocol,
                )
                return external_port
            else:
                logger.error("addportmapping zwrócił False.")
                return None

        except Exception as exc:
            logger.error("Błąd mapowania portu: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Usuwanie mapowania
    # ------------------------------------------------------------------
    def remove_port_mapping(
        self,
        external_port: int | None = None,
        protocol: str = "UDP",
    ) -> bool:
        """Usuwa przekierowanie portu z routera."""
        if external_port is None:
            external_port = self.mapped_port
        if external_port is None:
            return False
        try:
            self.upnp.deleteportmapping(external_port, protocol)
            logger.info("Usunięto mapowanie portu %d/%s.", external_port, protocol)
            if external_port == self.mapped_port:
                self.mapped_port = None
            return True
        except Exception as exc:
            logger.error("Błąd usuwania mapowania: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _find_free_external_port(
        self, protocol: str, start: int = 50000, max_tries: int = 100
    ) -> int:
        """Szuka wolnego portu zewnętrznego."""
        for port in range(start, start + max_tries):
            existing = self.upnp.getspecificportmapping(port, protocol)
            if not existing:
                return port
        raise RuntimeError("Nie znaleziono wolnego portu zewnętrznego.")

    def get_external_address(self) -> tuple[str, int] | None:
        """Zwraca (external_ip, external_port) lub None."""
        if self.external_ip and self.mapped_port:
            return (self.external_ip, self.mapped_port)
        return None

    def get_local_ip(self) -> str:
        """Zwraca adres IP w sieci lokalnej."""
        if self.local_ip:
            return self.local_ip
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            self.local_ip = ip
            return ip
        finally:
            s.close()

    @property
    def is_upnp_available(self) -> bool:
        """Czy UPnP działa na routerze."""
        return self._upnp_available

    def cleanup(self):
        """Usuwa mapowania przy zamykaniu."""
        if self.mapped_port and self._upnp_available:
            self.remove_port_mapping()

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass
