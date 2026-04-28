import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPT_DIR  # All repo files live alongside this script


# ── Helpers ────────────────────────────────────────────────────────────────────
def user_home() -> Path:
    """Return the real user's home, even when the script is running under sudo."""
    import pwd
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()

def run(cmd, check=False):
    if isinstance(cmd, str):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# ── Permission / Full Disk Access guard ───────────────────────────────────────

def has_full_disk_access():
    """
    Check Full Disk Access by attempting to read the macOS TCC database.
    That file is always present and always FDA-gated, so a PermissionError
    means the Terminal app has not been granted Full Disk Access.
    Root always passes regardless.
    """
    if os.geteuid() == 0:
        return True  # running as root — bypasses macOS sandbox

    tcc_db = Path("/Library/Application Support/com.apple.TCC/TCC.db")
    try:
        tcc_db.read_bytes()
        return True
    except PermissionError:
        return False
    except FileNotFoundError:
        # Unusual, but if the file doesn't exist we can't use it as a gate
        return True


def enforce_permissions():
    """
    If the script cannot write to protected directories, give the user two
    remediation options before continuing:

      [1] Re-launch under sudo  (root bypasses macOS permission checks)
      [2] Open System Settings to grant Full Disk Access to Terminal, then retry
    """
    if has_full_disk_access():
        return  # nothing to do

    print()
    print("!" * 50)
    print("  Permission problem".center(50))
    print("!" * 50)
    print()
    print("This script must write to protected directories in")
    print("~/Library. Choose how to proceed:\n")
    print("  [1] Re-run automatically with sudo")
    print("      (root access bypasses the restriction — quick fix)")
    print()
    print("  [2] Grant Full Disk Access to Terminal yourself")
    print("      System Settings > Privacy & Security > Full Disk Access")
    print("      Enable Terminal, then come back and press Enter.")
    print()
    print("  [q] Quit — no changes will be made")
    print()

    choice = input("Your choice [1 / 2 / q]: ").strip().lower()

    if choice == "1":
        print("\nRe-launching with sudo — you may be asked for your password.")
        # os.execvp replaces this process entirely; sudo then re-runs the script.
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)
        # execvp never returns on success; if we reach this line something went wrong.
        print("Could not exec sudo. Try running: sudo python3 User_Setup.py")
        sys.exit(1)

    elif choice == "2":
        run("open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'")
        print()
        print("Enable Full Disk Access for Terminal in the window that opened.")
        input("Press Enter when done to continue...")
        if not has_full_disk_access():
            print("\nStill cannot access the required directories.")
            print("Try option [1] (sudo) or restart Terminal after granting access.")
            sys.exit(1)

    else:
        print("\nExiting — no changes were made.")
        sys.exit(0)


# ── 1. Finder sidebar ─────────────────────────────────────────────────────────

def setup_finder_sidebar():
    """Copy pre-configured sidebar lists: Applications, Utilities, Users, Frameworks."""
    print("[1/5] Configuring Finder sidebar...")

    # Destination is always inside the user's home Library, not the script dir.
    sfl_dir = Path.home() / "Library/Application Support/com.apple.sharedfilelist"
    sfl_dir.mkdir(parents=True, exist_ok=True)

    run("osascript -e 'tell application \"Finder\" to quit'")
    time.sleep(1)

    sidebar_files = [
        "com.apple.LSSharedFileList.FavoriteItems.sfl4",
        "com.apple.LSSharedFileList.FavoriteVolumes.sfl4",
        "com.apple.LSSharedFileList.ProjectsItems.sfl4",
        "com.apple.LSSharedFileList.TopSidebarSection.sfl",
    ]
    for fname in sidebar_files:
        src = CONFIG_DIR / fname
        if src.exists():
            shutil.copy2(src, sfl_dir / fname)
        else:
            print(f"    Warning: {fname} not found in {CONFIG_DIR}, skipping.")

    print("    Finder sidebar configured (Applications, Utilities, Users, Frameworks).")


# ── 2. Terminal theme ──────────────────────────────────────────────────────────

