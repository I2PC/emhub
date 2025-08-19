#!/usr/bin/env python
# **************************************************************************
# *
# * Authors:     J.M. de la Rosa Trevin (delarosatrevin@gmail.com)
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# **************************************************************************

"""
Check the defocus values of the current active sessions. If there are streak
with a number of micrographs with defocus greater that a value, a notification
email will be sent.
"""

import os
import sys
import argparse
import json
import numpy as np
from datetime import timedelta, datetime
from pprint import pprint

from emtools.utils import Color, Process, Pretty, FolderManager
from emhub.client import open_client
from emtools.metadata import StarFile


def _analyzeMicStar(micFn, startIndex=0):
    print(f">>>>>>>> DEBUG: MicFn: {micFn}, starting index: ", startIndex)

    lines = ''

    with StarFile(micFn) as sf:
        size = sf.getTableSize('micrographs')
        bad_count = 0
        bad_streak = False
        N = 50
        values = np.zeros(N)
        lastIndex = startIndex
        # Check how many "bad" resolution values in a running windows of N
        for i, row in enumerate(sf.iterTable('micrographs', start=startIndex)):
            index = i % N
            bad_count -= values[index]  # Remove the contribution of the old value
            v = 1 if row.rlnCtfMaxResolution > 6 else 0
            bad_count += v
            values[index] = v
            if bad_count > 30:
                bad_streak = True
            lastIndex = startIndex + i

    if bad_streak:
        lines = f" >>> Micrographs: {micFn}: {size}\n"
        lines += f"     bad_streak: {bad_streak}"

    return lines, lastIndex


def check_sessions(dc, sessions, status):
    from pprint import pprint
    now = datetime.now()
    headers = ["SESSION_ID", "IMAGES", "OTF"]
    format_str = u'{:<15}{:<15}{:<30}'
    print(format_str.format(*headers))
    errors = {}
    last_check = status.get('last_check', None)
    if last_check:
        last_check = Pretty.parse_datetime(last_check)
        print(f">>> Last check: {Pretty.datetime(last_check)}")
    else:
        print(f">>> No previous check.")

    status['last_check'] = Pretty.datetime(now)
    status_sessions = status.get('sessions', {})

    for s in sessions:
        body = ''
        sid = s['id']
        ssid = str(sid)
        extra = s['extra']
        otf = extra.get('otf', {})
        raw = extra.get('raw', {})
        movies = raw.get('movies', 0)
        macPath = ""
        otfStr = ""

        if not otf:
            otfStr = 'BAD:NO-OTF:'
        elif isinstance(otf, dict):
            path = otf.get('path', 'BAD:NONE:')
            macPath = path.replace('/jude/facility/', '/Volumes/cryo_facility/')

            if os.path.exists(macPath):
                # fn, dt = Path.lastModified(macPath)
                s = os.stat(macPath)
                dt = datetime.fromtimestamp(s.st_mtime)
                otfStr = f"{path} ({Pretty.elapsed(dt)})"
            else:
                f'BAD: MISSING {path}'
        else:
            otfStr = f'OTF: {str(otf)}, type: {type(otf)}'

        if not movies:
            continue  # ignore sessions with 0 movies

        lineStr = format_str.format(sid, movies, otfStr)
        micLine = ''

        color = Color.red
        if not otfStr.startswith('BAD:'):
            color = Color.green
            fm = FolderManager(macPath)
            micFn = 'External/job002/micrographs.star'
            if fm.exists(micFn):
                micFnPath = fm.join(micFn)
                s = os.stat(micFnPath)
                dt = datetime.fromtimestamp(s.st_mtime)
                # Ignore also sessions that have not been updated for
                # more than X days or that have not been modified since last check
                if now - dt > timedelta(days=10) and dt > last_check:
                    continue

                micLine, lastIndex = _analyzeMicStar(micFnPath, status_sessions.get(ssid, 0))
                status_sessions[ssid] = lastIndex

        if micLine:
            color = Color.red
            body += f"\n{micLine}"
            r = dc.request('get_session_users', jsonData={'attrs': {'id': sid}})
            users = r.json()['session_users']
            o = users['owner']
            body += f"\nOwner: {o['name']} ({o['email']})"
            if oo := users.get('operator', None):
                body += f"\nStaff: {oo['name']} ({oo['email']})"

        print(color(lineStr))

        if body:
            errors[sid] = body

    if errors:
        print(Color.red(f"\n>>> There are issues:"))
        for sid, body in errors.items():
            print("\n>>> Session: ", sid)
            print(body)
        # with open_client() as dc:
        #     dc.send_email(['jdela80@stjude.org'], "Update", body)

    status['sessions'] = status_sessions


def main():
    p = argparse.ArgumentParser(prog='check_sessions_defocus.py')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--session', help='Session ID')
    g.add_argument('--since', default=7,
                   help="Number of days to check sessions. "
                        "(e.g. 7 days ago)")

    p.add_argument('--defocus', '-d', default=6,
                   help="Defocus threshold to check values.")
    p.add_argument('--streak', '-s', default=30,
                   help="Defocus threshold to check values.")
    p.add_argument('--notification', '-n', default='print',
                   choices=['print', 'email'],
                   help="Type of notification")
    p.add_argument('--json', default='check_sessions_defocus.json',
                   help="JSON file containing information of previous "
                        "checks. (e.g. last micrograph or last time)")

    args = p.parse_args()

    if os.path.exists(args.json):
        with open(args.json) as f:
            print(f">>> Loading JSON file: {args.json}")
            status = json.load(f)
    else:
        print(f">>> Not JSON found, starting from scratch")
        status = {}

    with open_client() as dc:
        now = datetime.now()
        sconfig = dc.get_config('sessions')

        if session_id := args.session:
            # Only check the session specified by its id
            sessions = [dc.get_session(int(session_id))]
        else:
            # Get sessions based on time

            td = timedelta(days=int(args.since))
            sessions = dc.request('get_sessions_range',
                                 jsonData={'start': Pretty.date(now - td),
                                           'end': Pretty.date(now)}).json()

        check_sessions(dc, sessions, status)

        with open(args.json, 'w') as f:
            json.dump(status, f, indent=4)


if __name__ == '__main__':
    main()





