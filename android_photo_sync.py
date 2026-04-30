#!/usr/bin/env python3
"""
Android Photo/Video Sync Script
Automatically syncs photos and videos from an Android phone to a local or
remote destination. Uses ADB for reliable file transfer and only copies
new/modified files. Supports local directories and remote SSH destinations.

INSTALLATION:
-------------
1. Install ADB (Android Debug Bridge):
   - Ubuntu/Debian:  sudo apt install adb
   - Arch/CachyOS:   sudo pacman -S android-tools
   - Fedora:         sudo dnf install android-tools
   - macOS:          brew install android-platform-tools

2. Enable USB Debugging on your Android phone:
   - Go to Settings → About Phone
   - Tap "Build Number" 7 times to enable Developer Options
   - Go to Settings → System → Developer Options
   - Enable "USB Debugging"

3. Connect your phone via USB
   - When prompted on your phone, authorize this computer

USAGE:
------
Basic sync to a folder:
    ./android_photo_sync.py ~/Pictures/Phone

Dry run (preview without copying):
    ./android_photo_sync.py --dry-run ~/Pictures/Phone

Test with limited files:
    ./android_photo_sync.py --max-files 5 ~/Pictures/Phone

Use flat directory structure (all files in one folder):
    ./android_photo_sync.py --flat ~/Pictures/Phone

Sync large library to remote (batched to save disk space):
    ./android_photo_sync.py --batch-size 50 myserver:~/backup/photos

Sync specific directories:
    ./android_photo_sync.py --dirs /sdcard/DCIM/Camera ~/Pictures/Phone

Include additional file types:
    ./android_photo_sync.py --extensions .raw .dng ~/Pictures/Phone

Sync to a remote server via SSH:
    ./android_photo_sync.py user@server.com:/path/to/photos
    ./android_photo_sync.py myserver:~/Pictures/Phone
    ./android_photo_sync.py user@192.168.1.100:~/backup/photos

View all options:
    ./android_photo_sync.py --help

NOTES:
------
- Only new or modified files are copied (like rsync)
- Consecutive runs are fast and only sync changes
- Common media directories are scanned by default
- For remote destinations, files are batched (default 100) to avoid filling local disk
- Directory structure from Android is preserved by default (use --flat for single folder)
"""

import subprocess
import sys
import os
import argparse
import tempfile
import shutil
from pathlib import Path


# Common Android directories containing photos/videos
ANDROID_MEDIA_DIRS = [
    "/sdcard/DCIM",
    "/sdcard/Pictures",
    "/sdcard/Movies",
    "/sdcard/Download",  # Sometimes screenshots/downloads contain media
]

# Media file extensions to sync
MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif',  # Photos
    '.bmp', '.tif', '.tiff', '.dng',  # Additional image formats (bitmap, TIFF, RAW)
    '.mp4', '.mkv', '.avi', '.mov', '.3gp', '.webm', '.m4v',     # Videos
}


def run_command(cmd, capture_output=True, check=True):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"Error: {e.stderr}")
        return None
    except FileNotFoundError:
        print(f"Command not found: {cmd[0]}")
        print("Please ensure the required tools are installed.")
        return None


def check_adb():
    """Check if adb is installed and accessible."""
    result = run_command(['adb', 'version'], check=False)
    if result is None or result.returncode != 0:
        print("ERROR: adb (Android Debug Bridge) is not installed or not in PATH.")
        print("\nTo install adb:")
        print("  Ubuntu/Debian: sudo apt install adb")
        print("  Arch/CachyOS:  sudo pacman -S android-tools")
        print("  Fedora:        sudo dnf install android-tools")
        return False
    return True


def check_rsync():
    """Check if rsync is installed (needed for remote destinations)."""
    result = run_command(['rsync', '--version'], check=False)
    if result is None or result.returncode != 0:
        print("ERROR: rsync is not installed or not in PATH.")
        print("\nTo install rsync:")
        print("  Ubuntu/Debian: sudo apt install rsync")
        print("  Arch/CachyOS:  sudo pacman -S rsync")
        print("  Fedora:        sudo dnf install rsync")
        return False
    return True