def setup_terminal():
    """Copy the provided Terminal plist into ~/Library/Preferences."""
    print("[2/5] Configuring Terminal...")

    src = CONFIG_DIR / "com.apple.Terminal.plist"
    if not src.exists():
        print(f"    Warning: com.apple.Terminal.plist not found in {CONFIG_DIR}, skipping.")
        return

    dst = Path.home() / "Library/Preferences/com.apple.Terminal.plist"

    run("osascript -e 'tell application \"Terminal\" to quit'")
    time.sleep(1)

    shutil.copy2(src, dst)
    print("    Terminal settings applied.")


# ── 3. Keyboard shortcut: open Terminal from Finder (interactive) ─────────────

# Maps user-friendly modifier names → macOS pbs/NSUserKeyEquivalents symbols.
# @ = Cmd  ^  = Ctrl  ~ = Option  $ = Shift
_MODIFIERS = {
    "cmd": "@", "command": "@",
    "ctrl": "^", "control": "^",
    "opt": "~", "option": "~", "alt": "~",
    "shift": "$",
}


def parse_shortcut(raw: str):
    """
    Convert a human-readable combo such as 'ctrl+option+t' into the pbs
    modifier string '^~t'. Returns None if the input cannot be parsed or
    contains no plain key character.
    """
    parts = [p.strip().lower() for p in raw.replace(",", "+").split("+")]
    modifiers = ""
    key = None

    for part in parts:
        if part in _MODIFIERS:
            symbol = _MODIFIERS[part]
            if symbol not in modifiers:   # avoid duplicates
                modifiers += symbol
        elif len(part) == 1:
            key = part
        else:
            return None  # unrecognised token

    if key is None:
        return None
    return modifiers + key


def shortcut_in_use(pbs_code: str) -> bool:
    """
    Return True if pbs_code (e.g. '^~t') appears in any of the three
    places macOS stores keyboard shortcut assignments:
      • Global NSUserKeyEquivalents
      • Finder-specific NSUserKeyEquivalents
      • pbs NSServicesStatus (already-registered services)
    """
    checks = [
        (["defaults", "read", "-g", "NSUserKeyEquivalents"],           "global shortcuts"),
        (["defaults", "read", "com.apple.finder", "NSUserKeyEquivalents"], "Finder shortcuts"),
        (["defaults", "read", "pbs", "NSServicesStatus"],              "service shortcuts"),
    ]
    for cmd, label in checks:
        result = run(cmd)
        if result.returncode == 0 and pbs_code in result.stdout:
            print(f"    Conflict: '{pbs_code}' is already used in {label}.")
            return True
    return False


def prompt_for_shortcut():
    """
    Interactively ask the user for a keyboard shortcut, validate the format,
    and verify there are no conflicts. Returns the pbs-format string or None
    if the user chooses to skip.
    """
    print()
    print("  Set a keyboard shortcut for 'New Terminal Here'")
    print("  ─────────────────────────────────────────────────")
    print("  Format: modifiers separated by '+', then the key.")
    print("  Modifiers: cmd  ctrl  opt (option)  shift")
    print("  Example:   ctrl+option+t   or   cmd+shift+t")
    print()
    print("  Press Enter with no input to skip and set it manually later.")
    print("  (System Settings > Keyboard > Keyboard Shortcuts > Services)")
    print()

    while True:
        raw = input("  Shortcut: ").strip()

        if not raw:
            print()
            print("    Skipped. The 'New Terminal Here' service is installed but")
            print("    has no shortcut. Assign one later in:")
            print("    System Settings > Keyboard > Keyboard Shortcuts >")
            print("    Services > Files & Folders > New Terminal Here")
            return None

        parsed = parse_shortcut(raw)

        if parsed is None:
            print("    Could not parse that input — try again (e.g. 'ctrl+option+t').")
            continue

        # Require at least one modifier to avoid accidental single-key capture
        if not any(sym in parsed for sym in _MODIFIERS.values()):
            print("    Include at least one modifier (ctrl, cmd, opt, shift).")
            continue

        print(f"    Checking '{raw}'  →  pbs code '{parsed}' ...")
        if shortcut_in_use(parsed):
            print(f"    '{raw}' is already in use — pick a different combination.")
            continue

        print(f"    '{raw}' is available.")
        return parsed


