import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPT_DIR


# ── Helpers ────────────────────────────────────────────────────────────────────
def user_home() -> Path:
    """Return the real user's home, even when the script is running under sudo."""
    import pwd
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


def get_real_uid() -> int:
    """Return the real user's UID — sudo sets SUDO_UID so we don't use root's."""
    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_uid:
        return int(sudo_uid)
    return os.getuid()


def copy_with_ownership(src: Path, dst: Path):
    """Copy a file and restore the real user's ownership when running as sudo."""
    shutil.copy2(src, dst)
    fix_ownership(dst)


def fix_ownership(path: Path):
    """Restore the real user's ownership on a file or directory under sudo."""
    if os.geteuid() == 0:
        import pwd
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            pw = pwd.getpwnam(sudo_user)
            os.chown(path, pw.pw_uid, pw.pw_gid)


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

    uid = get_real_uid()
    sfl_dir = user_home() / "Library/Application Support/com.apple.sharedfilelist"
    sfl_dir.mkdir(parents=True, exist_ok=True)

    # Quit Finder, then stop sharedfilelistd via launchctl before touching its
    # files — otherwise the running daemon overwrites whatever we copy.
    run("osascript -e 'tell application \"Finder\" to quit'")
    run(
        f"launchctl bootout gui/{uid} "
        "/System/Library/LaunchAgents/com.apple.sharedfilelistd.plist",
        check=False,
    )
    run("killall sharedfilelistd", check=False)  # belt-and-suspenders
    time.sleep(2)

    sidebar_files = [
        "com.apple.LSSharedFileList.FavoriteItems.sfl4",
        "com.apple.LSSharedFileList.FavoriteVolumes.sfl4",
        "com.apple.LSSharedFileList.ProjectsItems.sfl4",
        "com.apple.LSSharedFileList.TopSidebarSection.sfl",
    ]
    for fname in sidebar_files:
        src = CONFIG_DIR / fname
        if src.exists():
            copy_with_ownership(src, sfl_dir / fname)
        else:
            print(f"    Warning: {fname} not found in {CONFIG_DIR}, skipping.")

    # Restart the daemon so it loads our new files from a clean state.
    run(
        f"launchctl bootstrap gui/{uid} "
        "/System/Library/LaunchAgents/com.apple.sharedfilelistd.plist",
        check=False,
    )
    time.sleep(1)

    print("    Finder sidebar configured (Applications, Utilities, Users, Frameworks).")


# ── 2. Terminal theme ──────────────────────────────────────────────────────────

def setup_terminal():
    """Copy the provided Terminal plist into ~/Library/Preferences."""
    print("[2/5] Configuring Terminal...")

    src = CONFIG_DIR / "com.apple.Terminal.plist"
    if not src.exists():
        print(f"    Warning: com.apple.Terminal.plist not found in {CONFIG_DIR}, skipping.")
        return

    dst = user_home() / "Library/Preferences/com.apple.Terminal.plist"

    run("osascript -e 'tell application \"Terminal\" to quit'")
    time.sleep(1)

    shutil.copy2(src, dst)
    print("    Terminal settings applied.")


# ── 3. Keyboard shortcut: open Terminal from Finder ──────────────────────────
# Fixed shortcut: Option+Shift+\
# macOS modifier encoding:  ~ = Option   $ = Shift
TERMINAL_SHORTCUT = "~$\\"


def setup_terminal_shortcut():
    """
    Install the 'New Terminal Here' Automator Quick Action and bind it to
    Option+Shift+\\ in Finder.
    """
    print("[3/5] Installing 'New Terminal Here' service...")

    services_dir = user_home() / "Library/Services"
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

    # ── Register the fixed shortcut (Option+Shift+\) ───────────────────────────
    shortcut = TERMINAL_SHORTCUT

    # Method 1: Finder NSUserKeyEquivalents — binds by menu item display name,
    # the same mechanism System Settings uses for app-specific shortcuts.
    run([
        "defaults", "write", "com.apple.finder", "NSUserKeyEquivalents",
        "-dict-add", workflow_name, shortcut,
    ])

    # Method 2: pbs NSServicesStatus — enables the service in the Services /
    # context menus and records the shortcut in the Services broker database.
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

    # Force pbs to rescan services so both registrations take effect immediately.
    run("/System/Library/CoreServices/pbs -flush")
    run("killall pbs", check=False)
    print(f"    Shortcut set: Option+Shift+\\ opens Terminal at the selected folder.")


# ── 4. 'la' alias ─────────────────────────────────────────────────────────────

def setup_la_alias():
    """Append 'alias la=ls -la' to ~/.zshrc if not already present."""
    print("[4/5] Adding 'la' alias...")

    zshrc = user_home() / ".zshrc"
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
    print("  [3] Shortcut: Option+Shift+\\ opens Terminal at the selected Finder folder")
    print("  [4] Alias: 'la' = 'ls -la'  (open a new terminal to activate)")
    print("  [5] Screenshots: saved to clipboard instead of Desktop")
    print("=" * 50)


if __name__ == "__main__":
    main()