def is_remote_destination(dest):
    """Check if destination is a remote path (user@host:path or host:path format)."""
    if ':' not in dest:
        return False
    # If it starts with /, it's a local absolute path
    if dest.startswith('/'):
        return False
    # If : is at position 1, it could be a Windows drive letter (e.g., C:)
    colon_pos = dest.index(':')
    if colon_pos == 1:
        return False
    # Otherwise, if we have a colon, it's likely remote (host:path or user@host:path)
    return True


def check_device_connected():
    """Check if an Android device is connected via ADB."""
    result = run_command(['adb', 'devices'], check=False)
    if result is None:
        return False
    
    lines = result.stdout.strip().split('\n')
    # Skip header line and check for devices
    devices = [line for line in lines[1:] if line.strip() and 'device' in line]
    
    if not devices:
        print("ERROR: No Android device found.")
        print("\nPlease ensure:")
        print("  1. Your phone is connected via USB")
        print("  2. USB debugging is enabled on your phone")
        print("     (Settings > Developer Options > USB Debugging)")
        print("  3. You've authorized this computer on your phone")
        return False
    
    if len(devices) > 1:
        print("WARNING: Multiple devices detected. Using the first one.")
    
    device_id = devices[0].split()[0]
    print(f"✓ Device connected: {device_id}")
    return True


def list_android_files(directory):
    """List all media files in an Android directory."""
    print(f"Scanning {directory}...")
    result = run_command(['adb', 'shell', 'find', directory, '-type', 'f'], check=False)
    
    if result is None or result.returncode != 0:
        return []
    
    files = []
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        
        # Check if file has a media extension
        ext = Path(line.strip()).suffix.lower()
        if ext in MEDIA_EXTENSIONS:
            files.append(line.strip())
    
    return files


def get_remote_files(remote_dest):
    """Get a set of all files on remote destination (for check mode)."""
    if ':' not in remote_dest:
        return set()
    
    host_part, remote_path = remote_dest.rsplit(':', 1)
    
    # Use find to get all files relative to the remote path
    cmd = ['ssh', host_part, f'cd "{remote_path}" 2>/dev/null && find . -type f -printf "%P\\n" 2>/dev/null || true']
    result = run_command(cmd, check=False)
    
    files = set()
    if result and result.returncode == 0:
        for line in result.stdout.strip().split('\n'):
            if line:
                files.add(line)
    
    return files


def delete_files_from_android(file_paths, dry_run=False):
    """
    Delete files from Android device.
    
    Args:
        file_paths: List of Android file paths to delete
        dry_run: If True, only show what would be deleted
    
    Returns:
        Number of successfully deleted files
    """
    if not file_paths:
        return 0
    
    deleted = 0
    errors = 0
    
    print(f"\nDeleting {len(file_paths)} files from Android device...")
    
    for i, android_path in enumerate(file_paths, 1):
        if dry_run:
            print(f"[{i}/{len(file_paths)}] Would delete: {android_path}")
            deleted += 1
        else:
            result = run_command(['adb', 'shell', 'rm', android_path], check=False)
            if result and result.returncode == 0:
                deleted += 1
            else:
                errors += 1
                print(f"  ERROR: Failed to delete {android_path}")
    
    if not dry_run:
        print(f"✓ Deleted {deleted} files from Android")
        if errors > 0:
            print(f"✗ Failed to delete {errors} files")
    else:
        print(f"\n[DRY RUN] Would delete {deleted} files from Android")
    
    return deleted


