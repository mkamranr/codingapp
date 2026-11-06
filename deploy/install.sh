#!/usr/bin/env bash
# First install of CodingApp IN THIS FOLDER (air-gapped, no internet). Safe to re-run (repair).
# Later upgrades: sudo ./codingapp.sh update <package>
exec bash "$(dirname "$(readlink -f "$0")")/codingapp.sh" install "$@"