def setup_terminal_shortcut():
    """
    Install the 'New Terminal Here' Automator Quick Action and let the user
    choose (and validate) their own keyboard shortcut for it.
    """
    print("[3/5] Installing 'New Terminal Here' service...")

    services_dir = Path.home() / "Library/Services"
    services_dir.mkdir(exist_ok=True)

    workflow_name = "New Terminal Here"
    contents_dir = services_dir / f"{workflow_name}.workflow" / "Contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    # ── Bundle Info.plist ──────────────────────────────────────────────────────
    info = {
        "CFBundleDevelopmentRegion": "English",
        "CFBundleIdentifier": "com.user.NewTerminalHere",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": workflow_name,
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
    }
    with open(contents_dir / "Info.plist", "wb") as f:
        plistlib.dump(info, f)

    # ── Automator workflow document ────────────────────────────────────────────
    # Workflow type: Service (Quick Action) that accepts folders from Finder.
    # The "Run Shell Script" action receives the selected folder as $1 and
    # opens a new Terminal window at that path.
    wflow = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>AMApplicationBuild</key><string>521.1</string>
    <key>AMApplicationVersion</key><string>2.10</string>
    <key>AMDocumentVersion</key><string>2</string>
    <key>actions</key>
    <array>
        <dict>
            <key>action</key>
            <dict>
                <key>AMAccepts</key>
                <dict>
                    <key>Container</key><string>List</string>
                    <key>Optional</key><true/>
                    <key>Types</key>
                    <array><string>com.apple.cocoa.path</string></array>
                </dict>
                <key>AMActionVersion</key><string>2.0.3</string>
                <key>AMApplication</key>
                <array><string>Finder</string></array>
                <key>AMParameterProperties</key>
                <dict>
                    <key>COMMAND_STRING</key><dict/>
                    <key>CheckedForUserDefaultShell</key><dict/>
                    <key>inputMethod</key><dict/>
                    <key>shell</key><dict/>
                    <key>source</key><dict/>
                </dict>
                <key>AMProvides</key>
                <dict>
                    <key>Container</key><string>List</string>
                    <key>Types</key>
                    <array><string>com.apple.cocoa.path</string></array>
                </dict>
                <key>ActionBundlePath</key>
                <string>/System/Library/Automator/Run Shell Script.action</string>
                <key>ActionName</key><string>Run Shell Script</string>
                <key>ActionParameters</key>
                <dict>
                    <key>COMMAND_STRING</key>
                    <string>open -a Terminal "$1"</string>
                    <key>CheckedForUserDefaultShell</key><true/>
                    <key>inputMethod</key><integer>1</integer>
                    <key>shell</key><string>/bin/bash</string>
                    <key>source</key><string></string>
                </dict>
                <key>BundleIdentifier</key>
                <string>com.apple.automator.runshellscript</string>
                <key>CFBundleVersion</key><string>2.0.3</string>
                <key>CanShowSelectedItemsWhenRun</key><false/>
                <key>CanShowWhenRun</key><true/>
                <key>Category</key>
                <array><string>AMCategoryUtilities</string></array>
                <key>Class Name</key><string>RunShellScriptAction</string>
                <key>InputUUID</key><string>A1A2A3A4-B1B2-C1C2-D1D2-E1E2E3E4E5E6</string>
                <key>Keywords</key>
                <array>
                    <string>Shell</string>
                    <string>Script</string>
                    <string>Run</string>
                </array>
                <key>OutputUUID</key><string>F1F2F3F4-E1E2-D1D2-C1C2-B1B2B3B4B5B6</string>
                <key>UUID</key><string>01234567-89AB-CDEF-0123-456789ABCDEF</string>
                <key>UnlocalizedApplications</key>
                <array><string>Automator</string></array>
                <key>arguments</key><dict/>
                <key>isViewVisible</key><true/>
                <key>location</key><string>309.000000:253.000000</string>
                <key>nickname</key><string>Run Shell Script</string>
                <key>overrideClassCode</key><false/>
                <key>parent action</key><false/>
                <key>shouldShowSelectedItemsWhenRun</key><false/>
                <key>shouldShowWhenRun</key><true/>
            </dict>
        </dict>
    </array>
    <key>connectors</key><dict/>
    <key>workflowMetaData</key>
    <dict>
        <key>serviceInputTypeIdentifier</key>
        <string>com.apple.Automator.fileSystemObject.folder</string>
        <key>serviceOutputTypeIdentifier</key>
        <string>com.apple.Automator.nothing</string>
        <key>serviceProcessesInput</key><integer>0</integer>
        <key>workflowTypeIdentifier</key>
        <string>com.apple.Automator.servicesMenu</string>
    </dict>
