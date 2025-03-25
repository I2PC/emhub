import os
from glob import glob
import json
import datetime as dt
import statistics

from emtools.utils import Pretty, Path, Timer
from emhub.utils import datetime_from_isoformat


def register_content(dc):
    @dc.content
    def cluster_queues(**kwargs):
        dm = dc.app.dm
        queuesConf = dm.get_config('queues')
        queuesLayout = queuesConf['layout']
        queueWorker = queuesConf['worker']

        # FIXME: this is just for debugging purposes,
        # get real data from the worker task results
        jobsJson = queuesConf['sample_json']

        task = None
        # # TODO: Get worker that monitor cluster from config
        # ws = dm.get_worker_stream(queueWorker)
        # for t in ws.get_pending_tasks():
        #     task = t

        if task:
            event_id, event = dm.get_task_lastevent(task)
            jobsJson = json.loads(event['queues'])
            updated = Pretty.datetime(dm.dt_from_redis(event_id))
        else:
            updated = ''

        return {
            'queues': queuesLayout,
            'jobs': jobsJson,
            'task': task,
            'updated': updated
        }

    @dc.content
    def cluster_queues_content(**kwargs):
        return cluster_queues(**kwargs)

    @dc.content
    def access_microscopes(**kwargs):
        """ Load one of all batches. """
        dm = dc.app.dm  # shortcut
        formDef = dm.get_form_definition('access_microscopes')
        return {
            'request_resources': formDef['config']['request_resources']
        }

    @dc.content
    def create_session_form(**kwargs):
        """ Specific information needed to render the create-form template
        # for St.Jude CryoEM center.
        """
        dm = dc.app.dm  # shortcut
        user = dc.app.user
        booking_id = int(kwargs['booking_id'])
        b = dm.get_booking_by(id=booking_id)
        can_edit = b.project and user.can_edit_project(b.project)

        if not (user.is_manager or user.same_pi(b.owner) or can_edit):
            raise Exception("You can not create Sessions for this Booking. "
                            "Only members of the same lab can do it.")

        sconfig = dm.get_config('sessions')

        # load default acquisition params for the given microscope
        micName = b.resource.name
        acq = sconfig['acquisition'][micName]
        transfer_host = sconfig['raw']['hosts_default'][micName]

        # We provide cryolo_models to be used with the OTF
        cryolo_models_pattern = dm.get_config('sessions')['data']['cryolo_models']

        cryolo_models = glob(cryolo_models_pattern)

        if not user.is_manager:
            group = dm.get_user_group(user)
            cryolo_models = [cm for cm in cryolo_models if group in cm]

        def _key(model):
            d, base = os.path.split(model)
            return base if not user.is_manager else os.path.join(os.path.basename(d), base)

        dateStr = Pretty.date(b.start).replace('-', '')

        otf = sconfig['otf']
        data = {
            'booking': b,
            'acquisition': acq,
            'session_name_prefix': f'{dateStr}{b.resource.name}:',
            'otf_hosts': otf['hosts'],
            'otf_host_default': otf['hosts_default'][micName],
            'workflows': otf['workflows'],
            'workflow_default': otf['workflow_default'],
            'transfer_host': transfer_host,
            'cryolo_models': {_key(cm): cm for cm in cryolo_models}
        }
        data.update(dc.get_user_projects(b.owner, status='active'))
        frames = workers_frames(hours=10)['folderGroups']
        key = f"{transfer_host}:{acq['frames']}"
        data['frame_folders'] = frames.get(key, {'entries': []})['entries']
        return data

    @dc.content
    def session_details(**kwargs):
        session_id = kwargs['session_id']
        dm = dc.app.dm  # shortcut
        session = dm.get_session_by(id=session_id)

        if session.booking:
            a = session.booking.application
            if not (a is None or a.allows_access(dc.app.user)):
                raise Exception("You do not have access to this session information. ")


        sconfig = dm.get_config("sessions")

        # Try to get deletion days (used in SLL based on session name code)
        days = dm.get_session_data_deletion(session.name[:3])
        td = (session.start + dt.timedelta(days=days)) - dm.now()
        errors = []
        # TODO: We might check other type of errors in the future
        status_info = session.extra.get('status_info', '')
        if status_info.lower().startswith('error:'):
            errors.append(status_info)

        frames = Path.rmslash(session.extra['raw'].get('frames', ''))
        raw = session.extra['raw']
        group = dm.get_user_group(session.booking.owner)
        gscemRoot = Path.addslash(os.path.join(sconfig['raw']['root'], group))
        dataPath = raw['path'].replace(gscemRoot, '')
        judeRootDefault = sconfig['raw']['jude_group_folder'].format(group=group)
        judeRoot = sconfig['raw']['jude_group_mapping'].get(group, judeRootDefault)

        return {
            'session': session,
            'gscemRoot': gscemRoot,
            'judeRoot': judeRoot,
            'dataPath': dataPath,
            'epu_session': os.path.basename(frames),
            'deletion_days': td.days,
            'errors': errors,
            'files': [{'name': k.replace('.', ''),
                       'y': v['count'],
                       'z': v['size'],
                       'sizeH': Pretty.size(v['size'])}
                      for k, v in session.files.items()]
        }

    @dc.content
    def session_content(**kwargs):
        return session_details(**kwargs)

    @dc.content
    def session_data_card(**kwargs):
        return session_details(**kwargs)

    @dc.content
    def session_otf_plots(**kwargs):
        data = {}
        batches = []
        series = []
        means = {}

        def _td(secs):
            mins = secs // 60
            secs = secs % 60
            return f"{mins} m, {secs} s"

        project = dc.app.dm.get_processing_project(**kwargs)['project']

        if project.exists('session.json'):
            with open(project.join('session.json')) as f:
                session = json.load(f)
                run = os.path.dirname(session['micrographs'])
                if project.exists(run, 'info.json'):
                    with open(project.join(run, 'info.json')) as f2:
                        info = json.load(f2)
                        skeys = ['mc', 'ctf', 'cryolo', 'extract']
                        seriesDict = {k: [] for k in skeys}
                        N = len(info['batches'])
                        for key, batch in info['batches'].items():
                            batches.append(key)
                            for k in skeys:
                                td = Timer.parse_timedelta(batch[f'{k}_elapsed'])
                                seriesDict[k].append(td.seconds)

                        #batches.extend(info['batches'].keys())
                        series = [{'name': k, 'data': v} for k, v in seriesDict.items()]
                        values = {k: {'mean': round(statistics.fmean(v))} for k, v in seriesDict.items()}
                        mean_total = sum(v['mean'] for v in values.values())
                        for v in values.values():
                            m = v['mean']
                            v['percent'] = '%0.2f %%' % (m / mean_total)
                            v['td'] = _td(m)

                        n = 50
                        if N > n:
                            indexes = [(i*n, (i+1)*n-1) for i in range(N // n + 1)]
                            a, b = indexes[-1]
                            indexes[-1] = (a, b + N % n)
                        else:
                            indexes = [(0, N-1)]
        data.update({
            'batches': batches,
            'series': series,
            'values': values,
            'mean_total': mean_total,
            'td_total': _td(mean_total),
            'indexes': indexes
        })

        return data

    @dc.content
    def workers_frames(**kwargs):
        # Some optional parameters
        days = int(kwargs.get('days', 0))
        hours = int(kwargs.get('hours', 0))
        total_hours = days * 24 + hours
        td = dt.timedelta(hours=total_hours)

        sortKey = kwargs.get('sort', 'ts')
        reverse = int(kwargs.get('reverse', 1))

        dm = dc.app.dm
        hosts = dm.get_hosts()

        folderGroups = {}
        # TODO: Get worker that monitor cluster from config
        for h, host in hosts.items():
            ws = dm.get_worker_stream(h)
            for t in ws.get_all_tasks():
                if t['name'] == 'frames' and t['status'] == 'pending':
                    event_id, event = dm.get_task_lastevent(t['id'])
                    if 'error' in event:
                        continue
                    entries = json.loads(event.get('entries', []))
                    usage = json.loads(event['usage'])
                    folders = []
                    now = dm.now()
                    for e in entries:
                        ddt = dm.dt_from_timestamp(e['ts'])
                        if total_hours == 0 or now - ddt < td:
                            e['modified'] = ddt
                            folders.append(e)

                    folders.sort(key=lambda f: f[sortKey], reverse=bool(reverse))
                    root = t['args']['root']
                    key = f"{h}:{root}"
                    folderGroups[key] = {'usage': usage, 'entries': folders}

        return {
            'folderGroups': folderGroups
        }

    @dc.content
    def create_session_negstain(**kwargs):
        """ Specific information needed to render the create-form template
        # for St.Jude CryoEM center.
        """
        return create_session_form(**kwargs)

    @dc.content
    def dashboard_instrument_card(**kwargs):
        """ Load data for a single instrument. """
        data = dashboard(**kwargs)
        r = None
        for r in data['resources']:
            if r['id'] == int(kwargs['resource_id']):
                break
        data['r'] = r
        data['alignment'] = kwargs.get('alignment', 'v')
        return data

    @dc.content
    def dashboard_createslots_card(**kwargs):
        dm = dc.app.dm
        kwargs['load_requests'] = False
        data = dashboard_instrument_card(**kwargs)
        next_week = data['next_week']
        rid = int(kwargs['resource_id'])
        resource = dm.get_resource_by(id=rid)

        create_slots = int(kwargs.get('create_slots', 0))
        operators = json.loads(kwargs.get('operators', '[]'))
        bookings = data['resource_bookings'][rid].get('next_week', [])
        slots_config = dm.get_config('resources').get('slots', {})
        ranges = []

        def _time(timeStr):
            return dt.datetime.strptime(timeStr, '%H:%M').time()

        for start, end in slots_config.get(resource.name, []):
            ranges.append((_time(start), _time(end)))
        #range1 = _time('9:00'), _time("12:59")
        #range2 = dt.time(13), dt.time(23, minute=59)

        def _create_day_slots(i, d):
            day_slots = []
            for r in ranges:
                args = {
                    'resource_id': rid,
                    'type': 'slot',
                    'start': dm.date(d, r[0]),
                    'end': dm.date(d, r[1]),
                    'slot_auth': {'applications': ['any'], 'users': []}
                }
                if operators:
                    args['operator_id'] = int(operators[i])

                s = dm.Booking(**args)
                o = [b for b in bookings if b.overlap(s)]
                day_slots.append((s, o))
                if create_slots and not o:
                    dm.create_booking(**args)
            return day_slots

        slots = []
        for i in range(1):
            d = next_week + dt.timedelta(days=i)
            slots.append(_create_day_slots(i, d))

        data['slots'] = slots

        return data

    @dc.content
    def dashboard(**kwargs):
        """ Customized Dashboard data for the CryoEM center at St.Jude. """
        dm = dc.app.dm  # shortcut
        user = dc.app.user  # shortcut
        # If 'resource_id' is passed as argument, only display
        # that resource in the dashboard
        resource_id = int(kwargs.get('resource_id', 0))
        dataDict = dc.get_resources(image=True)
        resources = dataDict['resources']
        selected_resources = [r for r in resources if r['id'] == resource_id] or resources


        resource_bookings = {}

        # Provide upcoming bookings sorted by proximity
        bookings = [('Today', []),
                    ('Next 7 days', []),
                    ('Next 30 days', [])]

        def week_start(d):
            return (d - dt.timedelta(days=d.weekday())).date()

        if 'date' in kwargs:
            now = datetime_from_isoformat(kwargs['date'])
        else:
            now = dm.now()
        this_week = week_start(now)
        d7 = dt.timedelta(days=7)
        next_week = week_start(now + d7)
        prev7 = now - dt.timedelta(days=8)
        next7 = now + d7
        next30 = now + dt.timedelta(days=30)

        def is_same_week(d):
            return this_week == week_start(d)

        def is_next_week(d):
            return this_week == week_start(d - d7)

        def add_booking(b):
            start = dm.dt_as_local(b.start)
            end = dm.dt_as_local(b.end)

            r = b.resource
            if r.id not in resource_bookings:
                resource_bookings[r.id] = {
                    'today': [],
                    'this_week': [],
                    'next_week': []
                }

            if is_same_week(start):
                k = 'this_week'
            elif is_next_week(start):
                k = 'next_week'
            else:
                k = None

            if k:
                resource_bookings[r.id][k].append(b)

                if start.date() <= now.date() <= end.date():  # also add in today
                    resource_bookings[r.id]["today"].append(b)
                    bookings[0][1].append(b)
                elif k == 'next_week':
                    bookings[1][1].append(b)
            else:
                bookings[2][1].append(b)

        local_tag = dm.get_config('bookings').get('local_tag', '')
        local_scopes = {}

        for b in dm.get_bookings_range(prev7, next30):
            # if not user.is_manager and not user.same_pi(b.owner):
            #     continue
            r = b.resource
            if not local_tag or local_tag in r.tags:
                local_scopes[r.id] = r
                add_booking(b)

        scopes = {r.id: r for r in dm.get_resources()}

        for rbookings in resource_bookings.values():
            for k, bookingValues in rbookings.items():
                bookingValues.sort(key=lambda b: b.start)

        # Remove slots if there are overlapping bookings
        for rbookings in resource_bookings.values():
            for k, bookingValues in rbookings.items():
                def _slot_overlap(s):
                    return s.is_slot and any(s.overlap(b, strict=True) for b in bookingValues)

                slots_overlap = [s for s in bookingValues if _slot_overlap(s)]
                for s in slots_overlap:
                    bookingValues.remove(s)

                bookingValues.sort(key=lambda b: b.start)

        # Retrieve open requests for each scope from entries and bookings
        if kwargs.get('load_requests', True):
            for p in dm.get_projects():
                if p.is_active:
                    last_bookings = {}
                    # Find last bookings for each scope
                    for b in sorted(p.bookings, key=lambda b: b.end, reverse=True):
                        if len(last_bookings) < len(local_scopes) and b.resource_id not in last_bookings:
                            last_bookings[b.resource.id] = b

                    reqs = {}
                    for e in reversed(p.entries):
                        # Requests found for each scope, no need to continue
                        if len(reqs) == len(local_scopes):
                            break
                        if b := dc.booking_from_entry(e, scopes):
                            rid = b.resource_id
                            if (rid not in reqs and
                                    (rid not in last_bookings or
                                     b.start.date() > last_bookings[rid].end.date())):
                                b.id = e.id
                                add_booking(b)
                                reqs[rid] = b

        # Sort all entries
        for rbookings in resource_bookings.values():
            for k, bookingValues in rbookings.items():
                bookingValues.sort(key=lambda b: b.start)

        resource_create_session = dm.get_config('sessions').get('create_session', {})
        slots_config = dm.get_config('resources').get('slots', {})

        dataDict.update({'resource_bookings': resource_bookings,
                         'resource_create_session': resource_create_session,
                         'local_resources': local_scopes,
                         'next_week': next_week,
                         'date': now,
                         'create_slots': slots_config,
                         'resource_id': resource_id,
                         'selected_resources': selected_resources
                         })
        dataDict.update(dc.get_news(**kwargs))
        return dataDict
