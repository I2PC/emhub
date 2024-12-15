# **************************************************************************
# *
# * Authors:     J.M. De la Rosa Trevin (delarosatrevin@scilifelab.se) [1]
# *
# * [1] SciLifeLab, Stockholm University
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
Update missing forms to update SLL EMhub to current released version.
"""
import os
import sys
import json
import argparse
from pprint import pprint

from emhub.client import open_client, config

from emtools.utils import Pretty, Color


def date_str(datetimeStr):
    """ Helper to retrieve the date. """
    return datetimeStr.split('T')[0]


def process_users(portal_pis):
    with open_client() as dc:
        r = dc.request('get_users', jsonData={})
        usersDict = {u['id']: u for u in r.json() if u['pi_id'] is None}

        with open(portal_pis) as f:
            portalUsers = json.load(f)

        headers = ["USERID", "USERNAME", "EMAIL", "INVOICE_REF", "address"]
        format_str = u'{:<10}{:<40}{:<30}{:<40}{:<50}'

        print(format_str.format(*headers))

        keys = ['university', 'department', 'address', 'zip', 'city', 'country']
        for user in usersDict.values():
            if ppi := portalUsers.get(user['email'], None):
                invoiceRef = ppi['invoice_ref']
                ia = ppi['invoice_address']
                addressList = [ia.get(k, '') for k in keys if ia.get(k, '').strip()]
                invoiceAddress = '\n'.join(addressList)
            else:
                continue

            user['extra']['invoice'] = {'reference': invoiceRef, 'address': invoiceAddress}
            dc.request('update_user', jsonData={'attrs': user})
            print(format_str.format(user['id'], user['email'], user['name'],
                                    invoiceRef, invoiceAddress.replace('\n', '::')))


def process_forms():
    with open_client() as dc:
        forms = dc.request('get_forms', jsonData=None).json()
        form_ids = set(f['id'] for f in forms)

        formsJson = """
        [
            {
                "id": 16, "name": "config:permissions",
                "definition": {
                    "content": {"raw": ["admin"],
                                "usage_report": ["manager", "head", "admin"]},
                     "create_booking": {
                           "arctica": ["user"],
                           "microscope": ["manager", "admin"],
                           "prep": ["user"],
                           "talos": ["user"]
                           },
                    "create_session": ["manager", "admin"],
                    "delete_booking": {"microscope": ["manager", "admin"],
                           "prep": ["user"]},
                    "projects": {"can_create": "all",
                                 "view_options": [
                                      {"key": "mine",
                                       "label": "My Projects"},
                                      {"key": "lab",
                                       "label": "Labs Projects"},
                                      {"key": "all",
                                       "label": "All Projects"}
                                ]}
                }
             },
            {
                "id": 18, "name": "config:reports",
                "definition": {"microscope_usage": {},
                        "resources": ["Solna Krios α", "Solna Krios β", "Talos"]}
             },
             {
                "id": 19, "name": "config:users",
                "definition": {
                    "extra_roles": ["staff-solna", "staff-umea" ]
                    }
            },
            {
                "id": 20, "name": "config:resources",
                "definition": {
                    "currency": "SEK", "slots": {}
                }
            }
        ]
        """
        formList = json.loads(formsJson.replace("'", '"'))

        with open_client() as dc:
            for f in formList:
                if 'id' not in f or f['id'] not in form_ids:
                    print(f">>> Creating new form\t {f['name']}")
                    dc.request('create_form', jsonData={'attrs': f})
                else:
                    print(f">>> Updating form ID={f['id']}\t {f['name']}")
                    dc.request('update_form', jsonData={'attrs': f})


def main():
    process_forms()
    process_users(sys.argv[1])


if __name__ == '__main__':
    main()
