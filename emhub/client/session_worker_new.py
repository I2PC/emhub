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

import json
import os
import sys
import time
import shutil
import logging
import argparse
import threading
from datetime import datetime, timedelta
from glob import glob
from collections import OrderedDict
import configparser
from pprint import pprint
import traceback
import tempfile

from emtools.utils import Pretty, Process, Path, Color, System, Timer
from emtools.metadata import EPU, MovieFiles, StarFile

from emhub.client import config
from emhub.client.worker_new import (TaskHandler, DefaultTaskHandler,
                                     CmdTaskHandler, Worker)


class SessionTaskHandler(TaskHandler):
    def __init__(self, *args, **kwargs):
        TaskHandler.__init__(self, *args, **kwargs)
        self.mf = None
        self.epu_session = None  # for EPU parsing during OTF
        self.update_session = False

        targs = self.task['args']
        self.session_id = int(targs['session_id'])
        self.session_emhub_log = f'log:session:{self.session_id}'
        self.action = targs.get('action', 'Empty-Action')

        self.session = self.get_session()
        self.info("Getting config from EMhub.")
        attrs = {"attrs": {"id": self.session_id}}

        session_users = self.request_data('get_session_users', attrs)
        self.users = session_users.get('session_users', None)

        self.sconfig = self.request_config('sessions')
        self.resources = self.request_dict('get_resources',
                                           {"attrs": ["id", "name"]})
        self.microscope = self.resources[self.session['resource_id']]['name']

        self.sleep = targs.get('sleep', 60)

        self.info(f">>> Handling task for session {self.session_id}")
        self.info(f"\t action: {self.action}")
        self.info(f"\t   args: {targs}")


    def update_log(self, event):
        data = {
            'log_id': self.session_emhub_log, 'event': event
        }
        self.update_remote('update_log', data, tries=2, wait=5)

    def process(self):
        if self.users is None:
            raise Exception("Could not retrieve users information for this session")

        func = getattr(self, self.action, None)
        if func is None:
            return self.unknown_action()

        func()
        if self.update_session:
            # Update session information
            self.session = self.get_session()

    def getLogPrefix(self):
        prefix = self.task['args']['action'].upper()
        return f"{prefix}-{self.task['args']['session_id']}"

    def update_session_extra(self, extra):
        def _update_extra():
            extra['updated'] = Pretty.now()
            self.worker.request('update_session_extra',
                                {'id': self.session['id'], 'extra': extra})
            return True

        return self._request(_update_extra, 'updating session extra')

    def delete_task(self):
        def _delete():
            self.worker.request('delete')

    def get_session(self, tries=10):
        """ Retrieve session info to update local data. """

        def _get_session():
            self.info(f"Retrieving session {self.session_id} from EMhub "
                      f"({config.EMHUB_SERVER_URL})")
            return self.dc.get_session(self.session_id)

        errorMsg = f"retrieving session {self.session_id} info."
        session = self._request(_get_session, errorMsg)

        if session:
            return session

        error = f"Could not retrieve session {self.session_id} after {tries} attempts."
        self.error(error)
        raise Exception(error)

    def unknown_action(self):
        self.update_log({
            'error': f'Unknown action {self.action}',
            'done': 1
        })
        self.stop()

    def monitor(self):
        extra = self.session['extra']
        raw = extra['raw']
        # If repeat != 0, then repeat the scanning this number of times
        repeat = self.task['args'].get('repeat', 1)

        print(Color.bold(f"session_id = {self.session['id']}, monitoring files..."))
        print(f"    path: {raw['path']}")

        if self.count == 1:
            self.mf = MovieFiles()

        self.mf.scan(raw['path'])
        update_args = self.mf.info()
        raw.update(update_args)
        self.update_session_extra({'raw': raw})

        if repeat and self.count == repeat:
            self.stop()
            update_args['done'] = 1

            if 'check_frames' in self.task['args']:
                frames = raw.get('frames', '')
                uargs = {'frames': frames}
                if os.path.exists(frames):
                    mff = MovieFiles()
                    mff.scan(frames)
                    mffInfo = mff.info()
                    uargs.update({
                        'movies': mffInfo['movies'],
                        'size': mffInfo['sizeH'],
                        'lastFile': Pretty.elapsed(mffInfo['last_file'])
                    })
                self.update_log(uargs)

        # Remove dict from the task update
        del update_args['files']
        self.update_log(update_args)

    def get_session_name(self):
        """ Strip down : for uniqueness. """
        n = self.session['name']
        return n if ':' not in n else n.split(':')[1]

    def get_session_fullname(self):
        """ Unique folder based on session name, date and instrument. """
        date_ts = self.session['start']
        date = date_ts.split('T')[0].replace('-', '')
        return f"{date}_{self.microscope}_{self.get_session_name()}"

    def transfer(self):
        """ Move files from the Raw folder to the Offload folder.
        Files will be moved when there has been a time without modification
        (file's timeout).
        """
        extra = self.session['extra']
        logger = self.worker.logger
        raw = extra['raw']
        ### framesRoot = self.sconfig['raw']['root_frames']
        acq = dict(self.sconfig['acquisition'][self.microscope])
        framesRoot = acq['frames']
        sessionName = self.get_session_name()
        framesPath = Path.rmslash(raw.get('frames',
                                          os.path.join(framesRoot, sessionName)))
        baseName = self.users['owner']['email'].split('@')[0]
        if '.' in baseName:
            parts = baseName.split('.')
            userFolder = parts[0][0] + parts[1]
        else:
            userFolder = baseName
        rawRoot = self.sconfig['raw']['root']
        fullName = self.get_session_fullname()
        # Offload server path where to transfer the files
        rawPath = os.path.join(rawRoot, self.users['group'], self.microscope,
                               str(datetime.now().year), 'raw', 'EPU',
                               userFolder, fullName)
        framesPath = Path.addslash(framesPath)
        rawPath = Path.addslash(rawPath)

        #  First time the process function is called for this execution
        if self.count == 1:
            self.info(f"Monitoring FRAMES FOLDER: {framesPath}")
            self.info(f"Offloading to RAW FOLDER: {rawPath}")

            raw['frames'] = framesPath
            raw['path'] = rawPath
            self.mf = MovieFiles(root=rawPath)
            self.seen = {}

            if os.path.exists(rawPath):
                self.info("Restarting transfer task, loading transferred files.")
                self.mf.scan(rawPath)
                raw.update(self.mf.info())
            else:
                self.info("Starting transfer task")
                self.pl.mkdir(rawPath)

            self.update_session_extra({'raw': raw})

        mf = self.mf  # shortcut
        seen = self.seen
        self.n_files = 0
        self.n_movies = 0
        self._to_move = []
        self._to_copy = []

        def _rsync(file_list, move=False):
            tries = 5
            sleep = 60
            while tries:
                try:
                    # Create a named temporary file
                    with tempfile.NamedTemporaryFile() as tmpfile:
                        logPrefix = self.getLogPrefix()
                        prefix = logPrefix + ('move' if move else 'copy')
                        debugDstFile = f"/home/appdpcryoEM/{prefix}-{os.path.basename(tmpfile.name)}"
                        if existing := [f for f in file_list if os.path.exists(f)]:
                            with open(tmpfile.name, 'w') as f:
                                for fn in existing:
                                    f.write(f"{fn.replace(framesPath, '')}\n")
                            self.pl.cp(tmpfile.name, debugDstFile)
                        args = [
                            "-c",
                            "--temp-dir=/gscem/testgrp/TRANSFER_TMP/",
                            f"--files-from={tmpfile.name}"
                        ]
                        if missing := [f for f in file_list if not os.path.exists(f)]:
                            with open(debugDstFile + '_missing.txt', 'w') as f:
                                for fn in missing:
                                    f.write(f"{fn.replace(framesPath, '')}\n")
                        if move:
                            args.append("--remove-source-files")
                        if n := Path.rsync(framesPath, rawPath, *args):
                            return n
                except Exception as e:
                    tries -= 1
                    msg = f"RSYNC error: {str(e)}, sleeping"
                    self.info(msg)
                    time.sleep(sleep)
                    sleep *= 2

            raise Exception('RSYNC could not be completed after 5 tries.')

        def _update():
            self.info(f"Found {self.n_files} new files, "
                      f"{self.n_movies} new movies, seen: {len(self.seen)}")
            if self.n_files > 0:
                t = Timer()
                copied = _rsync(self._to_copy)
                if self.n_movies:
                    moved = _rsync(self._to_move, move=True)
                else:
                    moved = 0
                elapsed = t.getElapsedTime()
                raw.update(mf.info())
                self.update_session_extra({'raw': raw})
                # Remove dict from the task update
                self.update_log({'new_files': self.n_files,
                                  'new_movies': self.n_movies,
                                  'total_files': mf.total_files,
                                  'total_movies': mf.total_movies,
                                  'moved_files': moved,
                                  'copied_files': copied,
                                  'transfer_time': str(elapsed)
                                  })
            self.n_files = 0
            self.n_movies = 0
            self._to_move = []
            self._to_copy = []

        def _gsThumb(f):
            return f.startswith('GridSquare') and f.endswith('.jpg')

        td = timedelta(minutes=1)
        transferred = False

        now = datetime.now()
        self.info(f"Scanning framesPath: {framesPath}")

        for root, dirs, files in os.walk(framesPath):
            rootRaw = root.replace(framesPath, rawPath)
            for d in dirs:
                self.pl.mkdir(os.path.join(rootRaw, d))
            for f in files:
                srcFile = os.path.join(root, f)
                dstFile = os.path.join(rootRaw, f)

                # Do not waste time on already processed files
                if dstFile in mf:
                    continue

                now = datetime.now()
                # Sometimes there are temporary files that does not
                # exist and the os.stat fails, we will ignore these entries
                try:
                    s = os.stat(srcFile)
                except:
                    continue

                unmodified = False

                # JMRT 20240130: We are having issues with the modified date in
                # the Krios G4 DMP server, where files are in the future.
                # Then changed how to detect if a file is modified or not
                if seenFile := seen.get(dstFile, None):
                    if s.st_mtime != seenFile['mt']:
                        seen[dstFile] = {'mt': s.st_mtime, 't': now}
                    elif now - seenFile['t'] >= td:
                        unmodified = True
                else:
                    seen[dstFile] = {'mt': s.st_mtime, 't': now}

                # Old way to check modification
                # dt = datetime.fromtimestamp(s.st_mtime)
                # unmodified = now - dt >= td
                if unmodified:
                    mf.register(dstFile, stat=s)
                    del seen[dstFile]
                    transferred = True
                    self.n_files += 1
                    # Register creation time of movie files
                    if EPU.is_movie_fn(f):
                        self.n_movies += 1
                        # Only move now the movies files, not other metadata files
                        self._to_move.append(srcFile)
                        # self.pl.system(f'rsync -ac --temp-dir=/gscem/testgrp/TRANSFER_TMP/ --remove-source-files "{srcFile}" "{dstFile}"', retry=30)
                    else:  # Copy metadata files
                        self._to_copy.append(srcFile)
                        # self.pl.cp(srcFile, dstFile, retry=30)

                if self.n_files >= 32:  # make frequent updates to keep otf updated
                    _update()

        # Only sleep when no data was found
        self.sleep = 0 if transferred else 60
        _update()
        self.info(f"Sleeping {self.sleep} seconds.")

        info = mf.info()
        self.framesInfo = None

        def _elapsed(key, info, days):
            if ts := info.get(f'{key}_creation', None):
                td = now - datetime.fromtimestamp(ts)
                f = info.get(key, 'No-file')
                self.info(f'{key}: {f}, '
                          f'{Pretty.timestamp(ts)} -> '
                          f'{Pretty.elapsed(ts)}')
                if td > timedelta(days=days):
                    return True
            return False

        def _stop():
            """ Check various conditions that will make the TRANSFER task
            to stop. For example, last raw file older than 3 days. """
            if self.n_files or len(self.seen):  # Do not check stop while finding new files
                return False

            frames = False
            if os.path.exists(framesPath):
                mf = MovieFiles()
                mf.scan(framesPath)
                self.framesInfo = mf.info()
                frames = _elapsed('last_file', self.framesInfo, 3)

            return (frames or
                    _elapsed('first_file', info, 5) or
                    _elapsed('last_file', info, 3))

        if _stop():
            update_args = info
            update_args['done'] = 1
            # Remove dict from the task update
            if 'files' in info:
                del update_args['files']

            if self.framesInfo:
                if int(self.framesInfo['movies']) == 0:
                    self.info(f'Stopping transfer, cleaning frames folder: '
                              f'{framesPath}.')
                    self.pl.rm(framesPath)
            self.update_log(update_args)
            self.stop()

    def __delattr__(self, __name):
        super().__delattr__(__name)

    def deliver(self):
        """ Deliver session files from GSCEM to Jude. """
        extra = self.session['extra']
        sconfig_raw = self.sconfig['raw']
        gscemPath = extra['raw'].get('path', None)
        group = self.users['group']
        gscemRoot = Path.addslash(os.path.join(sconfig_raw['root'], group))

        if self.count == 1:
            # How much time to wait before stopping this delivery task
            # from the time no more files are delivered, by default 15 days
            self.deliver_wait = timedelta(seconds=self.task['args'].get('wait', 15 * 86400))

            if last := extra.get('last_delivered', None):
                self.last_delivered = Pretty.parse_datetime(last)
            else:
                self.last_delivered = datetime.now()

        # TODO: Increment the sleeping time when there are not new files
        self.sleep = 300

        if not gscemPath:
            self.info(f"Monitoring GSCEM FOLDER: {gscemPath} "
                      f"does not exists, waiting...")
            return

        dataPath = gscemPath.replace(gscemRoot, '')
        judeRootDefault = sconfig_raw['jude_group_folder'].format(group=group)
        judeRoot = sconfig_raw['jude_group_mapping'].get(group, judeRootDefault)
        judePath = os.path.join(judeRoot, dataPath)

        if not os.path.exists(judePath):
            self.pl.mkdir(judePath)

        self.info(f"Syncing files from {gscemPath} to {judePath}")
        t = Timer()
        sleep_minutes = self.sleep // 60
        msg = ''

        try:
            n = Path.rsync(gscemPath, judePath)
        except Exception as e:
            n = -1
            msg = f"Error during the rsync: {str(e)}"
            self.info(msg)
            sleep_minutes = 5  # try soon

        if n > 0:
            self.info(f"Synced {n} files from {gscemPath} to {judePath}")
            sleep_minutes = 1
            self.last_delivered = datetime.now()
            self.update_session_extra({
                'jude': {
                    'last_delivered': Pretty.datetime(self.last_delivered)
                }})
            msg = f"Transfer time: {str(t.getElapsedTime())}"
        else:
            sleep_minutes = min(60, sleep_minutes * 2)
            msg = f"No files delivered since: {Pretty.datetime(self.last_delivered)}"
            self.info(msg)
            if datetime.now() - self.last_delivered > self.deliver_wait:
                self.info("Delivery wait ended, stopping task.")
                self.stop()

        self.sleep = sleep_minutes * 60  # Bring sleep time back to 5 minutes

        self.update_log({
            'transferred_files': n,
            'msg': msg,
            'sleeping': sleep_minutes
        })

    def stop_all_otf(self, done=False):
        return
        self.info("Stopping all OTF tasks.")
        stopped = self.worker.notify_launch_otf(self.task)
        self.info(f"Stopped: {stopped}")
        event = {'stopped_tasks': json.dumps(stopped)}
        if done:
            event['done'] = 1
            self.stop()
        self.update_log(event)

    def get_path_from(self, pathDict, referencePath, root, suffix=''):
        path = pathDict.get('path', None)
        if not path:
            folder = os.path.basename(Path.rmslash(referencePath)) + suffix
            path = os.path.join(root, folder)
        return path

    def otf(self):
        extra = self.session['extra']
        raw = extra['raw']
        self.update_session = True  # update session to check for new images

        # Debugging option to only create the OTF folder and exit
        if otf_folder := self.task['args'].get('create_otf_folder'):
            self.create_otf_folder(otf_folder, update_session=False)
            self.update_log({
                'done': 1
            })
            self.stop()
            return

        # Stop all OTF tasks running in this worker
        if 'stop' in self.task['args']:
            self.stop_all_otf(done=True)

        clear = 'clear' in self.task['args'] and self.count == 1

        if clear:
            self.stop_all_otf(done=False)

        try:
            n = raw.get('movies', 0)
            raw_path = raw.get('path', '')
            raw_exists = os.path.exists(raw_path)
            # logger = self.logger
            otf = extra['otf']
            otf_path = self.get_path_from(otf, raw_path, self.sconfig['otf']['root'],
                                          suffix='_OTF_emwrap')
            otf_exists = os.path.exists(otf_path)

            otfStr = otf_path if len(otf_path) > 4 else 'NOT READY'
            self.info(f"OTF path: {otfStr}, do clear: {clear}, movies: {n}")

            if not otf_exists or clear:
                # OTF is not running, let's check if we need to launch it
                if raw_exists and n > 8:
                    self.info(f"Launching OTF after {n} images found.")
                    self.worker.notify_launch_otf(self.task)
                    self.create_otf_folder(otf_path)
                    otf_exists = True
                    self.launch_otf()
                    self.update_log({'otf_path': otf['path'],
                                      'otf_status': otf['status'],
                                      'count': self.count})
                    self.update_session = False  # after launching no need to update
            else:
                self.update_log({'count': self.count})

            if otf_exists and raw_exists:
                # epuFolder = os.path.join(otf_path, 'EPU')
                # epuStar = os.path.join(epuFolder, 'movies.star')

                # if self.epu_session is None:
                #     self.epu_session = EPU.Session(raw_path,
                #                                    outputStar=epuStar,
                #                                    backupFolder=epuFolder,
                #                                    pl=self.pl)
                # self.epu_session.scan()
                # if not os.path.exists(epuStar):
                #     self.info(f"File {epuStar} does not exist yet.")
                # else:
                #     with StarFile(epuStar) as sf:
                #         self.info(f"Scanned EPU folder, movies: {sf.getTableSize('Movies')}")
                if self.update_session:
                    self.info(f"No longer need to update session.")
                    self.update_session = False  # after launching no need to update

        except Exception as e:
            self.worker.logger.exception(e)
            self.update_log({
                'error': f'Exception {str(e)}',
                'done': 1
            })
            self.stop()

    def create_otf_folder(self, otf_path, update_session=True):
        extra = self.session['extra']
        raw_path = extra['raw']['path']
        otf = extra['otf']
        otf.update({'path': otf_path, 'status': 'created'})
        workflow = otf.get('workflow', 'none').lower()

        self.pl.rm(otf_path)

        def _path(*paths):
            return os.path.join(otf_path, *paths)

        if workflow != 'none':
            self.pl.mkdir(os.path.join(otf_path, 'EPU'))
            os.symlink(raw_path, _path('data'))

        gain_path = os.path.dirname(self.sconfig['data']['gain'])
        acq = dict(self.sconfig['acquisition'][self.microscope])

        # Copy the gain reference file to the OTF folder and set it for processing
        # We will try to get the gain from the following places:
        # 1. From the Raw data folder (now it is copied there with EPU-Falcon4i)
        # 2. From our storage of gains
        # We will copy to the raw folder if it is not there
        # We will copy to the storage if it is not there
        gain_pattern = acq.pop('gain_pattern').format(microscope=self.microscope)

        def _last_gain(path, pattern):
            if gains := glob(os.path.join(path, pattern)):
                gains.sort(key=lambda g: os.path.getmtime(g))
                return os.path.realpath(gains[-1])
            return None

        # Check first if there is a gain in the raw folder
        raw_gain = _last_gain(raw_path, gain_pattern)
        real_gain = raw_gain or _last_gain(gain_path, gain_pattern)
        base_gain = os.path.basename(real_gain)
        self.pl.cp(real_gain, _path(base_gain))

        if not raw_gain:
            self.pl.cp(real_gain, os.path.join(raw_path, base_gain))
        else:
            # Lets backup the gain if does not exists
            back_gain = os.path.join(gain_path, base_gain)
            if not os.path.exists(back_gain):
                self.pl.cp(real_gain, back_gain)

        if workflow == 'none':
            return

        # Create a general ini file with config/information of the session
        config = configparser.ConfigParser()

        operator = self.users['operator'].get('name', 'No-operator')
        config['GENERAL'] = {
            'group': self.users['group'],
            'user': self.users['owner']['name'],
            'operator': operator,
            'microscope': self.microscope,
            'raw_data': raw_path
        }
        acq['gain'] = base_gain
        acq.update(self.session['acquisition'])
        images_pattern = acq.get('images_pattern',
                                 "Images-Disc*/GridSquare_*/Data/Foil*fractions.*")
        config['ACQUISITION'] = acq

        config['PREPROCESSING'] = {
            'images': 'data/' + images_pattern,
            'software': 'None',  # or Relion or Scipion
        }

        with open(_path('README.txt'), 'w') as configfile:
            config.write(configfile)

        if workflow == 'relion':
            opts = self.sconfig['otf']['relion']['options']
            with open(_path('relion_it_options.py'), 'w') as f:
                optStr = ",\n".join(f"'{k}' : '{v.format(**acq)}'" for k, v in opts.items())
                f.write("{\n%s\n}\n" % optStr)

        elif workflow == 'scipion':
            opts = self.sconfig['otf']['scipion']['options']
            cryolo_model = otf.get('cryolo_model', None)

            if cryolo_model:
                model = os.path.basename(cryolo_model)
                os.symlink(cryolo_model, _path(model))
                opts['picking'] = {'cryolo_model': model}

            with open(_path('scipion_otf_options.json'), 'w') as f:
                opts['acquisition'] = acq
                json.dump(opts, f, indent=4)

        elif workflow == 'emwrap':
            from emwrap.mix.otf import OTF
            OTF(otf_path).create(self.session, self.sconfig, self.resources.values())

        # Update OTF status
        if update_session:
            self.info("Updating session, otf: %s" % str(otf))
            self.update_session_extra({'otf': otf})

    def launch_otf(self):
        """ Launch OTF for a session. """
        self.info(f"Running OTF")
        otf = self.session['extra']['otf']
        otf_path = otf['path']
        workflow = otf.get('workflow', 'none').lower()
        if workflow == 'none':
            msg = 'OTF workflow is None, so no doing anything.'
            self.pl.logger.info(msg)
            self.update_log({'msg': msg, 'done': 1})
            self.stop()
        else:
            workflow_conf = self.sconfig['otf'].get(workflow, None)
            if not workflow_conf:
                raise Exception(f"Missing workflow '{workflow}' from "
                                f"sessions::config OTF section. ")

            command = workflow_conf['command']
            cmd = command.format(otf_path=otf_path, session_id=self.session['id'])
            self.pl.system(cmd + ' &')

    def stop_otf(self):
        """ Stop the thread that is doing OTF and all subprocess.
        Also update the internal dictionary of threads-sessions-tasks
        """
        self.stop()
        otf = self.session['extra']['otf']
        otf_path = otf.get('path', '')
        try:
            if otf_path:
                processes = Process.ps('scipion', workingDir=otf['path'], children=True)
                for folder, procs in processes.items():
                    self.info(f"Killing processes for Session {self.session['id']}")
                    for p in procs:
                        p.kill()
            otf['status'] = 'stopped'
            self.update_session_extra({'otf': otf})
        except Exception as e:
            self.error(Color.red("Error: %s" % str(e)))
        self.update_log({'msg': 'Forced to stop ', 'done': 1})


