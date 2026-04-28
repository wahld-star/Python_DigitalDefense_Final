import plistlib
import shutil
import subprocess
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "UserSetup Assign"


def run(cmd, check=False):
    if isinstance(cmd, str):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# ── 1. Finder sidebar ─────────────────────────────────────────────────────────

def setup_finder_sidebar():
    """Copy pre-configured sidebar lists: Applications, Utilities, Users, Frameworks."""
    print("[1/5] Configuring Finder sidebar...")

    sfl_dir = Path.home() / "Library/Application Support/com.apple.sharedfilelist"
    sfl_dir.mkdir(parents=True, exist_ok=True)

    run("osascript -e 'tell application \"Finder\" to quit'")
    time.sleep(1)

    for fname in [
        "com.apple.LSSharedFileList.FavoriteItems.sfl4",
        "com.apple.LSSharedFileList.FavoriteVolumes.sfl4",
        "com.apple.LSSharedFileList.ProjectsItems.sfl4",
        "com.apple.LSSharedFileList.TopSidebarSection.sfl",
    ]:
        src = CONFIG_DIR / fname
        if src.exists():
            shutil.copy2(src, sfl_dir / fname)
        else:
            print(f"    Warning: {fname} not found in config dir, skipping.")

    print("    Finder sidebar configured (Applications, Utilities, Users, Frameworks).")


# ── 2. Terminal theme ──────────────────────────────────────────────────────────

def setup_terminal():
    """Import Terminal preferences from the provided plist."""
    print("[2/5] Configuring Terminal...")

    src = CONFIG_DIR / "com.apple.Terminal.plist"
    if not src.exists():
        print("    Warning: com.apple.Terminal.plist not found, skipping.")
        return

    dst = Path.home() / "Library/Preferences/com.apple.Terminal.plist"

    run("osascript -e 'tell application \"Terminal\" to quit'")
    time.sleep(1)

    shutil.copy2(src, dst)
    print("    Terminal settings applied.")


# ── 3. Keyboard shortcut: open Terminal from Finder ───────────────────────────

def setup_terminal_shortcut():
    """Install an Automator Quick Action that opens Terminal at the selected folder.

    The service is assigned Ctrl+Option+T. If the shortcut doesn't register
    automatically, go to System Settings > Keyboard > Keyboard Shortcuts >
    Services > Files & Folders > New Terminal Here and set it there.
    """
    print("[3/5] Creating 'Open Terminal Here' shortcut (Ctrl+Option+T)...")

    services_dir = Path.home() / "Library/Services"
    services_dir.mkdir(exist_ok=True)

    workflow_name = "New Terminal Here"
    contents_dir = services_dir / f"{workflow_name}.workflow" / "Contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    # Bundle Info.plist
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

    # Automator workflow: Run Shell Script action, pass input as arguments.
    # $1 is the POSIX path of the folder selected in Finder.
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

    # Register the keyboard shortcut via pbs (the macOS Services broker).
    # Key format: "AppName - ServiceDisplayName - MessageName"
    # Modifier encoding: ^ = Ctrl, ~ = Option, @ = Cmd, $ = Shift
    pbs_key = f"Finder - {workflow_name} - runWorkflow"
    shortcut = "^~t"  # Ctrl+Option+T

    run([
        "defaults", "write", "pbs", "NSServicesStatus",
        "-dict-add", pbs_key,
        (
            f"{{enabled_context_menu = 1; enabled_services_menu = 1; "
            f'key_equivalent = "{shortcut}"; '
            f"presentation_modes = {{ContextMenu = 1; ServicesMenu = 1;}};}}"
        ),
    ])

    # Flush pbs so it picks up the new workflow immediately
    run("/System/Library/CoreServices/pbs -flush")

    print(f"    Service '{workflow_name}' installed.")
    print("    Shortcut: Ctrl+Option+T (select a folder in Finder first).")
    print("    If the shortcut is missing, enable it in System Settings > Keyboard >")
    print("    Keyboard Shortcuts > Services > Files & Folders > New Terminal Here.")


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

    print("    Screenshots (Cmd+Shift+4 / Cmd+Shift+3) now copy to clipboard.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("       macOS New User Setup Script")
    print("=" * 50)
    print()
    print("NOTE: Terminal needs Full Disk Access for some")
    print("steps. Grant it in System Settings > Privacy &")
    print("Security > Full Disk Access if prompted.")
    print()

    setup_finder_sidebar()
    setup_terminal()
    setup_terminal_shortcut()
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
    print("  [3] Shortcut: Ctrl+Option+T opens Terminal at selected folder")
    print("  [4] Alias: 'la' = 'ls -la' (open a new terminal to activate)")
    print("  [5] Screenshots: saved to clipboard instead of Desktop")
    print("=" * 50)


if __name__ == "__main__":
    main()
