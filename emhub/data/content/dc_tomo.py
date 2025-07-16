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
        return {
            'tomo_session': DEFAULT_SESSION,
            'tomograms': []  # To be loaded
        }

    @dc.content
    def tomo_picking(**kwargs):
        return projects_list(**kwargs)

    @dc.content
    def tomo_session_content(**kwargs):
        dm = dc.app.dm

        print(kwargs, flush=True)

        tomo_session = json.loads(kwargs['tomo_session'])

        s = FolderManager(tomo_session['path'])
        picking = tomo_session['picking']
        data = {
            'errors': []
        }
        if not s.exists():
            data['errors'].append("Session path does not exist")
        else:
            for k in DEFAULT_SESSION:
                if k != 'path' and not s.exists(tomo_session[k]):
                    data['errors'].append(f"*{k}* folder does not exist.")

        if not data['errors']:
            t = FolderManager(s.join(tomo_session['tomograms']))
            c = FolderManager(s.join(picking, 'Coordinates'))
            r = FolderManager(s.join(tomo_session['reconstruction']))
            ts = FolderManager(r.path.replace('reconstruction', 'tiltstack'))

            tomograms = data['tomograms'] = []

            def _glob_file(fm, pattern):
                if files := fm.glob(pattern):
                    return files[0]
                else:
                    return ''

            for tstar in t.glob("*.tomostar"):
                tsName = Path.removeBaseExt(tstar)

                # Load coordinates file
                coordMd = _glob_file(c, tsName + '*default_particles.star')
                if coordMd:
                    with StarFile(coordMd) as sf:
                        coordN = sf.getTableSize('particles')
                else:
                    coordN = ''

                # Load xml, tomogram, and aligned TS files
                tomoFn = _glob_file(r, tsName + '*.mrc')
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

        return data