def sync_files(source_files, dest_dir, dry_run=False, preserve_paths=False, remote_dest=None, quiet=False, remote_files=None):
    """
    Sync files from Android device to local/remote destination.
    For local: only copies files that don't exist or are newer.
    For remote: rsync handles skipping existing files.
    
    Args:
        quiet: If True, don't print individual file operations (for check mode)
        remote_files: Set of files that exist on remote (for check mode optimization)
    
    Returns:
        Tuple of (copied_count, skipped_count, errors_count, successfully_backed_up_paths)
        successfully_backed_up_paths includes both copied and skipped files
    """
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    copied = 0
    skipped = 0
    errors = 0
    successfully_copied = []  # Track files that were successfully copied
    successfully_backed_up = []  # Track all files that are backed up (copied or already exist)
    
    for i, android_path in enumerate(source_files, 1):
        if preserve_paths:
            # Preserve directory structure: remove leading /sdcard/ and keep the rest
            relative_path = android_path.lstrip('/')
            if relative_path.startswith('sdcard/'):
                relative_path = relative_path[7:]  # Remove 'sdcard/'
            local_path = dest_path / relative_path
            # Create subdirectories if needed
            local_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Flat structure: just use filename
            filename = Path(android_path).name
            local_path = dest_path / filename
        
        # For local destinations, check if file already exists
        # For remote destinations with check mode, check against remote file list
        # Otherwise we pull everything and let rsync handle deduplication
        should_copy = True
        if not remote_dest and local_path.exists():
            # Local file exists - check modification time
            result = run_command(
                ['adb', 'shell', 'stat', '-c', '%Y', android_path],
                check=False
            )
            if result and result.returncode == 0:
                try:
                    android_mtime = int(result.stdout.strip())
                    local_mtime = int(local_path.stat().st_mtime)
                    
                    if android_mtime <= local_mtime:
                        should_copy = False
                        skipped += 1
                        successfully_backed_up.append(android_path)  # Already backed up
                except (ValueError, OSError):
                    pass  # If we can't compare, copy anyway
        elif remote_dest and remote_files is not None:
            # Check mode: see if file exists on remote
            if preserve_paths:
                relative_path = android_path.lstrip('/')
                if relative_path.startswith('sdcard/'):
                    relative_path = relative_path[7:]
                check_path = relative_path
            else:
                check_path = Path(android_path).name
            
            if check_path in remote_files:
                should_copy = False
                skipped += 1
                successfully_backed_up.append(android_path)  # Already backed up on remote
        
        if should_copy:
            display_path = str(local_path.relative_to(dest_path)) if preserve_paths else local_path.name
            if not quiet:
                print(f"[{i}/{len(source_files)}] Copying: {display_path}")
            
            if not dry_run:
                # Get modification time from Android before pulling
                mtime_result = run_command(
                    ['adb', 'shell', 'stat', '-c', '%Y', android_path],
                    check=False
                )
                android_mtime = None
                if mtime_result and mtime_result.returncode == 0:
                    try:
                        android_mtime = int(mtime_result.stdout.strip())
                    except ValueError:
                        pass
                
                # Pull the file
                result = run_command(['adb', 'pull', android_path, str(local_path)], check=False)
                if result and result.returncode == 0:
                    copied += 1
                    successfully_copied.append(android_path)
                    successfully_backed_up.append(android_path)  # Successfully copied
                    # Restore the original modification time
                    if android_mtime:
                        os.utime(str(local_path), (android_mtime, android_mtime))
                else:
                    errors += 1
                    if not quiet:
                        print(f"  ERROR: Failed to copy {local_path.name}")
            else:
                if not quiet:
                    print(f"  [DRY RUN] Would copy to {local_path}")
                copied += 1
        else:
            display_path = str(local_path.relative_to(dest_path)) if preserve_paths else local_path.name
            if not quiet:
                print(f"[{i}/{len(source_files)}] Skipping (already up to date): {display_path}")
    
    return copied, skipped, errors, successfully_backed_up