</dict>
</plist>"""

    with open(contents_dir / "document.wflow", "w") as f:
        f.write(wflow)

    print(f"    Service '{workflow_name}' written to ~/Library/Services/.")

    # ── Interactive shortcut selection ─────────────────────────────────────────
    shortcut = prompt_for_shortcut()

    if shortcut:
        # Register via pbs — the macOS Services broker.
        # Key format: "AppName - ServiceDisplayName - MessageName"
        pbs_key = f"Finder - {workflow_name} - runWorkflow"
        run([
            "defaults", "write", "pbs", "NSServicesStatus",
            "-dict-add", pbs_key,
            (
                f"{{enabled_context_menu = 1; enabled_services_menu = 1; "
                f'key_equivalent = "{shortcut}"; '
                f"presentation_modes = {{ContextMenu = 1; ServicesMenu = 1;}};}}"
            ),
        ])
        # Tell pbs to reload so the shortcut takes effect immediately
        run("/System/Library/CoreServices/pbs -flush")
        print(f"    Shortcut '{shortcut}' registered.")


# ── 4. 'la' alias ─────────────────────────────────────────────────────────────

def setup_la_alias():
    """Append 'alias la=ls -la' to ~/.zshrc if not already present."""
    print("[4/5] Adding 'la' alias...")

    zshrc = Path.home() / ".zshrc"
    alias_line = "alias la='ls -la'"

    existing = zshrc.read_text() if zshrc.exists() else ""
    if alias_line in existing:
        print("    'la' alias already present in ~/.zshrc.")
        return

    with open(zshrc, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"\n# Custom aliases\n{alias_line}\n")

    print("    Added 'la' alias to ~/.zshrc. Open a new terminal to use it.")


# ── 5. Screenshots → clipboard ────────────────────────────────────────────────

def setup_screenshot_clipboard():
    """Set the default screenshot destination to the clipboard."""
    print("[5/5] Configuring screenshot settings...")

    run(["defaults", "write", "com.apple.screencapture", "target", "clipboard"])
    run("killall SystemUIServer")

    print("    Screenshots (Cmd+Shift+3 / 4) now copy to clipboard.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("       macOS New User Setup Script")
    print("=" * 50)
    print()
    print(f"Config files: {CONFIG_DIR}")
    print()

    # Gate everything behind a permission check before touching any files.
    enforce_permissions()

    setup_finder_sidebar()
    setup_terminal()
    setup_terminal_shortcut()  # interactive — pauses for user input
    setup_la_alias()
    setup_screenshot_clipboard()

    print()
    print("Restarting Finder...")
    run("open ~")

    print()
    print("=" * 50)
    print("Setup complete!")
    print()
    print("Summary of changes:")
    print("  [1] Finder sidebar: Applications, Utilities, Users, Frameworks")
    print("  [2] Terminal: custom theme applied")
    print("  [3] Service: 'New Terminal Here' installed in ~/Library/Services/")
    print("  [4] Alias: 'la' = 'ls -la'  (open a new terminal to activate)")
    print("  [5] Screenshots: saved to clipboard instead of Desktop")
    print("=" * 50)


if __name__ == "__main__":
    main()
