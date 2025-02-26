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
import json
import os
from glob import glob
import numpy as np
import base64

import mrcfile
from emtools.utils import Path, Timer, Pretty
from emtools.metadata import StarFile, EPU, SqliteFile, RelionStar
from emtools.image import Thumbnail

from ..base import SessionRun, SessionData, hours
from .runs import RelionRun

location = os.path.dirname(__file__)


class RelionSessionData(SessionData):
    """
    Adapter class for reading Session data from Relion OTF
    """
    def __init__(self, *args, **kwargs):
        SessionData.__init__(self, *args, **kwargs)
        with open(self.join('session.json')) as f:
            session = json.load(f)
            for k in ['movies', 'micrographs', 'coordinates', 'classes2d']:
                setattr(self, k, self.join(session[k]))

        pipelineStar = self.join('default_pipeline.star')
        self.workflow = RelionStar.pipeline_to_workflow(pipelineStar)

        with StarFile(self.movies) as sf:
            self.movDataTable = sf.getTable('movies')

        with StarFile(self.micrographs) as sf:
            self.micOpticsTable = sf.getTable('optics')
            self.micDataTable = sf.getTable('micrographs')

    def get_stats(self):

        def _stats_from_table(table, attribute):
            s = {'count': len(table)}

            if attribute != 'count':
                firstRow, lastRow = table[0], table[-1]
                try:
                    first = self.mtime(getattr(firstRow, attribute))
                    last = self.mtime(getattr(lastRow, attribute))
                    h = hours(first, last)
                except:
                    first = last = h = 0
                s.update(hours=h, first=first, last=last)
            return s

        if not self.movies:
            return {'movies': {'count': 0}, 'ctfs': {'count': 0}}

        countEpu = 0

        if epuData := self.getEpuData():
            moviesTable = epuData.moviesTable
            first = moviesTable[0].timeStamp
            last = moviesTable[-1].timeStamp
            countEpu = moviesTable.size()
            msEpu = {
                'count': countEpu, 'first': first, 'last': last,
                'hours': hours(first, last)
            }
        else:
            msEpu = None

        msImport = _stats_from_table(self.movDataTable, 'rlnMicrographMovieName')
        movieStats = msEpu if countEpu > msImport['count'] else msImport
        print(">>>> DEBUG: ", movieStats)

        return {
            'movies': movieStats,
            'ctfs': _stats_from_table(self.movDataTable, 'rlnMicrographName'),
            'classes2d': len(self.get_classes2d_runs()),
            'coordinates': {'count': sum(row.rlnCoordinatesNumber for row in self.micDataTable)}
        }

    def get_micrographs(self):
        """ Return an iterator over the micrographs' CTF information. """
        for row in self.micDataTable:
            yield {
                'micrograph': row.rlnMicrographName,
                'ctfImage': row.rlnCtfImage,
                'ctfDefocus': row.rlnDefocusU,
                'ctfResolution': min(row.rlnCtfMaxResolution, 10),
                'ctfDefocusAngle': row.rlnDefocusAngle,
                'ctfAstigmatism': row.rlnCtfAstigmatism
            }

    def get_ctfs_runid(self):
        """ Return the run_id for the ctfs used for the general session overview. """
        return self.micrographs

    def get_workflow(self):
        protList = []
        status_map = {
            'Succeeded': 'finished',
            'Running': 'running',
            'Aborted': 'aborted',
            'Failed': 'failed'
        }

        for job in self.workflow.jobs():
            links = []
            for o in job.outputs:
                for c in o.childs:
                    links.append(c.id)

            protList.append({
                'id': job.id,
                'label': job['alias'],
                'links': links,
                'status': status_map.get(job['status'], job['status']),
                'type': job['jobtype']
            })

        return protList

    def get_run(self, runId):
        print(">>> runId: ", runId)
        parts = runId.split('/')
        rid = '/'.join(parts[-3:-1])
        return RelionRun(self, self.join(rid), self.workflow.getJob(rid),
                         data=runId)

    def get_classes2d_runs(self):
        runs = []
        for d in sorted(os.listdir(os.path.join(self.classes2d, 'Classes2D'))):
            if d.startswith('batch'):
                runs.append(d)
        return runs

    def get_classes2d_from_run(self, runId=None):
        """ Iterate over 2D classes. """
        runs2d = self.get_classes2d_runs()
        if runId is None:
            items = []
        else:
            batch = runs2d[runId]
            p = os.path.join(self.classes2d, 'Classes2D', batch, '*_classes.mrcs')
            items = self.get_classes2d_data(pattern=p, root=self.path)
        return {
            'runs': [{'id': i, 'label': r} for i, r in enumerate(runs2d)],
            'items': items,
            'selection': []
        }

    def get_classes2d(self, runId=None):
        return self.get_classes2d_from_run(runId=runId)

    @classmethod
    def get_classes2d_data(cls, **kwargs):
        """ Get classes information from a relion *classes.mrcs files pattern. """
        items = []
        root = kwargs.get('root', './')
        avgThumb = Thumbnail(max_size=(128, 128), output_format='base64')
        dataStar = modelStar = None

        if pattern := kwargs.get('pattern', None):
            if files := glob(pattern):
                files.sort()
                avgMrcs = files[-1]
                dataStar = avgMrcs.replace('_classes.mrcs', '_data.star')
                modelStar = dataStar.replace('_data.', '_model.')
                modelTable = 'model_classes'
        else:
            dataStar = kwargs.get('dataStar', None)
            modelStar = kwargs.get('modelStar', None)
            modelTable = kwargs.get('modelTable', '')
            avgMrcs = None

        if dataStar and modelStar:
            with StarFile(dataStar) as sf:
                n = sf.getTableSize('particles')

            lastFn = None
            mrc_stack = None

            with StarFile(modelStar) as sf:
                for row in sf.getTable(modelTable, guessType=False):
                    i, fn = row.rlnReferenceImage.split('@')
                    if mrc_stack is None:
                        avgMrcs = avgMrcs or os.path.join(root, avgMrcs)
                        mrc_stack = mrcfile.open(avgMrcs, permissive=True)
                    items.append({
                        'id': '%03d' % int(i),
                        'size': round(float(row.rlnClassDistribution) * n),
                        'average': avgThumb.from_array(mrc_stack.data[int(i) - 1, :, :])
                    })
            items.sort(key=lambda c: c['size'], reverse=True)
            mrc_stack.close()

        return items

    def coords_from_row(self, row):
        """ Iterate coordinates from a row containing the STAR file
         path with the coordinates. """
        coordStar = self.join(row.rlnMicrographCoordinates)
        with StarFile(coordStar) as sf:
            for c in sf.iterTable(''):
                yield c

    def load_micrograph_data(self, micId, micsStar):
        row = self.micDataTable[micId - 1]
        micThumb = Thumbnail.Micrograph()
        micFn = self.join(row.rlnMicrographName)
        micThumbBase64 = micThumb.from_mrc(micFn)
        pixelSize = self.micOpticsTable[0].rlnMicrographPixelSize

        # FIXME The following assumes a 1-1 mov-mic and the same order
        movFn = self.movDataTable[micId - 1].rlnMicrographMovieName

        loc = EPU.get_movie_location(movFn)
        print(">>>> DEBUG: LOC = ", loc)

        micData = {
            'micThumbData': micThumbBase64,
            'coordinates': [],  # Check for picking
            'micThumbPixelSize': pixelSize * micThumb.scale,
            'pixelSize': pixelSize,
            'gridSquare': loc['gs'],
            'foilHole': loc['fh']
        }

        if hasattr(row, 'rlnCtfImage'):
            psdThumb = Thumbnail.Psd()
            psdFn = self.join(row.rlnCtfImage).replace(":mrc", "")
            ctfProfile = psdFn.replace('.ctf', '_avrot.txt')

            if os.path.exists(ctfProfile) and ctfProfile.endswith('_avrot.txt'):
                with open(ctfProfile) as f:
                    ctfPlot = [line.split() for line in f
                               if not line.startswith('#')]
            else:
                ctfPlot = []

            micData.update({
                'psdData': psdThumb.from_mrc(psdFn),
                'ctfDefocusU': round(row.rlnDefocusU / 10000., 2),
                'ctfDefocusV': round(row.rlnDefocusV / 10000., 2),
                'ctfDefocusAngle': round(row.rlnDefocusAngle, 2),
                'ctfAstigmatism': round(row.rlnCtfAstigmatism / 10000, 2),
                'ctfResolution': round(row.rlnCtfMaxResolution, 2),
                'ctfPlot': ctfPlot
            })

        return micData

    def get_micrograph_coordinates(self, pickStar, micId):
        row = self.micDataTable[micId - 1]
        return [(round(c.rlnCoordinateX), round(c.rlnCoordinateY))
                for c in self.coords_from_row(row)]

    def load_coordinates_values(self, coordStar, index=False):
        data_values = {
            'numberOfParticles': {
                'label': 'Particles',
                'color': '#852999',
                'data': []
            },
            'averageFOM': {
                'data': []
            },
            'default_y': 'numberOfParticles',
            'default_color': 'averageFOM',
            'has_particles': True
        }
        # TODO: Write this info in a star file to avoid recalculating all the time
        pts = data_values['numberOfParticles']['data']
        fom = data_values['averageFOM']['data']
        indexes = []

        with StarFile(coordStar) as sf:
            for i, row in enumerate(sf.iterTable('coordinate_files')):
                indexes.append(i + 1)
                n = 0
                fomSum = 0
                for c in self.coords_from_row(row):
                    n += 1
                    fomSum += c.rlnAutopickFigureOfMerit
                pts.append(n)
                fom.append(fomSum / n)

        if index:
            data_values.update({
                'index': {'label': 'Index', 'data': indexes},
                'default_x': 'index'
            })

        return data_values

    def load_ctf_values(self, ctfStar, index=False):
        possible_labels = {
            'rlnDefocusU': {
                'label': 'Defocus U',
                'scale': 0.0001,
                'unit': 'µm',
                'color': '#852999',
                'maxX': 4,
                'data': []
            },
            'rlnDefocusV': {
                'label': 'Defocus V',
                'scale': 0.0001,
                'unit': 'µm',
                'color': '#852999',
                'maxX': 4,
                'data': []
            },
            'rlnCtfFigureOfMerit': {
                'data': []
            },
            'rlnCtfMaxResolution': {
                'color': '#EF9A53',
                'label': 'Resolution',
                'unit': 'Å',
                'data': []
            },
            'rlnCtfIceRingDensity': {
              'label': 'Ice Ring Density',
              'data': []
            }}
        data_values = {
            'default_y': 'rlnCtfMaxResolution',
            'default_x': '',
            'has_ctf': True
        }
        indexes = []
        with StarFile(ctfStar) as sf:
            ti = sf.getTableInfo('micrographs')
            for k, v in possible_labels.items():
                if ti.hasColumn(k):
                    data_values[k] = v

            for i, row in enumerate(sf.iterTable('micrographs')):
                indexes.append(i + 1)
                rowDict = row._asdict()
                for k, v in data_values.items():
                    if isinstance(v, dict):
                        scale = v.get('scale', 1)
                        v['data'].append(rowDict[k] * scale)
        if index:
            data_values.update({
                'index': {'label': 'Index', 'data': indexes},
                'default_x': 'index'
            })

        return data_values

    def get_volume_data(self, volName, **kwargs):
        volPath = self.join(volName)

        if not os.path.exists(volPath):
            raise Exception("Volume path %s does not exists." % volPath)

        data = {}
        volume_data = kwargs.get('volume_data', 'info')

        mrc = mrcfile.open(volPath, permissive=True)
        zdim, ydim, xdim = mrc.data.shape
        data['path'] = volPath
        data['dimensions'] = [xdim, ydim, zdim]

        if volume_data == "info":
            return data

        if "slices" in volume_data:
            axis = kwargs.get('axis', 'z')

            slice_dim = kwargs.get('slice_dim', 128)
            volThumb = Thumbnail(max_size=(slice_dim, slice_dim),
                                 output_format='base64',
                                 min_max=(mrc.data.min(), mrc.data.max()))
            if slice_number := kwargs.get('slice_number', None):
                # Do not take slices from star/end since they are usually empty
                n4 = np.round(xdim / 4)
                idx = np.round(np.linspace(n4, xdim - n4, slice_number)).astype(int)
                pass
            else:
                slice_number = min(xdim, slice_dim)
                idx = np.round(np.linspace(0, xdim - 1, slice_number)).astype(int)

            slices = {}

            if 'x' in axis:
                slices['x'] = {int(i): volThumb.from_array(mrc.data[:, :, i])
                               for i in idx}
            if 'y' in axis:
                slices['y'] = {int(i): volThumb.from_array(mrc.data[:, i, :])
                               for i in idx}

            if 'z' in axis:
                slices['z'] = {int(i): volThumb.from_array(mrc.data[i, :, :])
                               for i in idx}

            data.update({
                'slices': slices,
                'axis': axis
            })

        if 'array' in volume_data:
            iMax = mrc.data.max()  # min(imean + 10 * isd, imageArray.max())
            iMin = mrc.data.min()  # max(imean - 10 * isd, imageArray.min())
            im255 = ((mrc.data - iMin) / (iMax - iMin) * 255).astype(np.uint8)
            data['array'] = base64.b64encode(im255).decode("utf-8")

        #
        # else:
        #     raise Exception('Unknown volume_data value: %s' % volume_data)

        return data

    # ----------------------- UTILS ---------------------------
    def _jobs(self, jobType):
        jobs = glob(self.join(jobType, 'job*'))

        def _jobNumber(j):
            return int(j.split('/job')[1])

        jobs.sort(key=_jobNumber)

        return jobs

    def get_last_star(self, jobType, starFn):
        jobDirs = self._jobs(jobType)
        if not jobDirs:
            return None
        fn = self.join(jobDirs[-1], starFn)
        if '*' in starFn:  # it is a glob pattern, let's find the last file
            files = glob(fn)
            files.sort()
            fn = files[-1] if files else None
        return fn

    def _last_micFn(self):
        """ Return micrographs star file from the last CTF job or None
        if there is no run yet or output file.
        """
        return self.micrographs

        jobs = self._jobs('CtfFind')
        if jobs:
            micFn = self.join(jobs[-1], 'micrographs_ctf.star')
            if os.path.exists(micFn):
                return micFn
        return None
