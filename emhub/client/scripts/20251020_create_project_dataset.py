#!/usr/bin/env python
# **************************************************************************
# *
# * Authors:     J.M. De la Rosa Trevin
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 2 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'delarosatrevin@gmail.com'
# *
# **************************************************************************

""" 
This script will scan a given folder and register a new Dataset in EMhub
"""
import argparse
import os
import sys
import secrets
from pprint import pprint
from datetime import timezone, timedelta, datetime

from emtools.utils import Pretty, Color
from emhub.client import open_client, config, DataClient
from emhub.utils import datetime_from_isoformat
from emtools.metadata import MovieFiles


def create_project_dataset(dsPath):
    baseName = os.path.basename(dsPath)
    df = MovieFiles()
    df.scan(dsPath)

    data = df.info()
    data['path'] = dsPath
    acq = {
        "voltage": 300.0,
        "magnification": 165000.0,
        "pixel_size": 0.595,
        "dose": 0.038,
        "total_dose": 3.88,
        "cs": 2.7,
        "gain": "250822_164443_EER_GainReference.gain",
        "sampling": "4k"
    }

    with open_client() as dc:
        attrs = {
            'status': "special:dataset",
            'title': baseName,
            'validate': False,
            'extra': {'data': data, "acquisition": acq}
        }
        r = dc.request('create_project', {'attrs': attrs})
        pprint(r.json())


def delete_datasets(action='print'):
    with open_client() as dc:
        r = dc.request('get_projects', jsonData={'condition': 'status="special:dataset"'})
        project = r.json()[0]
        pid = project['id']

        for p in r.json():
            if action == 'delete':
                dc.request('delete_project', {'attrs': {'id': p['id']}})
            else:
                print(f"- {p['date']} {p['id']}: {p['title']}")





def main():
    delete = '--delete' in sys.argv or '-d' in sys.argv
    paths = [p for p in os.sys.argv[1:] if not p.startswith('-')]

    print("paths: ", paths)

    if delete:
        delete_datasets('delete')

    for path in paths:
        if not os.path.exists(path):
            raise Exception(f"Path '{path}' does not exist. ")

        create_project_dataset(path)



if __name__ == '__main__':
    main()





