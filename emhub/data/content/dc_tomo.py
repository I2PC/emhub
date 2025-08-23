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
import shutil
import random

from emtools.utils import Path, FolderManager, Process, Pretty
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
    def tomo_export(**kwargs):
        tomo_session = json.loads(kwargs['tomo_session'])
        tomograms = json.loads(kwargs.get('tomograms'))
        session_path = tomo_session['path']
        s = FolderManager(session_path)
        newTomoFolder = s.join(tomo_session['tomograms'] + '_selection')

        if os.path.exists(newTomoFolder):
            raise Exception(f"Selection folder '{newTomoFolder}' already exists.")

        os.mkdir(newTomoFolder)
        for t in tomograms:
            shutil.copy(t, newTomoFolder)

        return {
            'message': f'Exported {len(tomograms)} tomograms to folder {newTomoFolder}'
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
            # FIXME
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
                    'md': tstar,  #os.path.basename(tstar),
                    'coords_md': coordMd,
                    'coords_n': coordN,
                    'tomo_fn': tomoFn,
                    'aligned_ts': alignedTs,
                    'tomo_xml': tomoXml,
                    'defocus': defocus
                })

                if len(tomograms) == 10000:
                    break

        return data

    # FIXME: More benchmark_ functions to a separate place
    def get_benchmarks():
        return dc.app.dm.get_config('benchmarks')['benchmarks']

    def get_benchmark_by_id(benchmark_id):
        for bname, benchmark in get_benchmarks().items():
            if benchmark_id == benchmark['id']:
                return bname, benchmark

    @dc.content
    def benchmark_sessions_list(**kwargs):
        return {
            'benchmarks': get_benchmarks()
        }

    @dc.content
    def benchmark_session(**kwargs):
        data = {}
        if bid := kwargs.get('benchmark_session_id', ''):
            bname, benchmark = get_benchmark_by_id(bid)
            data = benchmark_session_content(benchmark_session=json.dumps(benchmark))
            data['title'] = bname

        return data

    @dc.content
    def benchmark_usage_plot(**kwargs):
        series = None
        tseries = {'name': 'total', 'id': 'total', 'data': []}

        gpu_monitor_file = kwargs['file_path']
        with open(gpu_monitor_file) as f:
            gpu_usage = json.load(f)
            for row in gpu_usage['rows']:
                tsStr, rowData = row
                ts = Pretty.parse_datetime(tsStr.split('.')[0]).timestamp() * 1000
                if not series:
                    series = [{
                        'name': f"gpu-{g}",
                        'id': f"gpu-{g}",
                        'data': []
                    } for g in rowData]
                t = 0
                for g, values in rowData.items():
                    try:
                        u = float(values[0])
                    except:
                        u = 0
                    t += u
                    series[int(g)]['data'].append([ts, u])
                tseries['data'].append([ts, t])

        series.insert(0, tseries)

        return {'plot': {'series': series}}

    @dc.content
    def benchmark_session_content(**kwargs):
        benchmark = json.loads(kwargs['benchmark_session'])
        series = []
        categories = None

        def _elapsed(s):
            if s['START'] and s['END']:
                start = Pretty.parse_datetime(s['START'])
                end = Pretty.parse_datetime(s['END'])
                return (end - start).seconds / 60
            else:
                return 0

        for r in benchmark['runs']:
            series.append({
                'name': r['label'],
                'data': [_elapsed(s) for s in r['steps']]})
            categories = [s['JOBNAME'] for s in r['steps']]
            for s in r['steps']:
                gpu_monitor = s['JOBID'].replace('job', 'gpu_monitor_') + '.json'
                if os.path.exists(os.path.join(r.get('path', ''), gpu_monitor)):
                    s['gpu_monitor'] = gpu_monitor

        return {
            'benchmark': benchmark,
            'plot': {
                'series': series,
                'categories': categories
            }
        }