class FramesTaskHandler(TaskHandler):
    """ Monitor frames folder located at
    config:sessions['raw']['root_frames']. """

    def __init__(self, microscope, root_frames, *args, **kwargs):
        self.microscope = microscope
        self.root_frames = root_frames
        TaskHandler.__init__(self, *args, **kwargs)
        self.entries = {}

    def getLogPrefix(self):
        """ Internal function to have a unique Log prefix. """
        return f"FRAMES-{self.microscope}"

    def process(self):
        args = {'logId': self.getLogPrefix()}
        updated = False

        try:
            for e in os.listdir(self.root_frames):
                entryPath = os.path.join(self.root_frames, e)
                s = os.stat(entryPath)
                if os.path.isdir(entryPath):
                    if e not in self.entries:
                        self.entries[e] = {'mf': MovieFiles(), 'ts': 0}
                    dirEntry = self.entries[e]
                    if dirEntry['ts'] < s.st_mtime:
                        dirEntry['mf'].scan(entryPath)
                        dirEntry['ts'] = s.st_mtime
                        updated = True
                elif os.path.isfile(entryPath):
                    if e not in self.entries or self.entries[e]['ts'] < s.st_mtime:
                        self.entries[e] = {
                            'type': 'file',
                            'size': s.st_size,
                            'ts': s.st_mtime
                        }
                        updated = True

            if updated:
                entries = []
                for e, entry in self.entries.items():
                    if 'mf' in entry:  # is a directory
                        newEntry = {
                            'type': 'dir',
                            'size': entry['mf'].total_size,
                            'movies': entry['mf'].total_movies,
                            'ts': entry['ts']
                        }
                    else:
                        newEntry = entry
                    newEntry['name'] = e
                    entries.append(newEntry)

                args['entries'] = json.dumps(entries)
                u = shutil.disk_usage(self.root_frames)
                args['usage'] = json.dumps({'total': u.total, 'used': u.used})

        except Exception as e:
            updated = True  # Update error
            args['error'] = f"Error: {e}"
            args.update({'error': str(e), 'stack': traceback.format_exc()})

        if updated:
            self.info("Sending frames folder info")
            self.update_log(args)

        self.sleep = 30  # will wait 30 seconds before next update


