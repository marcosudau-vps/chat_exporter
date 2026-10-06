"""Start automatic GitHub release preparation; finalization uses the protected release environment."""
import argparse
import subprocess


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--minor', action='store_true')
    group.add_argument('--major', action='store_true')
    parser.add_argument('--publish', action='store_true', help='publish GitHub release and final tag after environment approval; default: dry run')
    args = parser.parse_args(argv)
    bump = 'major' if args.major else 'minor' if args.minor else 'patch'
    subprocess.run(['gh', 'workflow', 'run', 'release.yml', '--repo', 'marcosudau-vps/chat_exporter', '--ref', 'main',
                    '-f', 'bump=' + bump, '-f', 'dry_run=' + str(not args.publish).lower()], check=True)


if __name__ == '__main__':
    main()
