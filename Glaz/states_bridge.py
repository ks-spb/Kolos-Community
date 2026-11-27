"""Glaz visual adapter for the native States child process.

Uses the existing peak detector, loupe signatures and object repository. Each
response is computed from a new screenshot, not the legacy geometry-only cache.
Tk and object-database writes remain on the Tk thread. The worker only computes.
"""
from __future__ import annotations
import time
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from kolos_states.ipc import atomic_json, read_json, MAX_OBSERVATION_AGE
from kolos_states.visual import sample_frame
from Glaz.cursor_target import bbox_contains_point, pointed_bbox_index
from Glaz.objects_repository import recognized_ids


class GlazStatesBridge:
    def __init__(self, app):
        self.app=app;self.session=uuid.uuid4().hex
        self.path=Path.home()/'.kolos'/'states-ipc'/self.session
        self.path.mkdir(parents=True,exist_ok=True)
        self.enabled=False;self.closed=False;self.last='';self.frame=0;self.future=None
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='states-glaz')
        self.request=None;self.allow_live=False
        self._reported_hover=None
        self.app.root.after(100,self.poll)

    def permission(self, enabled):
        self.allow_live=bool(enabled)
        atomic_json(self.path/'permission.json',dict(session=self.session,live=self.allow_live,stamp=time.time()))

    def close(self):
        self.closed=True;self.permission(False);self.worker.shutdown(wait=False,cancel_futures=True)

    def poll(self):
        if self.closed:return
        try:
            self.permission(self.allow_live)
            if self.future is not None and self.future.done():
                future=self.future;self.future=None
                try:self._publish(future.result())
                except Exception as exc:self._error(str(exc))
            if self.enabled and self.future is None:
                req=read_json(self.path/'request.json')
                if req and req.get('session')==self.session and req.get('id')!=self.last and 0<=time.time()-req.get('issued',0)<10:
                    self.request=req
                    if not self.app.capture.is_capturing or self.app.current_image is None:
                        self._error('Захват Glaz остановлен. Выберите монитор и нажмите «Захватить экран».')
                    elif self.app._states_frame and self.app._states_frame[1]>=req.get('after',0):
                        self.last=req['id'];self.frame+=1
                        image,frame_stamp,monitor=self.app._states_frame
                        monitor=dict(monitor)
                        job=dict(request=req['id'],captured_at=frame_stamp,frame=self.frame,
                            monitor=monitor,own_rect=[self.app.root.winfo_rootx(),self.app.root.winfo_rooty(),self.app.root.winfo_rootx()+self.app.root.winfo_width(),self.app.root.winfo_rooty()+self.app.root.winfo_height()],
                            loupe_size=int(self.app.loupe_controller.loupe_size),
                            segment_threshold=int(self.app.segment_peak_threshold.get()))
                        job['visual_requests'] = req.get('visual_requests', [])
                        job['own_rects'] = self._owned_rects()
                        if req.get('mode') == 'frame-only':
                            self._publish_frame(image, job)
                            return
                        if req.get('mode') is not None:
                            self._error('Неизвестный режим наблюдения')
                            return
                        self.future=self.worker.submit(self._compute,image.copy(),int(self.app.peaks_threshold.get()),bool(self.app.peaks_invert.get()),job)
        except Exception as exc:
            self.app.log_message('States bridge: '+str(exc),error=True)
        finally:
            if not self.closed:self.app.root.after(100,self.poll)

    def _error(self, message: str, *, retryable: bool = False) -> None:
        """Only expired evidence permits another scan of the same unsent operation."""
        if self.request:
            self.last=self.request['id'];atomic_json(self.path/'observation.json',dict(
                session=self.session, request=self.last, error=message, retryable=retryable))

    def _publish_frame(self, image, job: dict) -> None:
        """Supply Enter's baseline without detecting objects or publishing a hover ID."""
        from utils import get_cursor_pos
        if time.time()-job['captured_at'] > MAX_OBSERVATION_AGE:
            self._error('Кадр устарел до передачи; нужен новый кадр.', retryable=True)
            return
        x, y = get_cursor_pos()
        result = {k: job[k] for k in ('request', 'captured_at', 'frame', 'monitor', 'own_rect', 'own_rects')}
        result.update(session=self.session, mode='frame-only', complete=True,
                      cursor=dict(x=x, y=y), visual_sample=sample_frame(
                          image, monitor=job['monitor'], own_rects=job['own_rects']))
        atomic_json(self.path/'observation.json', result)

    def _owned_rects(self) -> list[list[int]]:
        """A displayed teaching screenshot must never become a desktop candidate."""
        root = self.app.root
        windows = [root]+[w for w in root.winfo_children() if w.winfo_toplevel() is w]
        return [[w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx()+w.winfo_width(),
                 w.winfo_rooty()+w.winfo_height()] for w in windows if w.winfo_viewable()]

    def _compute(self,frame,threshold,invert,job):
        job['source_frame'] = frame
        job['visual_sample']=sample_frame(frame,monitor=job['monitor'],own_rect=job['own_rect'],
                                         own_rects=job.get('own_rects'))
        result=self.app._compute_peaks_and_objects(frame,threshold,invert)
        loupe_size=job.pop('loupe_size',50)
        segment_threshold=job.pop('segment_threshold',3)
        rows=[]
        # Reproduce hover learning at each fresh object's mass center. Bbox
        # crops use different pixels/geometry and cannot recover hover IDs.
        for obj in result.objects:
            sig=self.app._signature_for_object_center(frame=frame,obj=obj,
                loupe_size=loupe_size,threshold=threshold,invert=invert,
                segment_threshold=segment_threshold,monitor=job['monitor'])
            rows.append((obj.bbox,sig))
        requests = job.pop('visual_requests', [])
        if requests:
            from Glaz.perception.retina import collect
            job['perception_samples'] = collect(frame, [bbox for bbox, _ in rows], requests,
                threshold, job['monitor'], job.get('own_rect'), own_rects=job.get('own_rects'))
        job['rows']=rows;return job

    @staticmethod
    def _screen_bbox(bbox: tuple, monitor: dict) -> list[int]:
        """Translate detector bounds into the OS coordinate system."""
        l,t,r,b=bbox
        return [l+monitor['left'],t+monitor['top'],r+monitor['left'],b+monitor['top']]

    def _recognized_icons(self, rows: list, monitor: dict, point: tuple,
                          pointed_index: int | None) -> tuple[list[dict], dict | None, int | None]:
        """Recognize fresh rows and distinguish duplicate IDs from pointer overlaps."""
        icons=[];counts={}
        refined_ids=[]
        for index,(bbox,sig) in enumerate(rows):
            ids,_=recognized_ids(self.app._objects_repo,sig,self.app._zoomed_signature_to_ids,self.app._signature_match_max_pct)
            if len(ids)!=1:continue
            id='glaz.'+str(ids[0]);counts[id]=counts.get(id,0)+1
            l,t,r,b=self._screen_bbox(bbox,monitor)
            icon=dict(id=id,label=id,x=round((l+r)/2),y=round((t+b)/2),bbox=[l,t,r,b])
            icons.append(icon)
            refined_ids.append(ids[0])
        screen_point=(point[0]+monitor['left'],point[1]+monitor['top'])
        known_index=pointed_bbox_index([icon['bbox'] for icon in icons],screen_point)
        pointed_icon=icons[known_index] if known_index is not None else None
        pointed_refined=refined_ids[known_index] if known_index is not None else None
        for icon in icons:
            if icon is not pointed_icon and bbox_contains_point(icon['bbox'],screen_point):
                icon['ambiguous_reason']='overlap'
            icon['ambiguous']=icon.get('ambiguous_reason')=='overlap' or (counts[icon['id']]!=1 and icon is not pointed_icon)
        return icons,pointed_icon,pointed_refined

    def _publish(self,result: dict) -> None:
        """Publish one fresh recognition result with its resolved pointer instance."""
        from utils import get_cursor_pos
        if not self.enabled or self.closed:return
        source = result.pop('source_frame', None)
        self._refresh_identical_capture(result, source)
        if time.time()-result['captured_at']>MAX_OBSERVATION_AGE:
            self._error('Распознавание кадра заняло слишком долго; нужен новый кадр.', retryable=True);return
        monitor=result['monitor'];x,y=get_cursor_pos();point=(x-monitor['left'],y-monitor['top'])
        rows=result.pop('rows')
        pointed_index=pointed_bbox_index([bbox for bbox,_ in rows],point)
        icons,pointed_icon,pointed_refined=self._recognized_icons(rows,monitor,point,pointed_index)
        hover_key=(pointed_icon['id'],tuple(pointed_icon['bbox'])) if pointed_icon and getattr(self.app,'_states_controls_owned',False) else None
        report_hover = hover_key and hover_key!=getattr(self,'_reported_hover',None)
        from kolos_states.concept_graph import registry
        result['object_registry'] = registry(self.app._zoomed_signature_to_ids)
        result.update(session=self.session,icons=icons,cursor=dict(x=x,y=y),complete=True,
            pointer_bboxes=[self._screen_bbox(bbox,monitor) for bbox,_ in rows if bbox_contains_point(bbox,point)])
        self._refresh_identical_capture(result, source)
        if time.time()-result['captured_at']>MAX_OBSERVATION_AGE:
            self._error('Кадр устарел до передачи; нужен новый кадр.', retryable=True);return
        self._preview_frame = (source, result['captured_at'], dict(monitor)) if source is not None else None
        atomic_json(self.path/'observation.json',result)
        self._reported_hover=hover_key
        if report_hover:
            self.app._event_bus.emit('object_recognized',refined_id=pointed_refined,is_new=False)

    def _refresh_identical_capture(self, result: dict, source: object) -> None:
        """Exact new pixels prove every computed feature, never just old geometry."""
        latest = getattr(self.app, '_states_frame', None)
        capture = getattr(self.app, 'capture', None)
        if source is None or not latest or not getattr(capture, 'is_capturing', False):
            return
        frame, stamp, monitor = latest
        if (stamp <= result['captured_at'] or monitor != result['monitor']
                or not 0 <= time.time()-stamp <= MAX_OBSERVATION_AGE):
            return
        if source.mode == frame.mode and source.size == frame.size and source.tobytes() == frame.tobytes():
            result['captured_at'] = stamp