class SessionWorker(Worker):
    """ This worker will have the primary tasks to monitor the Microscope
    data acquisition folders (defined in config:sessions). These folder
    will be provided when creating a new session on EMhub. Then, for each
    new session, new data will be monitored and transferred to another
    storage location.
    """

    def __init__(self, **kwargs):
        Worker.__init__(self, **kwargs)
        # Login into EMhub and keep a client instance
        self.transfer = None

    def setup(self):
        Worker.setup(self)
        # Load general configuration related to sessions and microscopes
        self.sconfig = self.request_config('sessions')
        self.resources = self.request_dict('get_resources',
                                           {"attrs": ["id", "name"]})

    def handle_tasks(self, tasks):
        for t in tasks:
            if t['name'] == 'transfer' and self.transfer is None:
                mics = t['args']['microscopes']
                self.transfer = {
                    'microscopes': {m: [] for m in mics},
                    'sessions': {}
                }

                # Add one handler to monitor the frames folder for each microscope
                ths = [FramesTaskHandler(m, self.sconfig['acquisition'][m]['frames'], self, t) for m in mics]
                self.add_tasks_handlers(*ths)
                # Create a separate thread to poll sessions
                threading.Thread(target=self.poll_sessions, daemon=True).start()

    def poll_sessions(self):
        """ Poll active sessions from EMhub server and keep trying, to register
        any new session and process it accordingly. """
        last_id = 1860
        while True:
            try:
                attrs = {
                    'last_id': last_id
                }
                self.info(f"Polling new sessions...last_id = {last_id}")
                r = self.dc.request('poll_active_sessions', jsonData={'attrs': attrs})
                if sessions := r.json():
                    ids = [s['id'] for s in sessions]
                    self.info(f"Got sessions: {ids}", flush=True)
                    last_id = max(ids)

            except:
                time.sleep(30)

    def add_tasks_handlers(self, *task_handlers):
        """ Add several tasks, some might be related to sessions. """
        try:
            with self._tasksLock:
                for th in task_handlers:
                    self.tasks[th.getLogPrefix()] = th
                    th.start()
                allth = ','.join(th.getLogPrefix() for th in task_handlers)
                self.info(f"Added {len(task_handlers)} new task handlers. "
                          f"Current tasks handlers: {allth}")
        except Exception as e:
            self.error(str(e))

    def add_handler(self, task, handler):
        """ Just ignore since this server will control all tasks. """
        pass

    def remove_handler(self, task):
        """ Just ignore since this server will control all tasks. """
        pass


