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
Content function to visualize tomography results
"""
import os
import json
from uuid import uuid4

from emtools.utils import Path, FolderManager
from emtools.image import Thumbnail
from emtools.metadata import StarFile, WarpXml


DEFAULT_SESSION = {
    'path': '/Volumes/CoESCB/home/common/purified_ApoF_tomo_data2_processing',  #'/Volumes/CoESCB/home/common/Thermo_20250620-Sample7',
    'tomograms': 'tomostar',
    'reconstruction': 'warp_tiltseries/reconstruction',
    'picking': 'pytomOutput',
}


def register_content(dc):

    @dc.content
    def tomo_session(**kwargs):
        data = {
            'tomo_session': DEFAULT_SESSION,
            'tomograms': []  # To be loaded
        }

        if tsId := kwargs.get('tomo_session_id', ''):
            for tsession in dc.app.dm.get_config('tomo_sessions')['sessions'].values():
                if tsession['id'] == tsId:
                    data['tomo_session'] = tsession
                    data.update(tomo_session_content(tomo_session=json.dumps(tsession)))
                    break

        return data

    @dc.content
    def tomo_picking(**kwargs):
        return projects_list(**kwargs)

    @dc.content
    def tomo_sessions_list(**kwargs):
        return {
            'tomo_sessions': dc.app.dm.get_config('tomo_sessions')['sessions']
        }

    @dc.content
    def tomo_session_content(**kwargs):
        dm = dc.app.dm
        tomo_session = json.loads(kwargs['tomo_session'])
        session_path = tomo_session['path']

        s = FolderManager(session_path)
        picking = tomo_session['picking']
        data = {
            'errors': [],
            'tomograms': [],
            'session_path': session_path
        }
        if not s.exists():
            data['errors'].append("Session path does not exist")
        else:
            for k in DEFAULT_SESSION:
                if k != 'path' and not s.exists(tomo_session[k]):
                    data['errors'].append(f"*{k}* folder does not exist.")

        if not data['errors']:
            # Temporarly store all sessions in a config form
            # just a quick and dirty way to save the sessions used
            tomo_sessions = dm.get_config('tomo_sessions')
            sessions = tomo_sessions['sessions']
            if session_path not in sessions:
                tomo_session['id'] = str(uuid4())
            else:
                tomo_session['id'] = sessions[session_path]['id']

            sessions[session_path] = tomo_session
            dm.update_config('tomo_sessions', tomo_sessions)

            t = FolderManager(s.join(tomo_session['tomograms']))
            c = FolderManager(s.join(picking, 'Coordinates'))
            r = FolderManager(s.join(tomo_session['reconstruction']))
            ts = FolderManager(r.path.replace('reconstruction', 'tiltstack'))

            tomograms = data['tomograms']

            def _glob_file(fm, pattern):
                if files := fm.glob(pattern):
                    return files[0]
                else:
                    return ''

            coordsDict = {}
            if coords := c.glob('*_default_particles.star'):
                # Get the splitting token (e.g 9.52Apx)
                token = coords[0].split('_')[-3]
                coordsDict = {os.path.basename(c.split(token)[0]): c for c in coords}

            tomoDict = {}
            if tomos := r.glob('*.mrc'):
                # Get the splitting token (e.g 9.52Apx)
                suffix = tomos[0].split('_')[-1]
                tomoDict = {os.path.basename(t).replace(suffix, ''): t for t in tomos}

            for tstar in t.glob("*.tomostar"):
                tsName = Path.removeBaseExt(tstar)

                # Load coordinates file
                #coordMd = _glob_file(c, tsName + '*default_particles.star')
                tsKey = f'{tsName}_'
                coordMd = coordsDict.get(tsKey, '')

                if coordMd:
                    with StarFile(coordMd) as sf:
                        coordN = sf.getTableSize('particles')
                else:
                    coordN = ''

                # Load xml, tomogram, and aligned TS files
                #tomoFn = _glob_file(r, tsName + '*.mrc')
                tomoFn = tomoDict.get(tsKey, '')
                alignedTs = _glob_file(ts, f"{tsName}/{tsName}_aligned.mrc")
                tomoXml = _glob_file(r, f"../{tsName}.xml")

                # Load defocus
                if tomoXml:
                    ctf = WarpXml(tomoXml).getDict('TiltSeries', 'CTF', 'Param')
                    defocus = round(float(ctf['Defocus']), 2)
                else:
                    defocus = ''

                tomograms.append({
                    'md': tstar, #os.path.basename(tstar),
                    'coords_md': coordMd,
                    'coords_n': coordN,
                    'tomo_fn': tomoFn,
                    'aligned_ts': alignedTs,
                    'tomo_xml': tomoXml,
                    'defocus': defocus
                })

                if len(tomograms) == 10:
                    break

        return data



