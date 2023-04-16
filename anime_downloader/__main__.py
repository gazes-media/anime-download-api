from time import sleep

from simple_term_menu import TerminalMenu  # type: ignore

from .downloader import download_form_m3u8, get_available_qualities, get_m3u8


def main():
    raw_url = input("Episode URL (from neko-sama): ")
    ctx = get_m3u8(raw_url)
    qualities = get_available_qualities(ctx)
    options = list(qualities.keys())
    terminal_menu = TerminalMenu(options)
    print("Select a quality:")
    menu_entry_index = terminal_menu.show()
    if not isinstance(menu_entry_index, int):
        return
    print("Selected quality:", options[menu_entry_index])
    output = input("Output file name (include extension): ")
    print("Your download is about to start...")
    process = download_form_m3u8(qualities[options[menu_entry_index]], output)

    while process.poll() is None:
        print("Downloading... No eta.")
        sleep(2)


if __name__ == "__main__":
    main()