class TaskWorker(Worker):
    """ Override Worker to handle a single Task. """
    def __init__(self, task, **kwargs):
        Worker.__init__(self, **kwargs)
        task_id = "{action}-{session_id}".format(**task['args'])
        # Let's override log folder and file
        self.logsFolder = os.path.join(self.logsFolder, task_id)
        self.logFile = 'task.log'
        task['id'] = task_id.upper()
        self.task = task

    def run(self):
        self.setup()
        SessionTaskHandler(self, self.task).run()


def main():
    p = argparse.ArgumentParser(prog='emh-session')
    p.add_argument('--url', '-u', default='')

    subparsers = p.add_subparsers(dest='mode')

    # ------------------------- USER subparser -------------------------------
    worker_p = subparsers.add_parser("worker")

    g = worker_p.add_mutually_exclusive_group()
    g.add_argument('--update', metavar='USER_JSON_STR',
                   help="Update user with the given JSON")
    g.add_argument('--list', '-l', nargs='*', metavar='USER_ID')
    worker_p.add_argument('--filters', '-f', nargs='*', metavar='FILTER',
                          help="Filter string to be used with list option."
                               "For example: ")

    # ------------------------- Form subparser -------------------------------
    task_p = subparsers.add_parser("task")
    task_p.add_argument('action')
    task_p.add_argument('session_id')
    task_p.add_argument('extra_args', nargs='?')

    args = p.parse_args()

    if args.url:
        config.EMHUB_SERVER_URL = args.url
        os.environ['EMHUB_SERVER_URL'] = args.url

    if args.mode == 'worker':
        process_users(args)

    elif args.mode == 'task':
        task = {
            'args': {
                'action': args.action,
                'session_id': args.session_id
            }
        }
        if args.extra_args:
            task['args'].update(json.loads(args.extra_args))

        TaskWorker(task).run()


if __name__ == '__main__':
    main()

