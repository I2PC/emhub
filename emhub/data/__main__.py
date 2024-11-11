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

import os
import sys
import argparse
import json

from emtools.utils import Process, Path

from .processing import get_processing_type


#TODO: move this functionality to emh-client
def dump(keys, json_file):
    from emhub.client import open_client, config

    with open_client() as dc:
        json_data = {}

        if 'forms' in keys:
            forms = dc.request('get_forms').json()
            json_data['forms'] = [{
                'id': f['id'],
                'name': f['name'],
                'definition': f['definition']
            } for f in forms]

        if 'resources' in keys:
            json_data['resources'] = dc.request('get_resources').json()

        if 'users' in keys:
            json_data['users'] = dc.request('get_users').json()

        if json_data:
            with open(json_file, 'w') as f:
                json.dump(json_data, f, indent=4)

def setup_processing(dm, instance_folder, workspaces):
    """ Create a processing instance. """
    template = """
    <!-- left sidebar -->
    <div class="nav-left-sidebar sidebar-dark">
        <div class="menu-list">
            <nav class="navbar navbar-expand-lg navbar-light">
                <a class="d-xl-none d-lg-none" href="#">Dashboard</a>
                <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav" aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="navbarNav">
                    <ul class="navbar-nav flex-column">

                        <li class="nav-divider"> MAIN </li>

                        <ul class="nav flex-column submenu">
                            <li class="nav-item">
                                <a class="nav-link" href="{{ url_for_content('processing_dashboard') }}">
                                    <i class="fas fa-tachometer-alt"></i>Processing Dashboard</a>
                            </li>

                        </ul>

                </div>
            </nav>
        </div>
    </div>
    <!-- end left sidebar -->
    """
    print("processing instance created!")
    extra_folder = os.path.join(instance_folder, 'extra', 'templates') 
    Process.Logger().mkdir(extra_folder) 
    with open(os.path.join(extra_folder, 'main_left_sidebar.html'), 'w') as f:
        f.write(template)

    for ws in workspaces:
        projects = []
        for d in os.listdir(ws):
            folder = os.path.join(ws, d)
            if get_processing_type(folder) != 'unknown':
                projects.append(folder)
        
        if projects:
            
            print("Creating workspace :", ws)
            p = dm.create_project(
                user_id=1,  #FIXME
                status='special:processing',
                user_can_edit=True,
                is_confidential=False,
                title=os.path.basename(Path.rmslash(ws)),
                description="Workspace imported from " + ws
            )
            for proj_folder in projects:
                print("   - creating project: ", proj_folder)
                dm.create_entry(project_id=p.id,
                        type='data_processing',
                        extra={"data": {"project_path": proj_folder}})


def main():
    p = argparse.ArgumentParser(prog='emh-data')
    g = p.add_mutually_exclusive_group()

    g.add_argument('--create_instance', nargs='*',
                   metavar=('FOLDER', 'JSON_FILE'),
                   help="Create a new instance in a FOLDER from a JSON_FILE. "
                        "If not FOLDER is provided, it will use by default:"
                        "~/.emhub/instances/test. "
                        "If not JSON is provided, a default one will be "
                        "created with some test data. ")
    g.add_argument('--create_processing', nargs='+',  metavar=('FOLDER', 'WORKSPACE_FOLDER'),
                   help="Create a new instance in FOLDER customized for "
                        "a data processing workspace. ")
    g.add_argument('--dump', nargs=2,
                   metavar=('KEYS', 'JSON_FILE'),
                   help="Dump data related to an Entity in the data model."
                        "For example: forms, resources, etc. "
                        "Write the output to a json file.")

    p.add_argument('--force', '-f', action='store_true',
                   help="Force to do some actions "
                        "(e.g. remove instance folder if existing)")

    args = p.parse_args()
    create = args.create_instance
    from emhub.data.imports import create_instance, MINIMAL_JSON

    if create is not None:
        n = len(create)
        instance_path = create[0] if n > 0 else None
        json_file = create[1] if n > 1 else None
        create_instance(instance_path, json_file, args.force)

    elif processing := args.create_processing:
        instance_path = processing[0]
        workspaces = processing[1:]

        for ws in workspaces:
            if not os.path.exists(ws):
                raise Exception(f"Workspace folder '{ws}' does not exists!")

        dm = create_instance(instance_path, MINIMAL_JSON, args.force)
        setup_processing(dm, instance_path, workspaces)

    if args.dump:
        dump(args.dump[0].split(','), args.dump[1])


if __name__ == '__main__':
    main()
