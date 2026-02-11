#!/usr/bin/env python3
"""Voice Chat P2P – główny punkt wejścia."""

import logging
import sys

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    """Uruchamia aplikację Voice Chat."""
    from voicechat.gui import VoiceChatGUI

    app = VoiceChatGUI()
    app.run()


if __name__ == "__main__":
    main()
