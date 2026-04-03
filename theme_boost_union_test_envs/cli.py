from .app import UserInterface, main as app_main


def main() -> int:
    return app_main(UserInterface.CLI)