def sync_to_remote(local_dir, remote_dest, dry_run=False):
    """
    Sync files from local directory to remote destination using rsync over SSH.
    """
    print(f"\nSyncing to remote destination: {remote_dest}")
    
    rsync_cmd = [
        'rsync',
        '-avz',  # archive mode, verbose, compressed
        '--progress',
        '--partial',  # keep partially transferred files
    ]
    
    if dry_run:
        rsync_cmd.append('--dry-run')
    
    # Add source and destination
    rsync_cmd.append(f"{local_dir}/")
    rsync_cmd.append(remote_dest)
    
    print(f"Running: {' '.join(rsync_cmd)}")
    print(f"  Local source:  {local_dir}/")
    print(f"  Remote dest:   {remote_dest}")
    result = run_command(rsync_cmd, capture_output=False, check=False)
    
    if result and result.returncode == 0:
        print("✓ rsync completed successfully")
        return True
    else:
        print(f"✗ rsync failed with exit code: {result.returncode if result else 'N/A'}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Sync photos and videos from Android phone to local folder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ~/Pictures/Phone
  %(prog)s --dirs /sdcard/DCIM ~/Pictures/Phone
  %(prog)s --check ~/Pictures/Phone
  %(prog)s --dry-run ~/Pictures/Phone
  %(prog)s --extensions .mp4 .mov ~/Pictures/Videos  # Only sync videos
  %(prog)s --delete-after ~/Pictures/Phone  # Delete from phone after sync
        """
    )
    parser.add_argument(
        'destination',
        help='Local or remote destination (remote: user@host:path or host:path)'
    )
    parser.add_argument(
        '--dirs',
        nargs='+',
        default=ANDROID_MEDIA_DIRS,
        help='Android directories to sync (default: common media folders)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be copied without actually copying'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check mode: only show summary of files to sync (no file listing)'
    )
    parser.add_argument(
        '--extensions',
        nargs='+',
        help='Sync only these file extensions (replaces defaults, e.g., --extensions .mp4 .mov)'
    )
    parser.add_argument(
        '--max-files',
        type=int,
        metavar='N',
        help='Limit sync to first N files (useful for testing)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        metavar='N',
        default=100,
        help='For remote sync: process N files at a time to avoid filling disk (default: 100)'
    )
    parser.add_argument(
        '--flat',
        action='store_false',
        dest='preserve_paths',
        help='Use flat directory structure instead of preserving Android paths'
    )
    parser.add_argument(
        '--delete-after',
        action='store_true',
        help='Delete files from phone after successful sync (use with caution!)'
    )
    
    args = parser.parse_args()
    
    # Replace default extensions if custom ones provided
    if args.extensions:
        MEDIA_EXTENSIONS.clear()
        for ext in args.extensions:
            if not ext.startswith('.'):
                ext = '.' + ext
            MEDIA_EXTENSIONS.add(ext.lower())
    
    print("=" * 60)
    print("Android Photo/Video Sync")
    print("=" * 60)
    print()
    
    # Pre-flight checks
    if not check_adb():
        return 1
    
    if not check_device_connected():
        return 1
    
    # Check if destination is remote
    is_remote = is_remote_destination(args.destination)
    if is_remote:
        print("Remote destination detected")
        if not check_rsync():
            return 1
    
    print()
    print("Destination:", args.destination)
    print("Scanning directories:", ', '.join(args.dirs))
    print()
    
    # Find all media files on the device
    all_files = []
    for directory in args.dirs:
        files = list_android_files(directory)
        all_files.extend(files)
    
    # Limit files if requested
    if args.max_files and args.max_files < len(all_files):
        all_files = all_files[:args.max_files]
        print(f"Limiting to first {args.max_files} files for testing")
    
    
    if not all_files:
        print("No media files found on device.")
        return 0
    
    print(f"\nFound {len(all_files)} media files")
    
    # Limit files if requested
    if args.max_files and args.max_files < len(all_files):
        all_files = all_files[:args.max_files]
        print(f"Limiting to first {args.max_files} files for testing")
    
    print()
    
    # Sync files
    if args.check:
        print("=" * 60)
        print("CHECK MODE - Counting files only")
        print("=" * 60)
        print()
    elif args.dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No files will be copied")
        print("=" * 60)
        print()
    
    # For remote destinations in check/dry-run mode, get list of existing files
    remote_files = None
    if is_remote and (args.check or args.dry_run):
        print("Fetching remote file list...")
        remote_files = get_remote_files(args.destination)
        print(f"Found {len(remote_files)} files on remote\n")
    
    # Determine working directory, args.destination
    temp_dir = None
    if is_remote:
        # For remote destinations, use batched sync to avoid filling disk
        if args.batch_size and len(all_files) > args.batch_size:
            print(f"Processing in batches of {args.batch_size} files to save disk space\n")
            total_copied = 0
            total_skipped = 0
            total_errors = 0
            all_successfully_backed_up = []  # Track all files that are backed up (copied or skipped)
            
            for batch_start in range(0, len(all_files), args.batch_size):
                batch_end = min(batch_start + args.batch_size, len(all_files))
                batch = all_files[batch_start:batch_end]
                batch_num = (batch_start // args.batch_size) + 1
                total_batches = (len(all_files) + args.batch_size - 1) // args.batch_size
                
                print(f"{'='*60}")
                print(f"Batch {batch_num}/{total_batches} (files {batch_start+1}-{batch_end})")
                print(f"{'='*60}\n")
                
                temp_dir = tempfile.mkdtemp(prefix="android_sync_")
                print(f"Using temporary directory: {temp_dir}\n")
                
                try:
                    # Pull batch from Android
                    copied, skipped, errors, successfully_backed_up = sync_files(batch, temp_dir, args.dry_run or args.check, args.preserve_paths, args.destination, quiet=args.check, remote_files=remote_files)
                    total_copied += copied
                    total_skipped += skipped
                    total_errors += errors
                    
                    # In dry-run/check mode, still track files that would be backed up
                    if args.dry_run or args.check:
                        all_successfully_backed_up.extend(successfully_backed_up)
                    # Sync batch to remote (only if not dry-run/check)
                    elif not args.dry_run and not args.check:
                        print()
                        file_count = len(list(Path(temp_dir).glob('*')))
                        print(f"Batch contains {file_count} files")
                        
                        if not sync_to_remote(temp_dir, args.destination, args.dry_run):
                            print("ERROR: Failed to sync batch to remote destination")
                            total_errors += 1
                        else:
                            # Only track for deletion if rsync succeeded
                            all_successfully_backed_up.extend(successfully_backed_up)
                finally:
                    # Clean up batch temp directory
                    if temp_dir and os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                        temp_dir = None
                
                print()
            
            # Summary
            print()
            print("=" * 60)
            if args.check:
                print("Check Complete")
            else:
                print("Sync Complete")
            print("=" * 60)
            if args.check:
                print(f"Files needing sync: {total_copied}")
                print(f"Files already synced: {total_skipped}")
            else:
                print(f"Files copied:  {total_copied}")
                print(f"Files skipped: {total_skipped}")
            if total_errors > 0:
                print(f"Errors:        {total_errors}")
            print()
            
            # Delete files from Android if requested and no errors
            if args.delete_after and not args.dry_run and not args.check and total_errors == 0:
                delete_files_from_android(all_successfully_backed_up, dry_run=False)
            elif args.delete_after and args.dry_run:
                delete_files_from_android(all_successfully_backed_up, dry_run=True)
            
            return 0 if total_errors == 0 else 1
        else:
            # Small number of files, use single batch
            temp_dir = tempfile.mkdtemp(prefix="android_sync_")
            working_dir = temp_dir
            print(f"Using temporary directory: {working_dir}\n")
    else:
        working_dir = args.destination
    
    try:
        # Pull files from Android
        copied, skipped, errors, successfully_backed_up = sync_files(all_files, working_dir, args.dry_run or args.check, args.preserve_paths, remote_dest=args.destination if is_remote else None, quiet=args.check, remote_files=remote_files)
        
        # If remote destination, sync to remote
        if is_remote and not args.dry_run and not args.check:
            print()
            # Show what's in the temp directory before rsync
            file_count = len(list(Path(working_dir).glob('*')))
            print(f"Temp directory contains {file_count} files")
            
            if not sync_to_remote(working_dir, args.destination, args.dry_run):
                print("ERROR: Failed to sync to remote destination")
                errors += 1
                successfully_backed_up = []  # Don't delete if rsync failed
        elif is_remote and (args.dry_run or args.check):
            if not args.check:
                print(f"\n[DRY RUN] Would sync {working_dir}/ to {args.destination}")
        
        # Summary
        print()
        print("=" * 60)
        if args.check:
            print("Check Complete")
        else:
            print("Sync Complete")
        print("=" * 60)
        if args.check:
            print(f"Files needing sync: {copied}")
            print(f"Files already synced: {skipped}")
        else:
            print(f"Files copied:  {copied}")
            print(f"Files skipped: {skipped}")
        if errors > 0:
            print(f"Errors:        {errors}")
        print()
        
        # Delete files from Android if requested and no errors
        if args.delete_after and not args.dry_run and not args.check and errors == 0:
            delete_files_from_android(successfully_backed_up, dry_run=False)
        elif args.delete_after and args.dry_run:
            delete_files_from_android(successfully_backed_up, dry_run=True)
        
        return 0 if errors == 0 else 1
    
    finally:
        # Clean up temporary directory
        if temp_dir and os.path.exists(temp_dir):
            print(f"Cleaning up temporary directory...")
            shutil.rmtree(temp_dir)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nSync cancelled by user.")
        sys.exit(130)
