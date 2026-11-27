"""Demonstrations record real observations and Glaz-confirmed user clicks.

One action must settle before the next is taught. Unsupported editing/hotkeys
invalidate the demonstration instead of quietly producing a misleading lesson.
"""
from __future__ import annotations
import time
from cv_core.glaz_ipc import LastConfirmedTarget, read_last_confirmed_target
from .protocol import clone, guard, observation_key, under, validate_record
from .desktop import Indeterminate, click_trace, observed_change
from .visual import SAMPLE_SIZE, changed as visual_changed, measure as visual_measure


class Recorder:
    def __init__(self,observer,query,*,settle_timeout=6.0):
        self.observer=observer;self.query=query;self.receipts=[];self.before=observer.observe();self.invalid=None;self.click_baseline=None
        self.settle_timeout=settle_timeout;self._click_at=None;self._click_last=None;self._click_stable=0;self._click_capture=None
        self._next_action_at=None

    def begin_action(self, at: float) -> None:
        """Close the preceding effect's observation interval at physical press."""
        if self._next_action_at is None:self._next_action_at=at

    def cancel_action(self, at: float | None) -> None:
        """Ignore a hook event belonging to the recorder's own user interface."""
        if self._next_action_at==at:self._next_action_at=None

    def _within_action(self, observed: dict) -> bool:
        """An in-flight scan after the next press cannot describe this effect."""
        captured=observed.get('observed_at') or observed.get('captured_at')
        return self._next_action_at is None or (captured is not None and captured<self._next_action_at)

    def receipt(self,a,before,after,verified_by='observed-user-action'):
        self.receipts.append(dict(id='demo:'+str(len(self.receipts)),action=clone(a),ok=True,reason='',before=clone(before),after=clone(after),verified_by=verified_by))

    def capture(self, a: dict, at: float, point: tuple | None = None,
                pressed_at: float | None = None, target: LastConfirmedTarget | None = None) -> None:
        """Record one physical event against its preceding observation."""
        action_start=pressed_at if pressed_at is not None else at
        self.cancel_action(action_start)
        if (self.before.get('observed_at') or self.before.get('captured_at') or 0)>action_start:
            raise ValueError('Следующее действие произошло до исходного наблюдения. Дождитесь подтверждения записи.')
        # Never scan after a second physical action and credit its result to the click.
        self._click_at=None
        before=clone(self.before)
        if a['kind']=='click':
            self._capture_click(before,at,point,pressed_at,target)
            return
        if a['kind']=='enter':
            clicked=self.receipts[-1]['action'] if self.receipts else {}
            if before['selected'] and clicked.get('kind')=='click' and before['selected']!=clicked['object']:
                raise ValueError('После клика выделен другой объект; Enter не записан')
            obj=before.get('last_clicked') or before['selected']
            if not obj:raise ValueError('Не удалось наблюдать выделенную иконку или подтверждённый клик перед Enter')
            a=dict(kind='enter',object=obj)
        reason=guard(before,a)
        if reason:
            if a['kind']=='key' and before.get('reason'):reason+=': '+before['reason']
            raise ValueError(f"Шаг {len(self.receipts)+1} ({a['kind']}): {reason}")
        self._capture_result(a,before,at)

    def _click_target(self, before: dict, at: float, point: tuple, pressed_at: float | None,
                      target: LastConfirmedTarget | None) -> LastConfirmedTarget:
        """Validate the pre-press Glaz evidence, not a later hover ID."""
        press=pressed_at if pressed_at is not None else at
        if target is None:target=read_last_confirmed_target(max_age_sec=10,now=press)
        bounds=target.bbox_ltrb if target else None
        if (not target or not bounds or not 0<=press-target.timestamp<=10.35
                or not (bounds[0]<=point[0]<=bounds[2] and bounds[1]<=point[1]<=bounds[3])):
            raise ValueError('Glaz не подтвердил объект в точке клика. Наведите мышь, дождитесь ID Glaz и кликните по нему.')
        monitor=before.get('monitor')
        if monitor and not (monitor['left']<=point[0]<monitor['left']+monitor['width']
                and monitor['top']<=point[1]<monitor['top']+monitor['height']):
            raise ValueError('Клик вне выбранного монитора Glaz')
        return target

    def _hover_observation(self, before: dict, target: LastConfirmedTarget, point: tuple) -> dict:
        """Record the actually demonstrated MOVE/CHECK appearance change."""
        bounds=target.bbox_ltrb
        obj_id='glaz.'+str(target.refined_id)
        # A later hover can refine the ID of the exact same screen region.
        # Only an older observation is superseded; other hits still conflict.
        snapshot_at=before.get('captured_at')
        replaced={i['id'] for i in before['icons'] if i['id']!=obj_id
                  and snapshot_at is not None and snapshot_at<target.timestamp
                  and tuple(i.get('bbox') or ())==tuple(bounds)}
        if any(i['id']!=obj_id and i['id'] not in replaced
               and under(dict(cursor=dict(x=point[0],y=point[1])),i) for i in before['icons']):
            raise ValueError('Под курсором несколько известных объектов; клик не записан')
        moved=clone(before)
        moved['icons']=[i for i in moved['icons'] if i['id']!=obj_id and i['id'] not in replaced]
        moved['icons'].append(dict(id=obj_id,label=obj_id,x=round((bounds[0]+bounds[2])/2),
                                  y=round((bounds[1]+bounds[3])/2),bbox=list(bounds)))
        obsolete={'visible:'+id for id in replaced}|{'selected:'+id for id in replaced}
        moved['features']=[f for f in moved['features'] if f not in obsolete]
        if moved['selected'] in replaced:
            moved['selected']=''
        moved['features']=sorted(set(moved['features'])|{'visible:'+obj_id})
        moved['features']=[f for f in moved['features'] if not f.startswith('clicked:')]
        moved.pop('last_clicked',None)
        moved['cursor']=dict(x=point[0],y=point[1])
        return moved

    def _capture_click(self, before: dict, at: float, point: tuple, pressed_at: float | None,
                       target: LastConfirmedTarget | None) -> None:
        """Start observing this click until another physical action ends its credit."""
        target=self._click_target(before,at,point,pressed_at,target)
        moved=self._hover_observation(before,target,point);obj_id='glaz.'+str(target.refined_id)
        self.receipt(dict(kind='move',x=point[0],y=point[1]),before,moved)
        self.receipt(dict(kind='check',object=obj_id),moved,moved)
        before=moved
        a=dict(kind='click',object=obj_id)
        observed=self.observer.observe(after=at)
        if not self._within_action(observed):
            raise ValueError('Следующее действие произошло до исходного наблюдения. Дождитесь подтверждения записи.')
        after=click_trace(before,observed,obj_id,next(i for i in moved['icons'] if i['id']==obj_id))
        self.receipt(a,before,after,'confirmed-target-user-click')
        self.receipts[-1]['effect_observed']=False
        self.before=after;self.click_baseline=observed
        self._click_at=at;self._click_last=None;self._click_stable=0;self._click_capture=None
        self._observe_click(observed)

    def _capture_result(self, a: dict, before: dict, at: float) -> None:
        """Require two independent, agreeing observations after Enter or a key."""
        baseline=self.click_baseline if a['kind']=='enter' and before.get('last_clicked')==a['object'] and self.click_baseline is not None else before
        end=time.monotonic()+7;last=None;stable=0;last_after=None;last_capture=None
        while time.monotonic()<end:
            after=self.observer.observe(after=at)
            if not self._within_action(after):
                raise ValueError('Следующее действие произошло до подтверждения результата предыдущего. Дождитесь сообщения о записи.')
            captured=after.get('captured_at')
            if captured is not None and captured==last_capture:continue
            last_capture=captured
            last_after=after
            if a['kind']=='key':valid=bool(after.get('readable')) and after['focus']==before['focus'] and after['output']==before['output']+a['value']
            else:valid=observed_change(baseline,after)
            visual_valid=a['kind']=='enter' and visual_changed(baseline,after)
            valid=valid or visual_valid
            fingerprint=(observation_key(after),after['output'])
            stable=stable+1 if valid and fingerprint==last else (1 if valid else 0);last=fingerprint
            if stable>=2:
                self.receipt(a,before,after,'visual-change' if visual_valid else 'observed-user-action')
                self.receipts[-1]['effect_observed']=True
                self.before=after;self.click_baseline=None;return
        if a['kind']=='enter':
            measure=visual_measure(baseline,last_after) if last_after else None
            if measure is None:
                raise Indeterminate('После Enter нет сопоставимых кадров Glaz. Перезапустите Glaz, выберите монитор и включите захват экрана.')
            raise Indeterminate(f'После Enter не подтверждено изменение экрана Glaz: изменилось {measure[0]}/{SAMPLE_SIZE[0] * SAMPLE_SIZE[1]} участков кадра, средняя разница {measure[1]:.1f}.')
        raise Indeterminate('Не наблюдён однозначный результат демонстрации. Нажимайте медленно, по одному действию после подтверждения; это поле может не поддерживать чтение.')

    def _observe_click(self, observed: dict) -> None:
        """Amend the existing receipt with delayed, independently observed evidence."""
        r=self.receipts[-1];captured=observed.get('captured_at')
        if not self._within_action(observed):return
        if captured is not None and captured==self._click_capture:return
        self._click_capture=captured
        fingerprint=(observation_key(observed),observed['output'])
        changed=observed_change(r['before'],observed)
        self._click_stable=self._click_stable+1 if changed and fingerprint==self._click_last else (1 if changed else 0)
        self._click_last=fingerprint
        icon=next(i for i in r['before']['icons'] if i['id']==r['action']['object'])
        self.before=click_trace(r['before'],observed,r['action']['object'],icon)
        r['after']=clone(self.before);self.click_baseline=clone(observed)
        if self._click_stable>=2:
            r.update(effect_observed=True,verified_by='observed-user-action')
            self._click_at=None

    def poll(self) -> bool:
        """While recording, watch only the result of the most recent physical click."""
        if self._click_at is not None and self._next_action_at is None:
            self._observe_click(self.observer.observe(after=self._click_at))
            return self._click_at is None
        return False

    def finish(self):
        if self.invalid:raise ValueError(self.invalid)
        deadline=time.monotonic()+self.settle_timeout
        while self._click_at is not None and time.monotonic()<deadline:
            self.poll()
        self._click_at=None
        return validate_record(dict(query=self.query,receipts=self.receipts,source='desktop'))
